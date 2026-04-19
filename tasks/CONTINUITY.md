# Continuity notes — Feature 3 implementation

_Last updated: 2026-04-19 (after 3.0b live-test). Delete this file after
Feature 3 lands._

## Where we are

- **Completed:** 3.0a (three-thread echo-back skeleton) and 3.0b
  (session resolution: `--session-id`, `--resume`, mutex, state file,
  startup probe). Both live-tested by user.
- **Next up:** 3.0c — wire `claude -p "<line>" --resume <id>
  --output-format json` into the bridge; add `claude_runner_factory` to
  `CliContext`; persist resolved id on successful turn.
- **Mode:** out of plan mode, coding. Plan approved.
- **Plan file:** `/Users/john/.claude/plans/stateful-stirring-pixel.md`
- **Refinement answers:** `tasks/TASK-REFINEMENT.md`
- **TODO sync:** `tasks/TODO.md` §Feature 3 updated — 3.0a/3.0b boxes
  checked.

## What 3.0b shipped (uncommitted in the working tree)

### `src/cli/converse.py`

- Helpers (inline, under 30 lines each — no separate `_session.py` yet):
  - `_cwd_slug()` — Claude Code project-dir slug rule: `/` and `_` →
    `-`. Verified against `~/.claude/projects/-Users-john-ai-bits-conversational-ai/`.
  - `_read_last_session_id()` / `_write_last_session_id(id)` —
    `~/.local/state/conversational_ai/session`, one line, best-effort.
  - `_probe_session(id)` — raises `click.ClickException` if
    `~/.claude/projects/<slug>/<id>.jsonl` is missing. Exit 1 before
    threads start.
  - `_resolve_session_id(session_id, resume)` — mutex (UsageError),
    `--resume` empty state → UsageError, default → None.
- New Click options: `--session-id UUID`, `--resume`.
- Bridge closure now takes `session_id` (unused in echo body; threaded
  through for 3.0c). Log prefix shows `[bridge:<id>]` when set.
- Docstring updated: "3.0b: session resolution, echo-back bridge".

### `install.sh` — CRITICAL FIX

Shim was using `uv run --directory "$INSTALL_DIR"` which `cd`s into the
installed copy before exec, so `Path.cwd()` returned
`/Users/john/.local/share/conversational_ai` and the slug came out
`-Users-john-.local-share-conversational-ai` — probe always failed.
Switched to `uv run --project "$INSTALL_DIR" python "$INSTALL_DIR/cli.py"`.
`--project` sets uv's project root without changing cwd. Caller's cwd
now reaches `Path.cwd()` inside the Python process.

Re-run `./install.sh` after any dev change that relies on caller cwd.

## 3.0b verification (done)

- Dev-tree helpers exercised: slug matches real project dir; mutex,
  empty-`--resume`, fresh (None), and invalid-id probe all behave.
- `uv run python cli.py converse --help` shows new flags.
- `./install.sh` + `cai converse --help` confirmed 3.0b.
- User live-tested: valid attach, invalid probe, `--resume`, mutex — all
  return as expected.

## Tests NOT written for 3.0b (intentional)

Tests land in 3.4 (`tests/test_converse.py`) once `claude_runner_factory`
(3.0c) gives us a stable surface to fake against. The session helpers
are testable in isolation now, but we'll bundle them into the 3.4 pass.

## Immediate next step: 3.0c — Wire `claude -p` into the bridge

Scope (from TODO.md and plan):

1. Add `claude_runner_factory: Callable[..., subprocess.CompletedProcess]`
   (or similar typed alias) to `src/cli/__init__.py:CliContext` with a
   default that actually shells out. This is the test seam.
2. Default runner invokes:
   `claude -p "<line>" --resume <id> --output-format json`
   via `subprocess.run(..., capture_output=True, text=True, timeout=…)`.
3. Replace the 3.0a/b echo body in `_make_bridge_callback` with:
   - call the runner,
   - parse JSON output (shape TBD — check `--output-format json` schema
     live; likely `{"result": "…", "session_id": "…", ...}`),
   - append the result text to `agent_path`,
   - if the response carries a session id (new session case, no prior
     `--session-id` was passed), capture and persist it via
     `_write_last_session_id`.
