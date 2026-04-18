# BUGS

Known issues and deferred rough edges, filed in priority order.

---

## B1 — Calibration never re-samples during long sessions

**Severity:** Low
**Affects:** `cai listen`, `cai dialogue`

`MicRecorder.calibrate()` runs once at startup and caches the result for
the lifetime of the instance. Long-running `listen` / `dialogue` sessions
won't adapt to a noise-floor shift (HVAC kicking on, fan speed change,
window opened).

**Workaround:** Ctrl+C and restart the command to re-calibrate.

**Fix ideas:** Periodic re-calibration during silence gaps, or an
exponential moving average over recent silence-chunk RMS values that
adjusts `_effective_threshold` without a separate calibration pass.

---

## B2 — Pre-latch ring buffer may clip short utterance onsets

**Severity:** Low
**Affects:** All mic-recording paths

The pre-latch ring buffer is sized to `min_speech_chunks`, so the
preserved leading audio is approximately `min_speech_seconds` of context.
Very short utterances ("yes", "no") that clip before the min-speech gate
trips may lose a millisecond or two of onset.

**Workaround:** None needed in practice — Whisper pads internally and
handles minor onset clipping gracefully.

**Fix ideas:** Size the ring buffer to `min_speech_chunks + N` extra
chunks of padding, or use a longer fixed ring (e.g. 0.5s) independent
of the gate length.

---

## B3 — No error handling for missing mic or speakers

**Severity:** Medium
**Affects:** All mic-recording paths (`transcribe`, `listen`, `dialogue`),
TTS playback (`speak`, `watch`, `dialogue`)

If `sounddevice` can't open an input or output device (no mic plugged in,
permission denied in macOS System Settings, Bluetooth headset disconnected
mid-session), `MicRecorder.record()`, `MicRecorder.calibrate()`, and
`AudioPlayer` will throw an opaque `sounddevice.PortAudioError`. In
threaded contexts (`dialogue` listener thread), this crashes the thread
silently with no user-visible message.

**Expected behavior:** A clear message like "No microphone found -- check
System Settings > Privacy & Security > Microphone" or "Audio output device
unavailable" before exiting with a non-zero code. In threaded contexts,
the error should propagate to the main thread and trigger a clean shutdown.

**Fix ideas:**
- Wrap `sd.InputStream` / `AudioPlayer` construction in a try/except for
  `sounddevice.PortAudioError`, translate to a `click.ClickException` with
  a human-readable message.
- In `_listener_loop` (dialogue), catch the error, log it, and set the
  shutdown event so the main thread exits cleanly.
- Add a `check_audio_devices()` helper that probes for available input/output
  devices at startup and fails fast with guidance.

---

## B4 — Dead imports in `tests/test_cli_subcommands.py` (two F401s) — RESOLVED

**Severity:** Low (lint-only; tests pass)
**Affects:** `tests/test_cli_subcommands.py` (file deleted in Task 5.4)
**First observed:** 2026-04-18, during Task 5.3 verification. Both errors
predate 5.3 — they existed at commit `5304ecf` on `main`.
**Resolved:** 2026-04-18 as part of Task 5.4's test-file split.

`uv run ruff check tests/test_cli_subcommands.py` reports two F401
"imported but unused" violations:

### B4.1 — `dataclasses.field` imported but unused

```
tests/test_cli_subcommands.py:12:36
  from dataclasses import dataclass, field
                                     ^^^^^
```

The file uses `@dataclass` on `FakeSTTOutput` (line 38) but no `field(...)`
default factories. The `field` symbol in the import is dead. Likely a
leftover from an earlier iteration of `FakeSTTOutput` that had
`segments: list[dict] = field(default_factory=list)` before the field was
simplified to a `None`-defaulted optional.

**Fix:** `from dataclasses import dataclass` (drop `field`).

### B4.2 — Unused local `import src.cli.dialogue as dialogue_mod`

```
tests/test_cli_subcommands.py:558:36
  import src.cli.dialogue as dialogue_mod
                             ^^^^^^^^^^^^
```

Inside `TestListenerLoop.test_record_failure_resets_backoff_after_success`.
The test body never references `dialogue_mod`. The sibling test
`test_record_failures_trigger_backoff_and_give_up` has its own identical
local import and *does* reference `dialogue_mod._RECORD_BACKOFF_START` /
`_RECORD_BACKOFF_MAX` / `_RECORD_MAX_CONSECUTIVE_FAILURES`; the reset-
backoff test was apparently cloned from that one and the import was kept
even though the constants aren't checked.

**Fix:** delete the local `import` line. Alternatively, re-assert against
`dialogue_mod._RECORD_BACKOFF_START` where the test sets up `fake_record`
so the constant stays in sync with the source.

### What happened during 5.4

- **B4.1:** `FakeSTTOutput` moved to `tests/_cli_fakes.py`, which imports
  only `dataclass` from `dataclasses`. The `field` symbol is gone entirely.
- **B4.2:** the dead `import src.cli.dialogue as dialogue_mod` inside
  `test_record_failure_resets_backoff_after_success` was dropped when the
  test moved to `tests/test_dialogue.py`. The sibling test
  `test_record_failures_trigger_backoff_and_give_up` kept its own (still
  used) copy of the import.

---

## B5 — Dead imports across other test files (five F401s)

**Severity:** Low (lint-only; tests pass)
**Affects:** `tests/test_config.py`, `tests/test_middleware.py`,
`tests/test_routes.py`
**First observed:** 2026-04-18, during Task 5.4 verification when a
repo-wide `ruff check` ran against the reorganized test tree. All five
predate 5.4 — they exist at commit `7247592` on `main`, before any 5.4
edits.

`uv run ruff check .` reports five F401 "imported but unused" violations
outside the 5.4 scope:

### B5.1 — `tomllib` imported but unused

```
tests/test_config.py:3:8
  import tomllib
```

Likely leftover from an earlier iteration that loaded TOML fixtures
directly instead of going through `Settings.from_toml(...)`. Fix: drop
the import line.

### B5.2 — `pytest` imported but unused in `test_middleware.py`

```
tests/test_middleware.py:5:8
  import pytest
```

No decorators (`@pytest.fixture`, `@pytest.mark.*`), no `pytest.raises`,
no `pytest.approx` anywhere in the file. Fix: drop the import line.

### B5.3 — `LimitsSettings` imported but unused

```
tests/test_middleware.py:9:24
  from src.config import LimitsSettings, Settings
```

Only `Settings` is referenced in the test body. Fix:
`from src.config import Settings`.

### B5.4 — `MagicMock` imported but unused in `test_routes.py`

```
tests/test_routes.py:10:27
  from unittest.mock import MagicMock
```

File uses `patch(...)` from elsewhere but never constructs a `MagicMock`
directly. Fix: drop the import line (or swap to
`from unittest.mock import patch` if `patch` comes from the same line —
check first).

### B5.5 — `pytest` imported but unused in `test_routes.py`

```
tests/test_routes.py:13:8
  import pytest
```

Same pattern as B5.2. Fix: drop the import line.

### Why deferred

Each fix is one line, and batching all five into a single `ruff check
--fix` sweep is mechanically trivial. Rolling them into 5.4 would've muddled
the diff for the subcommand-tests split; rolling them into a separate lint
pass keeps the intent clear. Candidate work: a small follow-up task after
Feature 2 lands, or bundled with CI hook work in Task 7.

**Guard rail:** if a lint CI hook (ruff-check pre-commit, GitHub Action)
lands before the sweep, fix all five immediately rather than exempting the
files. All five auto-fix with `uv run ruff check --fix tests/`.
