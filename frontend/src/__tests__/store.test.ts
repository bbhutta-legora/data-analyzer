// store.test.ts
// Tests for Step 9 store additions: Message type, addMessage,
// updateLastAssistantMessage, setStreaming actions.
//
// Behaviors tested:
//  1. addMessage appends a message to the messages array
//  2. addMessage does not mutate existing messages (new reference)
//  3. updateLastAssistantMessage merges fields into the last assistant message
//  4. updateLastAssistantMessage is a no-op when no messages exist
//  5. setStreaming(true) sets isStreaming to true
//  6. setStreaming(false) sets isStreaming to false

import { describe, it, expect, beforeEach } from "vitest";
import { useStore } from "../store";
import type { Message } from "../store";

function resetStore() {
  useStore.setState({
    messages: [],
    isStreaming: false,
  });
}

describe("store — message actions", () => {
  beforeEach(resetStore);

  // Behavior 1
  it("addMessage appends a message to the messages array", () => {
    const msg: Message = { role: "user", content: "What is the mean?" };
    useStore.getState().addMessage(msg);

    const messages = useStore.getState().messages;
    expect(messages).toHaveLength(1);
    expect(messages[0].role).toBe("user");
    expect(messages[0].content).toBe("What is the mean?");
  });

  // Behavior 2
  it("addMessage does not mutate existing messages array", () => {
    const msg1: Message = { role: "user", content: "first" };
    useStore.getState().addMessage(msg1);
    const refBefore = useStore.getState().messages;

    const msg2: Message = { role: "assistant", content: "second" };
    useStore.getState().addMessage(msg2);
    const refAfter = useStore.getState().messages;

    expect(refAfter).not.toBe(refBefore);
    expect(refAfter).toHaveLength(2);
  });

  // Behavior 3
  it("updateLastAssistantMessage merges fields into the last assistant message", () => {
    useStore.getState().addMessage({ role: "user", content: "question" });
    useStore.getState().addMessage({ role: "assistant", content: "thinking..." });

    useStore.getState().updateLastAssistantMessage({
      content: "The average is 42.",
      code: "print(df.mean())",
      figures: ["base64data"],
    });

    const last = useStore.getState().messages[1];
    expect(last.content).toBe("The average is 42.");
    expect(last.code).toBe("print(df.mean())");
    expect(last.figures).toEqual(["base64data"]);
  });

  // Behavior 4
  it("updateLastAssistantMessage is a no-op when no messages exist", () => {
    // Should not throw
    useStore.getState().updateLastAssistantMessage({ content: "hello" });
    expect(useStore.getState().messages).toHaveLength(0);
  });
});

describe("store — streaming state", () => {
  beforeEach(resetStore);

  // Behavior 5
  it("setStreaming(true) sets isStreaming to true", () => {
    useStore.getState().setStreaming(true);
    expect(useStore.getState().isStreaming).toBe(true);
  });

  // Behavior 6
  it("setStreaming(false) sets isStreaming to false", () => {
    useStore.getState().setStreaming(true);
    useStore.getState().setStreaming(false);
    expect(useStore.getState().isStreaming).toBe(false);
  });
});
