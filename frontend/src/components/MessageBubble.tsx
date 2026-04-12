// MessageBubble.tsx
// Renders a single chat message — user question or assistant response.
// Assistant responses may include: explanation text, chart images (base64 PNG),
// a code block (behind a toggle), stdout output, and error messages.
// Supports: PRD #3 (Conversational Q&A)
// Key deps: store.ts (Message type)
// Architecture ref: "Frontend Architecture" in planning/architecture.md §4

import { useState } from "react";
import type { Message } from "../store";
import { CleaningSuggestionCard } from "./CleaningSuggestionCard";

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  if (message.role === "user") {
    return <UserBubble content={message.content} />;
  }
  return <AssistantBubble message={message} />;
}

function UserBubble({ content }: { content: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 16 }}>
      <div
        style={{
          maxWidth: "80%",
          background: "#e8f0fe",
          borderRadius: 12,
          padding: "12px 16px",
        }}
      >
        <div style={labelStyle}>You</div>
        <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, color: "#1f2937" }}>
          {content}
        </p>
      </div>
    </div>
  );
}

function AssistantBubble({ message }: { message: Message }) {
  const [showCode, setShowCode] = useState(false);
  const [showErrorDetails, setShowErrorDetails] = useState(false);
  const hasFigures = message.figures && message.figures.length > 0;
  const hasCode = !!message.code;
  const hasCleaningSuggestions = message.cleaningSuggestions && message.cleaningSuggestions.length > 0;

  return (
    <div
      style={{
        background: "#fff",
        border: "1px solid #e5e7eb",
        borderRadius: 12,
        padding: "16px 20px",
        marginBottom: 16,
        boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
      }}
    >
      <div style={labelStyle}>Assistant</div>

      {message.error && (
        <div
          style={{
            padding: "10px 14px",
            background: "#fef2f2",
            border: "1px solid #fecaca",
            borderRadius: 8,
            marginBottom: 12,
            fontSize: 14,
            color: "#991b1b",
          }}
        >
          <p style={{ margin: "0 0 8px" }}>
            I couldn&apos;t execute the analysis. Try rephrasing your question or being more specific.
          </p>
          <button
            type="button"
            onClick={() => setShowErrorDetails(!showErrorDetails)}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              fontSize: 13,
              color: "#991b1b",
              padding: "4px 0",
            }}
          >
            {showErrorDetails ? "\u25BC Hide details" : "\u25B6 Show details"}
          </button>
          {showErrorDetails && (
            <pre
              style={{
                background: "#fef2f2",
                fontSize: 12,
                lineHeight: 1.5,
                overflowX: "auto",
                marginTop: 6,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {message.error}
            </pre>
          )}
        </div>
      )}

      {message.content && (
        <p style={{ margin: "0 0 12px", fontSize: 14, lineHeight: 1.7, color: "#1f2937" }}>
          {message.content}
        </p>
      )}

      {message.stdout && (
        <pre
          style={{
            background: "#f9fafb",
            border: "1px solid #e5e7eb",
            borderRadius: 6,
            padding: "10px 14px",
            fontSize: 13,
            lineHeight: 1.5,
            overflowX: "auto",
            marginBottom: 12,
            color: "#374151",
          }}
        >
          {message.stdout}
        </pre>
      )}

      {hasFigures &&
        message.figures!.map((fig, idx) => (
          <img
            key={idx}
            src={"data:image/png;base64," + fig}
            alt={"Chart " + (idx + 1)}
            style={{
              maxWidth: "100%",
              borderRadius: 8,
              marginBottom: 12,
              border: "1px solid #e5e7eb",
            }}
          />
        ))}

      {hasCleaningSuggestions && (
        <div style={{ marginTop: 12 }}>
          {message.cleaningSuggestions!.map((suggestion, idx) => (
            <CleaningSuggestionCard key={idx} suggestion={suggestion} />
          ))}
        </div>
      )}

      {hasCode && (
        <div style={{ marginTop: 4 }}>
          <button
            type="button"
            onClick={() => setShowCode(!showCode)}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              fontSize: 13,
              color: "#6b7280",
              padding: "4px 0",
            }}
          >
            {showCode ? "\u25BC Hide code" : "\u25B6 Show code"}
          </button>
          {showCode && (
            <pre
              style={{
                background: "#1f2937",
                color: "#e5e7eb",
                borderRadius: 6,
                padding: "12px 16px",
                fontSize: 13,
                lineHeight: 1.5,
                overflowX: "auto",
                marginTop: 6,
              }}
            >
              {message.code}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  color: "#6b7280",
  marginBottom: 8,
  textTransform: "uppercase",
  letterSpacing: "0.05em",
};
