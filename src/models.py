"""Model manager: singleton loader and inference wrappers for TTS and STT."""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import mlx.nn as nn
    from mlx_audio.stt.models.base import STTOutput
    from mlx_audio.tts.models.base import GenerationResult

logger = logging.getLogger(__name__)


class ModelManager:
    """Holds loaded TTS and STT model instances.

    Intended to be stored on ``app.state`` and loaded during the FastAPI
    lifespan startup event — not imported as a global singleton.
    """

    def __init__(self) -> None:
        self._tts_model: nn.Module | None = None
        self._tts_model_name: str | None = None
        self._stt_model: nn.Module | None = None
        self._stt_model_name: str | None = None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_tts(self, model_name: str) -> None:
        """Load (or reload) the TTS model by name/path."""
        from mlx_audio.tts import load

        logger.info("Loading TTS model: %s", model_name)
        self._tts_model = load(model_name)
        self._tts_model_name = model_name
        logger.info("TTS model loaded: %s", model_name)

    def load_stt(self, model_name: str) -> None:
        """Load (or reload) the STT model by name/path."""
        from mlx_audio.stt import load

        logger.info("Loading STT model: %s", model_name)
        self._stt_model = load(model_name)
        self._stt_model_name = model_name
        logger.info("STT model loaded: %s", model_name)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def tts_loaded(self) -> bool:
        return self._tts_model is not None

    @property
    def stt_loaded(self) -> bool:
        return self._stt_model is not None

    @property
    def tts_model_name(self) -> str | None:
        return self._tts_model_name

    @property
    def stt_model_name(self) -> str | None:
        return self._stt_model_name

    # ------------------------------------------------------------------
    # Inference wrappers (blocking — call via asyncio.to_thread)
    # ------------------------------------------------------------------

    def generate_tts(
        self,
        text: str,
        voice: str,
        speed: float,
        lang_code: str,
    ) -> list[GenerationResult]:
        """Run TTS inference and return all GenerationResult chunks.

        This is a blocking call; use ``asyncio.to_thread`` from async
        route handlers.
        """
        if self._tts_model is None:
            raise RuntimeError("TTS model is not loaded")

        results: list[GenerationResult] = []
        for result in self._tts_model.generate(
            text=text,
            voice=voice,
            speed=speed,
            lang_code=lang_code,
        ):
            results.append(result)

        return results

    def generate_tts_streaming(
        self,
        text: str,
        voice: str,
        speed: float,
        lang_code: str,
    ) -> Generator[GenerationResult, None, None]:
        """Yield TTS GenerationResult chunks as they arrive (streaming).

        This is a blocking generator; consume it from a thread, not the
        async event loop.
        """
        if self._tts_model is None:
            raise RuntimeError("TTS model is not loaded")

        yield from self._tts_model.generate(
            text=text,
            voice=voice,
            speed=speed,
            lang_code=lang_code,
        )

    def generate_stt(self, audio_path: Path | str) -> STTOutput:
        """Run STT inference on a file path and return STTOutput.

        This is a blocking call; use ``asyncio.to_thread`` from async
        route handlers.
        """
        if self._stt_model is None:
            raise RuntimeError("STT model is not loaded")

        return self._stt_model.generate(str(audio_path))
