// api.test.ts
// Tests for the SSE chat client added in Step 9.
//
// Behaviors tested:
//  7.  Calls POST /api/chat with session_id and question in the JSON body
//  8.  Parses an explanation SSE event and calls onExplanation
//  9.  Parses a result SSE event and calls onResult with parsed JSON
//  10. Parses a cleaning_suggestions SSE event and calls onCleaningSuggestions
//  11. Parses an error SSE event and calls onError
//  12. Calls onDone when a done event is received
//  13. Calls onError on a non-2xx HTTP response

import { describe, it, expect, vi, beforeEach } from "vitest";
import { sendChatMessage } from "../api";

// ── Helpers ────────────────────────────────────────────────────────────────

/** Build a fake SSE stream body from event/data pairs. */
function sseBody(events: Array<{ event: string; data: string }>): string {
  return events.map((e) => `event: ${e.event}\ndata: ${e.data}\n\n`).join("");
}

/** Create a ReadableStream from a string (simulates a streaming response). */
function streamFromString(text: string): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text));
      controller.close();
    },
  });
}

function mockFetchSSE(body: string, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ "content-type": "text/event-stream" }),
    body: streamFromString(body),
    json: () =>
      Promise.resolve({ error: "session_not_found", detail: "Not found" }),
  });
}

function makeCallbacks() {
  return {
    onExplanation: vi.fn(),
    onResult: vi.fn(),
    onCleaningSuggestions: vi.fn(),
    onError: vi.fn(),
    onDone: vi.fn(),
  };
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe("sendChatMessage — SSE client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // Behavior 7
  it("calls POST /api/chat with session_id and question", async () => {
    const body = sseBody([{ event: "done", data: "" }]);
    const fetchMock = mockFetchSSE(body);
    vi.stubGlobal("fetch", fetchMock);

    const cbs = makeCallbacks();
    await sendChatMessage("sess-123", "What is the mean?", cbs);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/chat");
    expect(init.method).toBe("POST");
    const parsed = JSON.parse(init.body);
    expect(parsed.session_id).toBe("sess-123");
    expect(parsed.question).toBe("What is the mean?");
  });

  // Behavior 8
  it("parses an explanation event and calls onExplanation", async () => {
    const body = sseBody([
      { event: "explanation", data: "The average is 42." },
      { event: "done", data: "" },
    ]);
    vi.stubGlobal("fetch", mockFetchSSE(body));

    const cbs = makeCallbacks();
    await sendChatMessage("s1", "q", cbs);

    expect(cbs.onExplanation).toHaveBeenCalledWith("The average is 42.");
  });

  // Behavior 9
  it("parses a result event and calls onResult with parsed JSON", async () => {
    const resultPayload = JSON.stringify({
      stdout: "42.0",
      figures: ["base64png"],
    });
    const body = sseBody([
      { event: "explanation", data: "Explaining." },
      { event: "result", data: resultPayload },
      { event: "done", data: "" },
    ]);
    vi.stubGlobal("fetch", mockFetchSSE(body));

    const cbs = makeCallbacks();
    await sendChatMessage("s1", "q", cbs);

    expect(cbs.onResult).toHaveBeenCalledWith({
      stdout: "42.0",
      figures: ["base64png"],
    });
  });

  // Behavior 10
  it("parses a cleaning_suggestions event and calls onCleaningSuggestions", async () => {
    const suggestions = JSON.stringify([
      { description: "Missing values", options: ["Drop", "Fill"] },
    ]);
    const body = sseBody([
      { event: "explanation", data: "Check." },
      { event: "cleaning_suggestions", data: suggestions },
      { event: "done", data: "" },
    ]);
    vi.stubGlobal("fetch", mockFetchSSE(body));

    const cbs = makeCallbacks();
    await sendChatMessage("s1", "q", cbs);

    expect(cbs.onCleaningSuggestions).toHaveBeenCalledWith([
      { description: "Missing values", options: ["Drop", "Fill"] },
    ]);
  });

  // Behavior 11
  it("parses an error event and calls onError", async () => {
    const body = sseBody([
      { event: "error", data: "NameError: x is not defined" },
      { event: "done", data: "" },
    ]);
    vi.stubGlobal("fetch", mockFetchSSE(body));

    const cbs = makeCallbacks();
    await sendChatMessage("s1", "q", cbs);

    expect(cbs.onError).toHaveBeenCalledWith("NameError: x is not defined");
  });

  // Behavior 12
  it("calls onDone when a done event is received", async () => {
    const body = sseBody([
      { event: "explanation", data: "Done." },
      { event: "done", data: "" },
    ]);
    vi.stubGlobal("fetch", mockFetchSSE(body));

    const cbs = makeCallbacks();
    await sendChatMessage("s1", "q", cbs);

    expect(cbs.onDone).toHaveBeenCalledOnce();
  });

  // Behavior 13
  it("calls onError on a non-2xx HTTP response", async () => {
    const fetchMock = mockFetchSSE("", 404);
    vi.stubGlobal("fetch", fetchMock);

    const cbs = makeCallbacks();
    await sendChatMessage("bad-session", "q", cbs);

    expect(cbs.onError).toHaveBeenCalled();
    expect(cbs.onDone).toHaveBeenCalled();
  });
});
