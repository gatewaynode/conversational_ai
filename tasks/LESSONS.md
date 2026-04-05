# Lessons — conversational-ai

Bugs, tricky workarounds, and non-obvious decisions discovered during development.
Format: rule/fact, then **Why:** (root cause) and **How to apply:** (when this matters).

---

## 1. Pin `transformers==5.3.0` — do not upgrade without checking mistral_common

`transformers 5.4+` imports `ReasoningEffort` from `mistral_common.protocol.instruct.request`. That symbol does not exist in any released version of `mistral_common` (latest as of April 2026: `1.9.1`). The import is inside `tokenization_mistral_common.py`, which gets pulled in when `WhisperProcessor.from_pretrained` is called.

**Why:** `mlx-audio` requires `transformers>=5.0.0` and `mistral-common[audio]` (unpinned). uv resolved `transformers==5.5.0` + `mistral-common==1.9.1`, which is a broken combination neither package maintainer has flagged.

**How to apply:** Before bumping `transformers`, grep the new wheel for `ReasoningEffort` in `tokenization_mistral_common.py` and verify it exists in the installed `mistral_common` version. If not, hold at `5.3.0`.

---

## 2. Whisper model loads without error but silently has no tokenizer

When `WhisperProcessor.from_pretrained` fails (e.g. due to lesson 1 above), mlx-audio's `whisper.py` catches the exception, sets `model._processor = None`, and emits a `UserWarning` — not an exception. The model object is returned successfully. Any subsequent call to `model.generate()` then fails deep inside `_detect_language` → `get_tokenizer()` with `ValueError: Processor not found`.

**Why:** The failure is a graceful degradation that isn't graceful in practice — the model is unusable but `load()` returns successfully and `ModelManager.stt_loaded` is `True`.

**How to apply:** After loading a Whisper STT model, assert `model._processor is not None` before marking it as ready. If adding a health check or model validation step, probe the tokenizer explicitly. Watch for `UserWarning: Could not load WhisperProcessor` in server startup logs — it means STT will fail at inference time.

---

## 3. `curl -si -o file` writes HTTP headers into the binary file

`curl -si` (silent + include response headers) prints headers to stdout before the body. When combined with `-o file`, both headers and body land in the file. The resulting WAV starts with `HTTP/1.1 200 OK\r\n...` and miniaudio raises `DecodeError: could not open/decode file`.

**Why:** `-i` / `--include` always prepends headers to whatever output sink is active, including `-o`.

**How to apply:** Use `-s` (no progress) without `-i` when saving binary output. To inspect headers separately, use `-D /dev/stderr` or a second request with `-sI` (HEAD).

---

## 4. FastAPI `TestClient` lifespan only fires inside a `with` block

Constructing `TestClient(app)` without entering it as a context manager does not run the lifespan startup event. `app.state.model_manager` and `app.state.settings` are never set, and every route raises `AttributeError: 'State' object has no attribute 'model_manager'`.

**Why:** Starlette's `TestClient` defers lifespan execution until `__enter__` is called (ASGI lifespan protocol).

**How to apply:** Always use `with TestClient(app) as client:` in tests — or a `pytest.fixture` that yields from inside a `with` block. The pattern `client = TestClient(app); client.get(...)` without `with` will silently skip startup.

---

## 5. mlx-audio STT `model.generate()` requires a file path, not bytes

`mlx_audio.stt.models.whisper.Model.generate()` calls `load_audio(audio)` which calls `miniaudio.get_file_info(str(file))`. It does not accept `bytes`, `BytesIO`, or numpy arrays — only a path string or `Path` object pointing to an audio file on disk.

**Why:** The underlying audio loading stack (miniaudio → audio_io) is file-oriented.

**How to apply:** Always write audio bytes to a `NamedTemporaryFile` before calling `generate_stt`, and delete it in a `finally` block. The suffix must match the audio format (`.wav`, `.mp3`, etc.) because miniaudio uses it for format detection.

---

## 6. CORS `allow_origins` doesn't support port wildcards — use `allow_origin_regex`

`CORSMiddleware(allow_origins=["http://localhost:*"])` does not work. FastAPI/Starlette matches origin strings exactly; the `*` is not treated as a wildcard in the origins list.

**Why:** The CORS spec requires exact origin matching. Port wildcarding is not part of the spec.

**How to apply:** Use `allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?"` to match any port on localhost. This covers development servers on arbitrary ports (Vite, webpack-dev-server, etc.) without opening the API to the internet.

---

## 7. `mx.array` does not support the numpy `__array__` protocol directly

`np.asarray(mx_array)` may fail or produce unexpected results depending on the mlx version. The safe conversion path is `np.array(mx_array.tolist(), dtype=np.float32)`.

**Why:** mlx arrays are on the Metal GPU. `tolist()` forces evaluation and copies to CPU as a Python list, which numpy can then consume.

**How to apply:** Wherever a `GenerationResult.audio` (type `mx.array`) needs to become numpy for processing, use `.tolist()` → `np.array(...)`. Note: `mlx_audio.audio_io.write` handles this conversion internally, so you only need to do it manually when manipulating audio data before passing it to the writer (e.g. concatenating chunks).

---

## 8. TTS `model.generate()` is a generator — collect all chunks before encoding

`mlx_audio.tts.Model.generate()` yields `GenerationResult` objects one per sentence segment. Calling `tts_result_to_wav_bytes` on a partial or unconsumed generator produces truncated audio.

**Why:** Kokoro (and other mlx-audio TTS models) split input text by a `split_pattern` (default `\n+`) and yield one chunk per segment.

**How to apply:** `ModelManager.generate_tts()` collects all chunks into a list before returning. Do not pass the raw generator to `tts_result_to_wav_bytes`. If streaming is added later, the encoder will need to be restructured to handle incremental WAV writing.
