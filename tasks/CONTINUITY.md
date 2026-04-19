# Continuity notes — Feature 3 implementation

_Last updated: 2026-04-19. Delete this file after Feature 3 lands._

## Where we are

- **Mode:** plan approved, out of plan mode, ready to start coding.
- **Plan file:** `/Users/john/.claude/plans/stateful-stirring-pixel.md`
  (Feature 3 — Voice conversation with Claude Code + skill ecosystem).
- **Refinement answers:** `tasks/TASK-REFINEMENT.md` — all 8 questions
  answered; plan has been updated to reflect them.
- **TODO sync:** `tasks/TODO.md` §Feature 3 has been rewritten to match the
  approved plan (3.0 runtime inserted before 3.1-3.5; 3.1 now ships 3
  skills including `voice-mode`; roadmap section added).
- **Status:** ready to start **3.0a** (stub `src/cli/converse.py` with
  three-thread skeleton, echo-back bridge). **Not started yet.** User
  asked to start a fresh session before any code is written.

## User's goals (verbatim paraphrase)

- **Primary:** converse with LLMs in audio instead of typing/reading.
- **Secondary:** accessibility (slow typists, reading/seeing difficulties).
- Voice mode must **extend the existing Claude Code session**, not spawn
  a parallel one (Q1 answer).

## Key architectural decisions (baked into the plan)

- **New subcommand `cai converse`** — three threads, all in one process:
  - listener (re-use `src/cli/dialogue.py:_listener_loop`, lines 84-174
    → writes transcriptions to `human.txt`)
  - bridge (NEW: tail `human.txt` → `claude -p "<line>" --resume <sid>
    --output-format json` → append to `agent.txt`)
  - watcher (re-use `src/cli/watch.py:TextFileHandler` +
    `src/cli/dialogue.py:_make_speak_callback`, lines 24-81)
- **Session resolution:** ship all three methods (Q4 answer):
  1. `cai converse --session-id <id>` — explicit attach (primary path
     when invoked from the voice-mode skill)
  2. `cai converse --resume` — load from
     `~/.local/state/conversational_ai/session`
  3. `cai converse` (no flag) — fresh; capture session id from first
     call's `--output-format json`; persist
- **Validation:** probe session id at startup; on invalid → exit 1 cleanly.
  Mid-session invalidation (nonzero exit from `claude -p`) → speak "session
  ended" + set shutdown.
- **Blocking in v1** (Q5); streaming on roadmap.
- **No voice-stop in v1** (Q6); on roadmap.
- **Cwd inherited** (Q7); document in help + SKILL.md.
- **Test seam:** add `claude_runner_factory: Callable` to `CliContext` so
  tests don't spawn real `claude`. Follows the existing
  `recorder_factory`/`speaker_factory` pattern.
- **Skills shipped in 3.1 (all three):** `voice-mode` (primary — style
  guide for Claude when spoken to), `cai-dictation`, `cai-dialogue`.

## Implementation sequence (approved, pause between phases)

1. **3.0a** — `src/cli/converse.py` skeleton: three-thread loop with
   echo-back bridge (no `claude` yet). Verify mic → STT → bridge → TTS.
2. **3.0b** — Session resolution: `--session-id` / `--resume` flags (mutex),
   state file helpers at `~/.local/state/conversational_ai/session`,
   probe-validate at startup.
3. **3.0c** — Wire `claude -p "<line>" --resume <id> --output-format json`
   into the bridge; parse response; persist session id on success.
4. **3.0d** — Error handling (timeout, nonzero exit, missing binary).
5. **3.0e** — Wake-word gating via `build_wake_gate`.
6. **3.1** — Author 3 SKILL.md files (voice-mode, cai-dictation,
   cai-dialogue).
7. **3.2** — `cai install-skill` / `cai uninstall-skill` subcommands.
8. **3.3** — PATH check (`shutil.which("cai")`).
9. **3.4** — Tests (`test_converse.py`, `test_install_skill.py`).
10. **3.5** — Docs sweep (PRD, README, CONTRIBUTING, ARCHITECTURE, TODO
    Review subsection).

## Reused primitives (no changes needed)

- `src/cli/dialogue.py:_listener_loop` (lines 84-174)
- `src/cli/dialogue.py:_make_speak_callback` (lines 24-81)
- `src/cli/watch.py:TextFileHandler`
- `src/cli/wake_word.py:build_wake_gate`
- `src/cli/__init__.py:CliContext` (add `claude_runner_factory` field)

## Files to create / modify (from plan)

**New:**
- `src/cli/converse.py`
- `src/cli/install_skill.py`
- `skills/voice-mode/SKILL.md`
- `skills/cai-dictation/SKILL.md`
- `skills/cai-dialogue/SKILL.md`
- `tests/test_converse.py`
- `tests/test_install_skill.py`

**Modified:**
- `cli.py` (register converse, install-skill, uninstall-skill)
- `src/cli/__init__.py` (MODEL_REQUIREMENTS + claude_runner_factory)
- `tasks/TODO.md` (already done this session)
- `PRD.md`, `README.md`, `CONTRIBUTING.md`, `tasks/ARCHITECTURE.md` (3.5)

## Key memory rules in force

- **Installer-before-live-CLI:** always run `install.sh` before live
  testing `cai converse`. The shim at `~/.local/bin/cai` runs the
  installed copy, not the dev tree.
- **Pause between tasks:** user wants a checkpoint after each phase
  (3.0a, 3.0b, etc.) — do not autonomously chain phases.
- **Propose resequencing:** already done; accepted.
- **User drives commits.** Don't run git commit.
- **Shared test helpers** go in `tests/_<topic>.py` plain modules, not
  conftest.py.

## Next action after new session starts

1. Read this file (CONTINUITY.md) first.
2. Read `/Users/john/.claude/plans/stateful-stirring-pixel.md` for the full
   plan detail.
3. Spot-check `tasks/TODO.md` §Feature 3 — it's already synced, no
   re-write needed.
4. Start **3.0a**: stub `src/cli/converse.py` with the three-thread
   echo-back skeleton. Keep diff minimal; pause for user review when
   3.0a is runnable.

## Out-of-scope right now

- Don't touch Features 4, 7, 8, or BUGS.md items.
- The pre-existing B5.1 F401 in `tests/test_config.py:3` stays deferred.
- Don't start 3.0b-3.0e in the same session as 3.0a — pause between.
