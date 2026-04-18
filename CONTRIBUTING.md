# Contributing

This document is written for both human contributors and LLM coding agents. It describes the project's architecture, conventions, and contribution workflow precisely enough to make changes without needing to ask clarifying questions.

---

## Architecture overview

The project ships two interfaces sharing one model layer and one config tree:

- **CLI** (`cai`) — Click group rooted at `src/cli/__init__.py`, re-exported
  by `cli.py`. Subcommands: `speak`, `transcribe`, `watch`, `listen`,
  `dialogue`, `serve`.
- **HTTP API** (`cai serve`) — FastAPI app from `main.py:create_app()`
  exposing `POST /v1/tts`, `POST /v1/stt`, `GET /v1/health`, `GET /v1/models`
  on localhost only.

Inference paths:

- **TTS**: text → Kokoro (or any mlx-audio TTS model) → WAV bytes / streamed speaker output
- **STT**: audio → Whisper (or any mlx-audio STT model) → text

### Module map

| File | Responsibility |
|------|---------------|
| `cli.py` | `cai` entry point — re-exports the Click group from `src.cli` |
| `main.py` | FastAPI `create_app()` factory (used by `cai serve`) |
| `src/config.py` | `Settings` Pydantic model, XDG config bootstrap, `build_settings()` merge |
| `src/models.py` | `ModelManager` — loads TTS/STT models; blocking inference wrappers |
| `src/audio.py` | `tts_result_to_wav_bytes()`, `validate_audio_upload()`, `save_temp_audio()` |
| `src/schemas.py` | Pydantic request/response models for all endpoints |
| `src/middleware.py` | `LimitsHeaderMiddleware` — injects `X-Limit-*` headers on every response |
| `src/logging_setup.py` | Rotating file logger setup (`[log]` config) |
| `src/routes/tts.py` | `POST /v1/tts` handler |
| `src/routes/stt.py` | `POST /v1/stt` handler |
| `src/routes/system.py` | `GET /v1/health`, `GET /v1/models` handlers |
| `src/cli/__init__.py` | Click group; shared startup (config load, model loading by subcommand) |
| `src/cli/audio_io.py` | `play_tts_streaming`, `MicRecorder` (VAD + calibration), `mic_recorder_from_settings` |
| `src/cli/serve.py` | `cai serve` — starts uvicorn on the FastAPI app |
| `src/cli/speak.py` | `cai speak` — text → TTS → speakers |
| `src/cli/transcribe.py` | `cai transcribe` — mic → STT → stdout/file |
| `src/cli/watch.py` | `cai watch` — `TextFileHandler` poller thread; file → TTS |
| `src/cli/listen.py` | `cai listen` — continuous mic → STT → append to file |
| `src/cli/dialogue.py` | `cai dialogue` — watch + listen with barge-in / duplex controls |

### Key design decisions

**`ModelManager` lives on `app.state`** — loaded during the FastAPI lifespan startup event, accessed in route handlers via `request.app.state.model_manager`. This avoids import-time side effects and makes the manager injectable in tests.

**`asyncio.to_thread()` for all inference** — mlx inference is blocking (runs on the GPU). Wrapping with `to_thread` keeps the async event loop responsive. Concurrent requests serialize naturally since mlx is single-threaded per process.

**Config layering**: hardcoded Pydantic defaults → XDG `config.toml` → CLI flags. The file lives at `~/.config/conversational_ai/config.toml` and is auto-created with the default template on first run (`ensure_xdg_config()` in `src/config.py`). `build_settings()` handles the merge; CLI `None` values are skipped so unset flags don't overwrite TOML values.

**CLI threading model**: The CLI uses threads (not asyncio) because `sounddevice` callbacks are thread-based and mlx inference is blocking. `dialogue` runs a watcher thread and a listener thread with a shared `threading.Lock` serializing inference and a shared `threading.Event` for graceful shutdown. Barge-in (`barge_event`) and half-duplex gating (`tts_active`) are additional `threading.Event`s — see `src/cli/dialogue.py`.

**Two-layer text length validation**: a hard cap of 10,000 chars in `TTSRequest` (schema level) and a softer configurable cap (`Settings.limits.max_text_length`, default 5,000) enforced in the route handler. Both quote the limit in their error messages.

**Temp files for STT**: mlx-audio's STT `model.generate()` takes a file path. The route writes a `NamedTemporaryFile` (prefix `stt_upload_`), calls inference, then deletes it in a `finally` block.

**CORS**: restricted to `https?://(localhost|127\.0\.0\.1)(:\d+)?` via `allow_origin_regex`. The server is not intended to be reachable from external origins.

---

## Data flow

### TTS request

```
POST /v1/tts  {text, voice?, speed?, lang_code?}
  → TTSRequest Pydantic validation (text length, speed bounds)
  → config limit check in route handler
  → asyncio.to_thread(model_manager.generate_tts, ...)
    → model.generate() yields GenerationResult chunks (mx.array audio)
  → tts_result_to_wav_bytes(results)
    → numpy concatenation + mlx_audio.audio_io.write(BytesIO, ...)
  → Response(audio/wav)
```

