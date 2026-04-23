# Continuity notes — Feature 3 implementation

_Last updated: 2026-04-19 (pre-compact, after 3.0c live-test + rich
is_error log). Delete this file after Feature 3 lands._

## Where we are

- **Completed:** 3.0a (three-thread echo-back skeleton), 3.0b (session
  resolution: `--session-id`, `--resume`, mutex, state file, startup
  probe), and **3.0c** (`claude -p` subprocess wired into the bridge
  with JSON parsing, session-id capture/persist, `shutil.which("claude")`
  pre-flight, `claude_runner_factory` test seam on `CliContext`). All
  three live-tested by user.
- **Next up:** 3.0d — error handling for subprocess failure modes
  (timeout, non-zero exit, missing `claude` at runtime).
- **Mode:** out of plan mode, coding. Plan approved.
- **Plan file:** `/Users/john/.claude/plans/stateful-stirring-pixel.md`
- **Refinement answers:** `tasks/TASK-REFINEMENT.md`
- **TODO sync:** `tasks/TODO.md` §Feature 3 updated — 3.0a/3.0b/3.0c
  boxes checked.

## What 3.0c shipped (uncommitted in the working tree)

### `src/cli/__init__.py`

- New `_default_claude_runner(prompt, session_id) -> CompletedProcess`:
  invokes `claude -p <prompt> [--resume <id>] --output-format json` with
  `timeout=300`, `capture_output=True`, `text=True`.
- `CliContext.claude_runner_factory` field: typed
  `Callable[[str, str | None], subprocess.CompletedProcess[str]]`,
  defaulted to `_default_claude_runner`. Tests swap it out.

### `src/cli/converse.py` (current line refs)

- Imports added: `json`, `shutil`, `subprocess` (lines 18–22).
- `_make_bridge_callback` (line 103) takes `runner` as its fourth arg
  and keeps `current_session_id` mutable via `nonlocal` (line 121) so
  the fresh-session case can capture the id returned by turn 1 and
  thread it into turn 2+.
- Inside `_bridge`: call runner → non-zero exit skip → `json.loads`
  stdout (skip on JSONDecodeError) → `is_error` rich log at line 154
  (subtype, stop_reason, num_turns, permission_denials, result) →
  extract `result` text → if response's `session_id` differs from
  `current_session_id`, update + `_write_last_session_id` → append
  `result` to agent file.
- `shutil.which("claude")` pre-flight at line 255 (in `converse()`
  command body): raises ClickException if missing.
- `ctx_obj.claude_runner_factory` threaded into the bridge at line 308.
- Startup banner (just after listener thread starts) prints
  `session=<id>` or `session=fresh`.

### `claude -p --output-format json` schema (verified empirically)

```json
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "result": "<agent response text>",
  "session_id": "<uuid>",
  "stop_reason": "end_turn",
  "permission_denials": [],
  "api_error_status": null,
  "num_turns": 1,
  "duration_ms": 2014,
  "total_cost_usd": 0.012,
  "usage": { ... }
}
```

- `session_id` stays stable across `--resume` calls (same id returned).
- Bogus `--resume <unknown-id>` prints non-JSON
  `No conversation found with session ID: …` to stdout and exits 0.
  So we can't rely on exit code for "session gone" — must JSON-parse.

Robust error handling (timeout, non-zero exit with TTS "session ended"
shutdown, missing-binary mid-run) is deliberately deferred to 3.0d. In
3.0c the bridge thread just logs and continues so it survives.

## 3.0c verification (done)

- Unit-style in-process test (no mic, fake runner) exercised all six
  branches: fresh happy path, id-carry to turn 2, is_error skip,
  non-zero exit skip, non-JSON stdout skip, runner-raises swallow,
  matched-id no-rewrite.
- `uv run python cli.py converse --help` still renders; `CliContext`
  carries the new factory with the correct annotations.
- Live tests (all three): fresh (no flags), throwaway-dir attach via
  `--session-id`, same-session resume. All three round-trip STT →
  bridge → `claude -p` → TTS successfully. First live attempt hit an
  `is_error=true` race from concurrent turns against the same session
  (user was typing in claude-code interactively while `cai converse`
  was also injecting turns) — a re-run succeeded. Rich `is_error`
  logging added in response to that incident.

### Known sharp edge (not a 3.0c bug)

Voicing into the **same** Claude Code session the user is actively
typing to elsewhere can race. `claude -p --resume` serialises turns
server-side but a refused/errored turn surfaces as `is_error=true` and
the bridge swallows it with a log. 3.0d will make this visible (speak
a failure tone or short phrase). Not worth a fix in 3.0c.

## Tests NOT written for 3.0c (intentional)

Tests land in 3.4 (`tests/test_converse.py`). The `claude_runner_factory`
test seam is now in place so tests can hand in a fake runner and assert
against `agent.txt` / the session state file. Will bundle 3.0a/b/c/d/e
into one test module in 3.4.

## Immediate next step: 3.0d — Error handling

Scope (from TODO.md and plan):

1. **`subprocess.TimeoutExpired`** — the 300s timeout on
   `_default_claude_runner` already raises. 3.0c swallows it in the
   bridge. 3.0d: log it, speak "claude turn timed out" (or similar
   short phrase) via the agent file, keep the bridge alive. Do **not**
   shutdown — timeouts are recoverable.
2. **Non-zero exit** — currently logged and skipped. Per plan:
   speak "session ended" and set `shutdown` event so all three threads
   exit cleanly. Rationale: non-zero usually means the session is
   unrecoverable (invalid resume id, quota, auth).
