# Architecture: Conversational AI — TTS/STT Server & CLI

## Overview

A localhost-only TTS/STT platform for Apple Silicon, built on `mlx-audio`. Two interfaces
share the same model layer and configuration:

1. **HTTP API Server** — FastAPI endpoints consumed by web pages and HTTP clients.
2. **CLI** — Click-based terminal interface with speaker output, microphone input,
   file watching, and a dialogue mode.

Both are accessed through the unified `cai` command (`cai serve`, `cai speak`, etc.).

---

## File Structure

```
conversational_ai/
├── pyproject.toml              # Dependencies, project metadata
├── config.toml                 # Default configuration (deprecated — XDG used)
├── cli.py                      # Click entry point — unified `cai` command
├── main.py                     # FastAPI app factory + uvicorn (used by `cai serve`)
├── PRD.md                      # Product requirements document
├── install.sh                  # Installs to ~/.local/share, creates ~/.local/bin/cai
├── src/
│   ├── __init__.py
│   ├── config.py               # TOML loading + CLI override merging (Pydantic Settings)
│   ├── models.py               # ModelManager: loader + inference for TTS/STT
│   ├── audio.py                # WAV encoding, upload validation, temp files
│   ├── schemas.py              # Pydantic request/response models
│   ├── middleware.py            # X-Limit-* response headers
│   ├── logging_setup.py         # Log rotation + setup
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── tts.py              # POST /v1/tts
│   │   ├── stt.py              # POST /v1/stt
│   │   └── system.py           # GET /v1/health, GET /v1/models
│   └── cli/
│       ├── __init__.py         # Click group, shared startup (config + model loading)
│       ├── audio_io.py         # Speaker playback + mic recording primitives
│       ├── speak.py            # `cai speak` — text → TTS → speakers
│       ├── transcribe.py       # `cai transcribe` — mic → STT → stdout
│       ├── watch.py            # `cai watch` — file changes → TTS → speakers
│       ├── listen.py           # `cai listen` — mic → STT → append to file
│       └── dialogue.py         # `cai dialogue` — watch + listen simultaneously
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_audio.py
    ├── test_schemas.py
    ├── test_routes.py
    └── test_cli_audio_io.py    # Unit tests for CLI audio primitives
```

---

## Component Architecture

```mermaid
graph TB
    subgraph "Clients"
        Browser[Web Page<br/>localhost]
        Terminal[Terminal<br/>cai CLI]
    end

    subgraph "Entry Points"
        CLI_EP[cli.py<br/>Click group]
        SERVE[cai serve]
        SPEAK[cai speak]
        TRANSCRIBE[cai transcribe]
        WATCH[cai watch]
        LISTEN[cai listen]
        DIALOGUE[cai dialogue]
    end

    subgraph "FastAPI Server"
        direction TB
        CORS[CORS Middleware<br/>localhost only]

        subgraph "Routes"
            TTS_R[POST /v1/tts]
            STT_R[POST /v1/stt]
            SYS_R[GET /v1/health<br/>GET /v1/models]
        end

        Schemas[schemas.py<br/>Pydantic validation]
        Audio_Util[audio.py<br/>WAV conversion<br/>file validation]
    end

    subgraph "CLI Audio I/O"
        AudioIO[audio_io.py]
        Player[AudioPlayer<br/>streaming TTS playback]
        MicRec[MicRecorder<br/>VAD + recording]
        FileWatch[TextFileHandler<br/>mtime poller thread]
    end

    subgraph "Shared Layer"
        Config[config.py<br/>TOML + CLI merge]
        MM[ModelManager]
        TTS_M[TTS Model<br/>e.g. Kokoro]
        STT_M[STT Model<br/>e.g. Whisper]
    end

    subgraph "External"
        MLX[mlx-audio library]
        HF[HuggingFace Hub<br/>model download]
        SD[sounddevice<br/>PortAudio]
    end

    Browser -->|HTTP| CORS
    Terminal --> CLI_EP
    CLI_EP --> SERVE & SPEAK & TRANSCRIBE & WATCH & LISTEN & DIALOGUE
    SERVE --> CORS
    CORS --> TTS_R & STT_R & SYS_R
    TTS_R --> Schemas & Audio_Util & MM
    STT_R --> Schemas & Audio_Util & MM
    SPEAK & WATCH & DIALOGUE --> AudioIO
    TRANSCRIBE & LISTEN & DIALOGUE --> AudioIO
    AudioIO --> Player & MicRec
    WATCH & DIALOGUE --> FileWatch
    AudioIO --> MM
    MM --> TTS_M & STT_M
    TTS_M & STT_M --> MLX
    MLX --> HF
    Player & MicRec --> SD
    Config -->|startup| MM
```

