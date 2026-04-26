# Continuity notes — Feature 3 implementation

_Last updated: 2026-04-26 (after 3.2 ship + 3.2.5 audio-summary
skill authoring). Delete this file after Feature 3 lands._

## Where we are

- **3.0 runtime is feature-complete and committed.** Commits:
  - `34cd5ea` "More error cases handled" → 3.0e (wake-word gating).
  - `e17c088` "Better error handling in converse command" → 3.0d.
  - `96d7483` "Changed 'dialogue' to 'converse' as commands." → 3.0c.
  - 3.0a / 3.0b / housekeeping bullet shipped earlier.
- **3.1 + 3.2.5 skills authored, NOT YET COMMITTED.** Four SKILL.md
  files under `skills/<name>/SKILL.md` — `voice-mode`, `cai-dictation`,
  `cai-dialogue` (3.1), and `audio-summary` (3.2.5: spoken status
  pip Claude triggers from the terminal between sections; opt-in
  via user phrase, skips during `cai converse`).
- **3.2 shipped.** `src/cli/install_skill.py` + registration in
  `cli.py` and `MODEL_REQUIREMENTS`; `cai install-skill` and
  `cai uninstall-skill` work with `--mode voice-mode|dictation|
  dialogue|audio-summary|all`, `--target DIR`, `--force`. Smoke
  matrix all green (fresh install, conflict-without-force,
  --force overwrite, --mode subset, uninstall, repeat-uninstall
  no-op). Source resolution diverges from the `importlib.resources`
  hint — uses `Path(__file__).resolve().parents[2] / "skills"`
  instead, since `skills/` lives at the project root, not inside a
  Python package.
- **Live-test status:** 3.0a–c live-tested by the user during their
  respective phases. **3.0d, 3.0e, and all four skills are NOT yet
  live-tested.** See "Pending live tests" below for probe scripts.
- **Installer up-to-date as of this session.** `./install.sh` ran
  cleanly; the new `skills/` directory was copied to
  `~/.local/share/conversational_ai/skills/` (verified — three
  subdirs present). The shim at `~/.local/bin/cai` runs the latest
  build.
- **Pending: project-level install of the four skills.** The
  installer is now shipped; the original "install the skills in
  this project" intent resolves to one command run from the repo
  root: `cai install-skill --target .claude/skills`. Not yet
  executed — paused for user review before any commit and before
  this install. The user's `.claude/` had only `settings.local.json`
  the last time it was checked; `~/.claude/skills/` had only
  `safe-fetch`.

## Next action after compact

1. Read this file (CONTINUITY.md).
2. Skim the four `skills/<name>/SKILL.md` files (`voice-mode`,
   `cai-dictation`, `cai-dialogue`, `audio-summary`) to re-orient.
3. Pause for user review of 3.2 + 3.2.5 before any commit, before the
   project-level install, and before starting 3.3 / 3.4 / 3.5 or any
   pending live test.
4. When the user gives the go-ahead, run
   `cai install-skill --target .claude/skills` from the repo root —
   that resolves the original "install the skills in this project"
   intent and replaces the manual copy step that was interrupted.
5. The §3.2 spec below stays as historical record; 3.2 is shipped.

## 3.2 spec — `cai install-skill` / `cai uninstall-skill`

**File:** new `src/cli/install_skill.py`. Same module style as the
other subcommands (`@click.command`, `@click.pass_obj`, types
annotated, ≤500 lines).

**Source resolution:** use `importlib.resources` (or
`importlib.resources.files()`) so the installer works whether
running from the repo (`skills/` next to `cli.py`) or from the
installed copy at `~/.local/share/conversational_ai/skills/`. The
plan flags this explicitly. A small helper
`_resolve_skills_source() -> Path` keeps that logic in one place.

**`install-skill` flags:**

- `--mode voice-mode|cai-dictation|cai-dialogue|all` (default `all`).
  Note: the TODO calls these `voice-mode|dictation|dialogue|all` but
  the directories are `cai-dictation` / `cai-dialogue`. Keep the
  flag values short (`voice-mode|dictation|dialogue|all`) and map
  them internally to the directory names. Decide which during
  implementation; either is fine.
