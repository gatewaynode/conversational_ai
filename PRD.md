# PRD: Conversational AI — CLI Interface

## Problem

The conversational-ai project exposes TTS/STT as a CLI (`cai`) and, for
browser-based clients that can't shell out, as a localhost HTTP API
(`cai serve`). Users who want to speak text through speakers, transcribe
from a microphone, or build simple voice pipelines between files should not
have to write their own client code against the API — a native CLI eliminates
that friction and plugs into existing UNIX-style workflows.

## Goals

1. Provide direct terminal access to TTS and STT without running the HTTP server.
2. Support real-time audio I/O (speakers and microphone) as first-class features.
3. Enable file-based voice pipelines (watch a file → speak changes, mic → append text to file).
4. Offer a dialogue mode that combines both directions for two-party voice interaction.
5. Unify the server and CLI under a single `cai` entry point with subcommands.

## Non-Goals

- Streaming audio over the network (the API server already handles this).
- GUI or TUI with widgets — this is a terminal-native tool.
- Speaker diarization or multi-speaker identification.
- Real-time translation or language detection.

## User Personas

- **Developer**: Testing TTS voices or STT accuracy from the terminal during development.
- **Power user**: Building voice-driven automations (e.g., dictation to file, narrating logs).
- **AI integrator**: Using dialogue mode to bridge a text-based AI (writes to a file) with a
  human speaking into a microphone.

## Subcommands

### `cai serve`

Starts the HTTP API server (current `main.py` behavior, relocated under a subcommand).

```bash
cai serve
# Host/port come from [server] in the config file.
# To override, edit the config or pass a CLI override like:
cai --tts-model mlx-community/Kokoro-82M-bf16 serve
```

### `cai speak`

Synthesize text and play through speakers.

```bash
# Inline text
cai speak "Hello, can you hear me?"

# From stdin (pipe-friendly)
echo "Hello world" | cai speak

# From file
cai speak --file notes.txt

# Override voice/speed (global flags, before the subcommand)
cai --voice af_sky --speed 1.2 speak "Good morning"
```

Options: `-f/--file`. `--voice`, `--speed`, and `--lang-code` are **global**
flags (before the subcommand) — they're inherited from config and apply to
every subcommand.

### `cai transcribe`

Record a single utterance from the microphone and print/write the transcription.

```bash
# Record until silence detected, print text
cai transcribe

# Write to file instead of stdout
cai transcribe -o transcript.txt

# Tighten the VAD gate
cai transcribe --mic-threshold 0.02 --mic-silence 1.0

# Calibrate room tone before recording (opt-in; adds ~1s startup)
cai transcribe --calibrate-noise
```

Options: `-o/--output FILE`, `--mic-threshold`, `--mic-silence`,
`--mic-min-speech`, `--calibrate-noise/--no-calibrate-noise`.

**Not yet implemented** (tracked in `tasks/TODO.md` Feature 4.1):
`--duration SECONDS` (max recording time), `--vad/--no-vad` (disable silence
detection, record until Enter pressed).

### `cai watch`

Watch a file for changes and speak new content through speakers.

```bash
# Watch a file, speak any new lines appended to it
cai watch conversation.txt

# With custom voice (voice is a global flag)
cai --voice af_sky watch agent_output.txt
```

Behavior:
- Tracks the file's byte offset. On each change, reads only new content from the last
  known position.
- If the file is truncated (size shrinks), resets to the beginning.
- Polls `st_mtime` on a 300ms interval; the interval doubles as a natural
  debounce (successive writes within one tick coalesce into a single read).
- Runs until Ctrl+C.

Options: `FILE` positional only. Voice/speed/lang are global flags. The poll
interval is a module constant today; a `--debounce` flag is tracked in
`tasks/TODO.md` Feature 4.2.

### `cai listen`

Continuously listen to the microphone and append transcriptions to a file.

```bash
# Listen and append to a file
cai listen output.txt

# Calibrate room tone once at startup, then loop
cai listen --calibrate-noise output.txt

# Tune the VAD gate for a noisy environment
cai listen --mic-threshold 0.03 --mic-min-speech 0.25 output.txt
```

Behavior:
- Records one utterance at a time (VAD-based silence detection).
- Transcribes and appends text to the output file.
- Prints each transcription to stderr for feedback.
- Calibration runs once at startup (opt-in), not per-utterance.
- Loops until Ctrl+C.

