# Feature 2 — pre-implementation design notes

Written mid-plan, before any code was touched, as a continuity checkpoint
across a planned compaction. Delete this file once Feature 2 lands.

## State at time of writing

- Tasks #24-#29 captured in the task list covering the six Feature 2 phases.
- Git working tree: unchanged relative to the last commit (pre-Feature-2).
- No source files touched yet. Resume point: start task #24.

## Decisions confirmed with the user (refined past the TODO wording)

### D1 — Architecture: gate-at-sink, not loop-owning detector

The TODO's `WakeWordDetector.wait_for_trigger(recorder, shutdown) -> None`
API would duplicate the existing record/STT loop. Instead we add a
lightweight `WakeWordGate` that sits at the **text sink** — both
`src/cli/listen.py:88-92` and `src/cli/dialogue.py:162-166` have an
identical `result.text.strip() → file append` step. The gate goes there.

No new lock, no new thread. Reuses the already-held `inference_lock` in
dialogue because the STT call already owned it.

### D2 — Match rule: trigger must be followed by punctuation OR end-of-utterance

Rejected the TODO's `\btrigger\b` regex (doesn't distinguish "Computer,
hello" from "Computer science"). User explicitly wants "Computer science
is cool" **not** to trigger the wake word.

Final regex (case-insensitive, applied after `.strip()`):

```python
_TRIGGER_RE = re.compile(
    rf"^\s*({re.escape(word)})(?:[.,!?;:]+|$)\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
```

- `"Computer."` → match, rest=`""` (opens the window, nothing to emit)
- `"Computer, play music"` → match, rest=`"play music"`
- `"Computer! Do X"` → match, rest=`"Do X"`
- `"Computer?!"` → match, rest=`""` (`+` absorbs the whole punctuation run)
- `"Computer science is cool"` → **no match** (no punctuation after "Computer")
- `"Computer hello"` → no match — user learns to pause

Relies on Whisper inserting punctuation on pauses (it does reliably).

### D3 — Timeout: sliding window from last-passed utterance

After a trigger match the gate disarms. Every utterance that passes during
the open window extends the window (updates `_last_pass_at`). When
`now - _last_pass_at > timeout_seconds`, re-arm. Next utterance must
re-match the trigger.

Edge case: re-arm falls *through* to the armed branch to gate the utterance
that triggered the re-arm check — an utterance arriving after the timeout
is part of a new session, must re-trigger.

### D4 — Duplex composition: gate is a third layer above barge_in / tts_active

- `barge_event` (VAD-level, cancels in-flight TTS) — fires on any speech
- `tts_active` (mic-level, gates record in half-duplex) — independent
- `wake_gate` (text-level, gates sink append) — layered above both

No interaction, no deadlock risk. Worth one line in ARCHITECTURE.md's
Dialogue Threading diagram to show the stacking.

### D5 — Docs also close TODO 0.2

TODO 0.2 deferred "Add wake word (Feature 2) as a new subsection once
implemented" in PRD.md. 2.5 closes it — one checkbox flip in Task 0.

### D6 — Feedback on trigger: stderr echo + optional chime

Two layers:

1. **stderr echo** always on (`[wake] listening…`). Works headless, no
   config toggle.
2. **Audio chime** toggleable via `[wake_word] alert_sound: bool = True`
   and `--wake-alert/--no-wake-alert`. Programmatic two-tone sine burst,
   ~80ms × 2 at 880 Hz → 1320 Hz with ~10% fade envelope to avoid click.
   Played via `sd.play(..., blocking=False)` on the listener thread.

Both fire **only on the armed→disarmed transition**. Subsequent utterances
during the open window are normal conversation — no chime spam.

Rationale against TTS "Yes?" feedback: latency. By the time TTS finishes
playing (~1 s) the user has already started talking. Chime is ≤200 ms
total and ends before the user's response starts.

Co-existence with in-flight TTS: in practice the listener thread fires the
chime right after STT completes, when TTS either isn't playing or was just
canceled by barge-in. `sd.play(blocking=False)` is used so the listener
doesn't stall. If CoreAudio multiplexing proves unreliable in practice,
fall back to `blocking=True` or add a gate on `tts_active`.

## Implementation shape (ready to write)

### `src/cli/wake_word.py` (new, ~100 lines)

```python
class WakeWordGate:
    def __init__(
        self,
        word: str,
        *,
        include_trigger: bool = False,
        timeout_seconds: float = 30.0,
        alert_sound: bool = True,
        clock: Callable[[], float] = time.monotonic,
        chime: Callable[[], None] | None = None,  # None → default _play_chime
        echo: Callable[[str], None] | None = None,  # None → click.echo(..., err=True)
    ) -> None: ...

    def filter(self, text: str) -> str | None:
        """Return passed text (possibly stripped), or None to drop."""

    # Internals
    _armed: bool           # True → next utterance must match trigger
    _last_pass_at: float | None
```