### STT request

```
POST /v1/stt  multipart file
  → validate_audio_upload(file, max_size)  [MIME type + size check]
  → save_temp_audio(bytes) → /tmp/stt_upload_XXXX.wav
  → asyncio.to_thread(model_manager.generate_stt, temp_path)
    → model.generate(path) → STTOutput(text, segments, language)
  → temp file deleted (finally)
  → STTResponse JSON
```

---

## Testing

Tests live in `tests/`. All tests are real behaviour tests — no always-true assertions, no mocks that hide real logic.

```bash
uv run pytest          # all 189 tests
uv run pytest -v       # verbose
uv run pytest tests/test_routes.py  # single file
```

### Test structure

| File | What it tests |
|------|--------------|
| `test_config.py` | TOML loading, CLI override precedence, Pydantic validation, mic section |
| `test_audio.py` | WAV encoding round-trips, upload validation, temp file lifecycle |
| `test_schemas.py` | Request/response Pydantic models, field validators |
| `test_models.py` | `ModelManager` load + inference wrappers (with fakes) |
| `test_middleware.py` | `X-Limit-*` headers appear on 2xx and error responses |
| `test_routes.py` | All route handlers via `TestClient` with a `FakeModelManager` |
| `test_integration.py` | Full app stack (real middlewares + real routes) with fake inference |
| `test_cli_audio_io.py` | `MicRecorder` VAD, min-speech gate, calibration, EMA, pre-latch ring, factory helper |
| `test_cli_subcommands.py` | Click subcommands via `CliRunner` (patched model manager + recorder factory) |

### Adding a new test

- Put it in the relevant `test_*.py` file
- Use `FakeModelManager` / `FakeGenerationResult` from `test_routes.py` or `test_integration.py` to avoid loading real models
- Async tests get `asyncio_mode = "auto"` from `pyproject.toml` — no decorator needed

---

## Conventions

### Python style

- Type annotations on all function signatures
- `async def` for FastAPI route handlers; blocking calls wrapped in `asyncio.to_thread()`
- Pydantic v2 models for all structured I/O
- No bare `except:`; catch specific exception types
- Files ≤ 500 lines — split by concern when approaching the limit

### Tooling

```bash
uv run ruff format src tests   # format
uv run ruff check src tests    # lint
```

### Dependencies

- Use `uv add` — never `pip install`
- Pin all new deps to an exact version: `uv add "package==x.y.z"`
- Follow N-1: prefer the release before latest; never add a package less than 30 days old
- Check for breakage before adding: `mlx-audio[all]` brings a large transitive tree; verify new packages don't conflict

### Known dependency constraint

`transformers` is pinned to `==5.3.0`. Versions 5.4+ import `ReasoningEffort` from `mistral_common.protocol.instruct.request`, which does not exist in any released version of `mistral_common` as of April 2026. Do not upgrade `transformers` without verifying that `mistral_common` has gained that symbol.

---

## Adding a new endpoint

1. Add request/response Pydantic models to `src/schemas.py`
2. Create the route handler in `src/routes/<name>.py` following the existing pattern:
   - Get `settings` and `model_manager` from `request.app.state`
   - Use `asyncio.to_thread()` for any blocking inference
   - Return typed response model or `Response` with explicit `media_type`
3. Register the router in `main.py`: `app.include_router(<name>_router, prefix="/v1")`
4. Add tests to `tests/test_routes.py` and `tests/test_integration.py`

## Switching inference models

The CLI / server load whichever model names are in the XDG config (or passed via `--tts-model` / `--stt-model`). To use a different model:

```bash
cai --tts-model mlx-community/outetts-0.3-500M-bf16 speak "hello"
cai --stt-model mlx-community/whisper-large-v3-mlx-4bit transcribe
```

Models are downloaded automatically from HuggingFace Hub on first use and cached in `~/.cache/huggingface/`. The `ModelManager` in `src/models.py` calls `mlx_audio.tts.load()` and `mlx_audio.stt.load()` which auto-detect model type, so no code changes are needed to switch models.

---

## Common tasks

### Run the server

```bash
cai serve
```

### Try the CLI

```bash
cai speak "Hello, world!"      # text → speakers
cai transcribe                 # mic → stdout
cai listen /tmp/notes.txt      # mic → append to file (Ctrl+C to stop)
```

### Test a TTS request (against `cai serve`)

```bash
curl -X POST http://127.0.0.1:4114/v1/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, world!"}' \
  -o speech.wav && afplay speech.wav
```

### Test an STT request

```bash
curl -X POST http://127.0.0.1:4114/v1/stt \
  -F "file=@speech.wav;type=audio/wav"
```

### Check active limits from headers

```bash
curl -sI -X POST http://127.0.0.1:4114/v1/tts \
  -H "Content-Type: application/json" \
  -d '{"text":"x"}' \
  | grep -i x-limit
```
