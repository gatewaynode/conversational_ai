"""Tests for CLI subcommands using Click CliRunner.

ModelManager and audio I/O are mocked so no hardware is required.
Each subcommand is invoked directly (not through the `cli` group) by
passing a pre-built CliContext via `obj=`.
"""

from __future__ import annotations

import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

import cli as cli_entry

from src.cli import MODEL_REQUIREMENTS, CliContext
from src.cli.dialogue import _listener_loop, _make_speak_callback, dialogue
from src.cli.listen import listen
from src.cli.serve import serve
from src.cli.speak import speak
from src.cli.transcribe import transcribe
from src.cli.watch import TextFileHandler, watch
from src.config import Settings


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeSTTOutput:
    text: str
    segments: list[dict] | None = None
    language: str | None = None


def _make_ctx(
    tts_side_effect: Any = None,
    stt_text: str = "hello from stt",
) -> CliContext:
    """Return a CliContext with a fake ModelManager."""
    mm = MagicMock()
    mm.generate_stt.return_value = FakeSTTOutput(text=stt_text)
    if tts_side_effect is not None:
        mm.generate_tts_streaming.side_effect = tts_side_effect
    else:
        mm.generate_tts_streaming.return_value = iter([])
    return CliContext(settings=Settings(), mm=mm)


# ---------------------------------------------------------------------------
# speak
# ---------------------------------------------------------------------------


class TestSpeak:
    def test_speak_positional_arg(self) -> None:
        ctx = _make_ctx()
        runner = CliRunner()

        with patch("src.cli.speak.play_tts_streaming") as mock_play:
            result = runner.invoke(speak, ["hello world"], obj=ctx)

        assert result.exit_code == 0, result.output
        mock_play.assert_called_once()
        args = mock_play.call_args
        assert args[0][1] == "hello world"

    def test_speak_strips_whitespace(self) -> None:
        ctx = _make_ctx()
        runner = CliRunner()

        with patch("src.cli.speak.play_tts_streaming") as mock_play:
            result = runner.invoke(speak, ["  trimmed  "], obj=ctx)

        assert result.exit_code == 0
        assert mock_play.call_args[0][1] == "trimmed"

    def test_speak_from_file(self, tmp_path: Path) -> None:
        f = tmp_path / "input.txt"
        f.write_text("text from file\n")
        ctx = _make_ctx()
        runner = CliRunner()

        with patch("src.cli.speak.play_tts_streaming") as mock_play:
            result = runner.invoke(speak, ["--file", str(f)], obj=ctx)

        assert result.exit_code == 0, result.output
        assert mock_play.call_args[0][1] == "text from file"

    def test_speak_from_stdin(self) -> None:
        ctx = _make_ctx()
        runner = CliRunner()

        with patch("src.cli.speak.play_tts_streaming") as mock_play:
            result = runner.invoke(speak, [], input="piped text\n", obj=ctx)

        assert result.exit_code == 0, result.output
        assert mock_play.call_args[0][1] == "piped text"

    def test_speak_empty_input_raises_usage_error(self) -> None:
        ctx = _make_ctx()
        runner = CliRunner()

        with patch("src.cli.speak.play_tts_streaming"):
            result = runner.invoke(speak, [], input="   \n", obj=ctx)

        assert result.exit_code != 0

    def test_speak_uses_settings_voice_and_speed(self) -> None:
        ctx = _make_ctx()
        # Override voice and speed in settings
        ctx.settings.tts.voice = "af_sky"
        ctx.settings.tts.speed = 1.5
        ctx.settings.tts.lang_code = "b"
        runner = CliRunner()

        with patch("src.cli.speak.play_tts_streaming") as mock_play:
            runner.invoke(speak, ["hi"], obj=ctx)

        _, text, voice, speed, lang_code = mock_play.call_args[0]
        assert voice == "af_sky"
        assert speed == 1.5
        assert lang_code == "b"

    def test_speak_missing_file_exits_nonzero(self) -> None:
        ctx = _make_ctx()
        runner = CliRunner()

        result = runner.invoke(speak, ["--file", "/no/such/file.txt"], obj=ctx)
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# transcribe
# ---------------------------------------------------------------------------