- `--target DIR` (default `~/.claude/skills`). Use this to support
  project-level installs (`--target .claude/skills`).
- `--force` to overwrite an existing `<target>/<name>/` dir. Without
  it, print a diff-style message and exit non-zero.

**`uninstall-skill` flags:**

- `--mode` and `--target` mirror install. Removes
  `<target>/<name>/` if it exists; no-op (with a friendly message)
  otherwise.

**PATH check (3.3-adjacent but cheap to do here):** at install
time, run `shutil.which("cai")` and warn (non-fatal, stderr) if
missing — pointing the user at `install.sh`. The skill bodies
assume `cai` is on PATH.

**Click registration:** add to `cli.py`:

```python
from src.cli.install_skill import install_skill, uninstall_skill
cli.add_command(install_skill, name="install-skill")
cli.add_command(uninstall_skill, name="uninstall-skill")
```

…and set both to `(False, False)` in `MODEL_REQUIREMENTS` (no model
loads needed for a file copy).

**Tests:** deferred to 3.4 (`tests/test_install_skill.py`). Don't
write them in 3.2.

**Idempotency:** without `--force`, repeating `install-skill` on an
existing target is a no-op-with-message. With `--force`, overwrite.
Use `shutil.copytree(..., dirs_exist_ok=True)` once we know the
target was either absent or `--force` is set.

**Out of scope for 3.2:** SKILL.md content edits, doc sweeps,
skill-loading verification flows. Just the file-copy/uninstall
plumbing.

## Pending live tests

Once 3.2 ships, drive these in order. They cover everything that
hasn't been live-validated yet.

### 3.0e — wake-word gating in converse

```
cai converse --wake-word computer
```

Speak `"what is the weather"` → bridge does NOT receive the prompt;
nothing in `~/.local/state/conversational_ai/converse/human.txt`
(after gating).

Speak `"computer what is the weather"` → trigger fires (chime +
stderr echo), prompt flows through `claude -p`, agent reply voiced.

Optional: `--strip-trigger` to confirm the trigger word is removed
from what `claude -p` sees; `--no-wake-word` for the always-pass
control case.

### 3.0d — error handling

Stub `claude` binaries on a temp PATH:

```bash
mkdir -p /tmp/cai-stubs

# A. Fatal non-zero exit:
cat > /tmp/cai-stubs/claude <<'EOF'
#!/bin/bash
echo "stub error" >&2
exit 1
EOF
chmod +x /tmp/cai-stubs/claude
```

```bash
# B. Recoverable timeout (>300s — the hardcoded
# _CLAUDE_HEADLESS_TIMEOUT_SECONDS in src/cli/__init__.py):
cat > /tmp/cai-stubs/claude <<'EOF'
#!/bin/bash
sleep 400
EOF
chmod +x /tmp/cai-stubs/claude
```

```bash
# C. Fatal missing binary mid-run (passes startup, deletes self):
cat > /tmp/cai-stubs/claude <<'EOF'
#!/bin/bash
rm "$0"
echo '{"is_error":false,"result":"ok","session_id":"stub","subtype":"success"}'
EOF
chmod +x /tmp/cai-stubs/claude
```

Run with `PATH=/tmp/cai-stubs:$PATH cai converse`.

| Stub | First utterance | Second utterance |
|------|------------------|------------------|
| A | TTS speaks `"Session ended."`, process shuts down. | — |
| B | After ~5 min, TTS `"Claude turn timed out."`, bridge stays alive. | Same recoverable behavior. |
| C | TTS speaks `"ok"` (success). | TTS `"Claude command not found."`, shutdown. |

For faster timeout testing, drop
`_CLAUDE_HEADLESS_TIMEOUT_SECONDS` in `src/cli/__init__.py` to e.g.
`5.0`, re-run `./install.sh`, restore after.

### Recoverable is_error race (already validated in 3.0c)

Open `claude` interactively on the same id; inject turns from both
sides simultaneously. Bridge logs is_error and TTS speaks
`"Claude returned an error."`. No shutdown.

### 3.1 — skill loadout (post-3.2 install)

