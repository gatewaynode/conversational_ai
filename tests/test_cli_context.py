"""CliContext factory fields + CLI group callback model loading.

Covers the two seams in `src/cli/__init__.py`:

1. `recorder_factory` / `speaker_factory` fields on `CliContext` — the hooks
   subcommand tests override to avoid touching audio hardware. Pins the
   defaults so a refactor that accidentally breaks the wiring fails loudly
   rather than silently falling back to a different implementation.

2. `MODEL_REQUIREMENTS` + the group callback's lazy model loading — each
   subcommand loads only the models it actually needs, and `--no-tts` /
   `--no-stt` can suppress loading regardless of the requirement map.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

import cli as cli_entry
from src.cli import MODEL_REQUIREMENTS, CliContext
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


class TestLazyModelLoading:
    """Each subcommand loads only the models it actually needs."""

    @pytest.mark.parametrize(
        "subcommand,expected_tts,expected_stt",
        [
            ("speak", True, False),
            ("watch", True, False),
            ("transcribe", False, True),
            ("listen", False, True),
            ("dialogue", True, True),
            ("serve", False, False),
        ],
    )
    def test_only_required_models_loaded(
        self, subcommand: str, expected_tts: bool, expected_stt: bool
    ) -> None:
        assert MODEL_REQUIREMENTS[subcommand] == (expected_tts, expected_stt)

        runner = CliRunner()
        mm_instance = MagicMock()

        # `--help` on the subcommand fires the group callback (which loads
        # models) but exits before the subcommand body runs.
        with patch("src.cli.ModelManager", return_value=mm_instance):
            result = runner.invoke(cli_entry.cli, [subcommand, "--help"])

        assert result.exit_code == 0, result.output
        assert mm_instance.load_tts.called is expected_tts
        assert mm_instance.load_stt.called is expected_stt

    def test_no_tts_flag_overrides_requirement(self) -> None:
        runner = CliRunner()
        mm_instance = MagicMock()

        with patch("src.cli.ModelManager", return_value=mm_instance):
            result = runner.invoke(cli_entry.cli, ["--no-tts", "dialogue", "--help"])

        assert result.exit_code == 0, result.output
        assert not mm_instance.load_tts.called
        assert mm_instance.load_stt.called

    def test_no_stt_flag_overrides_requirement(self) -> None:
        runner = CliRunner()
        mm_instance = MagicMock()

        with patch("src.cli.ModelManager", return_value=mm_instance):
            result = runner.invoke(cli_entry.cli, ["--no-stt", "dialogue", "--help"])

        assert result.exit_code == 0, result.output
        assert mm_instance.load_tts.called
        assert not mm_instance.load_stt.called
