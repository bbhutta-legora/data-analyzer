// CleaningSuggestionCard.tsx
// Renders a single data quality suggestion with action buttons.
// Used in DataSummary (upload-time suggestions) and MessageBubble (chat suggestions).
// Supports: PRD #4 (Data Cleaning)
// Key deps: store.ts (CleaningSuggestion, useStore), api.ts (applyCleaningAction)
// Architecture ref: "Frontend Architecture" in planning/architecture.md §4

import { useState } from "react";
import type { CleaningSuggestion } from "../store";
import { useStore } from "../store";
import { applyCleaningAction } from "../api";

type CardStatus = "idle" | "loading" | "success" | "error";

// Maps user-facing option text from the LLM to backend action names.
// The LLM produces options like "Drop rows", "Fill with median", "Drop duplicates".
// This lookup normalises those to the action identifiers backend/clean.py expects.
const OPTION_TO_ACTION: Record<string, string> = {
  "drop rows": "drop_missing_rows",
  "drop missing rows": "drop_missing_rows",
  "fill with median": "fill_median",
  "fill median": "fill_median",
  "drop duplicates": "drop_duplicates",
  "remove duplicates": "drop_duplicates",
};

// Regex to extract a column name from a suggestion description.
// Matches patterns like: "Column 'score' has..." or "Column score has..."
const COLUMN_NAME_RE = /column\s+['"]?(\w+)['"]?/i;

function resolveAction(optionText: string): string | null {
  const normalized = optionText.toLowerCase().trim();
  return OPTION_TO_ACTION[normalized] ?? null;
}

function extractColumnFromDescription(description: string): string | null {
  const match = COLUMN_NAME_RE.exec(description);
  return match ? match[1] : null;
}

interface CleaningSuggestionCardProps {
  suggestion: CleaningSuggestion;
}

export function CleaningSuggestionCard({ suggestion }: CleaningSuggestionCardProps) {
  const [status, setStatus] = useState<CardStatus>("idle");
  const [message, setMessage] = useState<string>("");
  const sessionId = useStore((s) => s.sessionId);
  const updateDatasetMetadata = useStore((s) => s.updateDatasetMetadata);
  const setHasAppliedCleaning = useStore((s) => s.setHasAppliedCleaning);

  async function handleOptionClick(option: string) {
    if (!sessionId || status === "loading") return;

    const action = resolveAction(option);
    if (!action) {
      setStatus("error");
      setMessage("Unknown action: '" + option + "'");
      return;
    }

    const column = extractColumnFromDescription(suggestion.description);
    const datasetName = suggestion.dataset_name;

    setStatus("loading");
    setMessage("");

    try {
      const result = await applyCleaningAction(sessionId, action, column ?? undefined, datasetName);
      setStatus("success");
      setMessage(result.message);
      setHasAppliedCleaning(true);

      // Update the store with the new metadata for the affected dataset.
      const targetName = datasetName ?? Object.keys(useStore.getState().datasetInfo?.datasets ?? {})[0];
      if (targetName) {
        updateDatasetMetadata(targetName, {
          row_count: result.row_count,
          column_count: result.column_count,
          columns: result.columns,
          dtypes: result.dtypes,
          missing_values: result.missing_values,
        });
      }
    } catch (err: unknown) {
      setStatus("error");
      setMessage(err instanceof Error ? err.message : "Cleaning action failed.");
    }
  }

  const isApplied = status === "success";
  const isLoading = status === "loading";

  return (
    <div
      style={{
        padding: "12px 16px",
        border: "1px solid " + (isApplied ? "#a7f3d0" : "#fde68a"),
        background: isApplied ? "#ecfdf5" : "#fffbeb",
        borderRadius: 8,
        marginBottom: 10,
        opacity: isLoading ? 0.7 : 1,
        transition: "background 0.2s, border-color 0.2s, opacity 0.2s",
      }}
    >
      <p style={{ margin: "0 0 10px", fontSize: 14, color: isApplied ? "#065f46" : "#92400e" }}>
        {suggestion.description}
      </p>

      {!isApplied && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {suggestion.options.map((option) => (
            <button
              key={option}
              type="button"
              disabled={isLoading}
              onClick={() => handleOptionClick(option)}
              style={{
                padding: "6px 14px",
                fontSize: 13,
                fontWeight: 500,
                background: isLoading ? "#f3f4f6" : "#fff",
                border: "1px solid #d6b35a",
                borderRadius: 5,
                cursor: isLoading ? "not-allowed" : "pointer",
                color: "#78350f",
              }}
            >
              {isLoading ? "Applying..." : option}
            </button>
          ))}
        </div>
      )}

      {message && (
        <p
          style={{
            margin: "8px 0 0",
            fontSize: 13,
            color: status === "error" ? "#991b1b" : "#065f46",
          }}
        >
          {message}
        </p>
      )}
    </div>
  );
}
