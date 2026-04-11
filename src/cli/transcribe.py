"""transcribe subcommand: mic → STT → stdout or file."""

from __future__ import annotations

import click

from src.cli import CliContext
from src.cli.audio_io import MicRecorder


@click.command()
@click.option(
    "-o",
    "--output",
    "output_file",
    type=click.Path(),
    help="Append transcribed text to file (default: print to stdout).",
)
@click.pass_obj
def transcribe(ctx_obj: CliContext, output_file: str | None) -> None:
    """Record from the microphone and transcribe speech to text via STT."""
    recorder = MicRecorder()
    path = recorder.record()
    try:
        result = ctx_obj.mm.generate_stt(path)
    finally:
        path.unlink(missing_ok=True)

    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(result.text + "\n")
    else:
        click.echo(result.text)
