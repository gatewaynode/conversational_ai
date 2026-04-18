"""speak subcommand: text → TTS → speakers."""

from __future__ import annotations

import sys

import click

from src.cli import CliContext
from src.cli.audio_io import AudioDeviceError


@click.command()
@click.argument("text", required=False)
@click.option(
    "-f",
    "--file",
    "text_file",
    type=click.Path(exists=True),
    help="Read text from file instead of argument or stdin.",
)
@click.pass_obj
def speak(ctx_obj: CliContext, text: str | None, text_file: str | None) -> None:
    """Speak TEXT aloud via TTS.

    TEXT may be passed as a positional argument, read from a file with --file,
    or piped / typed on stdin when neither is given.
    """
    if text_file is not None:
        content = click.open_file(text_file).read()
    elif text is not None:
        content = text
    else:
        if sys.stdin.isatty():
            click.echo("Reading from stdin — type text then press Ctrl+D.", err=True)
        content = click.get_text_stream("stdin").read()

    content = content.strip()
    if not content:
        raise click.UsageError("No text to speak.")

    s = ctx_obj.settings.tts
    try:
        ctx_obj.speaker_factory(ctx_obj.mm, content, s.voice, s.speed, s.lang_code)
    except AudioDeviceError as exc:
        raise click.ClickException(str(exc)) from exc