4. Keep `--resume <id>` only when a resolved id exists. For a fresh
   session, first turn runs `claude -p "<line>"` (no `--resume`), then
   subsequent turns use the captured id.
5. Pre-flight check in the command body (before threads): verify
   `shutil.which("claude")` and fail fast with `click.ClickException` if
   missing. (This is technically 3.0d's "missing binary" case but it's
   cheap and belongs at startup, so lift it now.)

Open questions to answer empirically before coding:

- What does `claude -p "hello" --output-format json` actually emit?
  Confirm the JSON schema — keys for result text, session id, success
  flag, stop reason. Run once by hand in a throwaway dir before writing
  the parser.
- Does `--resume <unknown-id>` error or silently start fresh? Probe
  result will inform 3.0d error copy.
- Stdin? Plan says pass the prompt as `-p "<text>"`, not stdin. Confirm
  that's still the supported surface.

No error handling beyond the pre-flight in 3.0c. Timeout, nonzero exit,
and mid-session failure land in 3.0d.

## Key architectural decisions (unchanged; restated for continuity)

- **Session resolution (Q4):** `--session-id`, `--resume`, default
  fresh — all three shipped in 3.0b.
- **Backend:** `claude -p "<line>" --resume <id> --output-format json`
  per turn.
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

- **3.0c** ← start here: wire `claude -p --resume <id>`; add
  `claude_runner_factory`; persist resolved id on success.
- **3.0d:** error handling (subprocess timeout, nonzero exit, missing
  `claude` binary at runtime).
- **3.0e:** wake-word gating via `build_wake_gate`.
- **3.1:** three SKILL.md files.
- **3.2:** `cai install-skill` / `cai uninstall-skill`.
- **3.3:** PATH check (`shutil.which("cai")`) in installer.
- **3.4:** tests.
- **3.5:** docs sweep.

## Reused primitives (no changes needed)

- `src/cli/dialogue.py:_listener_loop` (lines 84-174)
- `src/cli/dialogue.py:_make_speak_callback` (lines 24-81)
- `src/cli/watch.py:TextFileHandler`
- `src/cli/wake_word.py:build_wake_gate` (not used until 3.0e)

## Files that will be touched in 3.0c

**Modified:**
- `src/cli/__init__.py` — add `claude_runner_factory` field to
  `CliContext` with a sensible default.
- `src/cli/converse.py` — swap echo body for real subprocess call;
  parse JSON; capture/persist session id on success; add `shutil.which`
  startup check.

**Unchanged in 3.0c:**
- `cli.py` — already wired.
- `install.sh` — shim already correct.
- Docs — deferred to 3.5.
- Tests — deferred to 3.4.

## Key memory rules in force

- **Installer-before-live-CLI:** always run `./install.sh` before live
  testing `cai converse`. Shim at `~/.local/bin/cai` runs the installed
  copy, not the dev tree.
- **Pause between tasks:** user wants a checkpoint after each phase —
  do not autonomously chain 3.0c → 3.0d.
- **User drives commits.** Don't run `git commit`.
- **Shared test helpers** go in `tests/_<topic>.py` plain modules.

## Current git state

- Branch: `main`
- Uncommitted changes across 3.0a + 3.0b (all in working tree):
  - New: `src/cli/converse.py`
  - Modified: `cli.py`, `src/cli/__init__.py`, `install.sh`, `tasks/TODO.md`
- Pre-existing uncommitted (from earlier sessions):
  `tasks/TASK-REFINEMENT.md`, `tasks/CONTINUITY.md`, `CONTRIBUTING.md`.
- The user has not asked for a commit yet.

## Next action after new session starts

1. Read this file (CONTINUITY.md) first.
2. Skim `src/cli/converse.py` to re-orient on current shape.
3. Empirically probe `claude -p "…" --output-format json` output in a
   throwaway directory before writing the parser.
4. Start **3.0c**: wire the subprocess call. Keep diff minimal. Don't
   touch tests or docs. Pause for user review when runnable.

## Out-of-scope right now

- Don't touch Features 4, 7, 8, or BUGS.md.
- The pre-existing B5.1 F401 in `tests/test_config.py:3` stays deferred.
- Don't start 3.0d/3.0e in the same session as 3.0c.
- Don't add timeout or error-path handling — that's 3.0d.
