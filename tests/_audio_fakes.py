"""Shared test doubles for audio I/O tests.

Not a conftest.py (which would invite pytest's double-import trap) — just a
plain helper module imported explicitly where needed.
"""

from __future__ import annotations

import threading

import numpy as np


class FakeInputStream:
    """Test double for sounddevice.InputStream.

    On __enter__, feeds a scripted sequence of chunks to the user-supplied
    callback on a background thread so record()'s stop_event.wait() unblocks
    naturally when the trailing silence is delivered.
    """

    def __init__(self, chunks: list[np.ndarray], callback) -> None:  # type: ignore[no-untyped-def]
        self._chunks = chunks
        self._callback = callback
        self._thread: threading.Thread | None = None

    def __enter__(self) -> FakeInputStream:
        def pump() -> None:
            for chunk in self._chunks:
                indata = chunk.reshape(-1, 1)
                self._callback(indata, len(chunk), None, None)

        self._thread = threading.Thread(target=pump, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._thread is not None:
            self._thread.join(timeout=1)


class PortAudioError(Exception):
    """Stand-in for sounddevice.PortAudioError in tests."""
