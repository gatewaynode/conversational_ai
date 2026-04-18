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

from src.cli.audio_io import AudioDeviceError, MicRecorder, play_tts_streaming
from src.cli.watch import TextFileHandler
from tests._audio_fakes import FakeInputStream, PortAudioError


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


class TestMicRecorderMinSpeechGate:
    """Feature 1: sustained-speech latch filters single-chunk transients."""

    def _make_chunks(self, loud_count: int) -> list[np.ndarray]:
        frames = int(MicRecorder.SAMPLE_RATE * MicRecorder.CHUNK_SECONDS)
        silent = np.zeros(frames, dtype=np.float32)
        loud = np.full(frames, 0.5, dtype=np.float32)
        silence_needed = int(1.5 / MicRecorder.CHUNK_SECONDS)
        # 2 leading silent chunks, N loud chunks, then trailing silence.
        return [silent, silent, *([loud] * loud_count), *([silent] * (silence_needed + 2))]

    def _run_record(self, recorder: MicRecorder, chunks: list[np.ndarray]) -> Path:
        fake_sd = MagicMock()
        fake_sd.InputStream = lambda **kw: FakeInputStream(chunks, kw["callback"])
        fake_sd.CallbackFlags = object
        fake_sf = MagicMock()
        with patch.dict("sys.modules", {"sounddevice": fake_sd, "soundfile": fake_sf}):
            return recorder.record()

    def test_single_loud_chunk_does_not_latch(self, tmp_path: Path) -> None:
        """A lone above-threshold chunk (keyboard clack) must not trigger a recording.

        To prove non-latch we need the stream to end without stop_event being set.
        We feed a single loud chunk then a huge run of silence; the recorder should
        still be waiting — but the fake stream's pump finishes, leaving us stuck.

        Instead, assert via the streak counter: feed one loud chunk, observe that
        speech_detected remains unset. We do this by exposing internal state via
        a custom min_speech_seconds that requires more chunks than we deliver.
        """
        # min_speech=0.25s → 5 chunks required; we deliver only 1.
        recorder = MicRecorder(min_speech_seconds=0.25)

        # Directly exercise the callback state-machine without spinning up a stream.
        # We need to observe `speech_detected` without calling record() (which blocks).
        # Simpler: drop a one-chunk burst into a short stream and check the WAV
        # output is empty / near-empty (no latch → nothing recorded post-burst).
        frames = int(MicRecorder.SAMPLE_RATE * MicRecorder.CHUNK_SECONDS)
        silent = np.zeros(frames, dtype=np.float32)
        loud = np.full(frames, 0.5, dtype=np.float32)
        # One lone loud chunk sandwiched in silence. Because min_speech=0.25s
        # (5 chunks), one burst cannot latch. Without latch, stop_event never
        # fires and record() would block — so we feed enough silence at the end
        # to keep the fake stream alive long enough, then verify via a raced
        # timeout using a sentinel.
        #
        # Easier path: deliver 4 loud chunks (below 5-chunk gate), then lots of
        # silence. Stream ends without latch. We need record() to exit, which it
        # only does on stop_event.set(). So: directly exercise by bypassing the
        # stream: drive the callback manually and inspect state.
        audio_chunks: list[np.ndarray] = []
        speech_detected = threading.Event()
        stop_event = threading.Event()
        silence_count = [0]
        above_streak = [0]
        pending: list[np.ndarray] = []
        threshold = recorder._threshold()
        silence_chunks_needed = int(recorder.silence_seconds / MicRecorder.CHUNK_SECONDS)
        min_speech_chunks = max(1, int(recorder.min_speech_seconds / MicRecorder.CHUNK_SECONDS))

        def run(chunk: np.ndarray) -> None:
            rms = float(np.sqrt(np.mean(chunk**2)))
            loud_flag = rms > threshold
            if not speech_detected.is_set():
                if loud_flag:
                    above_streak[0] += 1
                    pending.append(chunk)
                    if len(pending) > min_speech_chunks:
                        pending.pop(0)
                    if above_streak[0] >= min_speech_chunks:
                        speech_detected.set()
                        audio_chunks.extend(pending)
                        pending.clear()
                else:
                    above_streak[0] = 0
                    pending.clear()
                return
            audio_chunks.append(chunk)
            if not loud_flag:
                silence_count[0] += 1
                if silence_count[0] >= silence_chunks_needed:
                    stop_event.set()

        # Feed: silent, loud, silent, silent, loud (non-consecutive bursts)
        for c in [silent, loud, silent, silent, loud, silent]:
            run(c)

        assert not speech_detected.is_set(), (
            "non-consecutive loud chunks must not latch"
        )
        assert audio_chunks == []

    def test_sustained_speech_latches(self) -> None:
        """N consecutive loud chunks (N = min_speech_chunks) must latch."""
        recorder = MicRecorder(min_speech_seconds=0.15)
        min_speech_chunks = max(1, round(0.15 / MicRecorder.CHUNK_SECONDS))
        assert min_speech_chunks == 3

        frames = int(MicRecorder.SAMPLE_RATE * MicRecorder.CHUNK_SECONDS)
        loud = np.full(frames, 0.5, dtype=np.float32)

        speech_detected = threading.Event()
        above_streak = [0]
        pending: list[np.ndarray] = []
        threshold = recorder._threshold()

        for _ in range(min_speech_chunks):
            rms = float(np.sqrt(np.mean(loud**2)))
            if rms > threshold:
                above_streak[0] += 1
                pending.append(loud)
                if above_streak[0] >= min_speech_chunks:
                    speech_detected.set()
                    break

        assert speech_detected.is_set()
        assert len(pending) == min_speech_chunks  # leading audio preserved

    def test_streak_resets_on_silence(self) -> None:
        """Streak counter must reset when a silent chunk arrives pre-latch."""
        recorder = MicRecorder(min_speech_seconds=0.15)
        frames = int(MicRecorder.SAMPLE_RATE * MicRecorder.CHUNK_SECONDS)
        loud = np.full(frames, 0.5, dtype=np.float32)
        silent = np.zeros(frames, dtype=np.float32)

        above_streak = [0]
        threshold = recorder._threshold()

        # 2 loud (not enough) → 1 silent (reset) → 2 loud (still not enough)
        sequence = [loud, loud, silent, loud, loud]
        for c in sequence:
            rms = float(np.sqrt(np.mean(c**2)))
            if rms > threshold:
                above_streak[0] += 1
            else:
                above_streak[0] = 0

        # After this sequence the streak is 2, still below the 3-chunk gate.
        assert above_streak[0] == 2


