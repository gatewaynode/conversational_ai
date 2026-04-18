"""Tests for `cai listen` — continuous mic + STT via factory seam."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from click.testing import CliRunner

from src.cli.listen import listen
from tests._cli_fakes import make_ctx


class TestListenCommand:
    def _fake_wav(self) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        return Path(tmp.name)

    def test_listen_appends_transcription_then_stops(self, tmp_path: Path) -> None:
        out = tmp_path / "heard.txt"
        ctx = make_ctx(stt_text="first utterance")

        wav_paths: list[Path] = []
        call_count = {"n": 0}

        def fake_record() -> Path:
            call_count["n"] += 1
            if call_count["n"] == 1:
                p = self._fake_wav()
                wav_paths.append(p)
                return p
            raise KeyboardInterrupt

        MockFactory = MagicMock()
        MockFactory.return_value.record.side_effect = fake_record
        ctx.recorder_factory = MockFactory
        runner = CliRunner()

        result = runner.invoke(listen, [str(out)], obj=ctx)

        assert result.exit_code == 0, result.output
        assert out.read_text() == "first utterance\n"
        assert not wav_paths[0].exists()

    def test_listen_skips_empty_transcription(self, tmp_path: Path) -> None:
        out = tmp_path / "heard.txt"
        ctx = make_ctx(stt_text="   ")  # whitespace only

        call_count = {"n": 0}

        def fake_record_once() -> Path:
            call_count["n"] += 1
            if call_count["n"] == 1:
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                return Path(tmp.name)
            raise KeyboardInterrupt

        MockFactory = MagicMock()
        MockFactory.return_value.record.side_effect = fake_record_once
        ctx.recorder_factory = MockFactory
        runner = CliRunner()

        runner.invoke(listen, [str(out)], obj=ctx)

        # Nothing written because stripped text was empty.
        assert not out.exists() or out.read_text() == ""

    def test_wake_word_gates_non_trigger_utterance(self, tmp_path: Path) -> None:
        """With --wake-word, non-matching utterances are dropped; matching open the gate."""
        out = tmp_path / "heard.txt"
        texts = iter(["Computer science is cool", "Computer, hello", "world"])
        ctx = make_ctx()
        ctx.mm.generate_stt.side_effect = lambda p: _FakeText(next(texts))

        call_count = {"n": 0}

        def fake_record() -> Path:
            call_count["n"] += 1
            if call_count["n"] <= 3:
                return self._fake_wav()
            raise KeyboardInterrupt

        MockFactory = MagicMock()
        MockFactory.return_value.record.side_effect = fake_record
        ctx.recorder_factory = MockFactory
        runner = CliRunner()

        result = runner.invoke(
            listen,
            [str(out), "--wake-word", "computer", "--no-wake-alert"],
            obj=ctx,
        )

        assert result.exit_code == 0, result.output
        # Line 1 rejected (no punctuation after "Computer").
        # Line 2 matches → rest "hello" emitted.
        # Line 3 passes through open window as-is.
        assert out.read_text() == "hello\nworld\n"

    def test_wake_word_and_no_wake_word_mutually_exclusive(self, tmp_path: Path) -> None:
        out = tmp_path / "heard.txt"
        ctx = make_ctx()
        runner = CliRunner()
        result = runner.invoke(
            listen,
            [str(out), "--wake-word", "computer", "--no-wake-word"],
            obj=ctx,
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output


class _FakeText:
    def __init__(self, text: str) -> None:
        self.text = text
