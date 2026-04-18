"""listen subcommand: continuous mic → STT → append to file."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from src.cli import CliContext
from src.cli.audio_io import AudioDeviceError
from src.cli.wake_word import build_wake_gate

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
@click.option(
    "--wake-word",
    "wake_word",
    type=str,
    default=None,
    help="Enable wake-word gating with the given trigger (forces enabled=true).",
)
@click.option(
    "--no-wake-word",
    "no_wake_word",
    is_flag=True,
    default=False,
    help="Disable wake-word gating regardless of config.",
)
@click.option(
    "--wake-timeout",
    type=float,
    default=None,
    help="Override wake-word open-window timeout in seconds.",
)
@click.option(
    "--include-trigger/--strip-trigger",
    "include_trigger",
    default=None,
    help="Keep or strip the trigger word from the emitted line.",
)
@click.option(
    "--wake-alert/--no-wake-alert",
    "wake_alert",
    default=None,
    help="Play or suppress the activation chime (stderr echo always fires).",
)
@click.pass_obj
def listen(
    ctx_obj: CliContext,
    file: str,
    mic_threshold: float | None,
    mic_silence: float | None,
    mic_min_speech: float | None,
    calibrate_noise: bool | None,
    wake_word: str | None,
    no_wake_word: bool,
    wake_timeout: float | None,
    include_trigger: bool | None,
    wake_alert: bool | None,
) -> None:
    """Continuously record from the microphone and append transcriptions to FILE.

    Each detected utterance is transcribed and written as a new line in FILE.
    Press Ctrl+C to stop.
    """
    if wake_word is not None and no_wake_word:
        raise click.UsageError("--wake-word and --no-wake-word are mutually exclusive.")

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
    recorder = ctx_obj.recorder_factory(mic, calibrate_override=calibrate_noise)
    wake_gate = build_wake_gate(
        ctx_obj.settings.wake_word,
        word_override=wake_word,
        disable=no_wake_word,
        timeout_override=wake_timeout,
        include_trigger_override=include_trigger,
        alert_sound_override=wake_alert,
    )
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
            if line and wake_gate is not None:
                line = wake_gate.filter(line)
            if line:
                with path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
                click.echo(line, err=True)
    except KeyboardInterrupt:
        click.echo("Stopped.", err=True)
