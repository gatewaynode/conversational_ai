"""Mic calibration tests — room-tone sampling and threshold derivation.

Split from test_cli_audio_io.py. Covers:
- Feature 1: calibrate() raises the effective threshold above measured floor
- B3: calibrate() surfaces AudioDeviceError when InputStream fails
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.cli.audio_io import AudioDeviceError, MicRecorder
from tests._audio_fakes import FakeInputStream, PortAudioError


class TestMicRecorderCalibration:
    """Feature 1: calibrate() raises the effective threshold above room tone."""

    def test_effective_threshold_is_max_of_configured_and_floor_times_mult(self) -> None:
        """calibrate() should choose max(configured, measured * multiplier)."""
        recorder = MicRecorder(
            rms_threshold=0.01,
            calibration_multiplier=3.0,
        )

        # Directly simulate: pretend calibrate was run and measured floor=0.02.
        # Then effective = max(0.01, 0.02 * 3.0) = 0.06.
        measured_floor = 0.02
        effective = max(recorder.rms_threshold, measured_floor * recorder.calibration_multiplier)
        recorder._effective_threshold = effective
        recorder._calibrated = True

        assert recorder._threshold() == 0.06

    def test_floor_below_configured_keeps_configured(self) -> None:
        """If measured floor * mult < configured, configured wins."""
        recorder = MicRecorder(rms_threshold=0.05, calibration_multiplier=3.0)
        measured_floor = 0.001  # 0.003 * 3 = 0.003 << 0.05
        effective = max(recorder.rms_threshold, measured_floor * recorder.calibration_multiplier)
        recorder._effective_threshold = effective
        recorder._calibrated = True

        assert recorder._threshold() == 0.05

    def test_threshold_defaults_to_configured_when_not_calibrated(self) -> None:
        recorder = MicRecorder(rms_threshold=0.02)
        assert recorder._threshold() == 0.02
        assert recorder._calibrated is False

    def test_calibrate_computes_mean_rms_over_samples(self) -> None:
        """The calibrate() method must average per-chunk RMS and set effective."""
        recorder = MicRecorder(
            rms_threshold=0.0,
            calibration_multiplier=2.0,
        )

        # Feed the fake stream chunks with known RMS: constant 0.1 → RMS = 0.1.
        frames = int(MicRecorder.SAMPLE_RATE * MicRecorder.CHUNK_SECONDS)
        const_chunk = np.full(frames, 0.1, dtype=np.float32)
        chunks = [const_chunk] * 20  # 1.0s of audio

        fake_sd = MagicMock()
        fake_sd.InputStream = lambda **kw: FakeInputStream(chunks, kw["callback"])
        fake_sd.CallbackFlags = object

        with patch.dict("sys.modules", {"sounddevice": fake_sd}):
            measured = recorder.calibrate(seconds=1.0)

        assert measured == pytest.approx(0.1, rel=0.01)
        # effective = max(0.0, 0.1 * 2.0) = 0.2
        assert recorder._threshold() == pytest.approx(0.2, rel=0.01)
        assert recorder._calibrated is True


class TestAudioDeviceErrorFromCalibrate:
    """MicRecorder.calibrate() must raise AudioDeviceError when InputStream fails."""

    def test_calibrate_raises_audio_device_error(self) -> None:
        fake_sd = MagicMock()
        fake_sd.PortAudioError = PortAudioError
        fake_sd.InputStream.side_effect = PortAudioError("Permission denied")
        fake_sd.CallbackFlags = object

        with patch.dict("sys.modules", {"sounddevice": fake_sd}):
            recorder = MicRecorder()
            with pytest.raises(AudioDeviceError, match="Microphone unavailable"):
                recorder.calibrate()
