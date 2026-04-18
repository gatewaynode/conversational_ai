"""listen subcommand: continuous mic → STT → append to file."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from src.cli import CliContext
from src.cli.audio_io import AudioDeviceError, mic_recorder_from_settings

logger = logging.getLogger(__name__)


@click.command()
@click.argument("file", type=click.Path())
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
def listen(
    ctx_obj: CliContext,
    file: str,
    mic_threshold: float | None,
    mic_silence: float | None,
    mic_min_speech: float | None,
    calibrate_noise: bool | None,
) -> None:
    """Continuously record from the microphone and append transcriptions to FILE.

    Each detected utterance is transcribed and written as a new line in FILE.
    Press Ctrl+C to stop.
    """
    path = Path(file)
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
    recorder = mic_recorder_from_settings(mic, calibrate_override=calibrate_noise)
    # Long-running mode: calibrate once up front, not per-utterance.
    try:
        if recorder.calibrate_noise:
            recorder.calibrate()
    except AudioDeviceError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Listening — transcriptions will be appended to {path}. Ctrl+C to stop.", err=True)
    try:
        while True:
            try:
                audio_path = recorder.record()
            except AudioDeviceError as exc:
                raise click.ClickException(str(exc)) from exc
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
