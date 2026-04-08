## Project Context

This project is a **TTS/STT API server** built on `mlx-audio` for use by locally hosted web apps.
It exposes REST endpoints for text-to-speech and speech-to-text over HTTP (localhost only).

Key stack:
- **Python 3.12+** managed by `uv`
- **FastAPI + uvicorn** for the HTTP API layer
- **mlx-audio** (local path `../mlx-audio`) for TTS and STT inference on Apple Silicon
- Models loaded from HuggingFace Hub or local paths via `mlx_audio.tts.load` / `mlx_audio.stt.load`

---

## Python & uv Toolchain

### Package Management
- Always use `uv` — never `pip` directly
  - `uv add <pkg>` to add a dependency (updates `pyproject.toml` + lockfile)
  - `uv sync` to install from lockfile
  - `uv run <script>` to execute without activating the venv
  - `uv run pytest` to run tests
- mlx-audio is installed as a local editable dependency: `uv add --editable ../mlx-audio[all]`
- Never use `pip install`, `poetry`, or `conda` in this project

### Python Style
- Use type annotations on all function signatures
- Prefer `dataclasses` or `pydantic` models for structured data (Pydantic for FastAPI I/O)
- Use `async def` for FastAPI route handlers; keep blocking mlx inference calls in a thread pool via `asyncio.to_thread()`
- Keep files ≤ 500 lines; split by concern (routes, models, audio utils)
- No bare `except:`; always catch specific exception types
- Format with `ruff format`; lint with `ruff check`

### mlx-audio Patterns

**TTS (Text-to-Speech):**
```python
from mlx_audio.tts import load

model = load("mlx-community/Kokoro-82M-bf16")
for result in model.generate(text="Hello!", voice="af_heart", speed=1.0, lang_code="a"):
    audio = result.audio        # mx.array
    sample_rate = result.sample_rate  # typically 24000
```

**STT (Speech-to-Text):**
```python
from mlx_audio.stt import load

model = load("mlx-community/whisper-large-v3-turbo-asr-fp16")
result = model.generate("path/to/audio.wav")
text = result.text
```

- Load models once at startup; keep them as module-level singletons
- Convert `mx.array` audio to `bytes` (wav) using `soundfile` or `scipy.io.wavfile` before sending over HTTP
- Prefer Kokoro or Whisper as defaults (fast, well-tested)

### Dependency Policy
- Pin all dependencies in `pyproject.toml` with exact versions (N-1 rule: no packages <30 days old)
- Use `uv lock` to regenerate the lockfile after changes
- `mlx-audio` installs via local editable path — no version pin needed for it

---

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep the main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One tack per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behaviour between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Write tests that provide real demonstration of working code — no mocks, no always-true tests
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "Is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user

---

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections

---

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Minimal code impact.
- **No laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary.

---

## Development Guidelines

- **Small and Modular**: Keep individual files ≤ 500 lines; use thoughtful composition
- **Follow the UNIX philosophy**:
  - "Make it easy to write, test, and run programs."
  - "Interactive instead of batch processing."
  - "Economy and elegance of design due to size constraints."
  - "Self-supporting system: avoid dependencies when possible."

---

## Security

- **Security First**: API is localhost-only; add CORS restrictions, no public exposure
- **Never Use Latest Dependencies**: N-1 rule; never use packages <30 days old
- **Pin Dependencies**: Always pin with exact versions in `pyproject.toml`
- **Input Validation**: Validate text length, audio file size, and MIME types at API boundaries
- **No Shell Injection**: Never pass user input to shell commands
- **Thoroughly Review Everything**: Run security, style, and architecture reviews regularly

## MCP Tools

- **tilth**: Smarter code reading for Agents
