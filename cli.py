"""Entry point for the `cai` CLI command."""

from src.cli import cli
from src.cli.serve import serve
from src.cli.speak import speak
from src.cli.transcribe import transcribe

cli.add_command(speak)
cli.add_command(transcribe)
cli.add_command(serve)

if __name__ == "__main__":
    cli()
