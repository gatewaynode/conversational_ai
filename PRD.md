# PRD: Conversational AI — CLI Interface

## Problem

The conversational-ai project currently only exposes TTS/STT via a REST API server.
Users who want to interact with these models directly from the terminal — speaking text
through speakers, transcribing from a microphone, or building simple voice pipelines
between files — must write their own client code against the API.

A native CLI interface eliminates this friction: same models, no server overhead, and
composable UNIX-style commands that plug into existing workflows.

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
cai serve --port 9000 --voice af_sky
```

### `cai speak`

Synthesize text and play through speakers.

```bash
# Inline text
cai speak "Hello, can you hear me?"

# From stdin (pipe-friendly)
echo "Hello world" | cai speak

# From file
cai speak --input-file notes.txt

# Override voice/speed
cai speak --voice af_sky --speed 1.2 "Good morning"
```

Options: `--voice`, `--speed`, `--lang-code`, `--input-file`

### `cai transcribe`

Record from microphone and print transcription.

```bash
# Record until silence detected, print text
cai transcribe

# Record for max 10 seconds
cai transcribe --duration 10

# Write to file instead of stdout
cai transcribe --output transcript.txt

# Disable silence detection (press Enter to stop)
cai transcribe --no-vad
```

Options: `--duration`, `--vad/--no-vad`, `--vad-threshold`, `--silence-duration`, `--output`

### `cai watch`

Watch a file for changes and speak new content through speakers.

```bash
# Watch a file, speak any new lines appended to it
cai watch conversation.txt

# With custom voice
cai watch --voice af_sky agent_output.txt
```

Behavior:
- Tracks the file's byte offset. On each change, reads only new content from the last
  known position.
- If the file is truncated (size shrinks), resets to the beginning.
- Debounces rapid writes (0.3s) to avoid partial reads.
- Runs until Ctrl+C.

Options: `--voice`, `--speed`, `--lang-code`, `--debounce`

### `cai listen`

Continuously listen to the microphone and append transcriptions to a file.

```bash
# Listen and append to a file
cai listen output.txt

# With timestamps
cai listen --timestamp output.txt

# Also print to stdout for feedback
# (stdout echo is on by default)
```

Behavior:
- Records one utterance at a time (VAD-based silence detection).
- Transcribes and appends text to the output file.
- Prints each transcription to stdout for feedback.
- Loops until Ctrl+C.

Options: `--timestamp/--no-timestamp`, `--vad-threshold`, `--silence-duration`

### `cai dialogue`

Run watch + listen simultaneously for two-party voice interaction.

```bash
# Watch speak-file for text to speak, write mic transcriptions to listen-file
cai dialogue --speak-file agent.txt --listen-file human.txt
```

Use case: An AI agent writes text to `agent.txt`. The human hears it spoken aloud and
responds verbally. Their speech is transcribed and appended to `human.txt`, which the
AI agent reads.

Behavior:
- Thread 1: Watches `--speak-file` and queues new text for TTS playback.
- Thread 2: Continuously records from the mic and appends transcriptions to `--listen-file`.
- An inference lock serializes TTS and STT calls (MLX is not thread-safe for concurrent ops).
- Both threads shut down gracefully on Ctrl+C.

Options: `--speak-file` (required), `--listen-file` (required), `--voice`, `--speed`,
`--vad-threshold`, `--silence-duration`, `--timestamp/--no-timestamp`

## Shared Configuration

All subcommands inherit the existing config system:

```bash
# Global options (before subcommand)
cai --config ~/.config/conversational_ai/config.toml speak "hello"
cai --tts-model mlx-community/Kokoro-82M-bf16 speak "hello"
cai --no-tts listen output.txt   # skip loading TTS model
cai --no-stt speak "hello"       # skip loading STT model
```

Config layering (unchanged): hardcoded defaults → TOML file → CLI flags.

## Audio I/O

- **Playback**: Streaming via mlx-audio's `AudioPlayer` (uses `sounddevice`). TTS chunks
  are fed to the player as they are generated for low-latency playback.
- **Recording**: `sounddevice.InputStream` at 16kHz mono. VAD via RMS energy thresholding:
  recording starts on speech detection and stops after ~1.5s of silence (configurable).
- **Sample rates**: TTS outputs 24kHz; STT expects 16kHz. mlx-audio handles resampling
  internally when given a file path, so recordings are saved as temp WAV files at the
  recording sample rate.

## File Watching

Uses the `watchdog` library (FSEvents on macOS) for efficient, event-driven file monitoring.
No polling. Changes are debounced to handle rapid writes from other processes.

## Concurrency Model

Threading, not asyncio. Rationale:
- `sounddevice` callbacks are thread-based.
- `watchdog` Observer is thread-based.
- MLX inference is blocking CPU/GPU work.
- A shared `threading.Lock` serializes all model inference calls.
- A shared `threading.Event` coordinates graceful shutdown.

## New Dependencies

| Package     | Version  | Purpose                            |
|-------------|----------|------------------------------------|
| click       | 8.1.8    | CLI framework                      |
| watchdog    | 6.0.0    | File system monitoring (FSEvents)  |

`sounddevice` and `soundfile` are already transitive dependencies via `mlx-audio[all]`.

## Entry Point Changes

The current `cai` shell script (from `install.sh`) calls `python main.py`. After this
change, `cai` will call `python cli.py` which is the Click entry point. The `serve`
subcommand replaces direct `main.py` invocation.

Backward compatibility: `cai` with no subcommand shows help text listing all subcommands.

## Success Criteria

1. `cai speak "hello"` plays audio through speakers within 2 seconds of invocation.
2. `cai transcribe` records speech and prints accurate text.
3. `cai watch file.txt` speaks new content within 1 second of a write.
4. `cai listen out.txt` transcribes speech and appends to file continuously.
5. `cai dialogue` runs both directions simultaneously without deadlocks or audio glitches.
6. `cai serve` starts the API server identically to the current behavior.
7. All existing tests continue to pass.
