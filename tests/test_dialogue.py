"""Tests for `cai dialogue` — duplex mic + TTS with barge-in / half-duplex gates."""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from src.cli.dialogue import _listener_loop, _make_speak_callback, dialogue
from tests._cli_fakes import FakeSTTOutput, make_ctx


class TestSpeakCallback:
    """Unit tests for the dialogue-mode speak callback (TTS side).

    After P8, the watchdog handler is `TextFileHandler` from watch.py; the
    dialogue-specific bits (inference lock + shutdown re-check) live in the
    callback built by `_make_speak_callback`.
    """

    def test_callback_invokes_tts_within_lock(self) -> None:
        ctx = make_ctx()
        lock = threading.Lock()
        shutdown = threading.Event()

        lock_state: dict[str, bool] = {"locked_during_call": False}

        def fake_play(*args: Any, **kwargs: Any) -> None:
            lock_state["locked_during_call"] = lock.locked()

        mock_play = MagicMock(side_effect=fake_play)
        ctx.speaker_factory = mock_play
        cb = _make_speak_callback(ctx, lock, shutdown)

        cb("say this")

        mock_play.assert_called_once()
        assert mock_play.call_args[0][1] == "say this"
        assert lock_state["locked_during_call"] is True
        assert not lock.locked()

    def test_callback_is_noop_when_shutdown_already_set(self) -> None:
        ctx = make_ctx()
        shutdown = threading.Event()
        shutdown.set()
        mock_play = MagicMock()
        ctx.speaker_factory = mock_play
        cb = _make_speak_callback(ctx, threading.Lock(), shutdown)

        cb("never spoken")

        mock_play.assert_not_called()

    def test_callback_forwards_barge_event_as_cancel(self) -> None:
        """The shared barge_event must reach speaker_factory as cancel=."""
        ctx = make_ctx()
        barge = threading.Event()
        mock_play = MagicMock()
        ctx.speaker_factory = mock_play
        cb = _make_speak_callback(ctx, threading.Lock(), threading.Event(), barge)

        cb("say this")

        mock_play.assert_called_once()
        assert mock_play.call_args.kwargs.get("cancel") is barge

    def test_callback_skips_if_shutdown_set_after_lock_acquired(self) -> None:
        """A callback queued behind the listener must drop post-Ctrl+C."""
        ctx = make_ctx()
        lock = threading.Lock()
        shutdown = threading.Event()
        mock_play = MagicMock()
        ctx.speaker_factory = mock_play
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
        ctx = make_ctx(stt_text="heard this")
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
        ctx = make_ctx()
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
        ctx = make_ctx()
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
        listen_path = tmp_path / "heard.txt"
        listen_path.touch()
        ctx = make_ctx(stt_text="ok")
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
        ctx = make_ctx()
        barge = threading.Event()
        mock_play = MagicMock()
        ctx.speaker_factory = mock_play
        cb = _make_speak_callback(ctx, threading.Lock(), threading.Event(), barge)

        cb("hi")

        assert mock_play.call_args.kwargs.get("cancel") is barge

    def test_barge_in_false_passes_cancel_none(self) -> None:
        """barge_event=None → speaker_factory receives cancel=None."""
        ctx = make_ctx()
        mock_play = MagicMock()
        ctx.speaker_factory = mock_play
        cb = _make_speak_callback(ctx, threading.Lock(), threading.Event(), barge_event=None)

        cb("hi")

        mock_play.assert_called_once()
        assert mock_play.call_args.kwargs.get("cancel") is None

    def test_half_duplex_sets_tts_active_around_play(self) -> None:
        """tts_active must be set while speaker_factory runs, cleared after."""
        ctx = make_ctx()
        tts_active = threading.Event()
        seen: dict[str, bool] = {}

        def fake_play(*args: Any, **kwargs: Any) -> None:
            seen["set_during_call"] = tts_active.is_set()

        ctx.speaker_factory = MagicMock(side_effect=fake_play)
        cb = _make_speak_callback(
            ctx,
            threading.Lock(),
            threading.Event(),
            barge_event=None,
            tts_active=tts_active,
        )

        cb("hi")

        assert seen["set_during_call"] is True
        assert not tts_active.is_set()  # cleared after

    def test_half_duplex_clears_tts_active_on_exception(self) -> None:
        """finally: block must clear tts_active even if TTS raises."""
        ctx = make_ctx()
        tts_active = threading.Event()
        ctx.speaker_factory = MagicMock(side_effect=RuntimeError("boom"))
        cb = _make_speak_callback(
            ctx,
            threading.Lock(),
            threading.Event(),
            barge_event=None,
            tts_active=tts_active,
        )

        cb("hi")

        assert not tts_active.is_set()

    def test_half_duplex_listener_waits_while_tts_active(self, tmp_path: Path) -> None:
        """Listener must not call record() while tts_active is set."""
        listen_path = tmp_path / "heard.txt"
        listen_path.touch()
        ctx = make_ctx(stt_text="ok")
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
        ctx = make_ctx(stt_text="ok")
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
        ctx = make_ctx()
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
            raise RuntimeError("simulated device gone")

        recorder_mock.record.side_effect = fake_record

        # Main-loop idle-wait: the dialogue command does
        # `listener_thread.join(timeout=1)` in a loop. Patch that join to
        # raise KeyboardInterrupt on first call so we exit the main loop.
        original_thread_join = threading.Thread.join
        join_raised = {"done": False}

        def fake_join(self: threading.Thread, timeout: float | None = None) -> None:
            if self.name == "dialogue-listener" and not join_raised["done"]:
                join_raised["done"] = True
                raise KeyboardInterrupt
            original_thread_join(self, timeout)

        ctx.recorder_factory = MagicMock(return_value=recorder_mock)
        with (
            patch("src.cli.dialogue.TextFileHandler", return_value=handler_instance),
            patch.object(threading.Thread, "join", fake_join),
        ):
            result = runner.invoke(dialogue, [], obj=ctx)

        assert result.exit_code == 0, result.output
        assert speak_path.exists()
        assert listen_path.exists()
        handler_instance.stop.assert_called_once()
