"""CLI audio primitives: streaming TTS playback and microphone recording."""

from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from src.config import MicSettings
    from src.models import ModelManager


def mic_recorder_from_settings(
    settings: MicSettings,
    *,
    calibrate_override: bool | None = None,
) -> MicRecorder:
    """Build a MicRecorder from a MicSettings block, optionally forcing
    calibration on/off regardless of the config value (used by CLI flags)."""
    calibrate = calibrate_override if calibrate_override is not None else settings.calibrate_noise
    return MicRecorder(
        rms_threshold=settings.rms_threshold,
        silence_seconds=settings.silence_seconds,
        min_speech_seconds=settings.min_speech_seconds,
        calibrate_noise=calibrate,
        calibration_seconds=settings.calibration_seconds,
        calibration_multiplier=settings.calibration_multiplier,
    )


logger = logging.getLogger(__name__)


class AudioDeviceError(Exception):
    """Human-readable wrapper for sounddevice.PortAudioError."""


def _format_device_error(err: Exception, device_type: str) -> str:
    detail = str(err).split("\n", 1)[0]
    if device_type == "input":
        return (
            f"Microphone unavailable — check System Settings > "
            f"Privacy & Security > Microphone. ({detail})"
        )
    return f"Audio output unavailable — check that a speaker or headphone is connected. ({detail})"


# ---------------------------------------------------------------------------
# TTS playback
# ---------------------------------------------------------------------------


def play_tts_streaming(
    mm: ModelManager,
    text: str,
    voice: str,
    speed: float,
    lang_code: str,
    *,
    cancel: threading.Event | None = None,
) -> None:
    """Generate TTS audio and play it through the default speakers.

    Feeds chunks to AudioPlayer as they arrive so playback starts before
    the full text is synthesised. Blocks until playback completes.

    If `cancel` is provided and set mid-stream (barge-in), playback is
    discarded immediately via `AudioPlayer.flush()` instead of drained —
    the speaker goes quiet right away so the listener's reply isn't
    stepped on.
    """
    import sounddevice as sd
    from mlx_audio.tts.audio_player import AudioPlayer

    try:
        player = AudioPlayer(sample_rate=24_000)
    except sd.PortAudioError as exc:
        raise AudioDeviceError(_format_device_error(exc, "output")) from exc
    cancelled = False
    try:
        for chunk in mm.generate_tts_streaming(text, voice, speed, lang_code):
            if cancel is not None and cancel.is_set():
                cancelled = True
                logger.info("TTS playback cancelled (barge-in)")
                break
            player.queue_audio(chunk.audio)
        # AudioPlayer only calls start_stream() from inside queue_audio(), and
        # only once buffered_samples >= arrival_rate * 1.5s. For short clips
        # where MLX generates faster than realtime, the threshold can climb
        # above the total sample count before the generator exhausts — so
        # start_stream() never fires and nothing plays. Kick it manually.
        if not cancelled and not player.playing and player.buffered_samples() > 0:
            player.start_stream()
    finally:
        if cancelled:
            player.flush()
        else:
            player.stop()
        # AudioPlayer.stop() skips stop_stream() when playing=False, which is
        # the common natural-completion path (the callback clears `playing`
        # the moment the buffer empties). Close the stream unconditionally so
        # the sd.OutputStream is freed on every exit path.
        player.stop_stream()


# ---------------------------------------------------------------------------
# Microphone recording with VAD
# ---------------------------------------------------------------------------


