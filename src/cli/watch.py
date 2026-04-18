"""watch subcommand: file changes → TTS → speakers."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

import click

from src.cli import CliContext
from src.cli.audio_io import AudioDeviceError, play_tts_streaming

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 0.3


class TextFileHandler:
    """Polls a single file for appended content and dispatches to a callback.

    A long-lived worker thread periodically stats the target file and calls
    `_read_new` whenever size or mtime changes. This watches only the target
    file — no parent-directory observation, no dependency on watchdog or
    platform-specific file-event APIs. The polling interval (`_POLL_INTERVAL`)
    doubles as a natural debounce: rapid successive writes that all land
    within one tick are coalesced into a single read.

    Call `stop()` to shut the worker down cleanly.
    """

    def __init__(self, path: Path, on_text: Callable[[str], None]) -> None:
        self._path = path.resolve()
        self._on_text = on_text
        try:
            st = self._path.stat()
            self._offset: int = st.st_size
            self._last_mtime: float = st.st_mtime
        except FileNotFoundError:
            self._offset = 0
            self._last_mtime = 0.0
        self._stop_event = threading.Event()
        self._worker = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"TextFileHandler-{self._path.name}",
        )
        self._worker.start()

    def stop(self) -> None:
        """Signal the worker to exit and wait for it briefly."""
        self._stop_event.set()
        self._worker.join(timeout=1)

    def _run(self) -> None:
        # `Event.wait(timeout)` returns True when set → loop exits on stop().
        while not self._stop_event.wait(timeout=_POLL_INTERVAL):
            try:
                st = self._path.stat()
            except FileNotFoundError:
                continue
            if st.st_mtime == self._last_mtime and st.st_size == self._offset:
                continue
            self._last_mtime = st.st_mtime
            try:
                self._read_new()
            except Exception:
                logger.exception("TextFileHandler read failed")

    def _read_new(self) -> None:
        try:
            file_size = self._path.stat().st_size
        except FileNotFoundError:
            return

        with self._path.open("rb") as f:
            if file_size < self._offset:
                # File was truncated — rewind and re-read from the start.
                logger.debug("File truncated; resetting offset to 0")
                self._offset = 0
            f.seek(self._offset)
            new_bytes = f.read()
            self._offset = f.tell()

        text = new_bytes.decode("utf-8", errors="replace").strip()
        if text:
            logger.debug("New text (%d chars): %.60s…", len(text), text)
            self._on_text(text)


@click.command()
@click.argument("file", type=click.Path())
@click.pass_obj
def watch(ctx_obj: CliContext, file: str) -> None:
    """Watch FILE for new content and speak it via TTS.

    Appending text to FILE while this command is running will speak the new
    content aloud. If FILE does not exist it will be created.
    """
    path = Path(file)
    path.touch(exist_ok=True)

    s = ctx_obj.settings.tts
    audio_error: threading.Event = threading.Event()

    def on_new_text(text: str) -> None:
        try:
            play_tts_streaming(ctx_obj.mm, text, s.voice, s.speed, s.lang_code)
        except AudioDeviceError as exc:
            click.echo(str(exc), err=True)
            audio_error.set()

    handler = TextFileHandler(path, on_new_text)
    click.echo(f"Watching {path} — press Ctrl+C to stop.", err=True)
    try:
        while not audio_error.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        handler.stop()
        if audio_error.is_set():
            raise click.ClickException("Audio output device error — see above.")
        click.echo("Stopped.", err=True)
