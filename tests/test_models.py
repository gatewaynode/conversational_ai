"""Unit tests for ModelManager helpers.

Covers ``_resolve_model_path`` across all four resolution branches:
absolute path, LM Studio layout, HuggingFace hub cache, and fall-through.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.models import _resolve_from_hf_cache, _resolve_model_path


class TestResolveModelPath:
    def test_absolute_path_returned_unchanged(self, tmp_path: Path) -> None:
        """An absolute path is passed through verbatim even if it doesn't exist."""
        abs_path = "/opt/models/my-model"
        result = _resolve_model_path(abs_path, tmp_path)
        assert result == abs_path

    def test_lmstudio_layout_match(self, tmp_path: Path) -> None:
        """A model at models_dir/org/name resolves to that absolute path."""
        model_dir = tmp_path / "mlx-community" / "Kokoro-82M-bf16"
        model_dir.mkdir(parents=True)

        # Belt-and-suspenders: the HF cache branch must not be consulted here.
        with patch("src.models._resolve_from_hf_cache") as mock_hf:
            result = _resolve_model_path("mlx-community/Kokoro-82M-bf16", tmp_path)

        assert Path(result) == model_dir.resolve()
        mock_hf.assert_not_called()

    def test_hf_cache_match_when_lmstudio_missing(self, tmp_path: Path) -> None:
        """When models_dir has no copy but HF cache does, return the HF snapshot path."""
        fake_snapshot = "/Users/test/.cache/huggingface/hub/models--mlx-community--whisper/snapshots/abc123"

        with patch(
            "src.models._resolve_from_hf_cache", return_value=fake_snapshot
        ) as mock_hf:
            result = _resolve_model_path(
                "mlx-community/whisper-large-v3-turbo-asr-fp16", tmp_path
            )

        assert result == fake_snapshot
        mock_hf.assert_called_once_with("mlx-community/whisper-large-v3-turbo-asr-fp16")

    def test_fallthrough_returns_hf_repo_id(self, tmp_path: Path) -> None:
        """When neither local layout nor HF cache has the model, return the ID unchanged."""
        with patch("src.models._resolve_from_hf_cache", return_value=None):
            result = _resolve_model_path("mlx-community/does-not-exist", tmp_path)

        assert result == "mlx-community/does-not-exist"

    def test_lmstudio_takes_precedence_over_hf_cache(self, tmp_path: Path) -> None:
        """A local copy in models_dir wins even if the HF cache also has the model."""
        model_dir = tmp_path / "mlx-community" / "model"
        model_dir.mkdir(parents=True)

        with patch(
            "src.models._resolve_from_hf_cache", return_value="/some/hf/snapshot"
        ) as mock_hf:
            result = _resolve_model_path("mlx-community/model", tmp_path)

        assert Path(result) == model_dir.resolve()
        mock_hf.assert_not_called()

    def test_lmstudio_layout_ignores_files(self, tmp_path: Path) -> None:
        """A file (not directory) at the expected path should not match."""
        (tmp_path / "mlx-community").mkdir()
        (tmp_path / "mlx-community" / "model").write_text("not a directory")

        with patch("src.models._resolve_from_hf_cache", return_value=None):
            result = _resolve_model_path("mlx-community/model", tmp_path)

        assert result == "mlx-community/model"


class TestResolveFromHfCache:
    """_resolve_from_hf_cache uses huggingface_hub.snapshot_download with local_files_only."""

    def test_returns_path_when_cached(self) -> None:
        fake_path = "/home/user/.cache/huggingface/hub/models--org--name/snapshots/abc"

        with patch("huggingface_hub.snapshot_download", return_value=fake_path) as mock_dl:
            result = _resolve_from_hf_cache("org/name")

        assert result == str(Path(fake_path).resolve())
        mock_dl.assert_called_once_with("org/name", local_files_only=True)

    def test_returns_none_when_not_cached(self) -> None:
        from huggingface_hub.errors import LocalEntryNotFoundError

        with patch(
            "huggingface_hub.snapshot_download",
            side_effect=LocalEntryNotFoundError("not cached"),
        ):
            result = _resolve_from_hf_cache("org/missing")

        assert result is None

    def test_returns_none_on_unexpected_error(self) -> None:
        """Any other exception (network, permissions, etc.) should not propagate."""
        with patch(
            "huggingface_hub.snapshot_download",
            side_effect=RuntimeError("unexpected"),
        ):
            result = _resolve_from_hf_cache("org/name")

        assert result is None

    def test_never_hits_network(self) -> None:
        """The local_files_only=True flag is the whole point — verify it's set."""
        with patch("huggingface_hub.snapshot_download", return_value="/tmp/x") as mock_dl:
            _resolve_from_hf_cache("org/name")

        _, kwargs = mock_dl.call_args
        assert kwargs.get("local_files_only") is True
