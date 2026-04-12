// ApiKeyInput.tsx
// Setup screen component: provider selector + API key input + model selector + validation.
// Supports: PRD #8 (BYOK) — the first screen the user sees; must complete before any
//   LLM feature is accessible.
// Key deps: api.ts (validateApiKey, fetchAvailableModels), store.ts (setApiKey, setProvider,
//   setModel, setScreen)
// Architecture ref: "Frontend Architecture" in planning/architecture.md §4

import { useEffect, useState } from "react";
import { validateApiKey, fetchAvailableModels, ApiError } from "../api";
import type { ModelInfo } from "../api";
import { useStore, type Provider } from "../store";

const PROVIDER_OPTIONS: { value: Provider; label: string; placeholder: string }[] = [
  {
    value: "openai",
    label: "OpenAI",
    placeholder: "sk-...",
  },
  {
    value: "anthropic",
    label: "Anthropic",
    placeholder: "sk-ant-...",
  },
];

export function ApiKeyInput() {
  const setApiKey = useStore((state) => state.setApiKey);
  const setProvider = useStore((state) => state.setProvider);
  const setModel = useStore((state) => state.setModel);
  const setScreen = useStore((state) => state.setScreen);

  const [selectedProvider, setSelectedProvider] = useState<Provider>("openai");
  const [apiKey, setApiKeyInput] = useState("");
  const [selectedModelId, setSelectedModelId] = useState<string>("");
  const [isValidating, setIsValidating] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Model catalog fetched from GET /api/models on mount.
  // Keyed by provider → array of ModelInfo.
  const [modelCatalog, setModelCatalog] = useState<Record<string, ModelInfo[]>>({});
  const [isLoadingModels, setIsLoadingModels] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setIsLoadingModels(true);
    fetchAvailableModels()
      .then((catalog) => {
        if (cancelled) return;
        setModelCatalog(catalog);
        // Pre-select the default model for the current provider.
        const defaultModel = catalog["openai"]?.find((m) => m.is_default);
        if (defaultModel) setSelectedModelId(defaultModel.model_id);
      })
      .catch(() => {
        if (cancelled) return;
        setErrorMessage("Could not load available models. Is the backend running?");
      })
      .finally(() => {
        if (!cancelled) setIsLoadingModels(false);
      });
    return () => { cancelled = true; };
  }, []);

  // When the user switches provider, pre-select that provider's default model.
  function handleProviderChange(provider: Provider) {
    setSelectedProvider(provider);
    setErrorMessage(null);
    const models = modelCatalog[provider] ?? [];
    const defaultModel = models.find((m) => m.is_default) ?? models[0];
    setSelectedModelId(defaultModel?.model_id ?? "");
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setErrorMessage(null);
    setIsValidating(true);

    try {
      await validateApiKey(apiKey, selectedProvider);
      setApiKey(apiKey.trim());
      setProvider(selectedProvider);
      setModel(selectedModelId);
      setScreen("upload");
    } catch (error) {
      if (error instanceof ApiError) {
        setErrorMessage(error.detail);
      } else {
        setErrorMessage(
          "Could not reach the server. Check your connection and try again."
        );
      }
    } finally {
      setIsValidating(false);
    }
  }

  const currentPlaceholder =
    PROVIDER_OPTIONS.find((p) => p.value === selectedProvider)?.placeholder ?? "";
  const modelsForProvider = modelCatalog[selectedProvider] ?? [];
  const isSubmitDisabled = isValidating || apiKey.trim().length === 0 || !selectedModelId;

  return (
    <div style={{ maxWidth: 480, margin: "80px auto", padding: "0 24px" }}>
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 8 }}>
        Smart Dataset Explainer
      </h1>
      <p style={{ color: "#555", marginBottom: 32 }}>
        Enter your API key to get started. Your key is never stored on our
        servers — it stays in your browser session.
      </p>

      <form onSubmit={handleSubmit}>
        {/* Provider selector */}
        <fieldset style={{ border: "none", padding: 0, margin: "0 0 16px 0" }}>
          <legend
            style={{ fontSize: 14, fontWeight: 500, marginBottom: 8, display: "block" }}
          >
            Provider
          </legend>
          <div style={{ display: "flex", gap: 12 }}>
            {PROVIDER_OPTIONS.map((option) => (
              <label
                key={option.value}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  cursor: "pointer",
                  fontSize: 14,
                }}
              >
                <input
                  type="radio"
                  name="provider"
                  value={option.value}
                  checked={selectedProvider === option.value}
                  onChange={() => handleProviderChange(option.value)}
                />
                {option.label}
              </label>
            ))}
          </div>
        </fieldset>

        {/* API key input */}
        <label
          htmlFor="api-key-input"
          style={{ fontSize: 14, fontWeight: 500, display: "block", marginBottom: 6 }}
        >
          API Key
        </label>
        <input
          id="api-key-input"
          type="password"
          value={apiKey}
          onChange={(e) => {
            setApiKeyInput(e.target.value);
            setErrorMessage(null);
          }}
          placeholder={currentPlaceholder}
          disabled={isValidating}
          autoComplete="off"
          style={{
            width: "100%",
            padding: "10px 12px",
            fontSize: 14,
            border: errorMessage ? "1px solid #d93025" : "1px solid #ccc",
            borderRadius: 6,
            boxSizing: "border-box",
            marginBottom: 16,
          }}
        />

        {/* Model selector */}
        <label
          htmlFor="model-select"
          style={{ fontSize: 14, fontWeight: 500, display: "block", marginBottom: 6 }}
        >
          Model
        </label>
        {isLoadingModels ? (
          <p style={{ fontSize: 13, color: "#888", margin: "0 0 16px 0" }}>
            Loading models…
          </p>
        ) : (
          <>
            <select
              id="model-select"
              value={selectedModelId}
              onChange={(e) => setSelectedModelId(e.target.value)}
              disabled={isValidating || modelsForProvider.length === 0}
              style={{
                width: "100%",
                padding: "10px 12px",
                fontSize: 14,
                border: "1px solid #ccc",
                borderRadius: 6,
                boxSizing: "border-box",
                marginBottom: 4,
                background: "#fff",
              }}
            >
              {modelsForProvider.map((m) => (
                <option key={m.model_id} value={m.model_id}>
                  {m.label} — {m.tier}
                </option>
              ))}
            </select>
            {/* Description of the currently selected model */}
            {(() => {
              const selected = modelsForProvider.find(
                (m) => m.model_id === selectedModelId
              );
              return selected ? (
                <p style={{ fontSize: 12, color: "#888", margin: "0 0 16px 0" }}>
                  {selected.description}
                </p>
              ) : null;
            })()}
          </>
        )}

        {/* Inline error message */}
        {errorMessage && (
          <p
            role="alert"
            style={{ color: "#d93025", fontSize: 13, marginBottom: 12 }}
          >
            {errorMessage}
          </p>
        )}

        <button
          type="submit"
          disabled={isSubmitDisabled}
          style={{
            width: "100%",
            padding: "10px 0",
            fontSize: 14,
            fontWeight: 500,
            background: isSubmitDisabled ? "#ccc" : "#1a73e8",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            cursor: isSubmitDisabled ? "not-allowed" : "pointer",
          }}
        >
          {isValidating ? "Validating…" : "Continue"}
        </button>
      </form>
    </div>
  );
}
