"""Tests for `cai speak` — TTS playback via the speaker factory seam."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from click.testing import CliRunner

from src.cli.speak import speak
from tests._cli_fakes import make_ctx


class TestSpeak:
    def test_speak_positional_arg(self) -> None:
        ctx = make_ctx()
        mock_play = MagicMock()
        ctx.speaker_factory = mock_play
        runner = CliRunner()

        result = runner.invoke(speak, ["hello world"], obj=ctx)

        assert result.exit_code == 0, result.output
        mock_play.assert_called_once()
        args = mock_play.call_args
        assert args[0][1] == "hello world"

    def test_speak_strips_whitespace(self) -> None:
        ctx = make_ctx()
        mock_play = MagicMock()
        ctx.speaker_factory = mock_play
        runner = CliRunner()

        result = runner.invoke(speak, ["  trimmed  "], obj=ctx)

        assert result.exit_code == 0
        assert mock_play.call_args[0][1] == "trimmed"

    def test_speak_from_file(self, tmp_path: Path) -> None:
        f = tmp_path / "input.txt"
        f.write_text("text from file\n")
        ctx = make_ctx()
        mock_play = MagicMock()
        ctx.speaker_factory = mock_play
        runner = CliRunner()

        result = runner.invoke(speak, ["--file", str(f)], obj=ctx)

        assert result.exit_code == 0, result.output
        assert mock_play.call_args[0][1] == "text from file"

    def test_speak_from_stdin(self) -> None:
        ctx = make_ctx()
        mock_play = MagicMock()
        ctx.speaker_factory = mock_play
        runner = CliRunner()

        result = runner.invoke(speak, [], input="piped text\n", obj=ctx)

        assert result.exit_code == 0, result.output
        assert mock_play.call_args[0][1] == "piped text"

    def test_speak_empty_input_raises_usage_error(self) -> None:
        ctx = make_ctx()
        ctx.speaker_factory = MagicMock()
        runner = CliRunner()

        result = runner.invoke(speak, [], input="   \n", obj=ctx)

        assert result.exit_code != 0

    def test_speak_uses_settings_voice_and_speed(self) -> None:
        ctx = make_ctx()
        ctx.settings.tts.voice = "af_sky"
        ctx.settings.tts.speed = 1.5
        ctx.settings.tts.lang_code = "b"
        mock_play = MagicMock()
        ctx.speaker_factory = mock_play
        runner = CliRunner()

        runner.invoke(speak, ["hi"], obj=ctx)

        _, text, voice, speed, lang_code = mock_play.call_args[0]
        assert voice == "af_sky"
        assert speed == 1.5
        assert lang_code == "b"

    def test_speak_missing_file_exits_nonzero(self) -> None:
        ctx = make_ctx()
        runner = CliRunner()

        result = runner.invoke(speak, ["--file", "/no/such/file.txt"], obj=ctx)
        assert result.exit_code != 0