class TestTranscribe:
    def _fake_record(self) -> Path:
        """Return a real temp WAV path (content irrelevant — STT is mocked)."""
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        return Path(tmp.name)

    def test_transcribe_prints_to_stdout(self) -> None:
        ctx = _make_ctx(stt_text="transcribed text")
        runner = CliRunner()

        with patch("src.cli.transcribe.mic_recorder_from_settings") as MockFactory:
            MockFactory.return_value.record.return_value = self._fake_record()
            result = runner.invoke(transcribe, [], obj=ctx)

        assert result.exit_code == 0, result.output
        assert "transcribed text" in result.output

    def test_transcribe_to_file(self, tmp_path: Path) -> None:
        out = tmp_path / "out.txt"
        ctx = _make_ctx(stt_text="saved to file")
        runner = CliRunner()

        with patch("src.cli.transcribe.mic_recorder_from_settings") as MockFactory:
            MockFactory.return_value.record.return_value = self._fake_record()
            result = runner.invoke(transcribe, ["-o", str(out)], obj=ctx)

        assert result.exit_code == 0, result.output
        assert out.read_text() == "saved to file\n"
        # Nothing printed to stdout when writing to file.
        assert result.output.strip() == ""

    def test_transcribe_appends_to_existing_file(self, tmp_path: Path) -> None:
        out = tmp_path / "out.txt"
        out.write_text("existing\n")
        ctx = _make_ctx(stt_text="appended")
        runner = CliRunner()

        with patch("src.cli.transcribe.mic_recorder_from_settings") as MockFactory:
            MockFactory.return_value.record.return_value = self._fake_record()
            runner.invoke(transcribe, ["-o", str(out)], obj=ctx)

        assert out.read_text() == "existing\nappended\n"

    def test_transcribe_cleans_up_temp_file(self) -> None:
        """Temp audio file must be deleted even if STT raises."""
        tmp_path_holder: list[Path] = []

        def fake_record() -> Path:
            p = self._fake_record()
            tmp_path_holder.append(p)
            return p

        ctx = _make_ctx()
        ctx.mm.generate_stt.side_effect = RuntimeError("STT failed")
        runner = CliRunner()

        with patch("src.cli.transcribe.mic_recorder_from_settings") as MockFactory:
            MockFactory.return_value.record.side_effect = fake_record
            runner.invoke(transcribe, [], obj=ctx)

        if tmp_path_holder:
            assert not tmp_path_holder[0].exists(), "Temp file was not cleaned up"


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------


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
        ctx = _make_ctx()
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


# ---------------------------------------------------------------------------
# listen
# ---------------------------------------------------------------------------


class TestListenCommand:
    def _fake_wav(self) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        return Path(tmp.name)

    def test_listen_appends_transcription_then_stops(self, tmp_path: Path) -> None:
        out = tmp_path / "heard.txt"
        ctx = _make_ctx(stt_text="first utterance")
        runner = CliRunner()

        wav_paths: list[Path] = []
        call_count = {"n": 0}

        def fake_record() -> Path:
            call_count["n"] += 1
            if call_count["n"] == 1:
                p = self._fake_wav()
                wav_paths.append(p)
                return p
            raise KeyboardInterrupt

        with patch("src.cli.listen.mic_recorder_from_settings") as MockFactory:
            MockFactory.return_value.record.side_effect = fake_record
            result = runner.invoke(listen, [str(out)], obj=ctx)

        assert result.exit_code == 0, result.output
        assert out.read_text() == "first utterance\n"
        # Temp wav cleaned up.
        assert not wav_paths[0].exists()

    def test_listen_skips_empty_transcription(self, tmp_path: Path) -> None:
        out = tmp_path / "heard.txt"
        ctx = _make_ctx(stt_text="   ")  # whitespace only
        runner = CliRunner()

        def fake_record() -> Path:
            raise KeyboardInterrupt

        # Raise on the first call so only one iteration happens — but we
        # also need at least one utterance first. Use a counter.
        call_count = {"n": 0}

        def fake_record_once() -> Path:
            call_count["n"] += 1
            if call_count["n"] == 1:
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                return Path(tmp.name)
            raise KeyboardInterrupt

        with patch("src.cli.listen.mic_recorder_from_settings") as MockFactory:
            MockFactory.return_value.record.side_effect = fake_record_once
            runner.invoke(listen, [str(out)], obj=ctx)

        # Nothing written because stripped text was empty.
        assert not out.exists() or out.read_text() == ""


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


