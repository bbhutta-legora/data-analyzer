# tests/test_providers.py
# Tests for provider catalog logic in providers.py.
# Related module: backend/providers.py
# PRD: supports #8 (BYOK) — model selection on the setup screen
#
# Confirmed behavior list (TEST-STRATEGY Steps 1–2, agreed in session):
#  1. get_default_model("openai") returns the model marked is_default=True
#  2. get_default_model("anthropic") returns the model marked is_default=True
#  3. get_default_model() with an unrecognised provider raises ValueError
#
# These tests guard against catalog misconfiguration — specifically, someone
# updating AVAILABLE_MODELS and accidentally removing all is_default=True flags,
# which would silently fall through to the first model with no warning.

import pytest
from providers import get_default_model, AVAILABLE_MODELS


def test_get_default_model_openai_returns_is_default_model():
    # Behavior 1: the returned model_id should match the entry with is_default=True.
    default_id = get_default_model("openai")
    openai_models = AVAILABLE_MODELS["openai"]
    marked_default = [m for m in openai_models if m.is_default]
    assert len(marked_default) == 1, (
        "Exactly one OpenAI model should be marked is_default=True — "
        f"found {len(marked_default)}"
    )
    assert default_id == marked_default[0].model_id


def test_get_default_model_anthropic_returns_is_default_model():
    # Behavior 2: same as above for Anthropic.
    default_id = get_default_model("anthropic")
    anthropic_models = AVAILABLE_MODELS["anthropic"]
    marked_default = [m for m in anthropic_models if m.is_default]
    assert len(marked_default) == 1, (
        "Exactly one Anthropic model should be marked is_default=True — "
        f"found {len(marked_default)}"
    )
    assert default_id == marked_default[0].model_id


def test_get_default_model_unknown_provider_raises_value_error():
    # Behavior 3: an unrecognised provider should raise ValueError, not silently
    # return None or an empty string — callers must never receive a blank model_id.
    with pytest.raises(ValueError, match="No models configured"):
        get_default_model("gemini")