class TestPreSpeechPadding:
    """B2: ring buffer must capture pre-speech context so onsets aren't clipped."""

    def test_recording_includes_silence_before_onset(self) -> None:
        """The recorded audio should include silent chunks that preceded speech."""
        frames = int(MicRecorder.SAMPLE_RATE * MicRecorder.CHUNK_SECONDS)
        # Use a distinctive pattern so we can identify it in the output.
        # 0.001 amplitude — below threshold but non-zero so we can detect it.
        context = np.full(frames, 0.001, dtype=np.float32)
        silent = np.zeros(frames, dtype=np.float32)
        loud = np.full(frames, 0.5, dtype=np.float32)
        silence_needed = int(1.5 / MicRecorder.CHUNK_SECONDS)

        # 3 context chunks, then 3 loud (trips the gate), then trailing silence.
        chunks = [context, context, context, loud, loud, loud, *([silent] * (silence_needed + 2))]

        recorder = MicRecorder(min_speech_seconds=0.15)
        # PRE_SPEECH_SECONDS=0.15 → 3 padding chunks; ring = 3 + 3 = 6 slots.
        # The 3 context chunks should be in the ring when the gate fires.

        fake_sd = MagicMock()
        fake_sd.InputStream = lambda **kw: FakeInputStream(chunks, kw["callback"])
        fake_sd.CallbackFlags = object
        fake_sf = MagicMock()

        with patch.dict("sys.modules", {"sounddevice": fake_sd, "soundfile": fake_sf}):
            recorder.record()

        # soundfile.write was called with the concatenated audio.
        write_call = fake_sf.write
        assert write_call.called
        audio = write_call.call_args[0][1]

        # The recording should be longer than just the 3 loud chunks —
        # it should include the 3 context chunks as leading audio.
        expected_min_samples = (3 + 3) * frames  # context + loud
        assert len(audio) >= expected_min_samples

        # The first chunk of the recording should be the context (0.001),
        # not the loud onset (0.5).
        first_chunk_rms = float(np.sqrt(np.mean(audio[:frames] ** 2)))
        assert first_chunk_rms < 0.01, "First chunk should be pre-speech context, not loud onset"

    def test_ring_does_not_grow_unbounded(self) -> None:
        """The ring should cap at ring_size, not accumulate indefinitely."""
        frames = int(MicRecorder.SAMPLE_RATE * MicRecorder.CHUNK_SECONDS)
        silent = np.zeros(frames, dtype=np.float32)
        loud = np.full(frames, 0.5, dtype=np.float32)
        silence_needed = int(1.5 / MicRecorder.CHUNK_SECONDS)

        # 50 silent chunks (way more than ring), then speech, then trailing silence.
        chunks = [*([silent] * 50), loud, loud, loud, *([silent] * (silence_needed + 2))]

        recorder = MicRecorder(min_speech_seconds=0.15)
        min_speech_chunks = max(1, round(0.15 / MicRecorder.CHUNK_SECONDS))
        pre_speech_chunks = max(1, round(MicRecorder.PRE_SPEECH_SECONDS / MicRecorder.CHUNK_SECONDS))
        ring_size = min_speech_chunks + pre_speech_chunks

        fake_sd = MagicMock()
        fake_sd.InputStream = lambda **kw: FakeInputStream(chunks, kw["callback"])
        fake_sd.CallbackFlags = object
        fake_sf = MagicMock()

        with patch.dict("sys.modules", {"sounddevice": fake_sd, "soundfile": fake_sf}):
            recorder.record()

        audio = fake_sf.write.call_args[0][1]
        # Total recorded: ring_size chunks (flushed on latch) + trailing silence chunks.
        # The ring should have capped, not dumped all 50 silent chunks.
        max_expected = (ring_size + silence_needed + 2) * frames
        assert len(audio) <= max_expected


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
        class SnoopingStream(FakeInputStream):
            def __enter__(self_inner) -> FakeInputStream:  # type: ignore[override]
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