class TestServeCommand:
    def test_serve_calls_uvicorn_with_host_and_port(self) -> None:
        ctx = _make_ctx()
        ctx.settings.server.host = "127.0.0.1"
        ctx.settings.server.port = 4242
        runner = CliRunner()

        fake_app = object()
        with (
            patch("main.create_app", return_value=fake_app) as mock_create,
            patch("uvicorn.run") as mock_run,
        ):
            result = runner.invoke(serve, [], obj=ctx)

        assert result.exit_code == 0, result.output
        mock_create.assert_called_once_with(ctx.settings)
        mock_run.assert_called_once_with(fake_app, host="127.0.0.1", port=4242)


# ---------------------------------------------------------------------------
# dialogue
# ---------------------------------------------------------------------------


class TestSpeakCallback:
    """Unit tests for the dialogue-mode speak callback (TTS side).

    After P8, the watchdog handler is `TextFileHandler` from watch.py; the
    dialogue-specific bits (inference lock + shutdown re-check) live in the
    callback built by `_make_speak_callback`.
    """

    def test_callback_invokes_tts_within_lock(self) -> None:
        ctx = _make_ctx()
        lock = threading.Lock()
        shutdown = threading.Event()
        cb = _make_speak_callback(ctx, lock, shutdown)

        lock_state: dict[str, bool] = {"locked_during_call": False}

        def fake_play(*args: Any, **kwargs: Any) -> None:
            lock_state["locked_during_call"] = lock.locked()

        with patch("src.cli.dialogue.play_tts_streaming", side_effect=fake_play) as mock_play:
            cb("say this")

        mock_play.assert_called_once()
        assert mock_play.call_args[0][1] == "say this"
        assert lock_state["locked_during_call"] is True
        assert not lock.locked()

    def test_callback_is_noop_when_shutdown_already_set(self) -> None:
        ctx = _make_ctx()
        shutdown = threading.Event()
        shutdown.set()
        cb = _make_speak_callback(ctx, threading.Lock(), shutdown)

        with patch("src.cli.dialogue.play_tts_streaming") as mock_play:
            cb("never spoken")

        mock_play.assert_not_called()

    def test_callback_forwards_barge_event_as_cancel(self) -> None:
        """The shared barge_event must reach play_tts_streaming as cancel=."""
        ctx = _make_ctx()
        barge = threading.Event()
        cb = _make_speak_callback(ctx, threading.Lock(), threading.Event(), barge)

        with patch("src.cli.dialogue.play_tts_streaming") as mock_play:
            cb("say this")

        mock_play.assert_called_once()
        assert mock_play.call_args.kwargs.get("cancel") is barge

    def test_callback_skips_if_shutdown_set_after_lock_acquired(self) -> None:
        """A callback queued behind the listener must drop post-Ctrl+C."""
        ctx = _make_ctx()
        lock = threading.Lock()
        shutdown = threading.Event()
        cb = _make_speak_callback(ctx, lock, shutdown)

        # Hold the lock so the callback blocks acquiring it, then set
        # shutdown before releasing — simulates listener holding the lock
        # while Ctrl+C is pressed.
        lock.acquire()

        def release_after_shutdown() -> None:
            shutdown.set()
            lock.release()

        t = threading.Timer(0.05, release_after_shutdown)
        t.daemon = True
        t.start()

        with patch("src.cli.dialogue.play_tts_streaming") as mock_play:
            cb("queued behind listener")

        t.join()
        mock_play.assert_not_called()


