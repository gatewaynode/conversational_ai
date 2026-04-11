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

_DEFAULT_MODELS_DIR = Path.home() / ".lmstudio" / "models"


def _resolve_from_hf_cache(model_name: str) -> str | None:
    """Return the local snapshot path if *model_name* is already in the HF hub cache.

    Uses ``snapshot_download(..., local_files_only=True)`` which returns the
    cached snapshot path without any network call, or raises
    ``LocalEntryNotFoundError`` if the model isn't cached.
    """
    try:
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError
    except ImportError:
        return None

    try:
        path = snapshot_download(model_name, local_files_only=True)
        return str(Path(path).resolve())
    except LocalEntryNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001 — any other failure → fall through
        logger.debug("HF cache lookup failed for %s: %s", model_name, exc)
        return None


def _resolve_model_path(model_name: str, models_dir: Path) -> str:
    """Return a local path when the model exists anywhere on disk, else *model_name*.

    Resolution order:

    1. Absolute path → returned unchanged.
    2. ``models_dir / org / name`` (LM Studio / custom layout) → absolute path.
    3. HuggingFace hub cache (``~/.cache/huggingface/hub/models--org--name``)
       via ``snapshot_download(local_files_only=True)`` → absolute snapshot path.
    4. Not found → return the HF repo ID so mlx-audio will download it.

    Returning an absolute path in cases 2 and 3 short-circuits mlx-audio's
    ``get_model_path`` at its ``model_path.exists()`` check, skipping the
    network metadata request ``snapshot_download`` would otherwise make.
    """
    p = Path(model_name)
    if p.is_absolute():
        return model_name

    local = (models_dir / model_name).expanduser().resolve()
    if local.is_dir():
        logger.info("Using local model at %s", local)
        return str(local)

    cached = _resolve_from_hf_cache(model_name)
    if cached is not None:
        logger.info("Using HF-cached model at %s", cached)
        return cached

    logger.info("Model not found locally; will download: %s", model_name)
    return model_name


class ModelManager:
    """Holds loaded TTS and STT model instances.

    Intended to be stored on ``app.state`` and loaded during the FastAPI
    lifespan startup event — not imported as a global singleton.

    **Threading invariant — NOT thread-safe.** The inference methods
    (``generate_tts``, ``generate_tts_streaming``, ``generate_stt``) wrap
    mlx-audio models whose internal state is not safe for concurrent
    calls. Callers that drive a single ``ModelManager`` from more than one
    thread **must** serialize access externally with a shared lock. The
    ``cai dialogue`` subcommand does this via ``inference_lock`` in
    ``src/cli/dialogue.py``; the FastAPI routes avoid the issue by giving
    TTS and STT their own manager instances via app lifespan. Adding a
    new concurrent caller without external serialization will race.
    """

    def __init__(self) -> None:
        self._tts_model: nn.Module | None = None
        self._tts_model_name: str | None = None
        self._stt_model: nn.Module | None = None
        self._stt_model_name: str | None = None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_tts(self, model_name: str, models_dir: Path | None = None) -> None:
        """Load (or reload) the TTS model by name/path.

        If *models_dir* is given (defaults to ``~/.lmstudio/models``), checks
        for a local copy before falling back to a HuggingFace Hub download.
        """
        from mlx_audio.tts import load

        resolved = _resolve_model_path(model_name, models_dir or _DEFAULT_MODELS_DIR)
        logger.info("Loading TTS model: %s", resolved)
        self._tts_model = load(resolved)
        self._tts_model_name = model_name
        logger.info("TTS model loaded: %s", resolved)

    def load_stt(self, model_name: str, models_dir: Path | None = None) -> None:
        """Load (or reload) the STT model by name/path.

        If *models_dir* is given (defaults to ``~/.lmstudio/models``), checks
        for a local copy before falling back to a HuggingFace Hub download.
        """
        from mlx_audio.stt import load

        resolved = _resolve_model_path(model_name, models_dir or _DEFAULT_MODELS_DIR)
        logger.info("Loading STT model: %s", resolved)
        self._stt_model = load(resolved)
        self._stt_model_name = model_name
        logger.info("STT model loaded: %s", resolved)

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
