"""HTTP middleware: inject server-side limits into every response header."""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class LimitsHeaderMiddleware(BaseHTTPMiddleware):
    """Add X-Limit-* headers to every response so clients know the active limits.

    Headers added:
        X-Limit-Max-Text-Length      — max characters accepted by POST /v1/tts
        X-Limit-Max-Audio-File-Size  — max upload bytes accepted by POST /v1/stt

    These are read from ``app.state.settings`` so they always reflect the
    live configuration (TOML file + any CLI overrides).
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        try:
            limits = request.app.state.settings.limits
            response.headers["X-Limit-Max-Text-Length"] = str(limits.max_text_length)
            response.headers["X-Limit-Max-Audio-File-Size"] = str(
                limits.max_audio_file_size
            )
        except AttributeError:
            # settings not yet on app.state during tests with minimal apps
            pass
        return response
