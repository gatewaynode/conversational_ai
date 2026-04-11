# Dialogue Mode — Design Notes

`cai dialogue` runs TTS (file watcher) and STT (mic listener) simultaneously
in one process, serializing GPU inference through a shared lock so the two
halves never fight for the model. This doc reconstructs the threading model,
lock/shutdown semantics, and file contracts that live in
`src/cli/dialogue.py`, and flags a few rough edges worth revisiting.

---

## Purpose

A single command that closes the loop between a text editor and a human
voice:

- **Speak side** — watch a text file; when new bytes are appended, read them
  aloud through the default audio device.
- **Listen side** — continuously record mic utterances (RMS VAD), transcribe
  each one with Whisper, and append the text to a second file.

Both sides share one `ModelManager` (TTS + STT loaded eagerly by the CLI
group) and one `threading.Lock` so the GPU is only running one model at a
time.

## File contracts

Two user-facing files, both defaulting to the `[dialogue]` section of the
TOML config, overridable with `--speak-file` / `--listen-file`:

| Role         | Direction              | Behavior                              |
|--------------|------------------------|---------------------------------------|
| `speak-file` | external writer → TTS  | New appended bytes are spoken aloud.  |
| `listen-file`| STT → external reader  | Each utterance is appended as a line. |

Both files are created (`touch`) and their parent directories `mkdir -p`'d
before threads start, so downstream code can assume they exist.

## Threading model

Three threads, one process:

1. **Main thread** — owns the `Observer`, blocks in a 1-second `observer.join`
   poll loop, and handles `KeyboardInterrupt`.
2. **Watchdog observer thread** — spawned by `Observer.start()`. On every
   `on_modified` event that matches the speak-file path, it (re)arms a
   `threading.Timer` for `_DEBOUNCE_SECONDS` (0.3 s). When the timer fires,
   `_read_and_speak` runs on the timer thread.
3. **Listener thread** — `daemon=True`, runs `_listener_loop`: record → lock
   → STT → append → repeat. Daemon so a hung join cannot block process exit.

### Why debounce

Editors and shells often write a file in multiple small writes (`open`,
`write`, `write`, `close`). Without debounce, each `on_modified` would fire a
separate TTS call mid-sentence. 0.3 s is long enough to coalesce a single
editor save, short enough that it doesn't feel laggy in interactive use.

## The inference lock

A single `threading.Lock` (`inference_lock`) is shared between
`_SpeakFileHandler._read_and_speak` and `_listener_loop`. Both sides acquire
it **only around the actual model call**:

```python
with self._lock:
    if not self._shutdown.is_set():
        play_tts_streaming(...)
```

```python
with lock:
    if shutdown.is_set():
        break
    result = ctx_obj.mm.generate_stt(audio_path)
```

Holding the lock strictly around inference (not around recording or file
I/O) keeps both halves responsive: the listener can be recording a new
utterance while the watcher is speaking the previous one, but the two models
never run simultaneously.

### Offset tracking on the speak side

`_SpeakFileHandler` remembers the speak-file's byte offset across events
(initialized to the file's size at startup, so pre-existing content is not
re-spoken). On each debounced read it:

1. Stats the file. If it vanished, return.
2. If `file_size < offset`, treat it as a truncation and reset `offset = 0`.
3. Seek to `offset`, read to EOF, update offset to `f.tell()`.
4. Strip whitespace; if empty, return.
5. Acquire the inference lock, re-check shutdown, then call TTS.

Truncation reset is important: `echo > speak.txt` should not permanently
desync the handler.

## Shutdown sequence

`shutdown` is a `threading.Event`. On `KeyboardInterrupt` (or either worker
dying), the main thread runs its `finally` block:

```
shutdown.set()
observer.stop()
observer.join()
listener_thread.join(timeout=5)
```

Every long-running step on the worker side checks `shutdown.is_set()`:

- `_read_and_speak`: top of function, after reading bytes, and *again* after
  acquiring the lock — so a TTS call queued behind the listener will drop
  cleanly instead of speaking post-Ctrl+C.
- `_listener_loop`: after every `recorder.record()`, and after acquiring the
  lock. The recorder returns on trailing silence, so we never have to
  interrupt it mid-capture — we just let it finish the current utterance and
  then exit.

