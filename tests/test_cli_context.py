"""CliContext factory field wiring.

The `recorder_factory` and `speaker_factory` fields on `CliContext` are the
seams subcommand tests hook in Task 5.3. This file pins the defaults so a
refactor that accidentally breaks the wiring fails loudly rather than
silently falling back to a different implementation.
"""

from __future__ import annotations

from src.cli import CliContext
from src.cli.audio_io import mic_recorder_from_settings, play_tts_streaming
from src.config import Settings


class TestCliContextFactoryDefaults:
    """Defaults match the real audio_io helpers."""

    def test_recorder_factory_defaults_to_mic_recorder_from_settings(self) -> None:
        ctx = CliContext(settings=Settings(), mm=None)
        assert ctx.recorder_factory is mic_recorder_from_settings

    def test_speaker_factory_defaults_to_play_tts_streaming(self) -> None:
        ctx = CliContext(settings=Settings(), mm=None)
        assert ctx.speaker_factory is play_tts_streaming

    def test_recorder_factory_is_overridable(self) -> None:
        """Tests override the factory per-invocation — this is the seam."""
        ctx = CliContext(settings=Settings(), mm=None)

        sentinel = object()
        ctx.recorder_factory = lambda *a, **kw: sentinel  # type: ignore[assignment]

        assert ctx.recorder_factory() is sentinel

    def test_speaker_factory_is_overridable(self) -> None:
        ctx = CliContext(settings=Settings(), mm=None)

        calls: list[tuple] = []
        ctx.speaker_factory = lambda *a, **kw: calls.append((a, kw))  # type: ignore[assignment,return-value]

        ctx.speaker_factory("mm", "hello", "af_heart", 1.0, "a")
        assert calls == [(("mm", "hello", "af_heart", 1.0, "a"), {})]
