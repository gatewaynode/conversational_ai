"""dialogue subcommand: watch + listen simultaneously with shared inference lock."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

import click

from src.cli import CliContext
from src.cli.audio_io import AudioDeviceError, MicRecorder
from src.cli.watch import TextFileHandler

logger = logging.getLogger(__name__)

_RECORD_BACKOFF_START = 0.5
_RECORD_BACKOFF_MAX = 8.0
_RECORD_MAX_CONSECUTIVE_FAILURES = 10


def _make_speak_callback(
    ctx_obj: CliContext,
    lock: threading.Lock,
    shutdown: threading.Event,
    barge_event: threading.Event | None = None,
    tts_active: threading.Event | None = None,
) -> Callable[[str], None]:
    """Build the on_text callback passed to TextFileHandler.

    Serializes TTS inference on `lock` and re-checks `shutdown` after
    acquiring it, so a callback queued behind the listener drops cleanly
    on Ctrl+C instead of speaking post-shutdown.

    `barge_event` (barge_in mode) is forwarded to `play_tts_streaming` as
    `cancel=` so mid-sentence playback is flushed the moment the
    listener's VAD fires. `None` when barge-in is disabled.

    `tts_active` (half-duplex mode) is set for the duration of the TTS
    call so the listener loop can gate its `record()` on it. `None` when
    full-duplex is enabled.
    """
    s = ctx_obj.settings.tts

    def _speak(text: str) -> None:
        if shutdown.is_set():
            return
        click.echo(f"[speaking] {text[:80]}{'…' if len(text) > 80 else ''}", err=True)
        try:
            with lock:
                if shutdown.is_set():
                    return
                # The listener's mic is always open, so barge_event may be
                # stale from ambient noise or the just-transcribed utterance.
                # Clear it here so TTS can start; any *new* rising edge from
                # the next record() call will re-fire it for real barge-in.
                if barge_event is not None:
                    barge_event.clear()
                if tts_active is not None:
                    tts_active.set()
                try:
                    ctx_obj.speaker_factory(
                        ctx_obj.mm,
                        text,
                        s.voice,
                        s.speed,
                        s.lang_code,
                        cancel=barge_event,
                    )
                finally:
                    if tts_active is not None:
                        tts_active.clear()
        except AudioDeviceError:
            logger.exception("Audio output device error — shutting down")
            shutdown.set()
        except Exception:
            logger.exception("Error speaking new text")

    return _speak


def _listener_loop(
    listen_path: Path,
    ctx_obj: CliContext,
    lock: threading.Lock,
    shutdown: threading.Event,
    barge_event: threading.Event | None = None,
    tts_active: threading.Event | None = None,
    recorder: MicRecorder | None = None,
) -> None:
    """Record mic utterances, transcribe, and append to listen_path.

    `barge_event` (barge_in mode) is forwarded to
    `MicRecorder.record(on_speech_start=…)` so TTS currently playing on
    the speak side can abort the moment VAD detects the user's voice,
    not when the utterance completes. `None` when barge-in is disabled.

    `tts_active` (half-duplex mode) gates the mic: while set, the loop
    waits instead of recording. This prevents the speaker's own output
    from being re-transcribed on open-speaker setups. `None` when
    full-duplex is enabled.
    """
    if recorder is None:
        recorder = MicRecorder()
    click.echo("Listener ready — speak to transcribe.", err=True)

    consecutive_failures = 0
    backoff = _RECORD_BACKOFF_START

    while not shutdown.is_set():
        if tts_active is not None:
            while tts_active.is_set() and not shutdown.is_set():
                if shutdown.wait(timeout=0.05):
                    break
            if shutdown.is_set():
                break
        try:
            audio_path = recorder.record(on_speech_start=barge_event)
        except AudioDeviceError as exc:
            click.echo(str(exc), err=True)
            shutdown.set()
            break
        except Exception:
            consecutive_failures += 1
            logger.exception(
                "MicRecorder.record() failed (%d/%d)",
                consecutive_failures,
                _RECORD_MAX_CONSECUTIVE_FAILURES,
            )
            if consecutive_failures >= _RECORD_MAX_CONSECUTIVE_FAILURES:
                click.echo(
                    f"Listener giving up after {_RECORD_MAX_CONSECUTIVE_FAILURES} "
                    "consecutive MicRecorder failures — check audio device.",
                    err=True,
                )
                shutdown.set()
                break
            if shutdown.wait(timeout=backoff):
                break
            backoff = min(backoff * 2, _RECORD_BACKOFF_MAX)
            continue

        consecutive_failures = 0
        backoff = _RECORD_BACKOFF_START

        if shutdown.is_set():
            audio_path.unlink(missing_ok=True)
            break

        try:
            with lock:
                if shutdown.is_set():
                    break
                result = ctx_obj.mm.generate_stt(audio_path)
        except Exception:
            logger.exception("STT generation failed")
            continue
        finally:
            audio_path.unlink(missing_ok=True)

        line = result.text.strip()
        if line:
            with listen_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            click.echo(f"[heard] {line}", err=True)


@click.command()
@click.option(
    "--speak-file",
    default=None,
    type=click.Path(),
    help="Watch this file for new content to speak via TTS (overrides config).",
)
@click.option(
    "--listen-file",
    default=None,
    type=click.Path(),
    help="Append STT transcriptions to this file (overrides config).",
)
@click.option(
    "--mic-threshold",
    type=float,
    default=None,
    help="Override RMS threshold for speech detection.",
)
@click.option(
    "--mic-silence",
    type=float,
    default=None,
    help="Override trailing silence (seconds) that ends an utterance.",
)
@click.option(
    "--mic-min-speech",
    type=float,
    default=None,
    help="Override minimum sustained speech (seconds) required to latch.",
)
@click.option(
    "--calibrate-noise/--no-calibrate-noise",
    "calibrate_noise",
    default=None,
    help="Sample room tone at startup to set the effective threshold.",
)
@click.pass_obj
def dialogue(
    ctx_obj: CliContext,
    speak_file: str | None,
    listen_file: str | None,
    mic_threshold: float | None,
    mic_silence: float | None,
    mic_min_speech: float | None,
    calibrate_noise: bool | None,
) -> None:
    """Run TTS (file watcher) and STT (mic listener) simultaneously.

    New content appended to SPEAK_FILE is spoken aloud. Mic utterances are
    transcribed and appended to LISTEN_FILE. Press Ctrl+C to stop both.

    File paths default to the [dialogue] section in the config file.
    """
    d = ctx_obj.settings.dialogue
    speak_path = Path(speak_file or d.speak_file).expanduser()
    listen_path = Path(listen_file or d.listen_file).expanduser()
    speak_path.parent.mkdir(parents=True, exist_ok=True)
    listen_path.parent.mkdir(parents=True, exist_ok=True)
    speak_path.touch(exist_ok=True)
    listen_path.touch(exist_ok=True)

    inference_lock = threading.Lock()
    shutdown = threading.Event()
    # barge_in → VAD rising edge cancels in-flight TTS (set by MicRecorder,
    # consumed by play_tts_streaming). None disables barge-in entirely.
    barge_event: threading.Event | None = threading.Event() if d.barge_in else None
    # full_duplex=False → tts_active gates the listener so the mic is deaf
    # while TTS is playing. None means full-duplex (mic always hot).
    tts_active: threading.Event | None = None if d.full_duplex else threading.Event()

    mode = f"barge_in={d.barge_in} full_duplex={d.full_duplex}"

    # Build the mic recorder once so calibration amortizes across the session.
    mic = ctx_obj.settings.mic.model_copy(
        update={
            k: v
            for k, v in {
                "rms_threshold": mic_threshold,
                "silence_seconds": mic_silence,
                "min_speech_seconds": mic_min_speech,
            }.items()
            if v is not None
        }
    )
    recorder = ctx_obj.recorder_factory(mic, calibrate_override=calibrate_noise)
    try:
        if recorder.calibrate_noise:
            recorder.calibrate()
    except AudioDeviceError as exc:
        raise click.ClickException(str(exc)) from exc

    # --- Watcher (file → TTS) ---
    handler = TextFileHandler(
        speak_path,
        _make_speak_callback(ctx_obj, inference_lock, shutdown, barge_event, tts_active),
    )

    # --- Listener (mic → STT → file) ---
    listener_thread = threading.Thread(
        target=_listener_loop,
        args=(listen_path, ctx_obj, inference_lock, shutdown, barge_event, tts_active, recorder),
        daemon=True,
        name="dialogue-listener",
    )
    listener_thread.start()

    click.echo(
        f"Dialogue active [{mode}] — watching {speak_path}, "
        f"listening → {listen_path}. Ctrl+C to stop.",
        err=True,
    )

    try:
        while listener_thread.is_alive() and not shutdown.is_set():
            listener_thread.join(timeout=1)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown.set()
        handler.stop()
        listener_thread.join(timeout=5)
        click.echo("Stopped.", err=True)
