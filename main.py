"""Entry point: parse CLI args, load config, assemble app, run server."""

from __future__ import annotations

import argparse
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import Settings, build_settings
from src.logging_setup import setup_logging
from src.middleware import LimitsHeaderMiddleware
from src.models import ModelManager
from src.routes.stt import router as stt_router
from src.routes.system import router as system_router
from src.routes.tts import router as tts_router

# Minimal bootstrap so import-time errors are visible before settings load.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(settings: Settings) -> FastAPI:
    """Build and return the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from pathlib import Path as _Path
        models_dir = _Path(settings.models.models_dir).expanduser()
        mm = ModelManager()
        logger.info("Loading models…")
        mm.load_tts(settings.tts.model, models_dir=models_dir)
        mm.load_stt(settings.stt.model, models_dir=models_dir)
        app.state.model_manager = mm
        app.state.settings = settings
        logger.info("Models ready. Server accepting requests.")
        yield
        logger.info("Shutting down.")

    app = FastAPI(
        title="Conversational AI — TTS/STT API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — localhost origins only (all ports, http and https)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    app.add_middleware(LimitsHeaderMiddleware)

    app.include_router(tts_router, prefix="/v1")
    app.include_router(stt_router, prefix="/v1")
    app.include_router(system_router, prefix="/v1")

    return app


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Conversational AI TTS/STT API server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to TOML config file (default: ~/.config/conversational_ai/config.toml).",
    )
    p.add_argument("--host", default=None, help="Bind address.")
    p.add_argument("--port", type=int, default=None, help="Port number.")
    p.add_argument("--tts-model", dest="tts_model", default=None, help="TTS model name/path.")
    p.add_argument("--stt-model", dest="stt_model", default=None, help="STT model name/path.")
    p.add_argument("--voice", default=None, help="Default TTS voice.")
    p.add_argument("--speed", type=float, default=None, help="Default TTS speed.")
    p.add_argument("--lang-code", dest="lang_code", default=None, help="Default TTS language code.")
    p.add_argument(
        "--max-text-length",
        dest="max_text_length",
        type=int,
        default=None,
        help="Max input text characters.",
    )
    p.add_argument(
        "--max-audio-file-size",
        dest="max_audio_file_size",
        type=int,
        default=None,
        help="Max audio upload size in bytes.",
    )
    return p


def _cli_overrides(args: argparse.Namespace) -> dict:
    """Convert parsed CLI args to the nested dict expected by build_settings."""
    overrides: dict = {}

    def _set(section: str, key: str, value) -> None:
        if value is not None:
            overrides.setdefault(section, {})[key] = value

    _set("server", "host", args.host)
    _set("server", "port", args.port)
    _set("tts", "model", args.tts_model)
    _set("tts", "voice", args.voice)
    _set("tts", "speed", args.speed)
    _set("tts", "lang_code", args.lang_code)
    _set("stt", "model", args.stt_model)
    _set("limits", "max_text_length", args.max_text_length)
    _set("limits", "max_audio_file_size", args.max_audio_file_size)
    return overrides


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    settings = build_settings(
        toml_path=args.config,
        cli_overrides=_cli_overrides(args),
    )

    setup_logging(settings.log)

    _LOOPBACK = {"127.0.0.1", "::1", "localhost"}
    if settings.server.host not in _LOOPBACK:
        logger.warning(
            "Server is bound to %s — the API is network-accessible with NO authentication. "
            "Ensure this is intentional.",
            settings.server.host,
        )

    logger.info(
        "Starting server on %s:%d | TTS: %s | STT: %s",
        settings.server.host,
        settings.server.port,
        settings.tts.model,
        settings.stt.model,
    )

    app = create_app(settings)
    uvicorn.run(app, host=settings.server.host, port=settings.server.port)


if __name__ == "__main__":
    main()
