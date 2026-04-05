# conversational-ai

A localhost TTS/STT API server built on [mlx-audio](https://github.com/Blaizzy/mlx-audio) for Apple Silicon. Exposes REST endpoints that a web page in Chrome (or any local client) can call to synthesise speech from text and transcribe audio files back to text.

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

# Start the server (downloads models on first run ~500 MB)
uv run python main.py
```

Server starts at `http://127.0.0.1:8000`. Visit `/docs` for the interactive OpenAPI UI.

## Configuration

Edit `config.toml` to change defaults:

```toml
[server]
host = "127.0.0.1"
port = 8000

[tts]
model    = "mlx-community/Kokoro-82M-bf16"
voice    = "af_heart"
speed    = 1.0
lang_code = "a"

[stt]
model = "mlx-community/whisper-large-v3-turbo-asr-fp16"

[limits]
max_text_length     = 5000      # characters
max_audio_file_size = 26214400  # bytes (25 MB)
```

Any value can be overridden at launch with a CLI flag:

```bash
uv run python main.py --voice af_sky --speed 1.2 --port 9000
uv run python main.py --tts-model mlx-community/Kokoro-82M-bf16 \
                      --stt-model mlx-community/whisper-large-v3-turbo-asr-fp16
```

Run `uv run python main.py --help` for the full flag list.

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
curl -X POST http://127.0.0.1:8000/v1/tts \
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
curl -X POST http://127.0.0.1:8000/v1/stt \
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
# Run tests
uv run pytest

# Lint / format
uv run ruff check src tests
uv run ruff format src tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for architecture details and contribution guidelines.

## Project layout

```
conversational_ai/
├── main.py              # Entry point — argparse, app factory, uvicorn
├── config.toml          # Default configuration
├── src/
│   ├── config.py        # TOML + CLI settings (Pydantic)
│   ├── models.py        # ModelManager — TTS/STT singleton loader
│   ├── audio.py         # WAV encoding, upload validation, temp files
│   ├── schemas.py       # Pydantic request/response models
│   ├── middleware.py    # X-Limit-* response headers
│   └── routes/
│       ├── tts.py       # POST /v1/tts
│       ├── stt.py       # POST /v1/stt
│       └── system.py    # GET /v1/health, GET /v1/models
└── tests/               # pytest test suite (79 tests)
```

## License

MIT — see [LICENSE](LICENSE).
