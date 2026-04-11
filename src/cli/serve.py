"""serve subcommand: start the TTS/STT HTTP API server."""

from __future__ import annotations

import click

from src.cli import CliContext


@click.command()
@click.pass_obj
def serve(ctx_obj: CliContext) -> None:
    """Start the TTS/STT HTTP API server.

    Host and port are read from the config file (default: 127.0.0.1:4114).
    Models are loaded by the server's startup lifespan, not by this command.
    """
    import uvicorn

    from main import create_app

    s = ctx_obj.settings
    app = create_app(s)
    uvicorn.run(app, host=s.server.host, port=s.server.port)