class MicRecorder:
    """Record a single utterance from the microphone using RMS-based VAD.

    Usage::

        recorder = MicRecorder()
        path = recorder.record()   # blocks until speech + silence detected
        # ... use path ...
        path.unlink()              # caller is responsible for cleanup

    Tunables (all ``__init__`` kwargs, default to the class-level constants
    so the zero-arg constructor still works):

    - ``rms_threshold`` — minimum RMS energy for a chunk to count as speech.
    - ``silence_seconds`` — trailing silence that ends an utterance.
    - ``min_speech_seconds`` — sustained above-threshold chunks required
      before the recorder latches onto the utterance. Filters out single
      loud transients (keyboard clacks, door slams).
    - ``calibrate_noise`` — if True, sample room tone on first ``record()``
      (or explicit ``calibrate()`` call) and raise the effective threshold
      to ``max(rms_threshold, measured_floor * calibration_multiplier)``.
    """

    SAMPLE_RATE: int = 16_000
    CHANNELS: int = 1
    DTYPE: str = "float32"
    RMS_THRESHOLD: float = 0.01
    SILENCE_SECONDS: float = 1.5
    CHUNK_SECONDS: float = 0.05
    MIN_SPEECH_SECONDS: float = 0.15
    CALIBRATION_SECONDS: float = 1.0
    CALIBRATION_MULTIPLIER: float = 3.0
    PRE_SPEECH_SECONDS: float = 0.15
    EMA_ALPHA: float = 0.05
    EMA_MIN_SAMPLES: int = 10

    def __init__(
        self,
        *,
        rms_threshold: float | None = None,
        silence_seconds: float | None = None,
        min_speech_seconds: float | None = None,
        calibrate_noise: bool = False,
        calibration_seconds: float | None = None,
        calibration_multiplier: float | None = None,
    ) -> None:
        self.rms_threshold = rms_threshold if rms_threshold is not None else self.RMS_THRESHOLD
        self.silence_seconds = (
            silence_seconds if silence_seconds is not None else self.SILENCE_SECONDS
        )
        self.min_speech_seconds = (
            min_speech_seconds if min_speech_seconds is not None else self.MIN_SPEECH_SECONDS
        )
        self.calibrate_noise = calibrate_noise
        self.calibration_seconds = (
            calibration_seconds if calibration_seconds is not None else self.CALIBRATION_SECONDS
        )
        self.calibration_multiplier = (
            calibration_multiplier
            if calibration_multiplier is not None
            else self.CALIBRATION_MULTIPLIER
        )
        self._effective_threshold: float | None = None
        self._calibrated: bool = False
        self._ema_floor: float | None = None
        self._ema_sample_count: int = 0

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def calibrate(self, seconds: float | None = None) -> float:
        """Sample room tone and set the effective RMS threshold.

        Opens a short ``InputStream``, averages the per-chunk RMS over
        ``seconds`` of audio, and sets ``self._effective_threshold`` to
        ``max(self.rms_threshold, measured_floor * calibration_multiplier)``.
        Returns the measured floor so callers can log it alongside the
        effective threshold.

        Safe to call multiple times; each call re-samples.
        """
        import sounddevice as sd

        duration = seconds if seconds is not None else self.calibration_seconds
        frames_per_chunk = int(self.SAMPLE_RATE * self.CHUNK_SECONDS)
        total_chunks_target = max(1, int(duration / self.CHUNK_SECONDS))

        rms_samples: list[float] = []
        done = threading.Event()

        def _callback(
            indata: np.ndarray,
            frames: int,
            time_info: object,
            status: sd.CallbackFlags,
        ) -> None:
            if status:
                logger.debug("sounddevice status during calibration: %s", status)
            chunk = indata[:, 0]
            rms_samples.append(float(np.sqrt(np.mean(chunk**2))))
            if len(rms_samples) >= total_chunks_target:
                done.set()

        logger.info("Calibrating noise floor (%.1fs of room tone)…", duration)
        try:
            with sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                dtype=self.DTYPE,
                blocksize=frames_per_chunk,
                callback=_callback,
            ):
                done.wait(timeout=duration + 2.0)
        except sd.PortAudioError as exc:
            raise AudioDeviceError(_format_device_error(exc, "input")) from exc

        measured_floor = float(np.mean(rms_samples)) if rms_samples else 0.0
        effective = max(self.rms_threshold, measured_floor * self.calibration_multiplier)
        self._effective_threshold = effective
        self._calibrated = True
        self._ema_floor = measured_floor
        self._ema_sample_count = len(rms_samples)
        logger.info(
            "Noise floor measured=%.4f, configured=%.4f, effective=%.4f",
            measured_floor,
            self.rms_threshold,
            effective,
        )
        return measured_floor

    def _threshold(self) -> float:
        """Return the threshold currently in force (calibrated or configured)."""
        if self._effective_threshold is not None:
            return self._effective_threshold
        return self.rms_threshold

    def _update_ema(self, rms: float) -> None:
        """Feed a silence-chunk RMS into the exponential moving average."""
        if self._ema_floor is None:
            self._ema_floor = rms
        else:
            self._ema_floor += self.EMA_ALPHA * (rms - self._ema_floor)
        self._ema_sample_count += 1

    def _recalculate_threshold(self) -> None:
        """Re-derive effective threshold from the running EMA noise floor."""
        if not self._calibrated:
            return
        if self._ema_floor is None or self._ema_sample_count < self.EMA_MIN_SAMPLES:
            return
        new_effective = max(self.rms_threshold, self._ema_floor * self.calibration_multiplier)
        if new_effective != self._effective_threshold:
            logger.debug(
                "Adaptive threshold: ema_floor=%.4f, effective %.4f → %.4f",
                self._ema_floor,
                self._effective_threshold or 0.0,
                new_effective,
            )
            self._effective_threshold = new_effective

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, on_speech_start: threading.Event | None = None) -> Path:
        """Block until one utterance is captured. Returns a temp WAV path.

        If ``calibrate_noise=True`` and no calibration has run yet, a
        one-shot calibration pass runs before recording starts. Callers
        that want to amortize calibration across many recordings (e.g.
        ``listen`` / ``dialogue``) should call ``calibrate()`` once at
        startup — subsequent ``record()`` calls will reuse the cached
        effective threshold.

        If ``on_speech_start`` is provided, it is set on the rising edge —
        the first chunk after the min-speech-duration gate latches — and
        cleared before this method returns. This is the barge-in signal
        consumed by ``play_tts_streaming(cancel=…)``.
        """
        import sounddevice as sd
        import soundfile as sf

        if self.calibrate_noise and not self._calibrated:
            self.calibrate()

        threshold = self._threshold()
        frames_per_chunk = int(self.SAMPLE_RATE * self.CHUNK_SECONDS)
        silence_chunks_needed = max(1, round(self.silence_seconds / self.CHUNK_SECONDS))
        min_speech_chunks = max(1, round(self.min_speech_seconds / self.CHUNK_SECONDS))
        pre_speech_chunks = max(1, round(self.PRE_SPEECH_SECONDS / self.CHUNK_SECONDS))
        ring_size = min_speech_chunks + pre_speech_chunks

        # Pre-latch ring: holds all recent chunks (loud and silent) so the
        # recording includes onset context when the gate latches.
        ring: list[np.ndarray] = []
        audio_chunks: list[np.ndarray] = []
        speech_detected = threading.Event()
        stop_event = threading.Event()
        silence_count = [0]
        above_streak = [0]

        def _callback(
            indata: np.ndarray,
            frames: int,
            time_info: object,
            status: sd.CallbackFlags,
        ) -> None:
            if status:
                logger.debug("sounddevice status: %s", status)

            chunk = indata[:, 0].copy()  # mono
            rms = float(np.sqrt(np.mean(chunk**2)))
            loud = rms > threshold

            if not speech_detected.is_set():
                ring.append(chunk)
                if len(ring) > ring_size:
                    ring.pop(0)
                if loud:
                    above_streak[0] += 1
                    if above_streak[0] >= min_speech_chunks:
                        speech_detected.set()
                        if on_speech_start is not None:
                            on_speech_start.set()
                        audio_chunks.extend(ring)
                        ring.clear()
                        silence_count[0] = 0
                else:
                    above_streak[0] = 0
                    if self._calibrated:
                        self._update_ema(rms)
                return

            # Post-latch: keep recording, tracking trailing silence.
            audio_chunks.append(chunk)
            if loud:
                silence_count[0] = 0
            else:
                silence_count[0] += 1
                if silence_count[0] >= silence_chunks_needed:
                    stop_event.set()

        logger.info("Listening… (speak now; threshold=%.4f)", threshold)
        try:
            with sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                dtype=self.DTYPE,
                blocksize=frames_per_chunk,
                callback=_callback,
            ):
                stop_event.wait()
        except sd.PortAudioError as exc:
            raise AudioDeviceError(_format_device_error(exc, "input")) from exc

        if on_speech_start is not None:
            on_speech_start.clear()

        if self._calibrated:
            self._recalculate_threshold()

        audio = np.concatenate(audio_chunks) if audio_chunks else np.zeros(1, dtype=np.float32)

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()

        sf.write(str(tmp_path), audio, self.SAMPLE_RATE)
        logger.info("Recorded %d samples to %s", len(audio), tmp_path)
        return tmp_path
