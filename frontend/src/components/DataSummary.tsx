// DataSummary.tsx
// Displays the LLM-generated initial summary as a conversational "first message"
// on the chat screen. Includes dataset metadata, cleaning suggestion action cards,
// and clickable suggested question cards.
// Supports: PRD #2 (initial summary), #4 (cleaning suggestions)
// Key deps: store.ts (DatasetInfo, CleaningSuggestion)
// Architecture ref: "Frontend Architecture" in planning/architecture.md §4
//
// Suggested question clicks are wired in Step 9 (Q&A frontend).
// Cleaning action API calls are wired in Step 10 (data cleaning).

import { useStore } from "../store";
import type { DatasetMetadata, CleaningSuggestion } from "../store";

function MetadataBadge({ label, value }: { label: string; value: string | number }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "4px 10px",
        background: "#f0f4f9",
        borderRadius: 4,
        fontSize: 13,
        color: "#444",
        marginRight: 8,
        marginBottom: 6,
      }}
    >
      <strong>{value}</strong> {label}
    </span>
  );
}

function CleaningSuggestionCard({ suggestion }: { suggestion: CleaningSuggestion }) {
  return (
    <div
      style={{
        padding: "12px 16px",
        border: "1px solid #fde68a",
        background: "#fffbeb",
        borderRadius: 8,
        marginBottom: 10,
      }}
    >
      <p style={{ margin: "0 0 10px", fontSize: 14, color: "#92400e" }}>
        {suggestion.description}
      </p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {suggestion.options.map((option) => (
          <button
            key={option}
            type="button"
            // REVIEW: onClick handler will be wired in Step 10 (data cleaning).
            // For now the buttons render but are non-functional.
            style={{
              padding: "6px 14px",
              fontSize: 13,
              fontWeight: 500,
              background: "#fff",
              border: "1px solid #d6b35a",
              borderRadius: 5,
              cursor: "pointer",
              color: "#78350f",
            }}
          >
            {option}
          </button>
        ))}
      </div>
    </div>
  );
}

function SuggestedQuestionCard({ question }: { question: string }) {
  return (
    <button
      type="button"
      // REVIEW: onClick handler will be wired in Step 9 (Q&A frontend).
      // Clicking will send this question as a chat message.
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        padding: "12px 16px",
        fontSize: 14,
        color: "#1a56db",
        background: "#f0f5ff",
        border: "1px solid #dbeafe",
        borderRadius: 8,
        cursor: "pointer",
        marginBottom: 8,
        transition: "background 0.15s",
      }}
      onMouseEnter={(e) => {
        (e.target as HTMLButtonElement).style.background = "#dbeafe";
      }}
      onMouseLeave={(e) => {
        (e.target as HTMLButtonElement).style.background = "#f0f5ff";
      }}
    >
      {question}
    </button>
  );
}

function DatasetMetadataSection({
  name,
  metadata,
  showName,
}: {
  name: string;
  metadata: DatasetMetadata;
  showName: boolean;
}) {
  return (
    <div style={{ marginBottom: 12 }}>
      {showName && (
        <p style={{ fontSize: 13, fontWeight: 600, color: "#555", margin: "0 0 6px" }}>
          {name}
        </p>
      )}
      <div>
        <MetadataBadge label="rows" value={metadata.row_count.toLocaleString()} />
        <MetadataBadge label="columns" value={metadata.column_count} />
      </div>
    </div>
  );
}

export function DataSummary() {
  const datasetInfo = useStore((s) => s.datasetInfo);

  if (!datasetInfo) return null;

  const { datasets, summary } = datasetInfo;
  const datasetNames = Object.keys(datasets);
  const showDatasetNames = datasetNames.length > 1;

  const hasCleaningSuggestions =
    summary && summary.cleaning_suggestions && summary.cleaning_suggestions.length > 0;
  const hasSuggestedQuestions =
    summary && summary.suggested_questions && summary.suggested_questions.length > 0;
  const hasSummaryError = summary && "error" in summary && summary.error;

  return (
    <div style={{ maxWidth: 640, margin: "0 auto", padding: "32px 24px" }}>
      {/* Assistant message container */}
      <div
        style={{
          background: "#fff",
          border: "1px solid #e5e7eb",
          borderRadius: 12,
          padding: "24px",
          boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
        }}
      >
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: "#6b7280",
            marginBottom: 16,
            textTransform: "uppercase" as const,
            letterSpacing: "0.05em",
          }}
        >
          Assistant
        </div>

        {/* LLM explanation */}
        {summary && summary.explanation && (
          <p style={{ fontSize: 15, lineHeight: 1.7, color: "#1f2937", margin: "0 0 20px" }}>
            {summary.explanation}
          </p>
        )}

        {/* Summary error fallback */}
        {hasSummaryError && (
          <p style={{ fontSize: 14, color: "#92400e", margin: "0 0 20px" }}>
            Could not generate an AI summary for this dataset. You can still
            explore it by asking questions below.
          </p>
        )}

        {/* Dataset metadata badges */}
        {datasetNames.map((name) => (
          <DatasetMetadataSection
            key={name}
            name={name}
            metadata={datasets[name]}
            showName={showDatasetNames}
          />
        ))}

        {/* Cleaning suggestions */}
        {hasCleaningSuggestions && (
          <div style={{ marginTop: 20 }}>
            <p style={{ fontSize: 14, fontWeight: 500, color: "#444", margin: "0 0 10px" }}>
              I noticed a few data quality issues:
            </p>
            {summary!.cleaning_suggestions.map((suggestion, idx) => (
              <CleaningSuggestionCard key={idx} suggestion={suggestion} />
            ))}
          </div>
        )}

        {/* Suggested questions */}
        {hasSuggestedQuestions && (
          <div style={{ marginTop: 20 }}>
            <p style={{ fontSize: 14, fontWeight: 500, color: "#444", margin: "0 0 10px" }}>
              Here are some questions you could explore:
            </p>
            {summary!.suggested_questions.map((question, idx) => (
              <SuggestedQuestionCard key={idx} question={question} />
            ))}
          </div>
        )}
      </div>

      {/* Chat input placeholder — replaced with real input in Step 9 */}
      <div style={{ marginTop: 24 }}>
        <div
          style={{
            display: "flex",
            gap: 8,
            alignItems: "center",
          }}
        >
          <input
            type="text"
            placeholder="Ask a question about your data..."
            disabled
            style={{
              flex: 1,
              padding: "12px 16px",
              fontSize: 14,
              border: "1px solid #d1d5db",
              borderRadius: 8,
              background: "#f9fafb",
              color: "#9ca3af",
            }}
          />
          <button
            type="button"
            disabled
            style={{
              padding: "12px 20px",
              fontSize: 14,
              fontWeight: 500,
              background: "#d1d5db",
              color: "#fff",
              border: "none",
              borderRadius: 8,
              cursor: "not-allowed",
            }}
          >
            Send
          </button>
        </div>
        <p style={{ fontSize: 12, color: "#9ca3af", marginTop: 6 }}>
          Chat will be available in a future update.
        </p>
      </div>
    </div>
  );
}
