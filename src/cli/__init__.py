"""CLI entry point: `cai` Click group with shared config and model loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from src.config import Settings, build_settings
from src.logging_setup import setup_logging
from src.models import ModelManager


@dataclass
class CliContext:
    """Shared state passed via Click's ctx.obj to every subcommand."""

    settings: Settings
    mm: ModelManager | None


# Subcommand → (needs_tts, needs_stt). `serve` loads models inside its FastAPI
# lifespan, so the group doesn't need to load anything for it. Unknown commands
# (e.g. `--help` with no subcommand) default to loading nothing.
MODEL_REQUIREMENTS: dict[str, tuple[bool, bool]] = {
    "speak": (True, False),
    "watch": (True, False),
    "transcribe": (False, True),
    "listen": (False, True),
    "dialogue": (True, True),
    "serve": (False, False),
}


def _build_overrides(
    tts_model: str | None,
    stt_model: str | None,
    voice: str | None,
    speed: float | None,
    lang_code: str | None,
    models_dir: str | None,
) -> dict[str, Any]:
    """Convert CLI option values to the nested dict expected by build_settings."""
    overrides: dict[str, Any] = {}

    def _set(section: str, key: str, value: Any) -> None:
        if value is not None:
            overrides.setdefault(section, {})[key] = value

    _set("tts", "model", tts_model)
    _set("tts", "voice", voice)
    _set("tts", "speed", speed)
    _set("tts", "lang_code", lang_code)
    _set("stt", "model", stt_model)
    _set("models", "models_dir", models_dir)
    return overrides


@click.group()
@click.option("--config", default=None, metavar="PATH", help="Path to TOML config file.")
@click.option("--tts-model", default=None, metavar="MODEL", help="TTS model name or path.")
@click.option("--stt-model", default=None, metavar="MODEL", help="STT model name or path.")
@click.option("--voice", default=None, metavar="VOICE", help="Default TTS voice.")
@click.option("--speed", default=None, type=float, metavar="SPEED", help="Default TTS speed (0.1–5.0).")
@click.option("--lang-code", default=None, metavar="CODE", help="Default TTS language code.")
@click.option("--models-dir", default=None, metavar="DIR", help="Local models directory (default: ~/.lmstudio/models).")
@click.option("--no-tts", is_flag=True, default=False, help="Skip loading the TTS model.")
@click.option("--no-stt", is_flag=True, default=False, help="Skip loading the STT model.")
@click.pass_context
def cli(
    ctx: click.Context,
    config: str | None,
    tts_model: str | None,
    stt_model: str | None,
    voice: str | None,
    speed: float | None,
    lang_code: str | None,
    models_dir: str | None,
    no_tts: bool,
    no_stt: bool,
) -> None:
    """Conversational AI — TTS/STT server and CLI."""
    ctx.ensure_object(dict)

    toml_path = Path(config) if config else None
    cli_overrides = _build_overrides(tts_model, stt_model, voice, speed, lang_code, models_dir)
    settings = build_settings(toml_path=toml_path, cli_overrides=cli_overrides)
    setup_logging(settings.log)

    resolved_models_dir = Path(settings.models.models_dir).expanduser()
    needs_tts, needs_stt = MODEL_REQUIREMENTS.get(ctx.invoked_subcommand or "", (False, False))
    load_tts = needs_tts and not no_tts
    load_stt = needs_stt and not no_stt

    mm: ModelManager | None = None
    if load_tts or load_stt:
        mm = ModelManager()
        if load_tts:
            mm.load_tts(settings.tts.model, models_dir=resolved_models_dir)
        if load_stt:
            mm.load_stt(settings.stt.model, models_dir=resolved_models_dir)

    ctx.obj = CliContext(settings=settings, mm=mm)
