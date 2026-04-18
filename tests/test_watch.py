"""Tests for `cai watch` — file polling + TTS playback via factory seam."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from src.cli.watch import TextFileHandler, watch
from tests._cli_fakes import make_ctx


class TestTextFileHandler:
    """Unit tests for the offset-tracking + debounce logic."""

    def test_reads_only_new_bytes(self, tmp_path: Path) -> None:
        f = tmp_path / "log.txt"
        f.write_text("initial\n")
        seen: list[str] = []
        h = TextFileHandler(f, seen.append)

        f.write_text("initial\nsecond line\n")
        h._read_new()

        assert seen == ["second line"]

    def test_resets_offset_on_truncation(self, tmp_path: Path) -> None:
        f = tmp_path / "log.txt"
        f.write_text("a very long line that sets a high offset\n")
        seen: list[str] = []
        h = TextFileHandler(f, seen.append)

        f.write_text("short\n")  # truncate below old offset
        h._read_new()

        assert seen == ["short"]

    def test_skips_empty_reads(self, tmp_path: Path) -> None:
        f = tmp_path / "log.txt"
        f.write_text("same\n")
        seen: list[str] = []
        h = TextFileHandler(f, seen.append)

        h._read_new()  # no new content

        assert seen == []

    def test_missing_file_is_noop(self, tmp_path: Path) -> None:
        f = tmp_path / "gone.txt"
        f.write_text("x")
        seen: list[str] = []
        h = TextFileHandler(f, seen.append)
        f.unlink()

        h._read_new()  # must not raise
        assert seen == []


class TestWatchCommand:
    def test_watch_starts_and_stops_cleanly(self, tmp_path: Path) -> None:
        target = tmp_path / "watched.txt"
        ctx = make_ctx()
        runner = CliRunner()

        handler_instance = MagicMock()

        # The watch command's idle loop is `while True: time.sleep(1)`.
        # Raise KeyboardInterrupt on the first sleep to exit cleanly.
        with (
            patch("src.cli.watch.TextFileHandler", return_value=handler_instance),
            patch("src.cli.watch.time.sleep", side_effect=KeyboardInterrupt),
        ):
            result = runner.invoke(watch, [str(target)], obj=ctx)

        assert result.exit_code == 0, result.output
        assert target.exists()  # touched on startup
        handler_instance.stop.assert_called_once()