Options: `--mic-threshold`, `--mic-silence`, `--mic-min-speech`,
`--calibrate-noise/--no-calibrate-noise`, `--wake-word WORD`, `--no-wake-word`,
`--wake-timeout SECONDS`, `--include-trigger/--strip-trigger`,
`--wake-alert/--no-wake-alert`. See **Wake word** below for gating behavior.

**Not yet implemented** (tracked in `tasks/TODO.md` Feature 8):
`--timestamp/--no-timestamp` + `--handle NAME` for stamped log lines.

### `cai dialogue`

Run watch + listen simultaneously for two-party voice interaction.

```bash
# Use the default file pair from [dialogue] config
cai dialogue

# Override file paths
cai dialogue --speak-file agent.txt --listen-file human.txt
```

Use case: An AI agent writes text to `agent.txt`. The human hears it spoken aloud and
responds verbally. Their speech is transcribed and appended to `human.txt`, which the
AI agent reads.

Behavior:
- Thread 1: Watches `--speak-file` and plays new text through TTS.
- Thread 2: Continuously records from the mic and appends transcriptions to `--listen-file`.
- An inference lock serializes TTS and STT calls (MLX is not thread-safe for concurrent ops).
- Barge-in and duplex behavior are controlled by the `[dialogue]` config
  section (see **Duplex modes** below).
- Both threads shut down gracefully on Ctrl+C.

Options: `--speak-file` (optional, defaults to `[dialogue].speak_file`),
`--listen-file` (optional, defaults to `[dialogue].listen_file`),
`--mic-threshold`, `--mic-silence`, `--mic-min-speech`,
`--calibrate-noise/--no-calibrate-noise`, `--wake-word WORD`, `--no-wake-word`,
`--wake-timeout SECONDS`, `--include-trigger/--strip-trigger`,
`--wake-alert/--no-wake-alert`.

#### Duplex modes

Two orthogonal `[dialogue]` flags in config control mic/speaker interaction:

| `barge_in` | `full_duplex` | Mode | When to use it |
|------------|---------------|------|----------------|
| `true`     | `true`        | **Full-duplex + barge-in** (default) | Headphones. Natural conversation — start talking and TTS cuts off. |
| `true`     | `false`       | **Speaker-safe half-duplex** | Open speakers. Mic is gated while TTS plays so the model never hears itself. |
| `false`    | `true`        | **Loopback / self-dialogue** | Agent speaks, transcribes its own output, and continues — the feedback loop is the feature. |
| `false`    | `false`       | **Walkie-talkie** | Strict turn-taking, no interrupts. |

See `README.md` § "Dialogue duplex modes" for the full example config.

### Wake word

`cai listen` and `cai dialogue` support an optional trigger-word gate that
filters Whisper's output before it reaches the sink file. Until a trigger
is spoken the gate drops every utterance; once matched it opens a sliding
window during which every utterance passes through. Silence past
`timeout_seconds` re-arms the gate.

Matching rule: the trigger must appear at the start of an utterance
**followed by punctuation** (`. , ! ? ; :`) or end-of-utterance. This
distinguishes addressing the system (`"Computer, hello"`) from using the
word in conversation (`"Computer science is cool"` — rejected). It relies
on Whisper's pause-based punctuation, so a deliberate pause after the
trigger is what actually opens the gate.

On activation the gate echoes `[wake] 'computer' heard — listening` to
stderr and (unless `--no-wake-alert`) plays a short two-tone chime.
Subsequent utterances in the open window are not re-announced.

Config (`[wake_word]`):

```toml
[wake_word]
enabled         = false       # turn the gate on globally
word            = "computer"  # trigger word
include_trigger = false       # false strips trigger + punctuation from the line
timeout_seconds = 30.0        # silence required to re-arm
alert_sound     = true        # play activation chime
```

CLI overrides: `--wake-word WORD` forces `enabled=true` and sets the
trigger; `--no-wake-word` forces the gate off regardless of config.
`--wake-timeout`, `--include-trigger/--strip-trigger`, and
`--wake-alert/--no-wake-alert` override the corresponding fields. The gate
composes with duplex modes — it's a third text-layer filter above
`barge_in` (VAD level) and `full_duplex` (mic level).

Implementation uses the already-loaded Whisper model; no separate
wake-word model is loaded.

## Shared Configuration

All subcommands read from the XDG config at
`~/.config/conversational_ai/config.toml` (auto-created on first run) and
accept global flag overrides:

```bash
# Global options (before subcommand)
cai --config ~/.config/conversational_ai/config.toml speak "hello"
cai --tts-model mlx-community/Kokoro-82M-bf16 speak "hello"
cai --no-tts listen output.txt   # skip loading TTS model
cai --no-stt speak "hello"       # skip loading STT model
```

