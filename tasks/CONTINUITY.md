# Continuity notes — Feature 3 implementation

_Last updated: 2026-04-24 (after 3.0d implementation, pre live-test).
Delete this file after Feature 3 lands._

## Where we are

- **Completed:** 3.0a (three-thread echo-back skeleton), 3.0b (session
  resolution: `--session-id`, `--resume`, mutex, state file, startup
  probe), **3.0c** (`claude -p` subprocess wired into the bridge with
  JSON parsing, session-id capture/persist, `shutil.which("claude")`
  pre-flight, `claude_runner_factory` test seam on `CliContext`), and
  **3.0d** (split recoverable vs fatal failure handling — see below).
  3.0a–c all live-tested. **3.0d not yet live-tested** — user needs to
  run `./install.sh` then verify each branch.
- **Next up:** 3.0e — wake-word gating via `build_wake_gate` (same
  knobs as `listen` / `dialogue`).
- **Mode:** out of plan mode, coding. Plan approved.
- **Plan file:** `/Users/john/.claude/plans/stateful-stirring-pixel.md`
- **Refinement answers:** `tasks/TASK-REFINEMENT.md`
- **TODO sync:** `tasks/TODO.md` §Feature 3 — 3.0a/3.0b/3.0c/3.0d
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

## What 3.0d shipped (uncommitted in the working tree)

### `src/cli/converse.py`

- New `_speak_error(agent_path, phrase)` module helper: appends a
  phrase to `agent.txt` so the agent watcher voices it via TTS.
  Used by the recoverable bridge branches.
- `_make_bridge_callback` gained a `speak_fatal: Callable[[str], None]`
  parameter (the same `speak_cb` the agent watcher uses), threaded
  in from `converse()`.
- Bridge error branches:
  - `subprocess.TimeoutExpired` → log warning, `_speak_error("Claude
    turn timed out.")`, continue. Recoverable.
  - `FileNotFoundError` → log error, `speak_fatal("Claude command not
    found.")`, `shutdown.set()`, return. Fatal.
  - Generic `Exception` from runner → log + `_speak_error("Claude
    returned an error.")`, continue. Recoverable.
  - Non-zero exit → log + `speak_fatal("Session ended.")`,
    `shutdown.set()`, return. Fatal.
  - JSON decode failure → log + `_speak_error("Claude returned an
    error.")`, continue. Recoverable.
  - `is_error=true` payload → existing rich log + `_speak_error("Claude
    returned an error.")`, continue. Recoverable across the board per
    user decision (no subtype-based fatal split).

### Why fatal voices synchronously instead of via the file watcher

`_make_speak_callback` gates on `shutdown.is_set()` at entry and
again after acquiring the inference lock. If the bridge appended a
fatal phrase to `agent.txt` and immediately set `shutdown`, the
watcher's poll cycle would fire on a closed shutdown gate and drop
the phrase. Calling `speak_fatal(phrase)` synchronously from the
bridge thread voices it before `shutdown` is set — the speak
callback's lock keeps it serialised against the listener's STT
inference, and `tts_active` flipping during playback gates the
listener cleanly.

### Recoverable phrases via the agent file (per continuity-doc plan)

Recoverable errors don't set `shutdown`, so the existing watcher
path is fine — phrase lands in `agent.txt`, watcher polls, speak
callback runs unblocked. Keeps the bridge thin and reuses the same
TTS pipeline as successful results.

### Phrases (final)

- Timeout (recoverable): `"Claude turn timed out."`
- Recoverable other (runner raised / non-JSON / is_error):
  `"Claude returned an error."`
- Non-zero exit (fatal): `"Session ended."`
- Missing `claude` binary mid-run (fatal): `"Claude command not
  found."`

### Deferred to post-3.0e polish (not in 3.0d)

- `--max-timeouts N` knob to escalate repeated recoverable timeouts
  to fatal shutdown. Out of 3.0d scope.

## 3.0d verification (partial)

- `uv run pytest -q` → 220 passed.
- `uv run ruff format src/cli/converse.py` + `ruff check` clean.
- `uv run python -c "from src.cli.converse import …"` imports OK.
- `uv run python cli.py converse --help` renders the same option
  surface (no flag changes in 3.0d).
- **Live test pending.** User must `./install.sh` then exercise each
  branch — the easiest fatal probe is `cai converse --session-id
  00000000-0000-0000-0000-000000000000` (startup probe rejects this
  before 3.0d kicks in, so for fatal the bridge needs a way to hit
  non-zero exit mid-session — see "How to live-test" below).

### How to live-test 3.0d

- **Recoverable timeout:** monkey-patch the runner factory or stub
  `subprocess.run` to raise `subprocess.TimeoutExpired`. Easier:
  drop the timeout to ~5s and hand `claude -p` a long prompt.
- **Recoverable is_error:** start two interactive `claude` sessions
  on the same id and inject a turn from `cai converse` while the
  other is mid-turn. (Same race that surfaced during 3.0c live-test.)
- **Fatal non-zero exit:** point `--session-id` at a real id, then
  delete the transcript file (or rename the cwd) so `claude -p`
  exits with an error mid-session. Or break network / log out of
  the Claude account between turns.
- **Fatal missing binary:** rename `claude` on PATH after startup
  succeeds and inject a turn.

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

- **3.0e** ← start here: wake-word gating via `build_wake_gate` (same
  knobs as `listen` / `dialogue`).
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
- `src/cli/wake_word.py:build_wake_gate` (slated for 3.0e)

## Key memory rules in force

- **Installer-before-live-CLI:** always run `./install.sh` before live
  testing `cai converse`. Shim at `~/.local/bin/cai` runs the installed
  copy, not the dev tree.
- **Pause between tasks:** user wants a checkpoint after each phase —
  do not autonomously chain 3.0d → 3.0e.
- **User drives commits.** Don't run `git commit`.
- **Shared test helpers** go in `tests/_<topic>.py` plain modules.

## Current git state

- Branch: `main`. Last commit `96d7483` ("Changed 'dialogue' to
  'converse' as commands.") shipped 3.0c.
- Uncommitted (3.0d only):
  - `M src/cli/converse.py` — `_speak_error` helper, `speak_fatal`
    parameter on `_make_bridge_callback`, recoverable/fatal split.
  - `M tasks/TODO.md` — 3.0d box checked with summary.
  - `M tasks/CONTINUITY.md` — this file.
- No untracked files.
- User drives commits. Don't run `git commit` autonomously.

## Next action after new session starts

1. Read this file (CONTINUITY.md) first.
2. If 3.0d hasn't been live-tested yet, walk the user through the
   four "How to live-test 3.0d" probes above before starting 3.0e.
3. Start **3.0e**: wake-word gating in `converse` via
   `build_wake_gate`. Mirror how `listen` and `dialogue` wire it up
   (same knobs); `_listener_loop` already accepts a `wake_gate`
   argument — `converse` currently passes `None` for it on line ~360.

## Out-of-scope right now

- Don't touch Features 4, 7, 8, or BUGS.md.
- The pre-existing B5.1 F401 in `tests/test_config.py:3` stays deferred.
- Don't start 3.1 in the same session as 3.0e.
- Don't write tests — that's 3.4.
- Don't write docs — that's 3.5.
