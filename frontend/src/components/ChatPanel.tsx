// ChatPanel.tsx
// Main chat screen: renders the initial DataSummary, a scrollable message list,
// and a text input bar for sending questions.
// Supports: PRD #3 (Conversational Q&A)
// Key deps: store.ts (messages, isStreaming, addMessage, etc.),
//           api.ts (sendChatMessage), MessageBubble, DataSummary
// Architecture ref: "Frontend Architecture" in planning/architecture.md §4

import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { sendChatMessage } from "../api";
import { DataSummary } from "./DataSummary";
import { MessageBubble } from "./MessageBubble";

export function ChatPanel() {
  const messages = useStore((s) => s.messages);
  const isStreaming = useStore((s) => s.isStreaming);
  const sessionId = useStore((s) => s.sessionId);

  const [inputValue, setInputValue] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages change.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, [messages]);

  function handleSend() {
    const trimmed = inputValue.trim();
    if (!trimmed || isStreaming || !sessionId) return;

    sendQuestion(trimmed);
    setInputValue("");
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      {/* Scrollable message area */}
      <div
        ref={scrollRef}
        style={{ flex: 1, overflowY: "auto", padding: "0 24px" }}
      >
        <div style={{ maxWidth: 640, margin: "0 auto", paddingTop: 32, paddingBottom: 16 }}>
          <DataSummary onSuggestedQuestionClick={sendQuestion} />

          {messages.map((msg, idx) => (
            <MessageBubble key={idx} message={msg} />
          ))}
        </div>
      </div>

      {/* Fixed input bar */}
      <div
        style={{
          borderTop: "1px solid #e5e7eb",
          padding: "12px 24px",
          background: "#fff",
        }}
      >
        <div style={{ maxWidth: 640, margin: "0 auto", display: "flex", gap: 8 }}>
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Ask a question about your data..."
            disabled={isStreaming}
            style={{
              flex: 1,
              padding: "12px 16px",
              fontSize: 14,
              border: "1px solid #d1d5db",
              borderRadius: 8,
              background: isStreaming ? "#f9fafb" : "#fff",
              color: "#1f2937",
              outline: "none",
            }}
          />
          <button
            type="button"
            onClick={handleSend}
            disabled={isStreaming || !inputValue.trim()}
            aria-label="Send"
            style={{
              padding: "12px 20px",
              fontSize: 14,
              fontWeight: 500,
              background: isStreaming || !inputValue.trim() ? "#d1d5db" : "#1a73e8",
              color: "#fff",
              border: "none",
              borderRadius: 8,
              cursor: isStreaming || !inputValue.trim() ? "not-allowed" : "pointer",
            }}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Orchestrates sending a question: adds the user message to the store,
 * creates a placeholder assistant message, starts streaming, dispatches
 * SSE events into the store, and finalizes when done.
 *
 * Defined outside the component to allow DataSummary's suggested questions
 * to call it via the onSuggestedQuestionClick prop.
 */
function sendQuestion(question: string) {
  const { sessionId, addMessage, updateLastAssistantMessage, setStreaming } =
    useStore.getState();
  if (!sessionId) return;

  addMessage({ role: "user", content: question });
  addMessage({ role: "assistant", content: "" });
  setStreaming(true);

  sendChatMessage(sessionId, question, {
    onExplanation: (text) => {
      updateLastAssistantMessage({ content: text });
    },
    onResult: (result) => {
      updateLastAssistantMessage({
        stdout: result.stdout || undefined,
        figures: result.figures.length > 0 ? result.figures : undefined,
      });
    },
    onCleaningSuggestions: (suggestions) => {
      updateLastAssistantMessage({ cleaningSuggestions: suggestions });
    },
    onError: (message) => {
      updateLastAssistantMessage({ error: message });
    },
    onDone: () => {
      setStreaming(false);
    },
  }).catch((err: unknown) => {
    // Catch unexpected errors (e.g. malformed JSON in stream) so they don't
    // become unhandled promise rejections.
    const message = err instanceof Error ? err.message : "An unexpected error occurred.";
    updateLastAssistantMessage({ error: message });
    setStreaming(false);
  });
}
