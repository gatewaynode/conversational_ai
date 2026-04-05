# Contributing

This document is written for both human contributors and LLM coding agents. It describes the project's architecture, conventions, and contribution workflow precisely enough to make changes without needing to ask clarifying questions.

---

## Architecture overview

The server is a **FastAPI application** that wraps `mlx-audio` inference behind REST endpoints. There are two inference paths:

- **TTS**: `POST /v1/tts` → text → Kokoro (or any mlx-audio TTS model) → WAV bytes
- **STT**: `POST /v1/stt` → audio upload → Whisper (or any mlx-audio STT model) → JSON text

### Module map

| File | Responsibility |
|------|---------------|
| `main.py` | CLI (`argparse`), config loading, FastAPI app factory, `uvicorn.run` |
| `src/config.py` | `Settings` Pydantic model, `load_config()` (TOML), `build_settings()` (merge) |
| `src/models.py` | `ModelManager` — loads TTS/STT models once at startup; blocking inference wrappers |
| `src/audio.py` | `tts_result_to_wav_bytes()`, `validate_audio_upload()`, `save_temp_audio()` |
| `src/schemas.py` | Pydantic request/response models for all endpoints |
| `src/middleware.py` | `LimitsHeaderMiddleware` — injects `X-Limit-*` headers on every response |
| `src/routes/tts.py` | `POST /v1/tts` handler |
| `src/routes/stt.py` | `POST /v1/stt` handler |
| `src/routes/system.py` | `GET /v1/health`, `GET /v1/models` handlers |

### Key design decisions

**`ModelManager` lives on `app.state`** — loaded during the FastAPI lifespan startup event, accessed in route handlers via `request.app.state.model_manager`. This avoids import-time side effects and makes the manager injectable in tests.

**`asyncio.to_thread()` for all inference** — mlx inference is blocking (runs on the GPU). Wrapping with `to_thread` keeps the async event loop responsive. Concurrent requests serialize naturally since mlx is single-threaded per process.

**Config layering**: hardcoded Pydantic defaults → `config.toml` → CLI flags. `build_settings()` in `src/config.py` handles the merge. CLI `None` values are skipped so unset flags don't overwrite TOML values.

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
uv run pytest          # all 79 tests
uv run pytest -v       # verbose
uv run pytest tests/test_routes.py  # single file
```

### Test structure

| File | What it tests |
|------|--------------|
| `test_config.py` | TOML loading, CLI override precedence, Pydantic validation |
| `test_audio.py` | WAV encoding round-trips, upload validation, temp file lifecycle |
| `test_schemas.py` | Request/response Pydantic models, field validators |
| `test_middleware.py` | `X-Limit-*` headers appear on 2xx and error responses |
| `test_routes.py` | All route handlers via `TestClient` with a `FakeModelManager` |
| `test_integration.py` | Full app stack (real middlewares + real routes) with fake inference |

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

The server loads whichever model names are in `config.toml` (or passed via CLI). To use a different model:

```bash
uv run python main.py --tts-model mlx-community/outetts-0.3-500M-bf16
uv run python main.py --stt-model mlx-community/whisper-large-v3-mlx-4bit
```

Models are downloaded automatically from HuggingFace Hub on first use and cached in `~/.cache/huggingface/`. The `ModelManager` in `src/models.py` calls `mlx_audio.tts.load()` and `mlx_audio.stt.load()` which auto-detect model type, so no code changes are needed to switch models.

---

## Common tasks

### Run the server

```bash
uv run python main.py
```

### Test a TTS request

```bash
curl -X POST http://127.0.0.1:8000/v1/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, world!"}' \
  -o speech.wav && afplay speech.wav
```

### Test an STT request

```bash
curl -X POST http://127.0.0.1:8000/v1/stt \
  -F "file=@speech.wav;type=audio/wav"
```

### Check active limits from headers

```bash
curl -sI -X POST http://127.0.0.1:8000/v1/tts \
  -H "Content-Type: application/json" \
  -d '{"text":"x"}' \
  | grep -i x-limit
```
