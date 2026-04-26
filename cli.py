"""Entry point for the `cai` CLI command."""

from src.cli import cli
from src.cli.converse import converse
from src.cli.dialogue import dialogue
from src.cli.install_skill import install_skill, uninstall_skill
from src.cli.listen import listen
from src.cli.serve import serve
from src.cli.speak import speak
from src.cli.transcribe import transcribe
from src.cli.watch import watch

cli.add_command(speak)
cli.add_command(transcribe)
cli.add_command(watch)
cli.add_command(listen)
cli.add_command(serve)
cli.add_command(dialogue)
cli.add_command(converse)
cli.add_command(install_skill, name="install-skill")
cli.add_command(uninstall_skill, name="uninstall-skill")

if __name__ == "__main__":
    cli()