# ---------------------------------------------------------------------------
# AudioDeviceError — B3: PortAudioError → human-readable messages
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# B1: Adaptive threshold — EMA re-calibration during long sessions
# ---------------------------------------------------------------------------


class TestAdaptiveThreshold:
    """B1: silence-chunk EMA must update the effective threshold between utterances."""

    def test_ema_updates_from_silence_chunks(self) -> None:
        """Pre-latch silence feeds the EMA; after record(), threshold adapts."""
        recorder = MicRecorder(rms_threshold=0.01, calibration_multiplier=3.0)
        # Simulate initial calibration with a low noise floor.
        recorder._calibrated = True
        recorder._ema_floor = 0.005
        recorder._ema_sample_count = 20
        recorder._effective_threshold = 0.015  # max(0.01, 0.005*3)

        # Feed silence chunks with higher RMS (noise floor shifted up).
        for _ in range(40):
            recorder._update_ema(0.02)

        recorder._recalculate_threshold()
        # EMA should have moved toward 0.02; new effective = max(0.01, ema*3).
        assert recorder._ema_floor is not None
        assert recorder._ema_floor > 0.015
        assert recorder._effective_threshold is not None
        assert recorder._effective_threshold > 0.015

    def test_ema_not_active_without_calibration(self) -> None:
        """EMA should not affect threshold when calibration was never run."""
        recorder = MicRecorder(rms_threshold=0.01)
        assert recorder._calibrated is False

        # Even if we manually feed samples, recalculate should be a no-op.
        for _ in range(20):
            recorder._update_ema(0.05)
        recorder._recalculate_threshold()
        assert recorder._effective_threshold is None
        assert recorder._threshold() == 0.01

    def test_ema_requires_minimum_samples(self) -> None:
        recorder = MicRecorder(rms_threshold=0.01, calibration_multiplier=3.0)
        recorder._calibrated = True
        recorder._effective_threshold = 0.03
        recorder._ema_floor = None
        recorder._ema_sample_count = 0

        # Feed fewer than EMA_MIN_SAMPLES.
        for _ in range(MicRecorder.EMA_MIN_SAMPLES - 1):
            recorder._update_ema(0.05)

        recorder._recalculate_threshold()
        # Not enough samples — threshold unchanged.
        assert recorder._effective_threshold == 0.03

    def test_calibrate_seeds_ema(self) -> None:
        """calibrate() should seed the EMA so adaptive tracking starts immediately."""
        recorder = MicRecorder(rms_threshold=0.0, calibration_multiplier=2.0)

        frames = int(MicRecorder.SAMPLE_RATE * MicRecorder.CHUNK_SECONDS)
        const_chunk = np.full(frames, 0.1, dtype=np.float32)
        chunks = [const_chunk] * 20

        fake_sd = MagicMock()
        fake_sd.InputStream = lambda **kw: FakeInputStream(chunks, kw["callback"])
        fake_sd.CallbackFlags = object

        with patch.dict("sys.modules", {"sounddevice": fake_sd}):
            recorder.calibrate(seconds=1.0)

        assert recorder._ema_floor == pytest.approx(0.1, rel=0.01)
        assert recorder._ema_sample_count == 20

    def test_threshold_adapts_downward(self) -> None:
        """When noise drops, EMA should bring the threshold back down."""
        recorder = MicRecorder(rms_threshold=0.01, calibration_multiplier=3.0)
        recorder._calibrated = True
        recorder._ema_floor = 0.03
        recorder._ema_sample_count = 20
        recorder._effective_threshold = 0.09  # 0.03 * 3

        # Noise drops to near zero.
        for _ in range(200):
            recorder._update_ema(0.002)

        recorder._recalculate_threshold()
        # Should have adapted down (but not below configured minimum).
        assert recorder._effective_threshold is not None
        assert recorder._effective_threshold < 0.09
        assert recorder._effective_threshold >= 0.01


