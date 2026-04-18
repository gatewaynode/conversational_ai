"""Tests for `cai transcribe` — one-shot mic capture + STT via factory seam."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from click.testing import CliRunner

from src.cli.transcribe import transcribe
from tests._cli_fakes import make_ctx


class TestTranscribe:
    def _fake_record(self) -> Path:
        """Return a real temp WAV path (content irrelevant — STT is mocked)."""
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        return Path(tmp.name)

    def test_transcribe_prints_to_stdout(self) -> None:
        ctx = make_ctx(stt_text="transcribed text")
        MockFactory = MagicMock()
        MockFactory.return_value.record.return_value = self._fake_record()
        ctx.recorder_factory = MockFactory
        runner = CliRunner()

        result = runner.invoke(transcribe, [], obj=ctx)

        assert result.exit_code == 0, result.output
        assert "transcribed text" in result.output

    def test_transcribe_to_file(self, tmp_path: Path) -> None:
        out = tmp_path / "out.txt"
        ctx = make_ctx(stt_text="saved to file")
        MockFactory = MagicMock()
        MockFactory.return_value.record.return_value = self._fake_record()
        ctx.recorder_factory = MockFactory
        runner = CliRunner()

        result = runner.invoke(transcribe, ["-o", str(out)], obj=ctx)

        assert result.exit_code == 0, result.output
        assert out.read_text() == "saved to file\n"
        assert result.output.strip() == ""

    def test_transcribe_appends_to_existing_file(self, tmp_path: Path) -> None:
        out = tmp_path / "out.txt"
        out.write_text("existing\n")
        ctx = make_ctx(stt_text="appended")
        MockFactory = MagicMock()
        MockFactory.return_value.record.return_value = self._fake_record()
        ctx.recorder_factory = MockFactory
        runner = CliRunner()

        runner.invoke(transcribe, ["-o", str(out)], obj=ctx)

        assert out.read_text() == "existing\nappended\n"

    def test_transcribe_cleans_up_temp_file(self) -> None:
        """Temp audio file must be deleted even if STT raises."""
        tmp_path_holder: list[Path] = []

        def fake_record() -> Path:
            p = self._fake_record()
            tmp_path_holder.append(p)
            return p

        ctx = make_ctx()
        ctx.mm.generate_stt.side_effect = RuntimeError("STT failed")
        MockFactory = MagicMock()
        MockFactory.return_value.record.side_effect = fake_record
        ctx.recorder_factory = MockFactory
        runner = CliRunner()

        runner.invoke(transcribe, [], obj=ctx)

        if tmp_path_holder:
            assert not tmp_path_holder[0].exists(), "Temp file was not cleaned up"