class TestListenerLoop:
    """Unit tests for the dialogue-mode mic listener (STT side)."""

    def _fake_wav(self) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        return Path(tmp.name)

    def test_writes_transcription_and_cleans_temp(self, tmp_path: Path) -> None:
        listen_path = tmp_path / "heard.txt"
        listen_path.touch()
        ctx = _make_ctx(stt_text="heard this")
        lock = threading.Lock()
        shutdown = threading.Event()

        wav_paths: list[Path] = []

        def fake_record(*args: Any, **kwargs: Any) -> Path:
            p = self._fake_wav()
            wav_paths.append(p)
            return p

        def fake_stt(audio_path: Any) -> Any:
            shutdown.set()  # exit after this utterance is processed
            return FakeSTTOutput(text="heard this")

        recorder_mock = MagicMock()
        recorder_mock.record.side_effect = fake_record
        ctx.mm.generate_stt.side_effect = fake_stt

        with patch("src.cli.dialogue.MicRecorder", return_value=recorder_mock):
            _listener_loop(listen_path, ctx, lock, shutdown)

        assert listen_path.read_text() == "heard this\n"
        assert wav_paths and not wav_paths[0].exists()

    def test_shutdown_halts_loop_before_first_record(self, tmp_path: Path) -> None:
        listen_path = tmp_path / "heard.txt"
        listen_path.touch()
        ctx = _make_ctx()
        shutdown = threading.Event()
        shutdown.set()

        recorder_mock = MagicMock()
        with patch("src.cli.dialogue.MicRecorder", return_value=recorder_mock):
            _listener_loop(listen_path, ctx, threading.Lock(), shutdown)

        recorder_mock.record.assert_not_called()
        assert listen_path.read_text() == ""

    def test_record_failures_trigger_backoff_and_give_up(self, tmp_path: Path) -> None:
        """Persistent MicRecorder failures must not tight-loop; they fail fast."""
        import src.cli.dialogue as dialogue_mod

        listen_path = tmp_path / "heard.txt"
        listen_path.touch()
        ctx = _make_ctx()
        shutdown = threading.Event()

        recorder_mock = MagicMock()
        recorder_mock.record.side_effect = RuntimeError("no audio device")

        waits: list[float | None] = []
        original_wait = shutdown.wait

        def fake_wait(timeout: float | None = None) -> bool:
            waits.append(timeout)
            return original_wait(0)  # don't actually sleep

        with (
            patch("src.cli.dialogue.MicRecorder", return_value=recorder_mock),
            patch.object(shutdown, "wait", side_effect=fake_wait),
        ):
            _listener_loop(listen_path, ctx, threading.Lock(), shutdown)

        # Bailed out after MAX consecutive failures, set shutdown itself.
        assert recorder_mock.record.call_count == dialogue_mod._RECORD_MAX_CONSECUTIVE_FAILURES
        assert shutdown.is_set()
        # Backoff doubled each time (0.5, 1.0, 2.0, 4.0, 8.0, capped).
        assert waits[0] == dialogue_mod._RECORD_BACKOFF_START
        assert waits[1] == 1.0
        assert waits[-1] == dialogue_mod._RECORD_BACKOFF_MAX
        # One fewer wait than attempts (last failure triggers give-up, no wait).
        assert len(waits) == dialogue_mod._RECORD_MAX_CONSECUTIVE_FAILURES - 1

    def test_record_failure_resets_backoff_after_success(self, tmp_path: Path) -> None:
        """A successful record() between failures must reset the backoff counter."""
        import src.cli.dialogue as dialogue_mod

        listen_path = tmp_path / "heard.txt"
        listen_path.touch()
        ctx = _make_ctx(stt_text="ok")
        shutdown = threading.Event()

        wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        wav.close()
        wav_path = Path(wav.name)

        call_count = {"n": 0}

        def fake_record(*args: Any, **kwargs: Any) -> Path:
            call_count["n"] += 1
            if call_count["n"] <= 3:
                raise RuntimeError("flaky mic")
            if call_count["n"] == 4:
                return wav_path
            shutdown.set()
            raise RuntimeError("done")

        recorder_mock = MagicMock()
        recorder_mock.record.side_effect = fake_record

        with (
            patch("src.cli.dialogue.MicRecorder", return_value=recorder_mock),
            patch.object(shutdown, "wait", return_value=False),
        ):
            _listener_loop(listen_path, ctx, threading.Lock(), shutdown)

        # 3 failures + 1 success + 1 final failure → 5 calls; loop exits cleanly
        # (give-up counter was reset by the success, so we never hit the cap).
        assert call_count["n"] == 5
        assert listen_path.read_text() == "ok\n"
        wav_path.unlink(missing_ok=True)


