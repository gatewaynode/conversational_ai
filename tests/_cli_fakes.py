"""Shared test doubles for CLI subcommand tests.

Plain module (not `conftest.py`) to avoid pytest's double-import trap — see
`tests/_audio_fakes.py` for the same pattern applied in Task 5.1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from src.cli import CliContext
from src.config import Settings


@dataclass
class FakeSTTOutput:
    text: str
    segments: list[dict] | None = None
    language: str | None = None


def make_ctx(
    tts_side_effect: Any = None,
    stt_text: str = "hello from stt",
) -> CliContext:
    """Return a CliContext wrapping a fake ModelManager."""
    mm = MagicMock()
    mm.generate_stt.return_value = FakeSTTOutput(text=stt_text)
    if tts_side_effect is not None:
        mm.generate_tts_streaming.side_effect = tts_side_effect
    else:
        mm.generate_tts_streaming.return_value = iter([])
    return CliContext(settings=Settings(), mm=mm)
