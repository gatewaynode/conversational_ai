"""mic_recorder_from_settings — Settings → MicRecorder kwargs passthrough.

Split from test_cli_audio_io.py. Tests the thin factory helper that wires
MicSettings values plus an optional calibrate override into a MicRecorder
instance.
"""

from __future__ import annotations

from src.cli.audio_io import mic_recorder_from_settings
from src.config import MicSettings


class TestMicRecorderFromSettings:
    """mic_recorder_from_settings wires MicSettings → MicRecorder kwargs."""

    def test_settings_passthrough(self) -> None:
        s = MicSettings(
            rms_threshold=0.03,
            silence_seconds=2.0,
            min_speech_seconds=0.2,
            calibrate_noise=True,
            calibration_seconds=1.5,
            calibration_multiplier=4.0,
        )
        r = mic_recorder_from_settings(s)
        assert r.rms_threshold == 0.03
        assert r.silence_seconds == 2.0
        assert r.min_speech_seconds == 0.2
        assert r.calibrate_noise is True
        assert r.calibration_seconds == 1.5
        assert r.calibration_multiplier == 4.0

    def test_calibrate_override_forces_on(self) -> None:
        s = MicSettings(calibrate_noise=False)
        r = mic_recorder_from_settings(s, calibrate_override=True)
        assert r.calibrate_noise is True

    def test_calibrate_override_forces_off(self) -> None:
        s = MicSettings(calibrate_noise=True)
        r = mic_recorder_from_settings(s, calibrate_override=False)
        assert r.calibrate_noise is False

    def test_calibrate_override_none_respects_settings(self) -> None:
        s = MicSettings(calibrate_noise=True)
        r = mic_recorder_from_settings(s, calibrate_override=None)
        assert r.calibrate_noise is True
