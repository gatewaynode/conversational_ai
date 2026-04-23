"""converse subcommand: voice bridge to Claude Code headless.

Three threads in one process:

- **Listener** (re-used `_listener_loop`): mic → STT → appends to the human
  file.
- **Bridge** (`TextFileHandler` + `_make_bridge_callback`): tails the human
  file and invokes `claude -p --output-format json [--resume <id>]` per
  line, then appends the `result` field to the agent file.
- **Watcher** (`TextFileHandler` + `_make_speak_callback`): tails the agent
  file and speaks new content via TTS.

Shutdown via Ctrl+C sets the shared event; all three threads exit cleanly.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
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
_SESSION_STATE_FILE = Path.home() / ".local" / "state" / "conversational_ai" / "session"
_CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"


def _cwd_slug() -> str:
    """Return Claude Code's project-dir slug for the current working directory.

    Claude Code stores transcripts at `~/.claude/projects/<slug>/<id>.jsonl`
    where `<slug>` is the absolute cwd with `/` and `_` replaced by `-`.
    """
    return str(Path.cwd().resolve()).replace("/", "-").replace("_", "-")


def _read_last_session_id() -> str | None:
    """Return the last persisted session id, or None if absent/empty."""
    try:
        text = _SESSION_STATE_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError:
        logger.exception("Failed to read session state %s", _SESSION_STATE_FILE)
        return None
    return text or None


def _write_last_session_id(session_id: str) -> None:
    """Persist `session_id` to the state file (best-effort)."""
    try:
        _SESSION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SESSION_STATE_FILE.write_text(session_id + "\n", encoding="utf-8")
    except OSError:
        logger.exception("Failed to write session state %s", _SESSION_STATE_FILE)


def _probe_session(session_id: str) -> None:
    """Raise ClickException if `session_id` has no transcript in this cwd."""
    transcript = _CLAUDE_PROJECTS / _cwd_slug() / f"{session_id}.jsonl"
    if not transcript.is_file():
        raise click.ClickException(
            f"Session {session_id!r} not found at {transcript}. "
            "Run `claude` once in this directory to create it, or pass a valid id."
        )


def _resolve_session_id(session_id: str | None, resume: bool) -> str | None:
    """Resolve the requested session id per the 3.0b policy.

    - Both set → UsageError (mutex).
    - `--session-id X` → X.
    - `--resume` → last persisted id; UsageError if none.
    - Neither → None (fresh session; 3.0c will capture the id from `claude`).
    """
    if session_id and resume:
        raise click.UsageError("--session-id and --resume are mutually exclusive.")
    if session_id:
        return session_id
    if resume:
        last = _read_last_session_id()
        if not last:
            raise click.UsageError(
                f"--resume requested but no prior session at {_SESSION_STATE_FILE}. "
                "Pass --session-id explicitly or omit both flags to start fresh."
            )
        return last
    return None


def _make_bridge_callback(
    agent_path: Path,
    shutdown: threading.Event,
    session_id: str | None,
    runner: Callable[[str, str | None], subprocess.CompletedProcess[str]],
) -> Callable[[str], None]:
    """Build the bridge on_text callback.

    Each transcribed line is sent to `claude -p` via `runner`; the JSON
    `result` field is appended to the agent file and the returned
    `session_id` is captured so the fresh-session case threads an id
    across subsequent turns. Robust error handling (timeouts, nonzero
    exits, missing binary mid-run) is deferred to 3.0d — here we log and
    continue so the bridge thread survives.
    """
    current_session_id = session_id

    def _bridge(text: str) -> None:
        nonlocal current_session_id
        if shutdown.is_set():
            return
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            tag = f"[bridge:{current_session_id}]" if current_session_id else "[bridge]"
            click.echo(f"{tag} {line}", err=True)

            try:
                proc = runner(line, current_session_id)
            except Exception:
                logger.exception("claude runner raised on prompt %r", line)
                continue

            if proc.returncode != 0:
                logger.warning(
                    "claude exited %d: %s",
                    proc.returncode,
                    (proc.stderr or "")[:500],
                )
                continue

            try:
                payload = json.loads(proc.stdout or "")
            except json.JSONDecodeError:
                logger.warning(
                    "claude stdout was not JSON: %s",
                    (proc.stdout or "")[:500],
                )
                continue

            if payload.get("is_error"):
                logger.warning(
                    "claude reported is_error (subtype=%r stop_reason=%r "
                    "num_turns=%r permission_denials=%r result=%r)",
                    payload.get("subtype"),
                    payload.get("stop_reason"),
                    payload.get("num_turns"),
                    payload.get("permission_denials"),
                    payload.get("result"),
                )
                continue

            result = (payload.get("result") or "").strip()
            if not result:
                continue

            new_session_id = payload.get("session_id")
            if new_session_id and new_session_id != current_session_id:
                current_session_id = new_session_id
                _write_last_session_id(current_session_id)

            try:
                with agent_path.open("a", encoding="utf-8") as f:
                    f.write(result + "\n")
            except OSError:
                logger.exception("Failed to append to agent file %s", agent_path)

    return _bridge


@click.command()
@click.option(
    "--session-id",
    "session_id",
    default=None,
    metavar="UUID",
    help="Attach to an existing Claude Code session by id (validated at startup).",
)
@click.option(
    "--resume",
    is_flag=True,
    default=False,
    help="Resume the last persisted session id. Mutually exclusive with --session-id.",
)
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
    session_id: str | None,
    resume: bool,
    human_file: str | None,
    agent_file: str | None,
    mic_threshold: float | None,
    mic_silence: float | None,
    mic_min_speech: float | None,
    calibrate_noise: bool | None,
) -> None:
    """Voice-converse with Claude Code.

    Three threads wire mic → STT → `claude -p` → TTS. Pass
    `--session-id <uuid>` to attach to an existing Claude Code session,
    `--resume` to pick up the last persisted id, or neither for a fresh
    session (the id returned by the first turn is persisted automatically).
    Claude Code must run from this cwd so transcripts resolve under
    ~/.claude/projects/<cwd-slug>/. Press Ctrl+C to stop.
    """
    if shutil.which("claude") is None:
        raise click.ClickException(
            "`claude` CLI not found on PATH. Install Claude Code "
            "(https://claude.com/claude-code) before running `cai converse`."
        )

    resolved_session_id = _resolve_session_id(session_id, resume)
    if resolved_session_id is not None:
        _probe_session(resolved_session_id)
        _write_last_session_id(resolved_session_id)

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

    bridge_cb = _make_bridge_callback(
        agent_path,
        shutdown,
        resolved_session_id,
        ctx_obj.claude_runner_factory,
    )
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

    session_banner = (
        f"session={resolved_session_id}" if resolved_session_id else "session=fresh"
    )
    click.echo(
        f"Converse active ({session_banner}) — "
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
