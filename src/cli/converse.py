"""converse subcommand: voice bridge to Claude Code headless.

Three threads in one process:

- **Listener** (re-used `_listener_loop`): mic → STT → appends to the human
  file.
- **Bridge** (`TextFileHandler` + `_make_bridge_callback`): tails the human
  file and writes to the agent file. 3.0a echoes verbatim; 3.0c wires
  `claude -p --resume <id>` in its place.
- **Watcher** (`TextFileHandler` + `_make_speak_callback`): tails the agent
  file and speaks new content via TTS.

Shutdown via Ctrl+C sets the shared event; all three threads exit cleanly.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

import click

from src.cli import CliContext
from src.cli.audio_io import AudioDeviceError
from src.cli.dialogue import _listener_loop, _make_speak_callback
from src.cli.watch import TextFileHandler

logger = logging.getLogger(__name__)

_DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "conversational_ai" / "converse"


def _make_bridge_callback(
    agent_path: Path,
    shutdown: threading.Event,
) -> Callable[[str], None]:
    """Build the bridge on_text callback.

    3.0a: echoes each transcribed line straight to the agent file. 3.0c
    replaces this with a `claude -p --resume <id>` subprocess call.
    """

    def _bridge(text: str) -> None:
        if shutdown.is_set():
            return
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            click.echo(f"[bridge] {line}", err=True)
            try:
                with agent_path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                logger.exception("Failed to append to agent file %s", agent_path)

    return _bridge


@click.command()
@click.option(
    "--human-file",
    default=None,
    type=click.Path(),
    help="File the listener appends transcriptions to (default: XDG state dir).",
)
@click.option(
    "--agent-file",
    default=None,
    type=click.Path(),
    help="File the bridge appends agent responses to (default: XDG state dir).",
)
@click.option(
    "--mic-threshold",
    type=float,
    default=None,
    help="Override RMS threshold for speech detection.",
)
@click.option(
    "--mic-silence",
    type=float,
    default=None,
    help="Override trailing silence (seconds) that ends an utterance.",
)
@click.option(
    "--mic-min-speech",
    type=float,
    default=None,
    help="Override minimum sustained speech (seconds) required to latch.",
)
@click.option(
    "--calibrate-noise/--no-calibrate-noise",
    "calibrate_noise",
    default=None,
    help="Sample room tone at startup to set the effective threshold.",
)
@click.pass_obj
def converse(
    ctx_obj: CliContext,
    human_file: str | None,
    agent_file: str | None,
    mic_threshold: float | None,
    mic_silence: float | None,
    mic_min_speech: float | None,
    calibrate_noise: bool | None,
) -> None:
    """Voice-converse with Claude Code (3.0a skeleton: echo-back only).

    Three threads wire mic → STT → bridge → TTS. In this 3.0a skeleton the
    bridge echoes each transcribed line straight to the agent file, so TTS
    speaks your own words back. This proves the pipeline before `claude -p`
    is wired in (phase 3.0c). Press Ctrl+C to stop.
    """
    human_path = Path(human_file).expanduser() if human_file else _DEFAULT_STATE_DIR / "human.txt"
    agent_path = Path(agent_file).expanduser() if agent_file else _DEFAULT_STATE_DIR / "agent.txt"
    human_path.parent.mkdir(parents=True, exist_ok=True)
    agent_path.parent.mkdir(parents=True, exist_ok=True)
    human_path.touch(exist_ok=True)
    agent_path.touch(exist_ok=True)

    inference_lock = threading.Lock()
    shutdown = threading.Event()
    tts_active = threading.Event()

    mic = ctx_obj.settings.mic.model_copy(
        update={
            k: v
            for k, v in {
                "rms_threshold": mic_threshold,
                "silence_seconds": mic_silence,
                "min_speech_seconds": mic_min_speech,
            }.items()
            if v is not None
        }
    )
    recorder = ctx_obj.recorder_factory(mic, calibrate_override=calibrate_noise)
    try:
        if recorder.calibrate_noise:
            recorder.calibrate()
    except AudioDeviceError as exc:
        raise click.ClickException(str(exc)) from exc

    speak_cb = _make_speak_callback(
        ctx_obj,
        inference_lock,
        shutdown,
        barge_event=None,
        tts_active=tts_active,
    )
    agent_handler = TextFileHandler(agent_path, speak_cb)

    bridge_cb = _make_bridge_callback(agent_path, shutdown)
    human_handler = TextFileHandler(human_path, bridge_cb)

    listener_thread = threading.Thread(
        target=_listener_loop,
        args=(
            human_path,
            ctx_obj,
            inference_lock,
            shutdown,
            None,
            tts_active,
            recorder,
            None,
        ),
        daemon=True,
        name="converse-listener",
    )
    listener_thread.start()

    click.echo(
        f"Converse active (3.0a echo-back) — "
        f"human→{human_path}, agent→{agent_path}. Ctrl+C to stop.",
        err=True,
    )

    try:
        while listener_thread.is_alive() and not shutdown.is_set():
            listener_thread.join(timeout=1)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown.set()
        human_handler.stop()
        agent_handler.stop()
        listener_thread.join(timeout=5)
        click.echo("Stopped.", err=True)