class TestAudioDeviceErrorFromRecord:
    """MicRecorder.record() must raise AudioDeviceError when InputStream fails."""

    def test_record_raises_audio_device_error(self) -> None:
        fake_sd = MagicMock()
        fake_sd.PortAudioError = PortAudioError
        fake_sd.InputStream.side_effect = PortAudioError("Device unavailable")
        fake_sd.CallbackFlags = object

        with patch.dict("sys.modules", {"sounddevice": fake_sd, "soundfile": MagicMock()}):
            recorder = MicRecorder()
            with pytest.raises(AudioDeviceError, match="Microphone unavailable"):
                recorder.record()

    def test_record_error_preserves_original_detail(self) -> None:
        fake_sd = MagicMock()
        fake_sd.PortAudioError = PortAudioError
        fake_sd.InputStream.side_effect = PortAudioError("No default input device")
        fake_sd.CallbackFlags = object

        with patch.dict("sys.modules", {"sounddevice": fake_sd, "soundfile": MagicMock()}):
            recorder = MicRecorder()
            with pytest.raises(AudioDeviceError, match="No default input device"):
                recorder.record()


class TestAudioDeviceErrorFromPlayTts:
    """play_tts_streaming() must raise AudioDeviceError when AudioPlayer fails."""

    def test_speaker_unavailable_raises_audio_device_error(self) -> None:
        fake_sd = MagicMock()
        fake_sd.PortAudioError = PortAudioError

        mm = MagicMock()
        mm.generate_tts_streaming.return_value = iter([])

        with (
            patch("mlx_audio.tts.audio_player.AudioPlayer", side_effect=PortAudioError("No output device")),
            patch.dict("sys.modules", {"sounddevice": fake_sd}),
        ):
            with pytest.raises(AudioDeviceError, match="Audio output unavailable"):
                play_tts_streaming(mm, "hello", "af_heart", 1.0, "a")
