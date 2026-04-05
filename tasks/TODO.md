# TODO: TTS/STT API Server

## Phase 1: Project Setup

- [x] Update `pyproject.toml`: add fastapi, uvicorn, python-multipart as pinned deps
- [x] Add mlx-audio as editable local dependency via `uv add --editable ../mlx-audio[all]`
- [x] Add ruff as dev dependency for linting/formatting
- [x] Create `src/__init__.py`
- [x] Create `src/routes/__init__.py`
- [x] Create `config.toml` with default values
- [x] Run `uv sync` to verify dependency resolution

## Phase 2: Config Layer

- [x] Write `src/config.py`: Pydantic `Settings` model with all fields
- [x] Write `load_config()` using `tomllib` (stdlib)
- [x] Write `build_settings()` that merges TOML + CLI overrides
- [x] Write `tests/test_config.py`: TOML loading, CLI override precedence, defaults

## Phase 3: Model Manager

- [x] Write `src/models.py`: `ModelManager` class with `load_tts()`, `load_stt()`
- [x] Add `generate_tts()` wrapper: call model.generate(), collect GenerationResult chunks
- [x] Add `generate_stt()` wrapper: call model.generate(path), return STTOutput
- [x] Smoke test: `uv run python -c "from src.models import ModelManager"`

## Phase 4: Audio Utilities

- [x] Write `src/audio.py`: `tts_result_to_wav_bytes()` — concatenate mx.array chunks, encode WAV
- [x] Add `validate_audio_upload()`: check Content-Type, file size
- [x] Add `save_temp_audio()`: write bytes to temp file, return path
- [x] Write `tests/test_audio.py`: WAV conversion, validation rejects oversized files

## Phase 5: Request/Response Schemas

- [x] Write `src/schemas.py`: TTSRequest, STTResponse, ModelsResponse, HealthResponse
- [x] Add Pydantic field validators (text length on TTSRequest)

## Phase 6: Route Handlers

- [x] Write `src/routes/tts.py`: POST /v1/tts with asyncio.to_thread()
- [x] Write `src/routes/stt.py`: POST /v1/stt with file upload, temp file, cleanup
- [x] Write `src/routes/system.py`: GET /v1/health, GET /v1/models
- [x] Write `tests/test_routes.py`: FastAPI TestClient with mocked ModelManager

## Phase 7: App Assembly & Entry Point

- [x] Rewrite `main.py`: argparse, config loading, FastAPI app factory, uvicorn.run
- [x] Add CORS middleware restricted to localhost origins (allow_origin_regex)
- [x] Wire lifespan event to load models from config at startup
- [x] Include all routers from `src/routes/`

## Phase 8: Integration Testing

- [x] Start server with `uv run python main.py`, verify /v1/health → `{"status":"ok"}`
- [x] Test TTS: WAV returned (92KB, 24kHz, ~2s for "Hello, can you hear me?")
- [x] Test STT round-trip: TTS-generated WAVs fed back through STT with near-perfect transcription
- [x] Verify CORS allows localhost:3000, blocks evil.example.com
- [x] Pin transformers==5.3.0 (5.5.0 had mistral_common ReasoningEffort import bug)
- [x] Play output WAV — audio quality confirmed

## Review

All 79 tests passing. Live round-trip results:
- "Hello, can you hear me?"                      → " Hello, can you hear me?" ✓
- "The quick brown fox jumps over the lazy dog."  → " The quick brown fox jumps over the lazy dog." ✓
- "Good morning! How are you feeling today?"      → " Good morning, how are you feeling today?" ✓
