"""install-skill / uninstall-skill subcommands: copy bundled skills into a Claude Code skills directory."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click

from src.cli import CliContext


_MODE_TO_DIR: dict[str, str] = {
    "voice-mode": "voice-mode",
    "dictation": "cai-dictation",
    "dialogue": "cai-dialogue",
    "audio-summary": "audio-summary",
}

_DEFAULT_TARGET = Path("~/.claude/skills").expanduser()


def _resolve_skills_source() -> Path:
    """Locate the bundled `skills/` directory.

    `skills/` lives at the project root in both layouts: the repo
    (`<repo>/skills/`) and the installed copy
    (`~/.local/share/conversational_ai/skills/`). From this module —
    `<root>/src/cli/install_skill.py` — `parents[2]` is the project root.
    """
    root = Path(__file__).resolve().parents[2]
    skills = root / "skills"
    if not skills.is_dir():
        raise click.ClickException(f"skills directory not found at {skills}")
    return skills


def _expand_mode(mode: str) -> list[str]:
    """Map the `--mode` flag value to one or more keys of `_MODE_TO_DIR`."""
    if mode == "all":
        return list(_MODE_TO_DIR)
    return [mode]


def _warn_missing_cai() -> None:
    """Stderr warning if `cai` isn't on PATH — skills assume it is."""
    if shutil.which("cai") is None:
        click.echo(
            "warning: 'cai' not on PATH; the skills assume the cai command is available. "
            "See install.sh.",
            err=True,
        )


_MODE_OPTION = click.option(
    "--mode",
    type=click.Choice([*_MODE_TO_DIR, "all"]),
    default="all",
    show_default=True,
    help="Which skill to act on (or 'all').",
)
_TARGET_OPTION = click.option(
    "--target",
    type=click.Path(file_okay=False, path_type=Path),
    default=_DEFAULT_TARGET,
    show_default=True,
    help="Destination skills directory (e.g. ~/.claude/skills or .claude/skills).",
)


@click.command()
@_MODE_OPTION
@_TARGET_OPTION
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite an existing skill directory at the target.",
)
@click.pass_obj
def install_skill(_ctx_obj: CliContext, mode: str, target: Path, force: bool) -> None:
    """Install bundled skills into TARGET (default: ~/.claude/skills)."""
    skills_root = _resolve_skills_source()
    target.mkdir(parents=True, exist_ok=True)

    conflicts: list[str] = []
    for key in _expand_mode(mode):
        dir_name = _MODE_TO_DIR[key]
        src = skills_root / dir_name
        if not (src / "SKILL.md").is_file():
            raise click.ClickException(f"missing SKILL.md in source {src}")

        dst = target / dir_name
        if dst.exists() and not force:
            click.echo(
                f"{dir_name} already installed at {dst}; pass --force to overwrite",
                err=True,
            )
            conflicts.append(dir_name)
            continue

        shutil.copytree(src, dst, dirs_exist_ok=True)
        click.echo(f"installed {dir_name} -> {dst}")

    _warn_missing_cai()

    if conflicts:
        sys.exit(1)


@click.command()
@_MODE_OPTION
@_TARGET_OPTION
@click.pass_obj
def uninstall_skill(_ctx_obj: CliContext, mode: str, target: Path) -> None:
    """Remove bundled skills from TARGET (default: ~/.claude/skills)."""
    for key in _expand_mode(mode):
        dir_name = _MODE_TO_DIR[key]
        dst = target / dir_name
        if dst.is_dir():
            shutil.rmtree(dst)
            click.echo(f"removed {dst}")
        else:
            click.echo(f"{dir_name} not installed at {dst}", err=True)