---

## TTS Request Flow

```mermaid
sequenceDiagram
    participant B as Browser
    participant F as FastAPI /v1/tts
    participant S as schemas.py
    participant M as ModelManager
    participant A as audio.py
    participant MLX as mlx_audio TTS

    B->>F: POST /v1/tts {text, voice?, speed?, lang_code?}
    F->>S: Validate TTSRequest (text length check)
    alt text too long
        S-->>F: ValidationError
        F-->>B: 422 Unprocessable Entity
    end
    F->>F: asyncio.to_thread(...)
    F->>M: generate_tts(text, voice, speed, lang_code)
    M->>MLX: model.generate(text, voice, speed, lang_code)
    loop each chunk
        MLX-->>M: GenerationResult (mx.array, sample_rate)
    end
    M-->>F: collected results
    F->>A: tts_result_to_wav_bytes(results)
    A->>A: concatenate chunks, encode WAV
    A-->>F: wav_bytes
    F-->>B: 200 Response (audio/wav)
```

---

## STT Request Flow

```mermaid
sequenceDiagram
    participant B as Browser
    participant F as FastAPI /v1/stt
    participant A as audio.py
    participant M as ModelManager
    participant MLX as mlx_audio STT

    B->>F: POST /v1/stt (multipart: audio file)
    F->>A: validate_audio_upload(file, max_size)
    alt invalid file
        A-->>F: HTTPException 400/413
        F-->>B: Error response
    end
    A-->>F: raw bytes
    F->>A: save_temp_audio(bytes) -> temp path
    F->>F: asyncio.to_thread(...)
    F->>M: generate_stt(temp_path)
    M->>MLX: model.generate(temp_path)
    MLX-->>M: STTOutput (text, segments, language)
    M-->>F: STTOutput
    F->>F: cleanup temp file
    F-->>B: 200 {text, segments, language}
```

---

## Configuration

### config.toml

```toml
[server]
host = "127.0.0.1"
port = 8000

[tts]
model = "mlx-community/Kokoro-82M-bf16"
voice = "af_heart"
speed = 1.0
lang_code = "a"

[stt]
model = "mlx-community/whisper-large-v3-turbo-asr-fp16"

[limits]
max_text_length = 5000
max_audio_file_size = 26214400  # 25 MB
```

### CLI Overrides

CLI args map 1:1 and take precedence over the TOML file:

```
--config PATH           Path to TOML config file (default: ./config.toml)
--host HOST             Server bind address
--port PORT             Server port
--tts-model MODEL       TTS model name/path
--stt-model MODEL       STT model name/path
--voice VOICE           Default TTS voice
--speed SPEED           Default TTS speed
--lang-code CODE        Default TTS language code
--max-text-length N     Max input text characters
--max-audio-file-size N Max upload bytes
```

### Layering Order

1. Hardcoded defaults in Pydantic Settings model
2. TOML config file overrides defaults
3. CLI args override TOML values

---

## API Endpoints

| Method | Path          | Input                              | Output                                  |
|--------|---------------|------------------------------------|-----------------------------------------|
| POST   | `/v1/tts`     | JSON: `{text, voice?, speed?, lang_code?}` | `audio/wav` binary                |
| POST   | `/v1/stt`     | Multipart: audio file              | JSON: `{text, segments?, language?}`    |
| GET    | `/v1/health`  | None                               | JSON: `{status, tts_loaded, stt_loaded}`|
| GET    | `/v1/models`  | None                               | JSON: `{tts: {name, loaded}, stt: {name, loaded}}` |

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| `asyncio.to_thread()` for inference | mlx calls block; keeps event loop responsive |
| ModelManager on `app.state` | Testable, no import-time side effects |
| TOML config via `tomllib` | stdlib in 3.11+, zero extra deps |
| Temp files for STT input | mlx-audio STT API requires file paths |
| No streaming in v1 | Simpler; TTS chunks concatenated server-side |
| 3 pinned deps only | fastapi, uvicorn, python-multipart; mlx-audio editable brings the rest |
| Localhost-only CORS | Security: not a public service |

---

---

## CLI Architecture

### Click Command Hierarchy