class TestDuplexModes:
    """P13 duplex-mode matrix: `barge_in` × `full_duplex`."""

    def test_barge_in_true_forwards_event_as_cancel(self) -> None:
        ctx = _make_ctx()
        barge = threading.Event()
        cb = _make_speak_callback(ctx, threading.Lock(), threading.Event(), barge)

        with patch("src.cli.dialogue.play_tts_streaming") as mock_play:
            cb("hi")

        assert mock_play.call_args.kwargs.get("cancel") is barge

    def test_barge_in_false_passes_cancel_none(self) -> None:
        """barge_event=None → play_tts_streaming receives cancel=None."""
        ctx = _make_ctx()
        cb = _make_speak_callback(
            ctx, threading.Lock(), threading.Event(), barge_event=None
        )

        with patch("src.cli.dialogue.play_tts_streaming") as mock_play:
            cb("hi")

        mock_play.assert_called_once()
        assert mock_play.call_args.kwargs.get("cancel") is None

    def test_half_duplex_sets_tts_active_around_play(self) -> None:
        """tts_active must be set while play_tts_streaming runs, cleared after."""
        ctx = _make_ctx()
        tts_active = threading.Event()
        seen: dict[str, bool] = {}

        def fake_play(*args: Any, **kwargs: Any) -> None:
            seen["set_during_call"] = tts_active.is_set()

        cb = _make_speak_callback(
            ctx,
            threading.Lock(),
            threading.Event(),
            barge_event=None,
            tts_active=tts_active,
        )

        with patch("src.cli.dialogue.play_tts_streaming", side_effect=fake_play):
            cb("hi")

        assert seen["set_during_call"] is True
        assert not tts_active.is_set()  # cleared after

    def test_half_duplex_clears_tts_active_on_exception(self) -> None:
        """finally: block must clear tts_active even if TTS raises."""
        ctx = _make_ctx()
        tts_active = threading.Event()
        cb = _make_speak_callback(
            ctx,
            threading.Lock(),
            threading.Event(),
            barge_event=None,
            tts_active=tts_active,
        )

        with patch(
            "src.cli.dialogue.play_tts_streaming",
            side_effect=RuntimeError("boom"),
        ):
            cb("hi")

        assert not tts_active.is_set()

    def test_half_duplex_listener_waits_while_tts_active(self, tmp_path: Path) -> None:
        """Listener must not call record() while tts_active is set."""
        listen_path = tmp_path / "heard.txt"
        listen_path.touch()
        ctx = _make_ctx(stt_text="ok")
        shutdown = threading.Event()
        tts_active = threading.Event()
        tts_active.set()  # TTS "playing" — listener must wait

        recorder_mock = MagicMock()

        def fake_record(*args: Any, **kwargs: Any) -> Path:
            # First record attempt: TTS must already be inactive.
            assert not tts_active.is_set()
            shutdown.set()
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            return Path(tmp.name)

        recorder_mock.record.side_effect = fake_record

        wait_call_count = {"n": 0}
        original_wait = shutdown.wait

        def fake_wait(timeout: float | None = None) -> bool:
            wait_call_count["n"] += 1
            # After a few polls, clear tts_active so the gate opens.
            if wait_call_count["n"] == 3:
                tts_active.clear()
            return original_wait(0)  # don't actually sleep

        with (
            patch("src.cli.dialogue.MicRecorder", return_value=recorder_mock),
            patch.object(shutdown, "wait", side_effect=fake_wait),
        ):
            _listener_loop(
                listen_path,
                ctx,
                threading.Lock(),
                shutdown,
                barge_event=None,
                tts_active=tts_active,
            )

        recorder_mock.record.assert_called_once()
        assert wait_call_count["n"] >= 3  # gate actually looped

    def test_full_duplex_listener_records_immediately(self, tmp_path: Path) -> None:
        """tts_active=None → listener skips the gate entirely (P7 behavior)."""
        listen_path = tmp_path / "heard.txt"
        listen_path.touch()
        ctx = _make_ctx(stt_text="ok")
        shutdown = threading.Event()

        recorder_mock = MagicMock()

        def fake_record(*args: Any, **kwargs: Any) -> Path:
            shutdown.set()
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            return Path(tmp.name)

        recorder_mock.record.side_effect = fake_record

        with patch("src.cli.dialogue.MicRecorder", return_value=recorder_mock):
            _listener_loop(
                listen_path,
                ctx,
                threading.Lock(),
                shutdown,
                barge_event=None,
                tts_active=None,
            )

        recorder_mock.record.assert_called_once()


