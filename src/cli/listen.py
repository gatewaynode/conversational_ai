"""listen subcommand: continuous mic → STT → append to file."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from src.cli import CliContext
from src.cli.audio_io import MicRecorder

logger = logging.getLogger(__name__)


@click.command()
@click.argument("file", type=click.Path())
@click.pass_obj
def listen(ctx_obj: CliContext, file: str) -> None:
    """Continuously record from the microphone and append transcriptions to FILE.

    Each detected utterance is transcribed and written as a new line in FILE.
    Press Ctrl+C to stop.
    """
    path = Path(file)
    recorder = MicRecorder()

    click.echo(f"Listening — transcriptions will be appended to {path}. Ctrl+C to stop.", err=True)
    try:
        while True:
            audio_path = recorder.record()
            try:
                result = ctx_obj.mm.generate_stt(audio_path)
            finally:
                audio_path.unlink(missing_ok=True)

            line = result.text.strip()
            if line:
                with path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
                click.echo(line, err=True)
    except KeyboardInterrupt:
        click.echo("Stopped.", err=True)
