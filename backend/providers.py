# providers.py
# Single source of truth for supported LLM providers and available models.
# Consumed by: main.py (/api/validate-key, /api/models routes),
#              llm.py (model dispatch), session.py (provider+model stored per-session)
#
# When adding a new provider or model, update this file only. All consumers
# reference these constants rather than hardcoding strings.
#
# The frontend fetches available models via GET /api/models, which returns
# AVAILABLE_MODELS directly — no duplication between frontend and backend.
#
# PRD: supports #8 (BYOK)

from dataclasses import dataclass
from typing import Literal

# ── Provider identifiers ──────────────────────────────────────────────────────

SUPPORTED_PROVIDERS = {"openai", "anthropic"}

ProviderLiteral = Literal["openai", "anthropic"]

# ── Model catalog ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ModelInfo:
    """Describes one selectable model in the setup screen dropdown."""
    model_id: str
    label: str
    tier: str
    description: str
    is_default: bool = False

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "label": self.label,
            "tier": self.tier,
            "description": self.description,
            "is_default": self.is_default,
        }


# Curated to models that are well-suited for data analysis, code generation,
# and conversational Q&A. Ordered from most capable to fastest per provider.
# Updated April 2026 — review quarterly or when providers announce new releases.
AVAILABLE_MODELS: dict[str, list[ModelInfo]] = {
    "openai": [
        ModelInfo(
            model_id="gpt-5.4",
            label="GPT-5.4",
            tier="Frontier",
            description="Best quality — complex analysis, ML workflows",
        ),
        ModelInfo(
            model_id="gpt-5.4-mini",
            label="GPT-5.4 Mini",
            tier="Balanced",
            description="Good balance of speed and quality for most tasks",
            is_default=True,
        ),
        ModelInfo(
            model_id="gpt-5.4-nano",
            label="GPT-5.4 Nano",
            tier="Fast",
            description="Fastest and cheapest — simple queries, data extraction",
        ),
    ],
    "anthropic": [
        ModelInfo(
            model_id="claude-opus-4-6",
            label="Claude Opus 4.6",
            tier="Frontier",
            description="Best quality — complex analysis, ML workflows",
        ),
        ModelInfo(
            model_id="claude-sonnet-4-6",
            label="Claude Sonnet 4.6",
            tier="Balanced",
            description="Good balance of speed and quality for most tasks",
            is_default=True,
        ),
        ModelInfo(
            model_id="claude-haiku-4-5",
            label="Claude Haiku 4.5",
            tier="Fast",
            description="Fastest and cheapest — simple queries, data extraction",
        ),
    ],
}

# ── Defaults ──────────────────────────────────────────────────────────────────

def get_default_model(provider: str) -> str:
    """Return the model_id of the default (is_default=True) model for a provider."""
    for model in AVAILABLE_MODELS.get(provider, []):
        if model.is_default:
            return model.model_id
    models = AVAILABLE_MODELS.get(provider, [])
    if models:
        return models[0].model_id
    raise ValueError(f"No models configured for provider '{provider}'")

# Cheap model used only for key validation — we send a 1-token request to confirm
# the key works without spending meaningful API credits.
# Uses the fastest tier to minimise cost; deliberately not the user's selected model.
ANTHROPIC_VALIDATION_MODEL = "claude-haiku-4-5"
