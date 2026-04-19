# TODO: Mic Controls, Wake Word, Claude Skill

Three features, landed in order so each one can lean on the previous.
Plus housekeeping tasks for architecture docs, test quality, and file size.

---

## Task 0 — Architecture review and doc sync

**Goal:** Bring `tasks/ARCHITECTURE.md` and `PRD.md` up to date with the
current codebase before adding more features. Stale docs mislead future
sessions and make onboarding harder.

### 0.1 ARCHITECTURE.md

- [x] Add `MicSettings` to the Configuration section (alongside existing
      `[server]`, `[tts]`, `[stt]`, `[limits]`).
- [x] Add `mic_recorder_from_settings()` to the CLI Audio I/O component
      diagram and the Microphone Recording Flow sequence diagram.
- [x] Document the min-speech-duration gate and calibration pass in the
      MicRecorder section.
- [x] Add `tests/test_cli_subcommands.py` and `tests/test_config.py` to
      the file structure tree.
- [x] Add Feature 1 CLI flags (`--mic-threshold`, `--mic-silence`,
      `--mic-min-speech`, `--calibrate-noise`) to the CLI Overrides table.
- [x] Note the `[wake_word]` config section as planned (Feature 2).

### 0.2 PRD.md

- [x] Reconcile documented-but-unimplemented flags:
      `--duration` and `--no-vad` on `cai transcribe`,
      `--debounce` on `cai watch`.
      Either implement them or remove from the PRD with a note.
- [x] Add mic noise-floor controls (Feature 1) to the Audio I/O and
      Shared Configuration sections.
- [x] Add wake word (Feature 2) as a new subsection once implemented.

### Review — Task 0

**Status:** Doc sync complete; 189/189 tests still passing (doc-only change).

**What shipped:**
- `tasks/ARCHITECTURE.md` — overview reframed CLI-first; file structure
  updated (added `src/cli/serve.py`, all missing tests, dropped the
  "deprecated config.toml" note in favor of the XDG bootstrap); full
  `_DEFAULT_TOML` expanded into the Configuration section with all seven
  sections (`[server]`, `[tts]`, `[stt]`, `[models]`, `[dialogue]`, `[mic]`,
  `[limits]`, `[log]`); `[wake_word]` noted as planned; CLI Overrides split
  into global + per-subcommand tables covering the mic flags;
  Microphone Recording Flow diagram expanded with calibration pre-pass,
  min-speech gate, pre-latch ring flush, `on_speech_start` signal, and a
  prose section on MicRecorder behavior; Dialogue Mode Threading diagram
  rewritten with `barge_event` (barge-in) and `tts_active` (half-duplex)
  gates; file-watcher poll interval corrected 100ms → 300ms; dependencies
  block expanded with `transformers==5.3.0` and the CONTRIBUTING pin note.
- `PRD.md` — Problem/Goals reframed CLI-and-API (CLI-first); flag lists
  fixed for `speak` (`--file`, not `--input-file`; voice/speed are global),
  `transcribe` (mic flags; `--duration` / `--no-vad` moved to a "Not yet
  implemented" note linking Feature 4), `watch` (removed non-existent
  `--voice`/`--speed`/`--lang-code`/`--debounce`; noted the 300ms poll
  interval), `listen` (mic flags; timestamps deferred to Feature 8),
  `dialogue` (files made optional with `[dialogue]` defaults; mic flags
  added; added Duplex modes matrix referencing README); Shared Configuration
  lists all config sections; Audio I/O section covers calibration + EMA +
  pre-latch ring; Entry Point section fixed; Future work section added.
- `README.md` — lead line reframed as "terminal-first TTS/STT platform"
  with API positioned as companion; Configuration snippet rewritten to
  match `_DEFAULT_TOML` (port 4114, all sections); API curl examples
  updated 8000 → 4114 (two sites); Development test count 79 → 189;
  global-options table gained `--models-dir`; new Mic flags subsection
  covering transcribe/listen/dialogue; Project layout tree updated with
  `src/cli/serve.py` and `logging_setup.py`.
- `CONTRIBUTING.md` — Architecture overview reframed CLI + HTTP API;
  module map rewritten (removed the stale "argparse" note on `main.py`;
  added all CLI modules and `logging_setup.py`); added a "CLI threading
  model" note covering `barge_event` / `tts_active`; XDG bootstrap
  documented; test count 79 → 189 with new test-file rows; Common tasks
  updated (`cai serve` / `cai speak`; port 8000 → 4114 in three curl
  snippets; `python main.py --tts-model …` → `cai --tts-model … speak`).