After `cai install-skill --target .claude/skills` (or whatever the
final flag surface is), open Claude Code in this repo:

- Trigger `voice-mode` by saying / typing "switch to voice mode"
  during a `cai converse` session — verify the description-trigger
  picks it up and the body shapes the reply (short sentences, no
  tables, etc.).
- Trigger `cai-dictation` with "transcribe my next thought to a
  file" — Claude should propose `cai listen FILE` or `cai
  transcribe -o FILE`.
- Trigger `cai-dialogue` with "set up a continuous voice scratchpad
  with one file feeding the speaker and another collecting my
  voice" — Claude should propose `cai dialogue --speak-file …
  --listen-file …`.
- Trigger `audio-summary` by telling Claude in a non-converse
  session "give me audio summaries while you work" or similar.
  After Claude finishes the next discrete unit of work it should
  invoke `cai speak "<≤2 sentences>"` and continue. Confirm: pip
  fires once per section (not per file), is short, doesn't read
  code aloud, and skips when you switch to `cai converse`.

If a description doesn't trigger reliably, tighten its phrasing —
the body content is more forgiving than the description.

## Key architectural decisions (settled)

- **Backend:** `claude -p "<line>" --resume <id> --output-format
  json` per turn. Blocking in v1; streaming on roadmap.
- **Session resolution:** `--session-id` (explicit, with startup
  probe), `--resume` (last persisted from
  `~/.local/state/conversational_ai/session`), default fresh.
  Mutex on the two flags.
- **Test seam:** `claude_runner_factory: Callable` on `CliContext`
  (default `_default_claude_runner` with 300s timeout). Tests in
  3.4 will swap this for a fake.
- **Cwd inherited.** `install.sh` shim preserves cwd so transcripts
  resolve under `~/.claude/projects/<cwd-slug>/`. Documented in
  `cai converse --help` and the `voice-mode` skill.
- **No voice-stop in v1.** Roadmap.
- **Skill set:** `voice-mode` (primary, style guide for spoken
  replies), `cai-dictation` (drive transcribe/listen),
  `cai-dialogue` (drive dialogue + duplex matrix).

## Reused primitives (no further changes)

- `src/cli/dialogue.py:_listener_loop` (lines 84-174)
- `src/cli/dialogue.py:_make_speak_callback` (lines 24-81)
- `src/cli/watch.py:TextFileHandler`
- `src/cli/wake_word.py:build_wake_gate` (now wired into converse).

## Key memory rules in force

- **Installer-before-live-CLI:** always run `./install.sh` before
  live-testing the `cai` shim. The shim at `~/.local/bin/cai`
  runs the installed copy, not the dev tree.
- **Pause between tasks:** user wants a checkpoint after each
  phase — do not autonomously chain 3.2 → 3.3.
- **User drives commits.** Don't run `git commit`.
- **Shared test helpers** go in `tests/_<topic>.py` plain modules
  (3.4 will follow this).
- **Propose resequencing** if 3.2 implementation reveals an
  ordering problem; don't silently rearrange.

## Current git state (pre-compact)

- Branch: `main`. HEAD `34cd5ea` (3.0e wake-word gating).
- Uncommitted (3.1 + doc updates):
  - `M tasks/TODO.md` — 3.0d, 3.0e, "Register converse"
    housekeeping, and 3.1 boxes checked.
  - `M tasks/CONTINUITY.md` — this file.
- Untracked: `skills/voice-mode/SKILL.md`,
  `skills/cai-dictation/SKILL.md`, `skills/cai-dialogue/SKILL.md`.
- 220 tests passing as of last `uv run pytest -q`.

## Out-of-scope right now

- Don't touch Features 4, 7, 8, or BUGS.md.
- The pre-existing B5.1 F401 in `tests/test_config.py:3` stays
  deferred.
- Don't start 3.3 in the same session as 3.2.
- Don't write tests — that's 3.4.
- Don't write docs (PRD/README/CONTRIBUTING/ARCHITECTURE) — that's
  3.5. The skill bodies themselves are docs and are in scope for
  3.1, but we keep them as authored unless content edits surface
  during live testing.
