"""Tests for model token-budget selection."""

from unittest.mock import patch

from petri_bloom._util.model import resolve_max_tokens


def test_resolve_max_tokens_uses_opus_maximum_when_model_info_is_missing() -> None:
    """Frontier models absent from Inspect's registry receive the full budget."""
    with patch("petri_bloom._util.model.get_model_info", return_value=None):
        assert resolve_max_tokens(object()) == 128_000