### `_play_chime()` helper (same file)

```python
def _play_chime(sample_rate: int = 24_000) -> None:
    import numpy as np
    import sounddevice as sd
    dur = 0.08  # seconds per tone
    t = np.linspace(0, dur, int(sample_rate * dur), endpoint=False)
    fade = int(len(t) * 0.1)
    env = np.ones_like(t)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    tone1 = np.sin(2 * np.pi * 880 * t) * 0.2 * env
    tone2 = np.sin(2 * np.pi * 1320 * t) * 0.2 * env
    chime = np.concatenate([tone1, tone2]).astype(np.float32)
    sd.play(chime, sample_rate, blocking=False)
```

### Integration points

Both `listen.py` and `dialogue._listener_loop` get the same change:

```python
line = result.text.strip()
if line and wake_gate is not None:
    line = wake_gate.filter(line)  # may return None
if line:
    # existing sink: append to file + echo
```

Gate convention: `wake_gate is None` when disabled (matches
`barge_event` / `tts_active` None-when-disabled pattern). Built in the
command body from merged settings — never built when
`settings.wake_word.enabled is False`.

### Config shape

`src/config.py`:

```python
class WakeWordSettings(BaseModel):
    enabled: bool = False
    word: str = "computer"
    include_trigger: bool = False
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0)
    alert_sound: bool = True
```

`_DEFAULT_TOML` gains:

```toml
[wake_word]
# Require the user to say a trigger word before STT output passes through
# to the sink file. Uses the already-loaded Whisper model on short
# utterances (no extra model).
enabled = false
# Trigger word must be followed by punctuation or end-of-utterance to
# match. "Computer, hello" → pass "hello"; "computer science" → no match.
# Pick a word you don't normally start sentences with.
word = "computer"
# When true, trigger is kept in the output line; when false (default) it's
# stripped along with the trailing punctuation and leading whitespace.
include_trigger = false
# Seconds of silence after the last passed utterance before the gate
# re-arms and requires the trigger again.
timeout_seconds = 30.0
# Play a short two-tone chime on trigger activation. stderr echo fires
# regardless.
alert_sound = true
```

### CLI flags (on `listen` and `dialogue`)

```
--wake-word WORD         # enables wake mode, overrides config word
--no-wake-word           # disables wake mode regardless of config
--wake-timeout SECONDS   # overrides timeout_seconds
--include-trigger        # keep trigger in output
--strip-trigger          # strip trigger (default)
--wake-alert             # play chime
--no-wake-alert          # suppress chime (stderr echo still fires)
```

`--wake-word WORD` being specified forces `enabled=True` even if config
has `enabled=false`. Matches how `--calibrate-noise` behaves as a CLI
override.

### Test plan (targets 197+/197+, 193 → 197+)

- `tests/test_wake_word.py` (new, ~8 tests):
  - match: "Computer, hello" → "hello"
  - match: "Computer." → "" (rest empty)
  - reject: "computer science is cool"
  - reject: "what a great computer"
  - include_trigger=True keeps full text
  - timeout re-arm via injected clock (utterance at t=0 passes, t=31
    must re-trigger)
  - sliding window: utterance at t=10 extends, utterance at t=35 also
    passes if last was at t=31
  - alert suppression: `alert_sound=False` → chime fn not called;
    echo still called
- `tests/test_config.py` (+3 tests): `[wake_word]` defaults, TOML
  overrides, timeout validator
- `tests/test_listen.py` (+1): `--wake-word computer` drops non-matching
  utterance, passes matching one
- `tests/test_dialogue.py` (+1): same via `_listener_loop` with the new
  `wake_gate` kwarg

All tests patch `_play_chime` / inject no-op `chime=lambda: None` so no
audio device is touched.

## File size projection

- `src/cli/wake_word.py` — new, ~100 lines
- `src/cli/dialogue.py` — 298 → ~315 lines (under the 350-line 5.6 threshold)
- `src/cli/listen.py` — 95 → ~115 lines
- `tests/test_wake_word.py` — new, ~150 lines

## Post-compact resume checklist

1. Re-read this file to recover design context.
2. Re-read `src/cli/audio_io.py:18-33` (the `mic_recorder_from_settings`
   factory — the wake-word config override shape mirrors its
   `calibrate_override` kwarg).
3. Re-read `src/cli/listen.py:88-92` and `src/cli/dialogue.py:162-166`
   for the exact insertion point.
4. Resume task #24 (`Build WakeWordGate + unit tests`).
5. Delete this file once Feature 2 is merged — it's a working document,
   not durable project docs.