Sections in the config file (see `src/config.py` for the exhaustive schema):

```toml
[server]       # host, port (default 127.0.0.1:4114) — used by `cai serve`
[tts]          # model, voice, speed, lang_code
[stt]          # model
[models]       # models_dir (local model cache)
[dialogue]     # speak_file, listen_file, barge_in, full_duplex
[mic]          # rms_threshold, silence_seconds, min_speech_seconds,
               # calibrate_noise, calibration_seconds, calibration_multiplier
[wake_word]    # enabled, word, include_trigger, timeout_seconds, alert_sound
[limits]       # max_text_length, max_audio_file_size (API-side only)
[log]          # log_dir, max_age_days
```

Config layering: hardcoded Pydantic defaults → TOML file → CLI flags.

## Audio I/O

- **Playback**: Streaming via mlx-audio's `AudioPlayer` (uses `sounddevice`). TTS chunks
  are fed to the player as they are generated for low-latency playback. Accepts a
  `cancel: threading.Event` for barge-in; when set mid-stream the player flushes
  instead of draining so the speaker goes quiet immediately.
- **Recording**: `sounddevice.InputStream` at 16kHz mono. VAD via RMS energy thresholding:
  recording starts when `min_speech_seconds` of sustained above-threshold audio is
  observed (pre-latch ring buffer preserves onset) and stops after
  `silence_seconds` of trailing silence. All knobs are in `[mic]` / CLI flags.
- **Noise calibration** (opt-in): samples room tone for `calibration_seconds`
  at startup and sets the effective threshold to
  `max(rms_threshold, measured_floor × calibration_multiplier)`. An EMA over
  silence-chunk RMS drifts the effective threshold during long sessions.
- **Sample rates**: TTS outputs 24kHz; STT expects 16kHz. mlx-audio handles resampling
  internally when given a file path, so recordings are saved as temp WAV files at the
  recording sample rate.

## File Watching

A dedicated worker thread per watched file polls `path.stat().st_mtime` on a
300ms interval (`_POLL_INTERVAL` in `src/cli/watch.py`) and reads any newly
appended bytes from the tracked offset. Pure stdlib — no FSEvents, inotify,
or cross-platform observer library. Truncation is detected by a shrinking
file size and resets the offset to 0.

## Concurrency Model

Threading, not asyncio. Rationale:
- `sounddevice` callbacks are thread-based.
- The mtime-poller file watcher runs on its own worker thread.
- MLX inference is blocking CPU/GPU work.
- A shared `threading.Lock` serializes all model inference calls.
- A shared `threading.Event` coordinates graceful shutdown.

## Dependencies

| Package          | Version   | Purpose                                    |
|------------------|-----------|--------------------------------------------|
| click            | 8.1.8     | CLI framework                              |
| fastapi          | 0.115.12  | HTTP API server                            |
| uvicorn          | 0.34.2    | ASGI server for FastAPI                    |
| python-multipart | 0.0.20    | File upload parsing (`/v1/stt`)            |
| transformers     | 5.3.0     | Pinned — see CONTRIBUTING.md §constraint   |
| mlx-audio        | editable  | TTS/STT inference on Apple Silicon         |

`sounddevice`, `soundfile`, and `numpy` are already transitive dependencies
via `mlx-audio[all]`.

## Entry Point

The `cai` shell wrapper at `~/.local/bin/cai` (created by `install.sh`) runs
`uv run --directory ~/.local/share/conversational_ai python cli.py "$@"`.
`cli.py` re-exports the Click group defined in `src/cli/__init__.py`. The
`serve` subcommand (`src/cli/serve.py`) is the only path that starts the
FastAPI app; all other subcommands skip it.

`cai` with no subcommand prints the standard Click help text.

## Future work

See `tasks/TODO.md` for the live roadmap:

- Feature 3: Claude Code skill + installer
- Feature 4: `--duration` / `--no-vad` on transcribe, `--debounce` on watch
- Feature 8: timestamped output with optional speaker handles

## Success Criteria

1. `cai speak "hello"` plays audio through speakers within 2 seconds of invocation.
2. `cai transcribe` records speech and prints accurate text.
3. `cai watch file.txt` speaks new content within 1 second of a write.
4. `cai listen out.txt` transcribes speech and appends to file continuously.
5. `cai dialogue` runs both directions simultaneously without deadlocks or audio glitches.
6. `cai serve` starts the API server identically to the current behavior.
7. All existing tests continue to pass.