- `CLAUDE.md` — Project Context rewritten CLI-first per user decision
  (option 2 from the plan's vision-alignment review); API positioned as
  companion for browser clients; stack expanded with `Click` and
  `sounddevice`; XDG config path noted.

**Test count surprise:**
Plan's Review noted 178 tests (matching the Feature 1 Review). Actual is
189 — 11 additional tests have landed since Feature 1 was reviewed. Updated
README + CONTRIBUTING to reflect the current count.

**Deferred (Feature 2 scope):**
- 0.2 "Add wake word (Feature 2) as a new subsection once implemented" —
  intentionally left unchecked. Will land with Feature 2.

### Addendum (2026-04-18) — 0.2 final closure

Last remaining 0.2 checkbox flipped as part of Feature 2 shipping. PRD now
has a dedicated **Wake word** subsection under Duplex modes, plus wake-word
options listed on `cai listen` and `cai dialogue` and a `[wake_word]` block
in Shared Configuration. Task 0 fully closed.

---

## Feature 1 — Mic noise-floor controls

**Goal:** filter keyboard clacks and household noise without hand-tuning a
magic constant per room. Ship configurable thresholds + an opt-in noise
calibration pass + a minimum-speech-duration gate.

### 1.1 Make `MicRecorder` params instance-level

- [x] Convert `MicRecorder` class constants (`RMS_THRESHOLD`, `SILENCE_SECONDS`,
      `CHUNK_SECONDS`) to `__init__` params with the current values as defaults.
- [x] Add new param `min_speech_seconds: float = 0.15` — consecutive chunks
      above threshold required before `speech_detected` latches. Kills single
      keystroke / door-slam false positives.
- [x] Update `_callback` to count consecutive above-threshold chunks and only
      set `speech_detected` once the count ≥ `min_speech_chunks`.
- [x] Unit-test in `tests/test_cli_audio_io.py`: single loud chunk does not
      latch; sustained chunks do; silence counter still works.

### 1.2 Config plumbing

- [x] Add `[mic]` section to `src/config.py` (Pydantic `MicSettings` submodel):
      `rms_threshold: float = 0.01`, `silence_seconds: float = 1.5`,
      `min_speech_seconds: float = 0.15`, `calibrate_noise: bool = False`,
      `calibration_seconds: float = 1.0`, `calibration_multiplier: float = 3.0`.
- [x] Update `config.toml` with a commented `[mic]` block showing defaults.
- [x] `tests/test_config.py`: TOML load + CLI override coverage for `[mic]`.

### 1.3 CLI flags

- [x] Add flags to `transcribe`, `listen`, `dialogue`:
      `--mic-threshold`, `--mic-silence`, `--mic-min-speech`, `--calibrate-noise/--no-calibrate-noise`.
- [x] Wire each subcommand to build `MicRecorder` from merged settings.

### 1.4 Noise-floor calibration

- [x] New method `MicRecorder.calibrate(seconds: float) -> float` — opens a
      short `InputStream`, collects RMS over `seconds`, returns the measured
      floor.
- [x] On `record()`, if `calibrate_noise=True`, run calibration once (cache
      the result on the instance), then set effective threshold =
      `max(configured_threshold, measured_floor * multiplier)`.
- [x] Log both values at INFO so users can see what was chosen.
- [x] `listen` and `dialogue` run calibration once at startup, not per-utterance.
- [x] `transcribe` skips calibration by default (one-shot UX); opt in with
      `--calibrate-noise`.

### 1.5 Verify

- [x] All existing `tests/test_cli_audio_io.py` tests still pass.
- [x] New tests for `min_speech_seconds` gate and calibration math.
- [ ] Live check on real hardware: clack the keyboard during `cai transcribe`,
      verify it does not trigger a recording. (user-driven — requires mic)

### Review — Feature 1

**Status:** Code + tests complete. 178/178 passing (162 → 178, +16 new).
Awaiting user-driven hardware validation.

**What shipped:**
- `MicRecorder.__init__` now accepts `rms_threshold`, `silence_seconds`,
  `min_speech_seconds`, `calibrate_noise`, `calibration_seconds`,
  `calibration_multiplier`. Class constants remain as defaults so the
  zero-arg constructor still works (and the existing test references to
  `MicRecorder.RMS_THRESHOLD` etc. keep passing).
- **Min-speech gate:** the VAD state machine now requires
  `min_speech_chunks` consecutive above-threshold chunks before latching.
  A single loud transient increments the streak and is immediately reset
  by the next silent chunk. The pre-latch audio is ring-buffered so the
  leading edge of the utterance is preserved once the gate trips.
- **Calibration:** `MicRecorder.calibrate()` opens a short `InputStream`,
  averages per-chunk RMS over the configured window, and sets
  `_effective_threshold = max(configured, measured_floor * multiplier)`.
  Logged at INFO. `listen` and `dialogue` call it once at startup;
  `transcribe` skips it by default but respects `--calibrate-noise`.
- `mic_recorder_from_settings()` helper wires `MicSettings` → recorder
  kwargs with an optional `calibrate_override` (so CLI flags can force
  calibration on/off without mutating the config).
- New CLI flags on all three mic-using subcommands: `--mic-threshold`,
  `--mic-silence`, `--mic-min-speech`, `--calibrate-noise/--no-calibrate-noise`.
- `[mic]` section added to `src/config.py` (Pydantic `MicSettings` with
  range validators) and the default TOML template.

**Float-rounding gotcha (fixed mid-implementation):**
`int(0.15 / 0.05)` evaluates to 2, not 3, because of float representation.
Switched both `silence_chunks_needed` and `min_speech_chunks` to
`max(1, round(...))` so the configured seconds translate to the expected
chunk counts.

**Tests added (+16):**
- `TestMicRecorderMinSpeechGate` (3): single burst does not latch,
  sustained chunks latch at exactly N=3, streak resets on silence.
- `TestMicRecorderCalibration` (4): effective-threshold math in both
  directions, defaults when not calibrated, full `calibrate()` run
  against a fake stream.
- `TestMicRecorderFromSettings` (4): settings passthrough, override
  forces on, override forces off, None respects settings.
- `tests/test_config.py` (+5): defaults, TOML overrides, CLI overrides,
  threshold validation, multiplier validation.

**Test patch migration:**
`test_cli_subcommands.py` previously patched `src.cli.transcribe.MicRecorder`
/ `src.cli.listen.MicRecorder` / `src.cli.dialogue.MicRecorder`. The first
two no longer import the class directly, so those patches moved to
`mic_recorder_from_settings` in the same modules. `_listener_loop`'s
default-recorder path in dialogue still instantiates `MicRecorder()`
directly, so those patches stayed put. The `dialogue` command-level test
moved to patching the factory helper.

**Rough edges (not fixed, not worth a BUGS entry yet):**
- Calibration runs once at startup and never re-samples. Long-running
  `listen` / `dialogue` sessions won't adapt to a noise-floor shift
  (HVAC kicking on, fan speed change). Deferrable — re-run via Ctrl+C
  and restart is a fine workaround.
- The pre-latch ring buffer is sized to `min_speech_chunks`, so the
  preserved leading audio is ≈`min_speech_seconds` of context. Short
  utterances ("yes") that clip before the gate trips may lose a
  millisecond or two of onset. Acceptable for Whisper — it pads internally.

---

## Feature 2 — Wake word / trigger word (Option A: rolling Whisper)

**Goal:** `cai listen` and `cai dialogue` ignore speech until the user says a
configurable trigger word (default: `"computer"`). Uses the already-loaded
Whisper model on short utterances — plenty of headroom on M3 Ultra / 512 GB.

### 2.1 Design

- [x] New module `src/cli/wake_word.py` with a `WakeWordGate` class.
      (API renamed from `WakeWordDetector` — gate-at-sink pattern rather
      than loop-owning detector. See Review below.)
- [x] API shape — final form:
      ```python
      class WakeWordGate:
          def __init__(
              self, word: str, *,
              include_trigger: bool = False,
              timeout_seconds: float = 30.0,
              alert_sound: bool = True,
              clock: Callable[[], float] = time.monotonic,
              chime: Callable[[], None] | None = None,
              echo: Callable[[str], None] | None = None,
          ) -> None: ...
          def filter(self, text: str) -> str | None: ...
      ```
- [x] Matching is case-insensitive, anchored-to-start, trigger followed by
      punctuation or end-of-string (regex
      `^\s*(TRIGGER)(?:[.,!?;:]+|$)\s*(.*)$`). Rejects "computer science";
      accepts "Computer, hello" → "hello"; accepts "Computer?!" with empty rest.
      (Stricter than the original `\btrigger\b` plan — relies on Whisper's
      pause-punctuation behavior as the distinguishing signal.)
- [x] `include_trigger=False` (default) emits only the post-trigger tail;
      `include_trigger=True` emits the full transcript.

### 2.2 Config plumbing

- [x] Add `[wake_word]` section to `src/config.py`:
      `enabled: bool = False`, `word: str = "computer"`,
      `include_trigger: bool = False`, `timeout_seconds: float = 30.0`,
      `alert_sound: bool = True`.
- [x] `timeout_seconds` = sliding open-window timeout. Every passing
      utterance extends the window via `_last_pass_at`; if no utterance
      arrives within `timeout_seconds` of the last pass, the gate re-arms.
- [x] Default TOML template (`_DEFAULT_TOML` in `src/config.py`) updated
      with `[wake_word]` block.
- [x] `tests/test_config.py`: coverage for `[wake_word]` (+5 tests:
      defaults, TOML overrides, CLI merge, non-positive timeout rejected,
      timeout > 600 rejected).

### 2.3 Integration

- [x] `listen` subcommand: wake-gate filter applied between
      `result.text.strip()` and the file append — no separate loop wrapping.
- [x] `dialogue` subcommand: same gate-at-sink placement inside
      `_listener_loop`. Composes cleanly with `barge_in` (VAD) and
      `full_duplex` (mic gating) as a third, independent layer — no new
      locks, no deadlock surface.
- [x] CLI flags on both commands: `--wake-word WORD` (forces enabled=true),
      `--no-wake-word`, `--wake-timeout SECONDS`,
      `--include-trigger/--strip-trigger`, `--wake-alert/--no-wake-alert`.
      `--wake-word` and `--no-wake-word` are mutually exclusive (UsageError).
- [x] `transcribe` intentionally skipped — one-shot, user already
      initiated it by running the command.

### 2.4 Tests

- [x] `tests/test_wake_word.py`: 19 unit tests across 6 classes
      (TriggerMatching, IncludeTrigger, OpenWindow, TimeoutRearm,
      AlertFeedback, Validation) — case/punctuation, strip vs include,
      sliding timeout via injected scripted clock, chime failure
      tolerance.
- [x] CliRunner tests: `tests/test_listen.py` (+2: flow coverage and
      mutual-exclusion); `tests/test_dialogue.py` (+1: listener-loop
      integration with a real gate and STT iterator).
- [x] Live check: `cai listen out.txt --wake-word computer` — talking random
      noise does nothing; saying "computer, hello world" appends "hello world".
      Verified 2026-04-18: wake fired on "computer", four follow-up
      utterances passed through cleanly within the sliding window, stderr
      echo + trigger-strip both behaved as designed.

### 2.5 Docs

- [x] Update `README.md` CLI section with wake-word usage + config example.
- [x] Update `PRD.md` with the wake-word feature in a new subsection.
- [x] Update `tasks/ARCHITECTURE.md` with `wake_word.py` in the file tree,
      `[wake_word]` config block, CLI Overrides entries, reworked Dialogue
      Mode Threading prose, and a dedicated Wake-Word Gate section.

### Review — Feature 2

**Status:** Code + tests + docs complete. 220/220 tests passing (193 → 220,
+27 new). Awaiting user-driven hardware validation of the live flow.

**What shipped:**
- `src/cli/wake_word.py` (new, 166 lines) — `WakeWordGate` class with
  `filter(text) -> str | None` that returns `None` to drop, or the
  emitted string to pass through. `build_wake_gate()` helper merges
  `WakeWordSettings` with CLI overrides and returns `None` when disabled
  (matching the existing `barge_event is None` convention).
- `src/config.py` — `WakeWordSettings` Pydantic submodel with
  `timeout_seconds` bounded `(0.0, 600.0]`. `[wake_word]` added to
  `_DEFAULT_TOML`.
- `src/cli/listen.py` (95 → 129 lines) — five new CLI flags, mutual-
  exclusion check, `build_wake_gate()` call, gate-at-sink filter between
  STT and file append.
- `src/cli/dialogue.py` (292 → 357 lines) — same five flags, same
  mutual-exclusion check, `build_wake_gate()` call, `wake_gate`
  threaded through to `_listener_loop` as a positional arg. Filter
  applied in the listener before file append.

**Design decisions worth remembering:**
- **Gate-at-sink over loop-owning detector.** The original 2.1 plan
  wrapped each utterance in a separate detector loop. Shipped form is a
  simple filter between `result.text.strip()` and the append — ~10 lines
  of call-site change, zero new threads or locks.
- **Strict punctuation match.** `^\s*(WORD)(?:[.,!?;:]+|$)\s*(.*)$`
  leans on Whisper's pause-punctuation behavior. "Computer science"
  misfires avoided; "Computer, hello" → "hello"; "Computer?!" accepted
  with empty rest.
- **Sliding timeout.** Every pass extends the window via
  `_last_pass_at`. On re-arm, the triggering utterance falls through
  back into the filter so the trigger word itself re-gates naturally.
- **Three-layer composition.** Wake gate (text) stacks above
  `barge_event` (VAD) and `tts_active` (mic). No interaction, no
  deadlock.
- **Two-tier feedback.** stderr echo on every activation; optional
  two-tone chime (880 → 1320 Hz, ~160 ms via `sd.play(blocking=False)`),
  wrapped in broad try/except so missing audio devices can't break the
  filter.

**dialogue.py crossed the Task 5.6 soft 350-line threshold (now 357).**
Primary cause: five `@click.option` decorators + `build_wake_gate()` call
+ mutual-exclusion check (~65 lines added). Tried collapsing the Thread
args from kwargs dict to positional tuple — saved ~8 lines but still 7
over. Candidate extraction (`_build_dialogue_runtime` helper) would drop
~30 lines but adds indirection that doesn't pay for itself yet.
Accepting the overshoot; Task 5.6 stays open as a monitor.

**Test split (+27 total):**
- `tests/test_wake_word.py` — 19 unit tests (new file).
- `tests/test_listen.py` — +2 tests (flow + mutual exclusion).
- `tests/test_dialogue.py` — +1 test (`_listener_loop` with real gate).
- `tests/test_config.py` — +5 tests (settings defaults, overrides,
  validators).

**Docs synced:**
- README.md — `[wake_word]` block added to config snippet, test count
  189 → 220, new "Wake-word flags (listen / dialogue)" subsection,
  `wake_word.py` added to the project-layout tree.
- PRD.md — wake-word options added to `cai listen` and `cai dialogue`
  Options lists; new **Wake word** subsection after Duplex modes
  (matching rule, activation feedback, config/CLI overrides — closes
  TODO 0.2); `[wake_word]` in Shared Configuration; Feature 2 removed
  from Future work.
- tasks/ARCHITECTURE.md — `wake_word.py` in file tree, `[wake_word]` in
  TOML example, CLI Overrides entries (noting mutex), reworked Dialogue
  Mode Threading prose describing the three-layer gate stack, new
  dedicated "Wake-Word Gate" section with regex + integration snippet.

**Deferred / rough edges:**
- Live hardware check (2.4 last item) — user-driven, requires mic.
- `dialogue.py` at 357 lines — flagged under Task 5.6.
- Pre-existing B5.1 F401 in `tests/test_config.py` still present (not in
  scope for this feature).

---

## Feature 3 — Voice conversation with Claude Code + skill ecosystem

**Goal:** ship the `cai converse` runtime that bridges voice ↔ Claude Code
headless (`claude -p --resume`), plus three reusable skills (`voice-mode`,
`cai-dictation`, `cai-dialogue`) and a `cai install-skill` installer.

**Primary UX:** user says "switch to voice mode" in a Claude Code session;
the `voice-mode` skill triggers Claude to run `cai converse --session-id
$CURRENT_SESSION`; the same session continues by voice until Ctrl+C.

**Approved plan:** `/Users/john/.claude/plans/stateful-stirring-pixel.md`.
Refinement answers: `tasks/TASK-REFINEMENT.md`.

### 3.0 `cai converse` runtime (NEW — runtime that makes skills useful)

Three-thread bridge: re-uses `_listener_loop` (mic→STT→file) and
`TextFileHandler` + `_make_speak_callback` (file→TTS) from `dialogue.py`;
adds a new bridge thread that tails the human file, calls `claude -p
"<line>" --resume <id> --output-format json`, and appends Claude's response
to the agent file.

- [ ] **3.0a** Skeleton `src/cli/converse.py` with three-thread wiring;
      bridge just echoes the transcribed line back (no `claude` yet).
      Verify end-to-end mic → STT → bridge → TTS.
- [ ] **3.0b** Session resolution: `--session-id <id>` (explicit attach),
      `--resume` (from state file), default (fresh). Mutex between the
      two flags. State file at `~/.local/state/conversational_ai/session`.
      Startup probe validates the session id; bail cleanly on invalid.
- [ ] **3.0c** Wire `claude -p "<line>" --resume <id> --output-format json`
      into the bridge. Parse response text. Persist session id on success.
- [ ] **3.0d** Error handling: subprocess timeout, non-zero exit (speak
      "session ended" + shutdown), missing `claude` binary (startup error).
- [ ] **3.0e** Wake-word gating via `build_wake_gate` (same knobs as
      `listen` / `dialogue`).
- [ ] Register `converse` in `cli.py` and `MODEL_REQUIREMENTS` as
      `(True, True)`; add `claude_runner_factory: Callable` to `CliContext`
      as the test seam for the subprocess call.

### 3.1 Author the skill files

- [ ] Create `skills/` directory in the repo.
- [ ] `skills/voice-mode/SKILL.md` — primary skill; Claude auto-loads when
      invoked via `cai converse`. Style guide: short declarative sentences,
      no markdown tables or code fences in the default path, verbal error
      handling ("that didn't work, here's why"), minimal clarifying
      questions (voice round-trips are slow), accessibility notes.
      Document the "don't type in the terminal while voice mode is active"
      constraint.
- [ ] `skills/cai-dictation/SKILL.md` — frontmatter + instructions for when
      Claude should invoke `cai listen` / `cai transcribe` on the user's
      behalf (e.g., "when the user asks to dictate to a file", "when they
      ask for voice input").
- [ ] `skills/cai-dialogue/SKILL.md` — frontmatter + instructions for
      driving `cai dialogue`, explaining the two-file contract and the
      duplex modes (barge-in / full-duplex matrix).
- [ ] Each SKILL.md explains: prerequisites (`cai` on PATH), config hints
      (where to set wake word, noise floor), and example invocations.

### 3.2 Installer subcommand

- [ ] New `src/cli/install_skill.py` implementing `cai install-skill`.
- [ ] Flags: `--mode voice-mode|dictation|dialogue|all` (default `all`),
      `--target DIR` (default `~/.claude/skills`), `--force` (overwrite).
- [ ] Copy `skills/<mode>/` into `<target>/<mode>/` idempotently.
      If target exists and `--force` not set, print a diff-style message
      and exit non-zero.
- [ ] Resolve skill source directory via `importlib.resources` so it works
      both from the repo and from the installed copy at
      `~/.local/share/conversational_ai`.
- [ ] `cai uninstall-skill [--mode …]` for symmetry.

### 3.3 PATH resolution

- [ ] Decision: skills assume `cai` is on PATH. Simpler, matches how every
      other Claude Code skill invokes CLIs, and the install.sh shim already
      puts `cai` at `~/.local/bin/cai`.
- [ ] `install-skill` checks `shutil.which("cai")` at install time and
      warns (non-fatal) if not found, pointing users at `install.sh`.

### 3.4 Tests

- [ ] `tests/test_converse.py`: listener/bridge/watcher wiring with a fake
      `claude_runner_factory`. Cover fresh-session, `--session-id`,
      `--resume`, mutex validation, invalid-session shutdown.
- [ ] `tests/test_install_skill.py`: CliRunner coverage for fresh install,
      `--force` overwrite, missing source directory, uninstall.
- [ ] Lint all three `SKILL.md` files for required frontmatter fields.

### 3.5 Docs

- [ ] PRD.md: add `cai converse` subcommand section (mirrors the
      `dialogue` section style); note `cai install-skill` briefly.
- [ ] README.md: "Voice conversation with Claude Code" as headline,
      "Claude Code skills" section with installer examples.
- [ ] CONTRIBUTING.md: module map rows for `converse.py`,
      `install_skill.py`, and new test files; bump test count.
- [ ] tasks/ARCHITECTURE.md: add converse threading diagram.

### Roadmap (post-v1, deferred)

- Streaming TTS via `--output-format stream-json` (speak sentence-by-
  sentence as tokens arrive).
- Voice-command stop (say "stop" cancels in-flight TTS + pending
  `claude -p` turn without ending the session).
- Direct Anthropic API backend (`--backend api`) for lower latency when
  tool access isn't needed.
- Shared terminal/voice safety: file lock or socket probe so `cai
  converse` and an active terminal Claude on the same session id don't
  interleave writes to the session jsonl.

---

## Feature 4 — Implement missing PRD flags

**Goal:** Reconcile the PRD with the actual CLI. These flags are documented
in `PRD.md` but were never built.

### 4.1 `cai transcribe` missing flags

- [ ] `--duration SECONDS` — maximum recording time; stop even if VAD
      hasn't triggered. Implement as a `threading.Timer` that sets
      `stop_event` after N seconds.
- [ ] `--no-vad` / `--vad` — disable silence detection entirely; record
      until `--duration` expires or user presses Enter. Requires an
      alternate `_callback` that never checks RMS.

### 4.2 `cai watch` missing flag

- [ ] `--debounce SECONDS` — configurable debounce interval (PRD says
      0.3s default). The current `TextFileHandler` polls on a fixed 100ms
      mtime interval with no debounce. Either add a debounce timer or
      document that the polling design makes it unnecessary and update the
      PRD accordingly.

### 4.3 Verify

- [ ] Tests for `--duration` and `--no-vad` in `test_cli_subcommands.py`
      (or its successor after the test split).
- [ ] Update PRD.md to match final implementation.

---

## Task 5 — Test suite decomposition and mocking refactor

**Goal:** Get oversized test files under the 500-line CLAUDE.md guideline
*and* replace the fragile import-path patching pattern with a factory on
`CliContext`. Done in interleaved order so each test file is split once,
against the final mocking pattern, rather than rewritten twice.

Sub-items below are in execution order — 5.2 (factory refactor) lands
between the two test-file splits on purpose: splitting
`test_cli_subcommands.py` (5.3) is mechanically simpler after the patches
have collapsed to a single factory override.

### 5.1 Split `tests/test_cli_audio_io.py` (852 lines)

- [x] Extract calibration tests → `tests/test_mic_calibration.py`.
- [x] Extract `mic_recorder_from_settings` tests → `tests/test_mic_factory.py`.
- [x] Keep VAD / recording core in `tests/test_cli_audio_io.py`.
- [x] Verify 189/189 still pass.

#### Review (2026-04-17)

Shipped the split as four files:

| File | Lines | Contents |
|---|---|---|
| `tests/test_cli_audio_io.py` | 708 (was 852) | VAD constants/RMS, TextFileHandler, play_tts_streaming barge-in, MinSpeechGate, PreSpeechPadding, BargeSignal, AdaptiveThreshold (EMA), AudioDeviceErrorFrom{Record,PlayTts} |
| `tests/test_mic_calibration.py` | 90 (new) | `TestMicRecorderCalibration` + `TestAudioDeviceErrorFromCalibrate` |
| `tests/test_mic_factory.py` | 47 (new) | `TestMicRecorderFromSettings` |
| `tests/_audio_fakes.py` | 43 (new) | `FakeInputStream`, `PortAudioError` — shared test doubles |

Shared helpers (`_FakeInputStream`, `_PortAudioError`) previously duplicated
private to `test_cli_audio_io.py` moved to `tests/_audio_fakes.py` (plain
module, not `conftest.py`, to avoid pytest's double-import trap). Renamed
without leading underscore since they're shared API now. 189/189 still pass;
`ruff check` clean on all four files.

Rough edge: `test_cli_audio_io.py` is still over the 500-line CLAUDE.md
guideline (708). The remaining concerns — VAD math, TextFileHandler, and
streaming playback — are cohesive enough that further splitting would
fragment rather than clarify. Flagging but not scheduling unless it grows.

### 5.2 Add factory callables to `CliContext`

**Goal:** Eliminate the fragile patch-target pattern where test patches
must track internal import paths. Feature 1 required migrating 7 patches
when `MicRecorder` imports moved — this will get worse as wake-word adds
more indirection.

- [x] Add a `recorder_factory` callable to `CliContext` (the Click
      `ctx.obj`) that subcommands call instead of importing
      `mic_recorder_from_settings` directly.
- [x] Default: `recorder_factory = mic_recorder_from_settings`.
- [x] Tests override `ctx.obj.recorder_factory` with a lambda returning a
      mock `MicRecorder` — single patch target, stable across refactors.
- [x] Same pattern for TTS playback: `speaker_factory` on `CliContext`.

#### Review (2026-04-17)

Scope stayed strictly on `CliContext` — subcommand wiring and test
migration remain 5.3. Two fields added to the dataclass in
`src/cli/__init__.py`:

```python
recorder_factory: Callable[..., MicRecorder] = field(
    default=mic_recorder_from_settings
)
speaker_factory: Callable[..., None] = field(default=play_tts_streaming)
```

Signature typed as `Callable[..., X]` rather than the full parameter list
— both defaults have kwarg-only parameters (`calibrate_override`, `cancel`)
that `Callable[[...], X]` can't express without a Protocol, and tests will
want to hand in terse lambdas rather than match the full signature.
`field(default=...)` is explicit rather than plain `= fn` — same runtime
behavior, but signals dataclass-default intent to a reader.

`MicRecorder` lives under `TYPE_CHECKING` (type-only); the two factory
functions are imported at runtime since they're the defaults.
`src.cli.__init__` → `src.cli.audio_io` is a new edge but `audio_io`
doesn't import back from `src.cli`, so no circular import.

Verification shipped as `tests/test_cli_context.py` (4 tests): the two
defaults are identity-equal to the real functions, and both fields are
overridable per-instance (the seam 5.3 will use). 189/189 → 193/193.
`ruff check` clean.

Intentionally NOT done in 5.2 (reserved for 5.3):
- Editing `transcribe`, `listen`, `dialogue`, `speak`, `watch` to call
  `ctx_obj.recorder_factory` / `ctx_obj.speaker_factory` instead of the
  module-level imports.
- Removing the `patch("src.cli.<mod>.mic_recorder_from_settings")` calls
  from `test_cli_subcommands.py`.

### 5.3 Migrate subcommand tests to the factory pattern

- [x] Update `transcribe`, `listen`, `dialogue`, `speak` subcommands to
      call `ctx.obj.recorder_factory` / `ctx.obj.speaker_factory` instead
      of importing the module-level helpers directly.
- [x] Update all subcommand tests to use the factory on `ctx.obj`.
- [x] Remove module-level
      `patch("src.cli.<mod>.mic_recorder_from_settings")` calls.
- [x] Verify 193/193 still pass.

#### Review (2026-04-18)

Seam is live. Every subcommand body now calls `ctx_obj.recorder_factory` /
`ctx_obj.speaker_factory` instead of the module-level helpers, and the
command-level tests override one attribute on `ctx.obj` rather than
patching import paths.

**Source edits (5 files):**
- `speak.py`, `watch.py` — dropped `play_tts_streaming` import,
  routed the playback call through `ctx_obj.speaker_factory`.
- `transcribe.py`, `listen.py` — dropped `mic_recorder_from_settings`
  import, routed recorder construction through `ctx_obj.recorder_factory`.
- `dialogue.py` — dropped both direct imports; `_make_speak_callback`
  now calls `ctx_obj.speaker_factory`, the command body builds the
  recorder via `ctx_obj.recorder_factory`. `MicRecorder` stayed in the
  import list because `_listener_loop`'s `recorder is None` fallback
  still constructs one directly.

**Test migration (`tests/test_cli_subcommands.py`):**
- Speak (6 sites), transcribe (4), listen (2), dialogue
  `_make_speak_callback` (7), dialogue command (1) — all collapsed
  to `ctx.<factory> = MagicMock(...)` assignments. The `with
  patch(...)` context managers are gone from the factory-using paths,
  so test bodies flattened by one indent and read more directly.

**Left intentionally unchanged (scheduled for 5.4):**
- Six `TestListenerLoop` / `TestDuplexModes` tests still carry
  `patch("src.cli.dialogue.MicRecorder", ...)` because they exercise
  `_listener_loop`'s default-recorder fallback. The cleaner move is
  to pass `recorder=recorder_mock` into `_listener_loop` directly and
  drop the fallback, but that belongs with the test-file split in 5.4
  where those tests are being moved anyway.

**Seam shape, for future reference:**
`ctx.recorder_factory` / `ctx.speaker_factory` accept the real
function's exact signature (positional mm/text/voice/speed/lang_code +
keyword `cancel=`, or `mic` + keyword `calibrate_override=`). A test
lambda that swallows `*args, **kwargs` works; so does a
`MagicMock(return_value=recorder_mock)`. No Protocol or stricter
typing needed — `Callable[..., X]` in the dataclass is deliberate.

**Pre-existing ruff violations, not mine to fix here:**
`ruff check` flags two F401s in `test_cli_subcommands.py` that predate
this task (`dataclasses.field` import and an unused
`import src.cli.dialogue as dialogue_mod` inside
`test_record_failure_resets_backoff_after_success`). Noted for the 5.4
pass when this file is being split anyway.

### 5.4 Split `tests/test_cli_subcommands.py` (850 lines)

- [x] Extract per-subcommand test modules: `tests/test_speak.py`,
      `tests/test_transcribe.py`, `tests/test_listen.py`,
      `tests/test_dialogue.py`, `tests/test_serve.py`,
      plus `tests/test_watch.py` (added for parity — watch tests needed
      a home and a stub `test_cli_subcommands.py` would've defeated the
      goal of splitting by concern).
- [x] Move shared fixtures to `tests/_cli_fakes.py` (plain module, not
      `conftest.py` — matches the Task 5.1 `_audio_fakes.py` precedent,
      avoids pytest's double-import trap, and keeps `make_ctx` as a plain
      function so call sites migrate with zero rewrites beyond imports).
- [x] Fold `TestLazyModelLoading` (group-level, not per-subcommand) into
      `tests/test_cli_context.py` — both concern the CLI group layer in
      `src/cli/__init__.py`.
- [x] Verify 193/193 still pass after the split.

#### Review (2026-04-18)

Split shipped as seven files plus a shared-fakes module:

| File | Lines | Contents |
|---|---|---|
| `tests/_cli_fakes.py` (new) | 35 | `FakeSTTOutput`, `make_ctx()` |
| `tests/test_speak.py` (new) | 94 | `TestSpeak` (7 tests) |
| `tests/test_transcribe.py` (new) | 81 | `TestTranscribe` (4 tests) |
| `tests/test_watch.py` (new) | 73 | `TestTextFileHandler`, `TestWatchCommand` (5 tests) |
| `tests/test_listen.py` (new) | 65 | `TestListenCommand` (2 tests) |
| `tests/test_serve.py` (new) | 27 | `TestServeCommand` (1 test) |
| `tests/test_dialogue.py` (new) | 359 | `TestSpeakCallback`, `TestListenerLoop`, `TestDuplexModes`, `TestDialogueCommand` (15 tests) |
| `tests/test_cli_context.py` (extended) | 100 (was 44) | Factory defaults/overrides + `TestLazyModelLoading` (12 tests) |
| `tests/test_cli_subcommands.py` | — | **deleted** (was 850) |

All seven new files are well under the 500-line guideline. The largest
(`test_dialogue.py`, 359 lines) is cohesive: every class tests some slice
of the dialogue listener/callback state machine — splitting further would
fragment rather than clarify.

**B4 resolved as part of the split:**
- B4.1 (`dataclasses.field` dead import) — the `FakeSTTOutput` dataclass
  moved to `_cli_fakes.py`, which imports only `dataclass`. Gone.
- B4.2 (dead `import src.cli.dialogue as dialogue_mod` in
  `test_record_failure_resets_backoff_after_success`) — deleted during
  the move to `test_dialogue.py`. The sibling test
  `test_record_failures_trigger_backoff_and_give_up` still imports the
  module (and uses it), unchanged.

**New F401s surfaced — pre-existing, logged as B5:**
Repo-wide `ruff check` during 5.4 verification turned up 5 unrelated F401s
in `test_config.py`, `test_middleware.py`, and `test_routes.py`. Confirmed
they exist at HEAD (commit 7247592) — none introduced by 5.4. Captured as
a new `BUGS.md` entry (B5) rather than fixed here; all five are one-line
deletions and the scope of 5.4 was the subcommand-tests split, not a
repo-wide lint sweep.

**Intentional: `_listener_loop` fallback + its tests preserved.**
The six `TestListenerLoop` / `TestDuplexModes` tests still patch
`src.cli.dialogue.MicRecorder` because `_listener_loop(..., recorder=None)`
still constructs one directly. The cleaner move (pass `recorder=recorder_mock`
from the tests and drop the fallback) was considered for 5.4 but rejected —
it's a behavior change on production code, not a test reorganization, and
doesn't belong bundled with the file split. Flagging for later if the
fallback earns its keep as a real feature (e.g., when wake-word integration
in Feature 2 looks at the listener loop).

### 5.5 Document the factory testing pattern

- [x] Add a "Testing patterns" section to `CONTRIBUTING.md` explaining
      the factory approach and why direct-import patching is discouraged.

#### Review (2026-04-18)

Added a new **Testing patterns** section to `CONTRIBUTING.md` (between
Testing and Conventions) covering three things:

1. **Factory seam on `CliContext`** — code snippet of the dataclass
   definition, followed by the `ctx.speaker_factory = MagicMock()` +
   `CliRunner(obj=ctx)` usage pattern that landed in 5.3. References
   `tests/_cli_fakes.make_ctx()` as the canonical starting point.
2. **Why direct-import patching is discouraged** — names the two
   legitimate remaining exceptions (`_listener_loop` recorder=None
   fallback; `ModelManager` lazy loading in the group callback) so
   future edits know what's a real branch under test vs. what's
   test-convenience plumbing that should migrate to a factory field.
3. **Shared helpers in `tests/_<topic>.py`** — documents the
   plain-module convention (vs. `conftest.py`) with the current
   two-row helper-file table and the double-import-trap rationale.
   Matches `feedback_shared_test_helpers.md` in memory.

**Collateral fix:** the Test structure table had gone stale —
`test_cli_subcommands.py` was listed but was deleted in 5.4, and the 5.1
spinoffs (`test_mic_calibration.py`, `test_mic_factory.py`) plus the 5.2
`test_cli_context.py` were missing. Replaced the one stale row with five
accurate rows covering the current tests/ directory.

Doc-only change; no test edits. 193/193 still passing per 5.4's
verification (no source touched).

### 5.6 Monitor `src/cli/dialogue.py` (298 lines)

- [ ] No split needed yet, but wake-word integration (Feature 2) will add
      ~50-80 lines. If it crosses 350 lines, extract `_listener_loop` into
      a separate module (e.g. `src/cli/listener.py`).

---

## Task 7 — Packaging and installer hardening

**Goal:** Make `install.sh` production-grade and add an uninstall path.
Currently the installer is a happy-path rsync script with no versioning,
no integrity checks, and no clean removal.

### 7.1 Version stamp

- [ ] Add a `__version__` string to `src/__init__.py` (or a top-level
      `VERSION` file) and have `install.sh` write it into the install
      directory so `cai --version` reports the installed version.
- [ ] `cai --version` flag on the Click group.

### 7.2 Uninstaller

- [ ] `cai uninstall` subcommand (or standalone `uninstall.sh`) that
      removes `~/.local/share/conversational_ai`,
      `~/.local/bin/cai`, and optionally
      `~/.config/conversational_ai` (prompt before deleting config).
- [ ] Idempotent — safe to run when already uninstalled.

### 7.3 Installer hardening

- [ ] Verify `uv sync --frozen` exit code and abort with a clear message
      on failure (currently the script runs `set -euo pipefail` but the
      error message is opaque).
- [ ] Check disk space before rsync (warn if < 500 MB free in
      `~/.local/share`).
- [ ] Add `--dry-run` flag that prints what would be copied/created
      without actually doing it.
- [ ] Skip mlx-audio copy if `$MLXAUDIO_DST` is already up to date
      (compare git rev or directory mtime) — saves ~30s on large repos.

### 7.4 XDG config bootstrap

- [ ] If `~/.config/conversational_ai/config.toml` does not exist,
      copy the default template there on first install so users have a
      file to edit. Currently the app falls back to hardcoded defaults
      but users have no obvious config file to customize.
- [ ] Print the config path at the end of install.

### 7.5 Tests

- [ ] Shellcheck `install.sh` (and `uninstall.sh` if created).
- [ ] Test `cai --version` output format.
- [ ] CliRunner test for `cai uninstall` if implemented as a subcommand.

---

## Feature 8 — Timestamped output lines

**Goal:** Every line written to a file gets a start/stop timestamp and an
optional user-defined speaker handle. Useful for reviewing dialogue
transcripts, debugging latency, and building conversation logs that
external tools can parse.

Output format (tab-separated, easy to `cut`/`awk`):

```
[2026-04-12T14:03:11.482 → 14:03:14.207]  John  Hello, what's the weather like?
[2026-04-12T14:03:15.001 → 14:03:17.890]  Agent Good morning — it's 18°C and sunny.
```

When `--no-timestamp` is active, lines are written plain (current behavior).

### 8.1 Timestamp formatter

- [ ] New helper `src/cli/timestamps.py` with:
      ```python
      def format_line(
          text: str,
          start: datetime,
          end: datetime,
          *,
          handle: str | None = None,
      ) -> str:
      ```
- [ ] Start time = moment speech was detected (rising edge of VAD gate).
      End time = moment the STT result is returned.
- [ ] For pure-text input (watch/speak reading from a file), start = file
      change detected, end = TTS playback finished.
- [ ] ISO 8601 for the full stamp, abbreviated (time-only) for the end
      when same day.

### 8.2 Config plumbing

- [ ] Add `[output]` section to `src/config.py`:
      `timestamps: bool = False`, `handle: str | None = None`,
      `timestamp_format: str = "iso"` (future: `"epoch"`, `"relative"`).
- [ ] Update `config.toml` with commented `[output]` block.
- [ ] `tests/test_config.py`: defaults and overrides for `[output]`.

### 8.3 CLI flags

- [ ] Add to `listen`, `dialogue`, `transcribe`:
      `--timestamp/--no-timestamp` (default from config, off if unset),
      `--handle NAME` (e.g. `--handle John`).
- [ ] `dialogue` gets two handles: `--listen-handle` for the human side,
      `--speak-handle` for lines read from the speak-file (stamped on
      read, not on write by the external agent).

### 8.4 Integration

- [ ] `listen`: capture `datetime.now()` before `recorder.record()` as
      start, after `generate_stt()` as end. Format with `format_line()`
      before writing.
- [ ] `dialogue._listener_loop`: same pattern. The speak-file watcher
      stamps lines as they arrive (start = mtime change detected,
      end = after TTS playback completes) — write stamped version to a
      separate log file or print to stderr, not back into the speak-file.
- [ ] `transcribe --output FILE`: stamp the single result if timestamps
      enabled; stdout output stays plain unless `--timestamp` is explicit.

### 8.5 Stretch — handle registry

- [ ] `[output.handles]` config section mapping handle names to short
      display aliases:
      ```toml
      [output.handles]
      human = "John"
      agent = "Claude"
      ```
- [ ] `dialogue` auto-selects `human` for listen-side and `agent` for
      speak-side from the registry when `--listen-handle` / `--speak-handle`
      are not given.

### 8.6 Tests

- [ ] Unit tests for `format_line()`: both timestamps present, handle
      present/absent, same-day abbreviation, timezone handling.
- [ ] CliRunner tests for `listen --timestamp --handle Alice` verifying
      the written file format.
- [ ] `dialogue` test verifying both handles appear in output.

---

## Sequencing

1. **Task 0** (done) — architecture/doc review before building more.
2. **Task 5 next** — test-suite decomposition + mocking factory refactor
   (merged from the old Task 5 + Task 6). Clean foundation for new
   feature work.
3. **Feature 1** (done) — mic noise-floor controls.
4. **Feature 2** — wake word, depends on #1's tightened VAD.
5. **Feature 4** — PRD flag reconciliation, can be done alongside #2.
6. **Feature 8** — timestamped output, can land alongside or after #2.
7. **Feature 3** — Claude Code skill + installer.
8. **Task 7 last** — packaging/installer hardening, best done after the
   final feature set is stable.

Each feature ends with a **Review** subsection appended here once complete,
summarizing what shipped, what tests were added, and any rough edges
deferred to `tasks/BUGS.md`.
