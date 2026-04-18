"""Tests for src/cli/wake_word.py — WakeWordGate behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.cli.wake_word import WakeWordGate


def make_gate(
    word: str = "computer",
    *,
    include_trigger: bool = False,
    timeout_seconds: float = 30.0,
    alert_sound: bool = True,
    clock_values: list[float] | None = None,
) -> tuple[WakeWordGate, MagicMock, MagicMock]:
    """Build a gate wired to a scripted clock and mock chime/echo."""
    chime = MagicMock()
    echo = MagicMock()
    if clock_values is None:
        clock = lambda: 0.0  # noqa: E731 — simple constant clock for match-only tests
    else:
        ticks = iter(clock_values)
        clock = lambda: next(ticks)  # noqa: E731
    gate = WakeWordGate(
        word,
        include_trigger=include_trigger,
        timeout_seconds=timeout_seconds,
        alert_sound=alert_sound,
        clock=clock,
        chime=chime,
        echo=echo,
    )
    return gate, chime, echo


class TestTriggerMatching:
    def test_comma_trigger_strips_word(self) -> None:
        gate, _, _ = make_gate()
        assert gate.filter("Computer, hello") == "hello"

    def test_period_trigger_with_empty_rest_returns_none(self) -> None:
        gate, _, _ = make_gate()
        assert gate.filter("Computer.") is None
        assert gate.armed is False

    def test_bang_question_combo_absorbed(self) -> None:
        gate, _, _ = make_gate()
        assert gate.filter("Computer?!") is None
        assert gate.armed is False

    def test_case_insensitive(self) -> None:
        gate, _, _ = make_gate()
        assert gate.filter("COMPUTER, do X") == "do X"

    def test_rejects_trigger_used_in_sentence(self) -> None:
        gate, _, _ = make_gate()
        assert gate.filter("Computer science is cool") is None
        assert gate.armed is True

    def test_rejects_trigger_not_at_start(self) -> None:
        gate, _, _ = make_gate()
        assert gate.filter("what a great computer") is None
        assert gate.armed is True

    def test_rejects_without_punctuation(self) -> None:
        gate, _, _ = make_gate()
        assert gate.filter("Computer hello") is None
        assert gate.armed is True


class TestIncludeTrigger:
    def test_include_trigger_preserves_full_line(self) -> None:
        gate, _, _ = make_gate(include_trigger=True)
        assert gate.filter("Computer, hello") == "Computer, hello"

    def test_include_trigger_preserves_period_only(self) -> None:
        gate, _, _ = make_gate(include_trigger=True)
        assert gate.filter("Computer.") == "Computer."
        assert gate.armed is False


class TestOpenWindow:
    def test_plain_text_passes_after_trigger(self) -> None:
        gate, _, _ = make_gate(clock_values=[0.0, 5.0])
        assert gate.filter("Computer, play music") == "play music"
        assert gate.filter("what is the weather") == "what is the weather"


class TestTimeoutRearm:
    def test_utterance_past_timeout_forces_retrigger(self) -> None:
        gate, _, _ = make_gate(
            timeout_seconds=30.0,
            clock_values=[0.0, 31.0],
        )
        assert gate.filter("Computer, hello") == "hello"
        # Second utterance arrives after timeout — must re-trigger.
        assert gate.filter("what time is it") is None
        assert gate.armed is True

    def test_sliding_window_extends_on_each_pass(self) -> None:
        gate, _, _ = make_gate(
            timeout_seconds=30.0,
            clock_values=[0.0, 25.0, 45.0],
        )
        assert gate.filter("Computer, start") == "start"
        # t=25: within 30s of trigger @ t=0 → passes, last_pass = 25.
        assert gate.filter("continue one") == "continue one"
        # t=45: 20s since last pass — still within window.
        assert gate.filter("continue two") == "continue two"


class TestAlertFeedback:
    def test_chime_fires_on_trigger_when_alert_on(self) -> None:
        gate, chime, echo = make_gate(alert_sound=True)
        gate.filter("Computer, hello")
        chime.assert_called_once()
        echo.assert_called_once()

    def test_chime_suppressed_when_alert_off(self) -> None:
        gate, chime, echo = make_gate(alert_sound=False)
        gate.filter("Computer, hello")
        chime.assert_not_called()
        echo.assert_called_once()

    def test_no_chime_on_non_trigger(self) -> None:
        gate, chime, echo = make_gate()
        gate.filter("Computer science is cool")
        chime.assert_not_called()
        echo.assert_not_called()

    def test_no_chime_on_subsequent_utterances(self) -> None:
        gate, chime, echo = make_gate(clock_values=[0.0, 5.0])
        gate.filter("Computer, hello")
        gate.filter("do the thing")
        chime.assert_called_once()
        echo.assert_called_once()

    def test_chime_failure_does_not_break_filter(self) -> None:
        gate, chime, _ = make_gate()
        chime.side_effect = RuntimeError("no audio device")
        # Should not raise.
        assert gate.filter("Computer, hello") == "hello"


class TestValidation:
    def test_empty_word_rejected(self) -> None:
        with pytest.raises(ValueError):
            WakeWordGate("")

    def test_whitespace_word_rejected(self) -> None:
        with pytest.raises(ValueError):
            WakeWordGate("   ")