class TestDialogueCommand:
    def test_dialogue_starts_and_stops_both_threads(self, tmp_path: Path) -> None:
        speak_path = tmp_path / "speak.txt"
        listen_path = tmp_path / "listen.txt"
        ctx = _make_ctx()
        ctx.settings.dialogue.speak_file = str(speak_path)
        ctx.settings.dialogue.listen_file = str(listen_path)

        runner = CliRunner()

        handler_instance = MagicMock()
        listener_started = threading.Event()

        recorder_mock = MagicMock()

        # Listener thread: block on record() until the main loop trips
        # KeyboardInterrupt, then raise a catchable Exception so the loop
        # notices shutdown and exits cleanly.
        def fake_record(*args: Any, **kwargs: Any) -> Path:
            listener_started.set()
            # Wait up to 2s; the main-loop KeyboardInterrupt will cause
            # `shutdown.set()` which this loop doesn't observe directly,
            # but the main thread's finally will call listener_thread.join
            # after it raises below.
            raise RuntimeError("simulated device gone")

        recorder_mock.record.side_effect = fake_record

        # Main-loop idle-wait: the dialogue command does
        # `listener_thread.join(timeout=1)` in a loop. Patch that join to
        # raise KeyboardInterrupt on first call so we exit the main loop.
        original_thread_join = threading.Thread.join
        join_raised = {"done": False}

        def fake_join(self: threading.Thread, timeout: float | None = None) -> None:
            # Only intercept the main-loop join on the listener thread.
            if self.name == "dialogue-listener" and not join_raised["done"]:
                join_raised["done"] = True
                raise KeyboardInterrupt
            original_thread_join(self, timeout)

        with (
            patch("src.cli.dialogue.TextFileHandler", return_value=handler_instance),
            patch("src.cli.dialogue.mic_recorder_from_settings", return_value=recorder_mock),
            patch.object(threading.Thread, "join", fake_join),
        ):
            result = runner.invoke(dialogue, [], obj=ctx)

        assert result.exit_code == 0, result.output
        assert speak_path.exists()
        assert listen_path.exists()
        handler_instance.stop.assert_called_once()


# ---------------------------------------------------------------------------
# Lazy per-subcommand model loading (P3)
# ---------------------------------------------------------------------------


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
