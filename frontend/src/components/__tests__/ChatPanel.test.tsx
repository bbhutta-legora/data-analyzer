// ChatPanel.test.tsx
// Tests for the ChatPanel component added in Step 9.
//
// Behaviors tested:
//  23. Renders the DataSummary as the first item in the chat
//  24. Renders a MessageBubble for each message in the store
//  25. Typing in the input and clicking Send adds a user message to the store
//  26. Input is cleared after sending
//  27. Input and Send button are disabled while isStreaming is true
//  28. Send button is disabled when input is empty or whitespace-only
//  29. Clicking a suggested question in DataSummary sends it as a chat message

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatPanel } from "../ChatPanel";
import { useStore } from "../../store";
import type { DatasetInfo } from "../../store";

// Mock sendChatMessage so tests don't make real fetch calls
vi.mock("../../api", () => ({
  sendChatMessage: vi.fn().mockResolvedValue(undefined),
}));

const TEST_DATASET_INFO: DatasetInfo = {
  datasets: {
    data: {
      row_count: 100,
      column_count: 3,
      columns: ["a", "b", "c"],
      dtypes: { a: "int64", b: "float64", c: "object" },
      missing_values: { a: 0, b: 0, c: 0 },
    },
  },
  summary: {
    explanation: "This dataset has 100 rows.",
    cleaning_suggestions: [],
    suggested_questions: ["What is the average of column a?"],
  },
};

function resetStore() {
  useStore.setState({
    messages: [],
    isStreaming: false,
    datasetInfo: TEST_DATASET_INFO,
    sessionId: "test-session",
  });
}

describe("ChatPanel", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  // Behavior 23
  it("renders the DataSummary as the first item", () => {
    render(<ChatPanel />);

    // DataSummary renders the explanation from the summary
    expect(screen.getByText("This dataset has 100 rows.")).toBeInTheDocument();
  });

  // Behavior 24
  it("renders a MessageBubble for each message in the store", () => {
    useStore.setState({
      messages: [
        { role: "user", content: "Hello" },
        { role: "assistant", content: "Hi there" },
      ],
    });

    render(<ChatPanel />);

    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("Hi there")).toBeInTheDocument();
  });

  // Behavior 25
  it("typing and clicking Send adds a user message to the store", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    const input = screen.getByPlaceholderText(/ask a question/i);
    await user.type(input, "What is the mean?");
    await user.click(screen.getByRole("button", { name: /send/i }));

    const messages = useStore.getState().messages;
    expect(messages.length).toBeGreaterThanOrEqual(1);
    expect(messages[0]).toEqual({ role: "user", content: "What is the mean?" });
  });

  // Behavior 26
  it("input is cleared after sending", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    const input = screen.getByPlaceholderText(/ask a question/i);
    await user.type(input, "Test question");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(input).toHaveValue("");
  });

  // Behavior 27
  it("input and Send button are disabled while isStreaming", () => {
    useStore.setState({ isStreaming: true });
    render(<ChatPanel />);

    const input = screen.getByPlaceholderText(/ask a question/i);
    const sendButton = screen.getByRole("button", { name: /send/i });

    expect(input).toBeDisabled();
    expect(sendButton).toBeDisabled();
  });

  // Behavior 28
  it("Send button is disabled when input is empty", () => {
    render(<ChatPanel />);

    const sendButton = screen.getByRole("button", { name: /send/i });
    expect(sendButton).toBeDisabled();
  });

  // Behavior 29
  it("clicking a suggested question sends it as a chat message", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    const suggestedQ = screen.getByText("What is the average of column a?");
    await user.click(suggestedQ);

    const messages = useStore.getState().messages;
    expect(messages.length).toBeGreaterThanOrEqual(1);
    expect(messages[0]).toEqual({
      role: "user",
      content: "What is the average of column a?",
    });
  });
});
