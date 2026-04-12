# tests/test_validate_key.py
# Tests for the /api/validate-key endpoint.
# Related module: backend/main.py (/api/validate-key route)
# PRD: supports #8 (BYOK) — the user must supply a valid key before any LLM feature works
#
# Confirmed behavior list (TEST-STRATEGY Steps 1–2):
#  1. A valid OpenAI key returns 200 {"valid": true}
#  2. A valid Anthropic key returns 200 {"valid": true}
#  3. An invalid OpenAI key returns 401 {"valid": false}
#  4. An invalid Anthropic key returns 401 {"valid": false}
#  5. An empty api_key returns 400 before any provider API call is made
#  6. An unsupported provider value returns 422 (Pydantic validation)
#  7. A missing provider field returns 422 (Pydantic validation)
#  8. When provider is "openai", only the OpenAI validation function is called
#  9. When provider is "anthropic", only the Anthropic validation function is called
# 10. Leading/trailing whitespace in api_key is stripped before validation
#
# Tests: FastAPI TestClient (synchronous, in-process).
# LLM API calls are mocked — real key validation is in the integration test suite.

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


# ── Valid key — OpenAI ─────────────────────────────────────────────────────────

def test_valid_openai_key_returns_200():
    # Behavior 1: a valid OpenAI key is accepted.
    with patch("main.validate_openai_key", return_value=True):
        response = client.post(
            "/api/validate-key",
            json={"api_key": "sk-valid-openai-key", "provider": "openai"},
        )
    assert response.status_code == 200
    assert response.json()["valid"] is True


# ── Valid key — Anthropic ──────────────────────────────────────────────────────

def test_valid_anthropic_key_returns_200():
    # Behavior 2: a valid Anthropic key is accepted.
    with patch("main.validate_anthropic_key", return_value=True):
        response = client.post(
            "/api/validate-key",
            json={"api_key": "sk-ant-valid-key", "provider": "anthropic"},
        )
    assert response.status_code == 200
    assert response.json()["valid"] is True


# ── Invalid key — OpenAI ───────────────────────────────────────────────────────

def test_invalid_openai_key_returns_401():
    # Behavior 3: an invalid OpenAI key is rejected with 401.
    with patch("main.validate_openai_key", return_value=False):
        response = client.post(
            "/api/validate-key",
            json={"api_key": "sk-invalid", "provider": "openai"},
        )
    assert response.status_code == 401
    assert response.json()["valid"] is False


# ── Invalid key — Anthropic ────────────────────────────────────────────────────

def test_invalid_anthropic_key_returns_401():
    # Behavior 4: an invalid Anthropic key is rejected with 401.
    with patch("main.validate_anthropic_key", return_value=False):
        response = client.post(
            "/api/validate-key",
            json={"api_key": "sk-ant-invalid", "provider": "anthropic"},
        )
    assert response.status_code == 401
    assert response.json()["valid"] is False


# ── Input validation ───────────────────────────────────────────────────────────

def test_empty_api_key_returns_400_without_calling_provider():
    # Behavior 5: empty key is rejected before any provider API call.
    with patch("main.validate_openai_key") as mock_openai, \
         patch("main.validate_anthropic_key") as mock_anthropic:
        response = client.post(
            "/api/validate-key",
            json={"api_key": "", "provider": "openai"},
        )
    assert response.status_code == 400
    mock_openai.assert_not_called()
    mock_anthropic.assert_not_called()


def test_unsupported_provider_returns_422():
    # Behavior 6: providers outside the supported set are rejected by Pydantic
    # before the route handler runs — no mocking needed.
    response = client.post(
        "/api/validate-key",
        json={"api_key": "sk-somekey", "provider": "gemini"},
    )
    assert response.status_code == 422


def test_missing_provider_field_returns_422():
    # Behavior 7: omitting the provider field fails Pydantic validation.
    response = client.post(
        "/api/validate-key",
        json={"api_key": "sk-somekey"},
    )
    assert response.status_code == 422


# ── Correct dispatch ───────────────────────────────────────────────────────────

def test_openai_provider_calls_only_openai_validator():
    # Behavior 8: only the OpenAI validation function is called for provider "openai".
    with patch("main.validate_openai_key", return_value=True) as mock_openai, \
         patch("main.validate_anthropic_key") as mock_anthropic:
        client.post(
            "/api/validate-key",
            json={"api_key": "sk-valid", "provider": "openai"},
        )
    mock_openai.assert_called_once()
    mock_anthropic.assert_not_called()


def test_anthropic_provider_calls_only_anthropic_validator():
    # Behavior 9: only the Anthropic validation function is called for provider "anthropic".
    with patch("main.validate_anthropic_key", return_value=True) as mock_anthropic, \
         patch("main.validate_openai_key") as mock_openai:
        client.post(
            "/api/validate-key",
            json={"api_key": "sk-ant-valid", "provider": "anthropic"},
        )
    mock_anthropic.assert_called_once()
    mock_openai.assert_not_called()


# ── Whitespace stripping ───────────────────────────────────────────────────────

def test_api_key_whitespace_is_stripped_before_validation():
    # Behavior 10: leading/trailing whitespace from copy-paste is stripped
    # so "  sk-real-key  " validates the same as "sk-real-key".
    with patch("main.validate_openai_key", return_value=True) as mock_openai:
        response = client.post(
            "/api/validate-key",
            json={"api_key": "  sk-real-key  ", "provider": "openai"},
        )
    assert response.status_code == 200
    # The validator should have been called with the stripped key, not the padded one.
    called_with = mock_openai.call_args[0][0]
    assert called_with == "sk-real-key"