The 5-second listener join timeout is a safety valve: because the listener
is `daemon=True`, a wedged STT call cannot keep the process alive past
interpreter shutdown. The timeout buys time for a clean exit in the common
case without hanging the terminal in the pathological one.

## Duplex modes (P13)

Two orthogonal config flags on `[dialogue]` cover the headphones /
open-speaker / loopback / walkie-talkie matrix without a mode enum:

| `barge_in` | `full_duplex` | Behavior                                                                                   |
|------------|---------------|--------------------------------------------------------------------------------------------|
| `true`     | `true`        | **Default.** Full-duplex with interrupt. Listener's VAD rising edge flushes in-flight TTS. Good on headphones. |
| `true`     | `false`       | **Speaker-safe half-duplex.** Mic is gated while TTS plays (no echo feedback); interrupt applies to the *next* utterance. |
| `false`    | `true`        | **Loopback / self-dialogue.** Mic always hot, TTS always runs to completion — the feedback loop is the intended path. |
| `false`    | `false`       | **Walkie-talkie.** Strict half-duplex, no interrupt. Simplest and most predictable.        |

Implementation hooks both through `_make_speak_callback` and
`_listener_loop`:

- `barge_in=False` → the shared `barge_event` is not constructed;
  `play_tts_streaming` receives `cancel=None` and `recorder.record()`
  receives `on_speech_start=None`.
- `full_duplex=False` → a `tts_active: threading.Event` is constructed;
  the speak callback sets it around `play_tts_streaming` (cleared in a
  `finally:` so exceptions still release the gate), and the listener
  loop polls `tts_active.is_set()` before each `record()` call,
  sleeping via `shutdown.wait(0.05)` until the gate opens or shutdown
  fires.

## Error handling

Both workers catch broad exceptions and log via `logger.exception(...)`
rather than crashing the thread. That is deliberate: a single bad transcode
or unreadable file should not take down the dialogue session. The user still
sees the traceback via logging, and the loop picks up on the next event /
utterance.

---

## Known rough edges / future improvements

These are not bugs that need fixing today, but they are the places I'd push
back on in a staff-engineer review:

1. **Debounce timers leak on rapid rewrites.** Each `on_modified` cancels
   the previous timer and starts a new one. Under a pathological writer
   (hundreds of modifies/sec) we churn `Timer` threads. Cheap, but not free.
   A single long-lived worker thread fed by a `queue.Queue` would be
   cleaner and is how `watch.py` should probably also work.

2. **No barge-in.** If the user starts talking while TTS is mid-sentence,
   the listener blocks on the inference lock until TTS finishes, *then*
   records. For true conversational feel we'd want to either (a) interrupt
   TTS playback when the VAD detects speech, or (b) duck TTS volume while
   recording. Both require plumbing through `AudioPlayer` that doesn't
   exist yet.

3. **`_SpeakFileHandler` duplicates `_TextFileHandler` from `watch.py`.**
   The offset / truncation / debounce logic is copy-pasted with only the
   lock + shutdown additions. Extracting a base class (or a plain
   `read_new_bytes(path, offset)` helper) would kill the drift risk.

4. **Listener's `continue` on record failure is a tight loop.** If
   `MicRecorder.record()` raises synchronously and immediately (e.g. no
   audio device), `_listener_loop` will spin at full CPU logging
   exceptions until Ctrl+C. A small backoff (`time.sleep(0.5)` after an
   exception) would make this safe.

5. **Observer watches the whole parent directory.** `observer.schedule(...,
   str(speak_path.parent.resolve()), recursive=False)` fires on *any* file
   event in that directory; we filter by path inside `on_modified`. That's
   fine for `~/dialogue/speak.txt` but noisy if someone points `--speak-file`
   at `/tmp` or their home directory. Watching a single file (or a dedicated
   subdirectory) would be tidier.

6. **`CliContext.mm` is shared mutable state across threads.** Today
   `ModelManager.generate_tts_streaming` and `generate_stt` are effectively
   single-threaded because of `inference_lock`, but nothing in the type
   system enforces that. A comment on `ModelManager` noting "external
   serialization required" would document the invariant.

7. **No integration test on real audio hardware.** `tasks/TODO.md:135` still
   has the E2E checkbox open. The mocked CliRunner tests prove the wiring;
   they cannot prove that a real mic + a real speaker + a real inference
   lock actually hand off cleanly under load.
