# TODO: Mic Controls, Wake Word, Claude Skill

Three features, landed in order so each one can lean on the previous.

---

## Feature 1 — Mic noise-floor controls

**Goal:** filter keyboard clacks and household noise without hand-tuning a
magic constant per room. Ship configurable thresholds + an opt-in noise
calibration pass + a minimum-speech-duration gate.

### 1.1 Make `MicRecorder` params instance-level

- [ ] Convert `MicRecorder` class constants (`RMS_THRESHOLD`, `SILENCE_SECONDS`,
      `CHUNK_SECONDS`) to `__init__` params with the current values as defaults.
- [ ] Add new param `min_speech_seconds: float = 0.15` — consecutive chunks
      above threshold required before `speech_detected` latches. Kills single
      keystroke / door-slam false positives.
- [ ] Update `_callback` to count consecutive above-threshold chunks and only
      set `speech_detected` once the count ≥ `min_speech_chunks`.
- [ ] Unit-test in `tests/test_cli_audio_io.py`: single loud chunk does not
      latch; sustained chunks do; silence counter still works.

### 1.2 Config plumbing

- [ ] Add `[mic]` section to `src/config.py` (Pydantic `MicSettings` submodel):
      `rms_threshold: float = 0.01`, `silence_seconds: float = 1.5`,
      `min_speech_seconds: float = 0.15`, `calibrate_noise: bool = False`,
      `calibration_seconds: float = 1.0`, `calibration_multiplier: float = 3.0`.
- [ ] Update `config.toml` with a commented `[mic]` block showing defaults.
- [ ] `tests/test_config.py`: TOML load + CLI override coverage for `[mic]`.

### 1.3 CLI flags

- [ ] Add flags to `transcribe`, `listen`, `dialogue`:
      `--mic-threshold`, `--mic-silence`, `--mic-min-speech`, `--calibrate-noise/--no-calibrate-noise`.
- [ ] Wire each subcommand to build `MicRecorder` from merged settings.

### 1.4 Noise-floor calibration

- [ ] New method `MicRecorder.calibrate(seconds: float) -> float` — opens a
      short `InputStream`, collects RMS over `seconds`, returns the measured
      floor.
- [ ] On `record()`, if `calibrate_noise=True`, run calibration once (cache
      the result on the instance), then set effective threshold =
      `max(configured_threshold, measured_floor * multiplier)`.
- [ ] Log both values at INFO so users can see what was chosen.
- [ ] `listen` and `dialogue` run calibration once at startup, not per-utterance.
- [ ] `transcribe` skips calibration by default (one-shot UX); opt in with
      `--calibrate-noise`.

### 1.5 Verify

- [ ] All existing `tests/test_cli_audio_io.py` tests still pass.
- [ ] New tests for `min_speech_seconds` gate and calibration math.
- [ ] Live check on real hardware: clack the keyboard during `cai transcribe`,
      verify it does not trigger a recording.

---

## Feature 2 — Wake word / trigger word (Option A: rolling Whisper)

**Goal:** `cai listen` and `cai dialogue` ignore speech until the user says a
configurable trigger word (default: `"computer"`). Uses the already-loaded
Whisper model on short utterances — plenty of headroom on M3 Ultra / 512 GB.

### 2.1 Design

- [ ] New module `src/cli/wake_word.py` with a `WakeWordDetector` class.
- [ ] API shape:
      ```python
      class WakeWordDetector:
          def __init__(self, mm, word: str, *, include_trigger: bool = False): ...
          def wait_for_trigger(self, recorder: MicRecorder, shutdown: Event) -> None:
              """Loop: record utterance, transcribe, match trigger.
              Returns when matched, or raises on shutdown."""
          def strip_trigger(self, text: str) -> str: ...
      ```
- [ ] Matching is case-insensitive, punctuation-stripped, whole-word (regex
      `\btrigger\b`) — avoids "computer science" misfires vs "computer, list…".
- [ ] `include_trigger=False` (default) causes `strip_trigger` to remove the
      trigger and any leading comma/filler from the transcript before write-out.

### 2.2 Config plumbing

- [ ] Add `[wake_word]` section to `src/config.py`:
      `enabled: bool = False`, `word: str = "computer"`,
      `include_trigger: bool = False`, `timeout_seconds: float = 30.0`.
- [ ] `timeout_seconds` = re-arm window. After a successful trigger, the next
      utterance goes through unconditionally; if no utterance arrives within
      `timeout_seconds`, detector re-engages.
- [ ] Update `config.toml` with commented defaults.
- [ ] `tests/test_config.py`: coverage for `[wake_word]`.

### 2.3 Integration

- [ ] `listen` subcommand: if wake word enabled, wrap the record loop so each
      utterance first passes through `WakeWordDetector` state machine.
- [ ] `dialogue` subcommand: same wrapping on the listener thread. Must
      compose with `barge_in` / `full_duplex` duplex modes without deadlock —
      wake-word detection acquires the inference lock exactly like a normal
      STT call.
- [ ] CLI flags: `--wake-word WORD`, `--no-wake-word`, `--wake-timeout SECONDS`,
      `--include-trigger/--strip-trigger`.
- [ ] `transcribe` is intentionally skipped — one-shot, user already
      initiated it by running the command.

### 2.4 Tests

- [ ] `tests/test_wake_word.py`: unit tests for matching (case, punctuation,
      whole-word), `strip_trigger` output, timeout re-arm behavior.
- [ ] Mocked CliRunner tests for `listen --wake-word` and `dialogue --wake-word`.
- [ ] Live check: `cai listen out.txt --wake-word computer` — talking random
      noise does nothing; saying "computer, hello world" appends "hello world".

### 2.5 Docs

- [ ] Update `README.md` CLI section with wake-word usage + config example.
- [ ] Update `PRD.md` with the wake-word feature in a new subsection.

---

## Feature 3 — Claude Code skill + installer

**Goal:** ship reusable Claude Code skills that wrap `cai` for two use cases
(dictation, dialogue), plus a `cai install-skill` command that drops them
into `~/.claude/skills/`.

### 3.1 Author the skill files

- [ ] Create `skills/` directory in the repo.
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
- [ ] Flags: `--mode dictation|dialogue|both` (default `both`),
      `--target DIR` (default `~/.claude/skills`), `--force` (overwrite).
- [ ] Copy `skills/cai-<mode>/` into `<target>/cai-<mode>/` idempotently.
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

- [ ] `tests/test_install_skill.py`: CliRunner coverage for fresh install,
      `--force` overwrite, missing source directory, uninstall.
- [ ] Lint the two `SKILL.md` files for required frontmatter fields.

### 3.5 Docs

- [ ] README section: "Claude Code integration" with `cai install-skill`
      example and a one-line description of each skill.

---

## Sequencing

1. **Feature 1 first** — the `min_speech_seconds` gate and calibration are
   prerequisites for a low-false-positive wake-word loop.
2. **Feature 2 second** — depends on #1's tightened VAD so we aren't
   transcribing every keyboard burst.
3. **Feature 3 last** — packaging layer; best wrapped around the final UX.

Each feature ends with a **Review** subsection appended here once complete,
summarizing what shipped, what tests were added, and any rough edges
deferred to `tasks/BUGS.md`.
