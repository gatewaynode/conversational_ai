# conversational-ai

A terminal-first TTS/STT platform built on [mlx-audio](https://github.com/Blaizzy/mlx-audio) for Apple Silicon. The primary interface is the `cai` CLI — speak text, transcribe speech, watch files, and run two-way voice dialogues from the terminal. A companion HTTP API (`cai serve`) exposes the same TTS/STT models to browser-based clients that can't invoke the CLI directly.

## Requirements

- macOS with Apple Silicon (M1/M2/M3/M4)
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

## Quick start

```bash
# Clone and enter the project
git clone <repo-url>
cd conversational_ai

# Install dependencies (creates .venv automatically)
uv sync

# Try the CLI (downloads models on first run ~500 MB)
uv run python cli.py speak "Hello, world!"

# Or start the HTTP API for browser clients
uv run python cli.py serve
```

The HTTP server (when `cai serve` is running) listens at
`http://127.0.0.1:4114`. Visit `/docs` for the interactive OpenAPI UI.

## Installation (persistent `cai` command)

`install.sh` copies the app to `~/.local/share/conversational_ai/` and creates a
`cai` launcher at `~/.local/bin/cai`.

```bash
# mlx-audio must be checked out as a sibling directory: ../mlx-audio
bash install.sh
```

Ensure `~/.local/bin` is in your PATH (add to `~/.zshrc` or `~/.bashrc` if not):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

**Updating:** re-run `install.sh` at any time to sync the latest source and dependency changes to the installed copy.

## Configuration

The config file lives at `~/.config/conversational_ai/config.toml` and is
auto-created with the default template on first run. Edit it to change
defaults:

```toml
[server]
host = "127.0.0.1"
port = 4114

[tts]
model     = "mlx-community/Kokoro-82M-bf16"
voice     = "af_heart"
speed     = 1.0
lang_code = "a"

[stt]
model = "mlx-community/whisper-large-v3-turbo-asr-fp16"

[models]
models_dir = "~/.lmstudio/models"

[dialogue]
speak_file  = "~/.local/share/conversational_ai/speak.txt"
listen_file = "~/.local/share/conversational_ai/listen.txt"
barge_in    = true   # VAD rising edge cancels in-flight TTS
full_duplex = true   # mic stays hot while TTS is playing

[mic]
rms_threshold          = 0.01   # RMS above which a chunk counts as speech
silence_seconds        = 1.5    # trailing silence that ends an utterance
min_speech_seconds     = 0.15   # sustained speech required to latch
calibrate_noise        = false  # sample room tone at startup (opt-in)
calibration_seconds    = 1.0
calibration_multiplier = 3.0

[limits]
max_text_length     = 5000      # characters
max_audio_file_size = 26214400  # bytes (25 MB)

[log]
log_dir      = "~/.local/state/conversational_ai"
max_age_days = 7
```

See [Dialogue duplex modes](#dialogue-duplex-modes) for the `barge_in` /
`full_duplex` matrix.

Any value can be overridden at launch with a CLI flag:

```bash
cai --voice af_sky --speed 1.2 speak "Good morning"
cai --tts-model mlx-community/Kokoro-82M-bf16 \
    --stt-model mlx-community/whisper-large-v3-turbo-asr-fp16 \
    transcribe
```

Run `cai --help` for the full global flag list, or `cai <subcommand> --help`
for per-subcommand options.

## API

All responses include `X-Limit-Max-Text-Length` and `X-Limit-Max-Audio-File-Size` headers so clients always know the active limits.

### `POST /v1/tts`

Convert text to speech. Returns a WAV audio file.

**Request** (`application/json`):
```json
{
  "text": "Hello, can you hear me?",
  "voice": "af_heart",
  "speed": 1.0,
  "lang_code": "a"
}
```
`voice`, `speed`, and `lang_code` are optional — server defaults apply when omitted.

**Response**: `audio/wav` binary

```bash
curl -X POST http://127.0.0.1:4114/v1/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, world!"}' \
  -o speech.wav
```

### `POST /v1/stt`

Transcribe an audio file. Returns JSON with the transcribed text.

**Request**: multipart form upload, field name `file`.  
Accepted types: WAV, MP3, MP4, OGG, FLAC, WebM, AAC.

**Response** (`application/json`):
```json
{
  "text": "Hello, world!",
  "segments": [...],
  "language": "en"
}
```

```bash
curl -X POST http://127.0.0.1:4114/v1/stt \
  -F "file=@speech.wav;type=audio/wav"
```

### `GET /v1/health`

```json
{"status": "ok", "tts_loaded": true, "stt_loaded": true}
```

`status` is `"ok"` when both models are loaded, `"degraded"` when one is, `"unavailable"` when neither is.

### `GET /v1/models`

```json
{
  "tts": {"name": "mlx-community/Kokoro-82M-bf16", "loaded": true},
  "stt": {"name": "mlx-community/whisper-large-v3-turbo-asr-fp16", "loaded": true}
}
```

## CORS

The server allows requests from `http://localhost:*` and `http://127.0.0.1:*` only. External origins are blocked.

## Development

```bash
# Run tests (189 as of 2026-04-17)
uv run pytest

# Lint / format
uv run ruff check src tests
uv run ruff format src tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for architecture details and contribution guidelines.

## CLI usage

`cai` is the unified entry point for both the API server and direct terminal TTS/STT.

### Subcommands

| Command | Description |
|---------|-------------|
| `cai serve` | Start the HTTP API server |
| `cai speak [TEXT]` | Speak text via TTS (arg, `--file`, or stdin) |
| `cai transcribe` | Record from mic → print transcription |
| `cai watch FILE` | Watch a file — speak any new content appended to it |
| `cai listen FILE` | Continuous mic → append transcriptions to FILE |
| `cai dialogue --speak-file A --listen-file B` | Watch + listen simultaneously |

### Examples

```bash
# Speak text directly
cai speak "Hello, world!"

# Speak a file
cai speak --file notes.txt

# Transcribe one utterance to stdout
cai transcribe

# Transcribe to a file
cai transcribe -o transcript.txt

# Speak whatever gets appended to a file (Ctrl+C to stop)
cai watch /tmp/tts.txt

# Append mic transcriptions to a file (Ctrl+C to stop)
cai listen /tmp/stt.txt

# Two-way: speak from a.txt, transcribe mic to b.txt
cai dialogue --speak-file a.txt --listen-file b.txt

# Start the HTTP server
cai serve
```

### Dialogue duplex modes

`cai dialogue` runs TTS (file → speaker) and STT (mic → file) at the same
time. Two orthogonal flags in the `[dialogue]` section of `config.toml`
cover the four useful combinations:

```toml
[dialogue]
speak_file  = "~/.local/share/conversational_ai/speak.txt"
listen_file = "~/.local/share/conversational_ai/listen.txt"
barge_in    = true   # VAD rising edge cancels in-flight TTS
full_duplex = true   # mic stays hot while TTS is playing
```

| `barge_in` | `full_duplex` | Mode | When to use it |
|------------|---------------|------|----------------|
| `true`     | `true`        | **Full-duplex + barge-in** (default) | Headphones. Natural conversation — start talking and TTS stops mid-sentence. |
| `true`     | `false`       | **Speaker-safe half-duplex** | Open speakers, no headphones. Mic is gated while TTS plays so the model never hears itself; your next utterance still interrupts the *following* TTS reply. |
| `false`    | `true`        | **Loopback / self-dialogue** | Intentional TTS → mic → STT chains. The agent speaks, transcribes its own output, and continues — the feedback loop is the feature. |
| `false`    | `false`       | **Walkie-talkie** | Predictable turn-taking. Strict half-duplex, TTS always finishes, no interrupts. Simplest model when you want zero surprises. |

Example — running dialogue in speaker-safe mode on a laptop without
headphones:

```toml
# ~/.config/conversational_ai/config.toml
[dialogue]
barge_in    = true
full_duplex = false
```

```bash
cai dialogue --speak-file a.txt --listen-file b.txt
# Startup banner shows the active mode:
#   Dialogue active [barge_in=True full_duplex=False] — watching …
```

Loopback mode for agent-talks-to-itself workflows — point both files at
the same path and let the agent drive its own conversation:

```toml
[dialogue]
barge_in    = false
full_duplex = true
```

```bash
cai dialogue --speak-file scratch.txt --listen-file scratch.txt
```

### Global options

All subcommands accept these options **before** the subcommand name:

```
--config PATH        Path to TOML config file (overrides XDG path)
--tts-model MODEL    Override TTS model
--stt-model MODEL    Override STT model
--voice VOICE        Override TTS voice
--speed SPEED        Override TTS speed (0.1–5.0)
--lang-code CODE     Override TTS language code
--models-dir DIR     Local models directory (default: ~/.lmstudio/models)
--no-tts             Skip loading the TTS model
--no-stt             Skip loading the STT model
```

### Mic flags (transcribe / listen / dialogue)

These subcommands share a common set of per-command flags for tuning the
voice-activity detector and opting into noise calibration:

```
--mic-threshold FLOAT                   Override [mic].rms_threshold
--mic-silence SECONDS                   Override [mic].silence_seconds
--mic-min-speech SECONDS                Override [mic].min_speech_seconds
--calibrate-noise / --no-calibrate-noise
                                        Sample room tone at startup
```

Example:

```bash
# Tighten the gate and calibrate before a noisy-kitchen dictation session
cai listen --mic-threshold 0.03 --mic-min-speech 0.25 --calibrate-noise out.txt
```

## Project layout

```
conversational_ai/
├── cli.py               # `cai` entry point — re-exports src.cli.cli
├── main.py              # FastAPI app factory (used by `cai serve`)
├── src/
│   ├── config.py        # XDG TOML + CLI settings (Pydantic)
│   ├── models.py        # ModelManager — TTS/STT loader and inference
│   ├── audio.py         # WAV encoding, upload validation, temp files
│   ├── schemas.py       # Pydantic request/response models
│   ├── middleware.py    # X-Limit-* response headers
│   ├── logging_setup.py # Log rotation + setup
│   ├── routes/
│   │   ├── tts.py       # POST /v1/tts
│   │   ├── stt.py       # POST /v1/stt
│   │   └── system.py    # GET /v1/health, GET /v1/models
│   └── cli/
│       ├── __init__.py  # Click group, shared startup (config + models)
│       ├── audio_io.py  # Streaming TTS playback + mic recording (VAD, calibration)
│       ├── serve.py     # `cai serve`
│       ├── speak.py     # `cai speak`
│       ├── transcribe.py# `cai transcribe`
│       ├── watch.py     # `cai watch`
│       ├── listen.py    # `cai listen`
│       └── dialogue.py  # `cai dialogue`
└── tests/               # pytest test suite (189 tests)
```

## License

MIT — see [LICENSE](LICENSE).
