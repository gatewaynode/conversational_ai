"""Unit tests for CLI audio I/O primitives.

Tests cover:
- MicRecorder VAD constants and RMS math (no microphone required)
- TextFileHandler offset tracking and truncation detection (no watchdog events)
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pytest

from unittest.mock import MagicMock, patch

from src.cli.audio_io import MicRecorder, play_tts_streaming
from src.cli.watch import TextFileHandler


# ---------------------------------------------------------------------------
# MicRecorder — VAD constants and RMS math
# ---------------------------------------------------------------------------


class TestMicRecorderConstants:
    def test_chunk_and_silence_relationship(self) -> None:
        """silence_chunks_needed should be SILENCE_SECONDS / CHUNK_SECONDS."""
        expected = int(MicRecorder.SILENCE_SECONDS / MicRecorder.CHUNK_SECONDS)
        frames = int(MicRecorder.SAMPLE_RATE * MicRecorder.CHUNK_SECONDS)
        silence_chunks = int(MicRecorder.SILENCE_SECONDS / MicRecorder.CHUNK_SECONDS)
        assert silence_chunks == expected
        assert frames > 0

    def test_sample_rate_is_16k(self) -> None:
        assert MicRecorder.SAMPLE_RATE == 16_000

    def test_rms_threshold_positive(self) -> None:
        assert MicRecorder.RMS_THRESHOLD > 0


class TestRMSComputation:
    """The VAD decision is based on RMS energy. Test the math directly."""

    def _rms(self, chunk: np.ndarray) -> float:
        return float(np.sqrt(np.mean(chunk**2)))

    def test_silence_chunk_below_threshold(self) -> None:
        chunk = np.zeros(800, dtype=np.float32)
        assert self._rms(chunk) < MicRecorder.RMS_THRESHOLD

    def test_loud_chunk_above_threshold(self) -> None:
        # Sine wave at amplitude 0.5 → RMS ≈ 0.354
        t = np.linspace(0, 0.05, 800, endpoint=False)
        chunk = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        assert self._rms(chunk) > MicRecorder.RMS_THRESHOLD

    def test_near_threshold_discrimination(self) -> None:
        # RMS_THRESHOLD is 0.01; a very quiet signal should be below it.
        chunk = np.full(800, 0.005, dtype=np.float32)
        assert self._rms(chunk) < MicRecorder.RMS_THRESHOLD

        chunk_loud = np.full(800, 0.02, dtype=np.float32)
        assert self._rms(chunk_loud) > MicRecorder.RMS_THRESHOLD

    def test_rms_is_non_negative(self) -> None:
        chunk = np.random.default_rng(42).uniform(-1, 1, 800).astype(np.float32)
        assert self._rms(chunk) >= 0


# ---------------------------------------------------------------------------
# TextFileHandler — offset tracking and truncation detection
# ---------------------------------------------------------------------------


def _make_handler(path: Path) -> tuple[TextFileHandler, list[str]]:
    """Create a handler wired to a callback list for inspection."""
    received: list[str] = []
    handler = TextFileHandler(path, received.append)
    return handler, received


class TestTextFileHandlerOffset:
    def test_initial_offset_skips_existing_content(self, tmp_path: Path) -> None:
        """Handler created after file has content should skip existing bytes."""
        f = tmp_path / "test.txt"
        f.write_text("existing content\n")

        handler, received = _make_handler(f)
        # Manually trigger read — should find nothing new.
        handler._read_new()
        assert received == []

    def test_new_content_is_delivered(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("")

        handler, received = _make_handler(f)
        f.write_text("hello world")
        handler._read_new()

        assert len(received) == 1
        assert received[0] == "hello world"

    def test_offset_advances_between_reads(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("")
        handler, received = _make_handler(f)

        # First append
        with f.open("a") as fp:
            fp.write("first\n")
        handler._read_new()

        # Second append
        with f.open("a") as fp:
            fp.write("second\n")
        handler._read_new()

        assert received == ["first", "second"]

    def test_whitespace_only_not_delivered(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("")
        handler, received = _make_handler(f)

        with f.open("a") as fp:
            fp.write("   \n  \n")
        handler._read_new()

        assert received == []

    def test_truncation_resets_offset(self, tmp_path: Path) -> None:
        """When file shrinks below offset, offset resets and full content is re-read."""
        f = tmp_path / "test.txt"
        f.write_text("old content that will be replaced\n")
        handler, received = _make_handler(f)

        # Simulate truncation by overwriting with shorter content.
        f.write_text("new\n")
        handler._read_new()

        assert received == ["new"]
        assert handler._offset == f.stat().st_size

    def test_missing_file_does_not_raise(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("")
        handler, received = _make_handler(f)

        f.unlink()
        # Should return silently, not raise.
        handler._read_new()
        assert received == []

    def test_poller_picks_up_appended_content(self, tmp_path: Path) -> None:
        """The worker thread should detect an mtime change and deliver new text."""
        import time

        f = tmp_path / "test.txt"
        f.write_text("")
        handler, received = _make_handler(f)

        # Ensure mtime advances meaningfully on very fast filesystems.
        time.sleep(0.01)
        with f.open("a") as fp:
            fp.write("delivered by poller\n")

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not received:
            time.sleep(0.02)

        handler.stop()

        assert received == ["delivered by poller"]

    def test_poller_does_not_scope_to_parent_directory(self, tmp_path: Path) -> None:
        """P10: a sibling file being modified must not trigger a read on ours.

        With the old watchdog-on-parent-dir approach, a change to any file in
        the same dir would wake the handler (and get filtered by src_path).
        With the pure poller, the sibling file is simply never stat()ed —
        proving we only touch the target file.
        """
        import time

        f = tmp_path / "target.txt"
        f.write_text("")
        sibling = tmp_path / "noise.txt"

        handler, received = _make_handler(f)

        # Hammer the sibling. If the handler were scoped to the parent dir
        # it might at least stat the sibling; the poller should not care.
        for _ in range(50):
            sibling.write_text("should not reach handler")

        time.sleep(0.5)  # give the poller ~1-2 ticks
        handler.stop()
        assert received == []

    def test_single_worker_thread_regardless_of_writes(self, tmp_path: Path) -> None:
        """The poller uses exactly one worker thread no matter how many writes."""
        import time

        f = tmp_path / "test.txt"
        f.write_text("")
        handler, received = _make_handler(f)

        before = threading.active_count()
        # 500 rapid writes — all landing within one poll tick will coalesce.
        for i in range(500):
            with f.open("a") as fp:
                fp.write(f"line{i}\n")

        # Thread count must not scale with write count.
        assert threading.active_count() - before <= 1

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not received:
            time.sleep(0.02)

        handler.stop()
        # We don't care how many reads it took; just that content arrived.
        assert received and "line499" in received[-1]


# ---------------------------------------------------------------------------
# play_tts_streaming — barge-in (P7)
# ---------------------------------------------------------------------------


class _FakeChunk:
    def __init__(self, audio: np.ndarray) -> None:
        self.audio = audio


class TestPlayTtsStreamingBargeIn:
    """P7: setting cancel mid-stream must flush the player, not drain."""

    def _make_mm(self, chunk_count: int) -> MagicMock:
        mm = MagicMock()
        chunks = [_FakeChunk(np.zeros(1024, dtype=np.float32)) for _ in range(chunk_count)]
        mm.generate_tts_streaming.return_value = iter(chunks)
        return mm

    def test_cancel_set_mid_stream_breaks_loop_and_flushes(self) -> None:
        """With cancel set before the second chunk, exactly one chunk is queued
        and the player is flushed (not drained via stop)."""
        mm = self._make_mm(chunk_count=5)
        cancel = threading.Event()

        player = MagicMock()

        # Trip the cancel as soon as the first chunk is queued.
        def queue_side_effect(audio: np.ndarray) -> None:
            cancel.set()

        player.queue_audio.side_effect = queue_side_effect

        with patch("mlx_audio.tts.audio_player.AudioPlayer", return_value=player):
            play_tts_streaming(mm, "hello", "af_heart", 1.0, "a", cancel=cancel)

        # Only the first chunk actually queued before the cancel check caught up.
        assert player.queue_audio.call_count == 1
        # Cancelled path: flush(), not stop().
        player.flush.assert_called_once()
        player.stop.assert_not_called()

    def test_no_cancel_drains_via_stop(self) -> None:
        """Normal completion path still calls stop() (drain), not flush()."""
        mm = self._make_mm(chunk_count=3)
        player = MagicMock()

        with patch("mlx_audio.tts.audio_player.AudioPlayer", return_value=player):
            play_tts_streaming(mm, "hi", "af_heart", 1.0, "a")

        assert player.queue_audio.call_count == 3
        player.stop.assert_called_once()
        player.flush.assert_not_called()

    def test_cancel_none_is_supported(self) -> None:
        """Absent cancel event (default) behaves exactly like the pre-P7 API."""
        mm = self._make_mm(chunk_count=2)
        player = MagicMock()

        with patch("mlx_audio.tts.audio_player.AudioPlayer", return_value=player):
            play_tts_streaming(mm, "hi", "af_heart", 1.0, "a", cancel=None)

        assert player.queue_audio.call_count == 2
        player.stop.assert_called_once()
        player.flush.assert_not_called()


class _FakeInputStream:
    """Test double for sounddevice.InputStream.

    On __enter__, feeds a scripted sequence of chunks to the user-supplied
    callback on a background thread so record()'s stop_event.wait() unblocks
    naturally when the trailing silence is delivered.
    """

    def __init__(self, chunks: list[np.ndarray], callback) -> None:  # type: ignore[no-untyped-def]
        self._chunks = chunks
        self._callback = callback
        self._thread: threading.Thread | None = None

    def __enter__(self) -> _FakeInputStream:
        def pump() -> None:
            for chunk in self._chunks:
                indata = chunk.reshape(-1, 1)
                self._callback(indata, len(chunk), None, None)

        self._thread = threading.Thread(target=pump, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._thread is not None:
            self._thread.join(timeout=1)


class TestMicRecorderBargeSignal:
    """P7: on_speech_start must fire on the VAD rising edge, not at utterance end."""

    def _build_chunks(self) -> list[np.ndarray]:
        """Silence → speech → trailing silence long enough to end the utterance."""
        frames = int(MicRecorder.SAMPLE_RATE * MicRecorder.CHUNK_SECONDS)
        silent = np.zeros(frames, dtype=np.float32)
        loud = np.full(frames, 0.5, dtype=np.float32)  # RMS = 0.5, way above 0.01
        silence_needed = int(MicRecorder.SILENCE_SECONDS / MicRecorder.CHUNK_SECONDS)
        # 2 leading silent chunks (ignored pre-speech), 3 speech chunks,
        # then enough trailing silence to trip the end-of-utterance gate.
        return [silent, silent, loud, loud, loud, *([silent] * (silence_needed + 1))]

    def test_event_fires_on_rising_edge_and_clears_on_return(
        self, tmp_path: Path
    ) -> None:
        barge = threading.Event()
        fire_moments: list[bool] = []  # records whether barge was set while still recording

        chunks = self._build_chunks()

        # Snoop on the callback by wrapping InputStream: we'll observe `barge`
        # inside the pump thread to prove it was set mid-stream, not just at
        # the end.
        original_fake = _FakeInputStream

        class SnoopingStream(_FakeInputStream):
            def __enter__(self_inner) -> _FakeInputStream:  # type: ignore[override]
                def pump() -> None:
                    saw_rising_edge = False
                    for chunk in self_inner._chunks:
                        self_inner._callback(chunk.reshape(-1, 1), len(chunk), None, None)
                        if barge.is_set() and not saw_rising_edge:
                            fire_moments.append(True)  # set mid-stream
                            saw_rising_edge = True

                self_inner._thread = threading.Thread(target=pump, daemon=True)
                self_inner._thread.start()
                return self_inner

        # Stub sounddevice + soundfile so record() doesn't touch real hardware.
        fake_sd = MagicMock()
        fake_sd.InputStream = lambda **kw: SnoopingStream(chunks, kw["callback"])
        fake_sd.CallbackFlags = object

        fake_sf = MagicMock()

        with (
            patch.dict("sys.modules", {"sounddevice": fake_sd, "soundfile": fake_sf}),
        ):
            recorder = MicRecorder()
            path = recorder.record(on_speech_start=barge)

        # Rising edge was observed before the stream finished.
        assert fire_moments == [True], "barge event must fire mid-stream, not at end"
        # Contract: event is cleared before record() returns.
        assert not barge.is_set()
        # Cleanup the fake temp wav path that tempfile created.
        Path(path).unlink(missing_ok=True)
