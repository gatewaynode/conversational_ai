"""transcribe subcommand: mic → STT → stdout or file."""

from __future__ import annotations

import click

from src.cli import CliContext
from src.cli.audio_io import AudioDeviceError, mic_recorder_from_settings


@click.command()
@click.option(
    "-o",
    "--output",
    "output_file",
    type=click.Path(),
    help="Append transcribed text to file (default: print to stdout).",
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
def transcribe(
    ctx_obj: CliContext,
    output_file: str | None,
    mic_threshold: float | None,
    mic_silence: float | None,
    mic_min_speech: float | None,
    calibrate_noise: bool | None,
) -> None:
    """Record from the microphone and transcribe speech to text via STT."""
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
    try:
        path = recorder.record()
    except AudioDeviceError as exc:
        raise click.ClickException(str(exc)) from exc
    try:
        result = ctx_obj.mm.generate_stt(path)
    finally:
        path.unlink(missing_ok=True)

    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(result.text + "\n")
    else:
        click.echo(result.text)