3. **`is_error=true`** — similar to non-zero? Or treat as recoverable
   (just log, skip, continue)? Decision needed. Leaning: recoverable
   if `subtype == "error_during_execution"` but unrecoverable if
   `permission_denials` or `api_error_status` is set. Confirm with the
   user before coding.
4. **Missing `claude` binary mid-run** — `FileNotFoundError` from
   `subprocess.run`. Treat as unrecoverable: speak "claude binary
   gone" and shutdown. Startup pre-flight already covers the common
   case.
5. **Helper:** consider a small `_speak_error(agent_path, phrase)`
   that just appends the phrase to `agent.txt` so the existing watcher
   path handles TTS. Keeps the bridge thread from having to talk to
   the TTS pipeline directly.

Open questions to answer before coding:

- Should timeouts use the same "append to agent.txt" trick to voice
  the error, or a separate channel? (Probably same — consistent and
  simple.)
- What phrase for each failure mode? User may want to customise.
  Default: "session ended" (non-zero, fatal) / "turn timed out"
  (recoverable) / "claude binary missing" (fatal).
- Do we want a `--max-timeouts N` knob so repeated timeouts escalate
  to shutdown? Probably not in 3.0d scope; defer to post-3.0e polish.

## Key architectural decisions (unchanged; restated for continuity)

- **Session resolution (Q4):** `--session-id`, `--resume`, default
  fresh — all three shipped in 3.0b.
- **Backend:** `claude -p "<line>" --resume <id> --output-format json`
  per turn — shipped in 3.0c.
- **Validation:** startup probe → exit 1 on invalid (done in 3.0b).
  Mid-session nonzero exit → "session ended" TTS + shutdown (3.0d).
- **Blocking in v1** (Q5); streaming on roadmap.
- **No voice-stop in v1** (Q6); on roadmap.
- **Cwd inherited** (Q7); install.sh shim preserves it. Document in
  help + SKILL.md later.
- **Test seam:** `claude_runner_factory: Callable` on `CliContext` —
  added in 3.0c.
- **Skills in 3.1:** `voice-mode` (primary), `cai-dictation`,
  `cai-dialogue`.

## Remaining implementation sequence

- **3.0d** ← start here: error handling (subprocess timeout, nonzero
  exit with "session ended" + shutdown, missing-binary mid-run).
- **3.0e:** wake-word gating via `build_wake_gate`.
- **3.1:** three SKILL.md files.
- **3.2:** `cai install-skill` / `cai uninstall-skill`.
- **3.3:** PATH check (`shutil.which("cai")`) in installer.
- **3.4:** tests (including all 3.0a-e branches against the
  `claude_runner_factory` test seam).
- **3.5:** docs sweep.

## Reused primitives (no changes needed)

- `src/cli/dialogue.py:_listener_loop` (lines 84-174)
- `src/cli/dialogue.py:_make_speak_callback` (lines 24-81)
- `src/cli/watch.py:TextFileHandler`
- `src/cli/wake_word.py:build_wake_gate` (not used until 3.0e)

## Files that will be touched in 3.0d

**Modified:**
- `src/cli/converse.py` — expand the bridge callback's error branches:
  separate the recoverable (timeout, recoverable is_error) from the
  fatal (nonzero exit, missing binary, fatal is_error). Add shutdown
  trigger on fatal branches. Use a small helper that appends an error
  phrase to `agent.txt` so TTS speaks it via the existing watcher.

**Unchanged in 3.0d:**
- `src/cli/__init__.py` — runner factory already typed correctly;
  timeout is already baked in.
- `cli.py` — already wired.
- `install.sh` — shim already correct.
- Docs — deferred to 3.5.
- Tests — deferred to 3.4.

## Key memory rules in force

- **Installer-before-live-CLI:** always run `./install.sh` before live
  testing `cai converse`. Shim at `~/.local/bin/cai` runs the installed
  copy, not the dev tree.
- **Pause between tasks:** user wants a checkpoint after each phase —
  do not autonomously chain 3.0d → 3.0e.
- **User drives commits.** Don't run `git commit`.
- **Shared test helpers** go in `tests/_<topic>.py` plain modules.

## Current git state

- Branch: `main` (up to date with origin/main).
- 3.0a + 3.0b already committed (recent commits include `9edc9d6` "AI
  skill development and integration glue" and `aecbaf1` "Working on
  the skill and persistent conversational support structures").
- Uncommitted (3.0c only):
  - `M src/cli/__init__.py` — `_default_claude_runner` +
    `claude_runner_factory` field.
  - `M src/cli/converse.py` — bridge subprocess wiring + rich
    `is_error` log.
  - `M tasks/TODO.md` — 3.0c box checked with live-test note.
  - `M tasks/CONTINUITY.md` — this file.
- No untracked files.
- User has not asked for a commit yet. Don't run `git commit`
  autonomously.

## Next action after new session starts

1. Read this file (CONTINUITY.md) first.
2. Skim `src/cli/converse.py` to re-orient — especially the bridge
   callback's current error branches (log-and-continue across all
   failure modes).
3. Confirm with user: is_error classification (recoverable vs fatal)
   and the exact phrases to speak on each failure.
4. Start **3.0d**: refine the bridge callback's error handling.
   Keep diff minimal. Don't touch tests or docs. Pause for user review
   when runnable.

## Out-of-scope right now

- Don't touch Features 4, 7, 8, or BUGS.md.
- The pre-existing B5.1 F401 in `tests/test_config.py:3` stays deferred.
- Don't start 3.0e in the same session as 3.0d.
- Don't add wake-word gating — that's 3.0e.
- Don't write tests — that's 3.4.
