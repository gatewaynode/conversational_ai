"""CLI audio primitives: streaming TTS playback and microphone recording."""

from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from src.models import ModelManager

logger = logging.getLogger(__name__)

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
    from mlx_audio.tts.audio_player import AudioPlayer

    player = AudioPlayer(sample_rate=24_000)
    cancelled = False
    try:
        for chunk in mm.generate_tts_streaming(text, voice, speed, lang_code):
            if cancel is not None and cancel.is_set():
                cancelled = True
                logger.info("TTS playback cancelled (barge-in)")
                break
            player.queue_audio(chunk.audio)
    finally:
        if cancelled:
            player.flush()
        else:
            player.stop()


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
    """

    SAMPLE_RATE: int = 16_000
    CHANNELS: int = 1
    DTYPE: str = "float32"
    RMS_THRESHOLD: float = 0.01   # energy above this → speech
    SILENCE_SECONDS: float = 1.5  # consecutive silence to end utterance
    CHUNK_SECONDS: float = 0.05   # callback block size

    def record(self, on_speech_start: threading.Event | None = None) -> Path:
        """Block until one utterance is captured. Returns a temp WAV path.

        If `on_speech_start` is provided, it is set on the rising edge —
        the first chunk whose RMS crosses the threshold — and cleared
        before this method returns. This is the barge-in signal consumed
        by `play_tts_streaming(cancel=…)`.
        """
        import sounddevice as sd
        import soundfile as sf

        frames_per_chunk = int(self.SAMPLE_RATE * self.CHUNK_SECONDS)
        silence_chunks_needed = int(self.SILENCE_SECONDS / self.CHUNK_SECONDS)

        audio_chunks: list[np.ndarray] = []
        speech_detected = threading.Event()
        stop_event = threading.Event()
        silence_count = [0]  # mutable counter accessible inside callback

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

            if rms > self.RMS_THRESHOLD:
                if not speech_detected.is_set():
                    speech_detected.set()
                    if on_speech_start is not None:
                        on_speech_start.set()
                silence_count[0] = 0
                audio_chunks.append(chunk)
            elif speech_detected.is_set():
                # Record silence after speech so we capture trailing sounds
                audio_chunks.append(chunk)
                silence_count[0] += 1
                if silence_count[0] >= silence_chunks_needed:
                    stop_event.set()

        logger.info("Listening… (speak now)")
        with sd.InputStream(
            samplerate=self.SAMPLE_RATE,
            channels=self.CHANNELS,
            dtype=self.DTYPE,
            blocksize=frames_per_chunk,
            callback=_callback,
        ):
            stop_event.wait()

        # Clear the barge-in signal so it doesn't leak into the next turn.
        if on_speech_start is not None:
            on_speech_start.clear()

        audio = np.concatenate(audio_chunks) if audio_chunks else np.zeros(1, dtype=np.float32)

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()

        sf.write(str(tmp_path), audio, self.SAMPLE_RATE)
        logger.info("Recorded %d samples to %s", len(audio), tmp_path)
        return tmp_path
