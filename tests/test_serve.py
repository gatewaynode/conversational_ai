"""Tests for `cai serve` — FastAPI app startup wiring."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from src.cli.serve import serve
from tests._cli_fakes import make_ctx


class TestServeCommand:
    def test_serve_calls_uvicorn_with_host_and_port(self) -> None:
        ctx = make_ctx()
        ctx.settings.server.host = "127.0.0.1"
        ctx.settings.server.port = 4242
        runner = CliRunner()

        fake_app = object()
        with (
            patch("main.create_app", return_value=fake_app) as mock_create,
            patch("uvicorn.run") as mock_run,
        ):
            result = runner.invoke(serve, [], obj=ctx)

        assert result.exit_code == 0, result.output
        mock_create.assert_called_once_with(ctx.settings)
        mock_run.assert_called_once_with(fake_app, host="127.0.0.1", port=4242)
