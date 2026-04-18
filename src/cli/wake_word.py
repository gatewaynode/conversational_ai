"""Wake-word gate for text-sink filtering.

Sits downstream of Whisper STT on both `cai listen` and `cai dialogue`
listener paths. Matches a trigger word followed by punctuation or
end-of-utterance, opens a timed window during which subsequent utterances
pass through unchanged, re-arms on silence past the timeout.

No separate wake-word model — reuses the already-loaded Whisper output.
"""

from __future__ import annotations

import re
import time
from typing import Callable

import click

from src.config import WakeWordSettings


def _play_chime(sample_rate: int = 24_000) -> None:
    """Two-tone sine burst (880 Hz → 1320 Hz) with edge fade, ~160 ms total.

    Played via `sd.play(..., blocking=False)` so it doesn't stall the
    listener thread. Imports are local so tests can run without a working
    audio stack.
    """
    import numpy as np
    import sounddevice as sd

    dur = 0.08
    t = np.linspace(0, dur, int(sample_rate * dur), endpoint=False)
    fade = max(int(len(t) * 0.1), 1)
    env = np.ones_like(t)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    tone1 = np.sin(2 * np.pi * 880 * t) * 0.2 * env
    tone2 = np.sin(2 * np.pi * 1320 * t) * 0.2 * env
    chime = np.concatenate([tone1, tone2]).astype(np.float32)
    sd.play(chime, sample_rate, blocking=False)


def _default_echo(message: str) -> None:
    click.echo(message, err=True)


class WakeWordGate:
    """Stateful filter: drop text until trigger, pass through during open window.

    The trigger must appear at the start of an utterance followed by
    punctuation or end-of-utterance — "Computer, hello" matches; "Computer
    science is cool" does not. Relies on Whisper inserting punctuation on
    pauses.
    """

    def __init__(
        self,
        word: str,
        *,
        include_trigger: bool = False,
        timeout_seconds: float = 30.0,
        alert_sound: bool = True,
        clock: Callable[[], float] = time.monotonic,
        chime: Callable[[], None] | None = None,
        echo: Callable[[str], None] | None = None,
    ) -> None:
        if not word or not word.strip():
            raise ValueError("wake word must be a non-empty string")
        self._word = word.strip()
        self._include_trigger = include_trigger
        self._timeout_seconds = float(timeout_seconds)
        self._alert_sound = alert_sound
        self._clock = clock
        self._chime = chime if chime is not None else _play_chime
        self._echo = echo if echo is not None else _default_echo
        self._pattern = re.compile(
            rf"^\s*({re.escape(self._word)})(?:[.,!?;:]+|$)\s*(.*)$",
            re.IGNORECASE | re.DOTALL,
        )
        self._armed: bool = True
        self._last_pass_at: float | None = None

    @property
    def armed(self) -> bool:
        return self._armed

    def filter(self, text: str) -> str | None:
        """Filter an STT line.

        Returns the (possibly-stripped) text to emit, or None to drop it.
        """
        if self._armed:
            match = self._pattern.match(text)
            if match is None:
                return None
            self._on_trigger()
            rest = match.group(2).strip()
            emitted = text.strip() if self._include_trigger else rest
            return emitted or None

        now = self._clock()
        if self._last_pass_at is not None and (now - self._last_pass_at) > self._timeout_seconds:
            self._armed = True
            self._last_pass_at = None
            return self.filter(text)

        self._last_pass_at = now
        stripped = text.strip()
        return stripped or None

    def _on_trigger(self) -> None:
        self._armed = False
        self._last_pass_at = self._clock()
        self._echo(f"[wake] {self._word!r} heard — listening")
        if self._alert_sound:
            try:
                self._chime()
            except Exception:
                pass


def build_wake_gate(
    base: WakeWordSettings,
    *,
    word_override: str | None = None,
    disable: bool = False,
    timeout_override: float | None = None,
    include_trigger_override: bool | None = None,
    alert_sound_override: bool | None = None,
) -> WakeWordGate | None:
    """Merge CLI overrides into `WakeWordSettings` and build a gate (or None).

    Returns None when the merged settings disable wake-word gating. CLI flags
    win over config:

    - ``--wake-word WORD`` forces ``enabled=True`` and sets the word.
    - ``--no-wake-word`` forces ``enabled=False`` regardless of config.
    - Remaining overrides only take effect when enabled.
    """
    if disable:
        return None

    enabled = base.enabled
    word = base.word
    if word_override is not None:
        word = word_override
        enabled = True

    if not enabled:
        return None

    return WakeWordGate(
        word,
        include_trigger=(
            include_trigger_override
            if include_trigger_override is not None
            else base.include_trigger
        ),
        timeout_seconds=(
            timeout_override if timeout_override is not None else base.timeout_seconds
        ),
        alert_sound=(
            alert_sound_override if alert_sound_override is not None else base.alert_sound
        ),
    )