```
cai (Click group)
├── serve         Start the HTTP API server
├── speak         Text → TTS → speakers
├── transcribe    Mic → STT → stdout
├── watch FILE    File changes → TTS → speakers
├── listen FILE   Mic → STT → append to file
└── dialogue      Watch + listen simultaneously
```

Global options (before subcommand): `--config`, `--tts-model`, `--stt-model`, `--voice`,
`--speed`, `--lang-code`, `--no-tts`, `--no-stt`.

### Streaming TTS Playback Flow

```mermaid
sequenceDiagram
    participant CMD as speak/watch/dialogue
    participant AIO as audio_io.py
    participant MM as ModelManager
    participant MLX as mlx_audio TTS
    participant AP as AudioPlayer
    participant SPK as Speakers

    CMD->>AIO: play_tts_streaming(text, voice, speed, lang_code)
    AIO->>MM: generate_tts_streaming(text, voice, speed, lang_code)
    loop each chunk
        MM->>MLX: model.generate() yields GenerationResult
        MLX-->>MM: GenerationResult (mx.array)
        MM-->>AIO: yield chunk
        AIO->>AP: queue_audio(chunk.audio)
        AP->>SPK: sounddevice OutputStream callback
    end
    AIO->>AP: stop() — wait for drain
```

### Microphone Recording Flow

```mermaid
sequenceDiagram
    participant CMD as transcribe/listen/dialogue
    participant MR as MicRecorder
    participant SD as sounddevice InputStream
    participant MIC as Microphone
    participant MM as ModelManager
    participant MLX as mlx_audio STT

    CMD->>MR: record()
    MR->>SD: start InputStream (16kHz mono)
    loop audio chunks
        MIC-->>SD: raw audio frames
        SD-->>MR: chunk callback
        MR->>MR: compute RMS energy
        alt speech detected + silence > 1.5s
            MR->>SD: stop InputStream
        end
    end
    MR->>MR: save to temp WAV
    MR-->>CMD: temp file path
    CMD->>MM: generate_stt(temp_path)
    MM->>MLX: model.generate(path)
    MLX-->>MM: STTOutput
    MM-->>CMD: text
    CMD->>CMD: cleanup temp file
```

### Dialogue Mode Threading

```mermaid
sequenceDiagram
    participant Main as Main Thread
    participant WT as Watcher Thread
    participant LT as Listener Thread
    participant Lock as Inference Lock
    participant MM as ModelManager

    Main->>Main: setup shutdown_event
    Main->>WT: start (mtime-poller thread)
    Main->>LT: start (mic loop)

    par Watcher
        WT->>WT: poll st_mtime (100ms)
        WT->>WT: read new bytes from offset
        WT->>Lock: acquire
        WT->>MM: generate_tts_streaming(text)
        MM-->>WT: audio chunks → speakers
        WT->>Lock: release
    and Listener
        LT->>LT: record utterance (VAD)
        LT->>Lock: acquire
        LT->>MM: generate_stt(temp_path)
        MM-->>LT: text
        LT->>Lock: release
        LT->>LT: append text to file
    end

    Main->>Main: Ctrl+C → set shutdown_event
    WT->>WT: stop poller thread
    LT->>LT: stop recording
```

### File Watcher Design

- Pure stdlib `TextFileHandler` worker thread — no `watchdog`, no FSEvents,
  no inotify. See P10 in `tasks/BUGS.md` for the rationale.
- Polls `path.stat().st_mtime` on a 100ms interval and tracks the byte offset
  of the last read. On each tick where `mtime` advanced:
  1. `seek` to last known offset, read to EOF.
  2. If file size < offset (truncation), reset offset to 0 and re-read.
  3. Feed new text to TTS playback.
- Worst-case detect-to-speak latency is ~100ms (one poll interval), vs. the
  ~0–50ms FSEvents latency plus the 300ms debounce the old design needed.

### Concurrency Model

Threading (not asyncio) throughout the CLI:
- `sounddevice` uses PortAudio callbacks (thread-based).
- The mtime-poller file watcher runs on its own worker thread.
- MLX inference is blocking CPU/GPU work.
- A shared `threading.Lock` serializes all inference calls (MLX is not thread-safe
  for concurrent operations).
- A shared `threading.Event` coordinates graceful shutdown across threads.

---

## Dependencies

```
fastapi==0.115.12
uvicorn==0.34.2
python-multipart==0.0.20
click==8.1.8
mlx-audio (editable, ../mlx-audio with [all] extras)
```

`sounddevice` and `soundfile` are transitive deps via `mlx-audio[all]`.
