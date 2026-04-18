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
