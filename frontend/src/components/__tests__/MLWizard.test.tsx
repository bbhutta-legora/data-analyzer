// MLWizard.test.tsx
// Tests for the ML wizard UI (Step 13).
//
// Behaviors tested:
//  1.  "Build a Model" button triggers wizard target stage
//  2.  Target stage renders column names as radio options
//  3.  Selecting target + confirming sends ML step request, advances to features
//  4.  Features stage renders checkboxes and LLM explanation text
//  5.  Results stage displays evaluation metrics (stdout)
//  6.  Results stage renders figure images
//  7.  Error in a stage shows an error message and Retry button
//  8.  Confirm button is disabled until user makes a selection (target stage)
//  9.  Training stage shows a loading indicator
// 10.  Cancel exits the wizard and re-enables chat
// 11. "Done — return to chat" exits the wizard
// 12.  Chat input is disabled while wizard is active
// 13.  "Build a Model" button is disabled while wizard is active or streaming
// 14.  Back button returns to previous stage with selection preserved
// 16.  Confirm and Back are disabled while a stage's request is streaming

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatPanel } from "../ChatPanel";
import { useStore } from "../../store";
import type { DatasetInfo } from "../../store";
import { sendMlStep } from "../../api";

vi.mock("../../api", () => ({
  sendChatMessage: vi.fn().mockResolvedValue(undefined),
  exportNotebook: vi.fn().mockResolvedValue(undefined),
  resetDatasets: vi.fn().mockResolvedValue({ datasets: {} }),
  sendMlStep: vi.fn(),
}));

// vi.clearAllMocks() (called per-describe) clears call history but does NOT
// flush the mockImplementationOnce queue. Unconsumed one-time mocks from one
// test would otherwise leak into the next. Reset the queue globally instead.
beforeEach(() => {
  vi.mocked(sendMlStep).mockReset();
});

const TEST_COLUMNS = ["price", "category", "rating"];

const TEST_DATASET_INFO: DatasetInfo = {
  datasets: {
    data: {
      row_count: 100,
      column_count: 3,
      columns: TEST_COLUMNS,
      dtypes: { price: "float64", category: "object", rating: "int64" },
      missing_values: { price: 0, category: 0, rating: 0 },
    },
  },
  summary: {
    explanation: "Dataset has 100 rows.",
    cleaning_suggestions: [],
    suggested_questions: [],
  },
};

function resetStore() {
  useStore.setState({
    messages: [],
    isStreaming: false,
    datasetInfo: TEST_DATASET_INFO,
    sessionId: "test-session",
    hasAppliedCleaning: false,
    mlWizardActive: false,
  });
}

// Simulate a successful ML step: calls onExplanation, optional onResult, then onDone.
function mockMlStepSuccess(
  explanation: string,
  result?: { stdout: string; figures: string[] },
) {
  vi.mocked(sendMlStep).mockImplementationOnce(
    async (_sid, _stage, _input, callbacks) => {
      callbacks.onExplanation(explanation);
      if (result) callbacks.onResult(result);
      callbacks.onMlState({});
      callbacks.onDone();
    },
  );
}

// Simulate a failing ML step: calls onError then onDone.
function mockMlStepError(message: string) {
  vi.mocked(sendMlStep).mockImplementationOnce(
    async (_sid, _stage, _input, callbacks) => {
      callbacks.onError(message);
      callbacks.onDone();
    },
  );
}

// Simulate a hanging ML step: never calls onDone, keeping isStreaming true.
function mockMlStepHanging() {
  vi.mocked(sendMlStep).mockImplementationOnce(() => new Promise(() => {}));
}

// Navigate past the target stage by clicking "Build a Model", selecting a column,
// and confirming. Leaves the test at the features stage.
async function advanceToFeatures(
  user: ReturnType<typeof userEvent.setup>,
  targetColumn = "price",
) {
  mockMlStepSuccess(`LLM target explanation for ${targetColumn}`);

  await user.click(screen.getByRole("button", { name: /build a model/i }));
  await user.click(screen.getByRole("radio", { name: targetColumn }));
  await user.click(screen.getByRole("button", { name: /^confirm$/i }));

  await waitFor(() =>
    expect(screen.getByText(/select features/i)).toBeInTheDocument(),
  );
}

// Navigate all the way to the results stage (target → features → training).
async function advanceToResults(user: ReturnType<typeof userEvent.setup>) {
  await advanceToFeatures(user);

  // features confirm + auto-triggered backend calls (preprocessing, model, training)
  mockMlStepSuccess("LLM features explanation");
  mockMlStepSuccess("Preprocessing done");
  mockMlStepSuccess("Model selected");
  mockMlStepSuccess("Training complete", {
    stdout: "Accuracy: 0.95\nPrecision: 0.90",
    figures: ["base64encodedimage1"],
  });

  await user.click(screen.getByRole("button", { name: /^confirm$/i }));

  await waitFor(() =>
    expect(screen.getByText(/Accuracy: 0\.95/)).toBeInTheDocument(),
  );
}

// ── Wizard activation ────────────────────────────────────────────────────────

describe("Wizard activation", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  // Behavior 1a
  it("clicking Build a Model shows wizard with target stage", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.click(screen.getByRole("button", { name: /build a model/i }));

    expect(screen.getByText(/select target column/i)).toBeInTheDocument();
  });

  // Behavior 13a
  it("Build a Model button is disabled when wizard is active", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.click(screen.getByRole("button", { name: /build a model/i }));

    expect(
      screen.getByRole("button", { name: /build a model/i }),
    ).toBeDisabled();
  });

  // Behavior 13b
  it("Build a Model button is disabled when isStreaming is true", () => {
    useStore.setState({ isStreaming: true });
    render(<ChatPanel />);

    expect(
      screen.getByRole("button", { name: /build a model/i }),
    ).toBeDisabled();
  });
});

// ── Target stage ─────────────────────────────────────────────────────────────

describe("Target stage", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  // Behavior 2a
  it("shows one radio option for each column in the dataset", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);
    await user.click(screen.getByRole("button", { name: /build a model/i }));

    for (const col of TEST_COLUMNS) {
      expect(screen.getByRole("radio", { name: col })).toBeInTheDocument();
    }
  });

  // Behavior 8a
  it("Confirm button is disabled until a column is selected", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);
    await user.click(screen.getByRole("button", { name: /build a model/i }));

    expect(
      screen.getByRole("button", { name: /^confirm$/i }),
    ).toBeDisabled();
  });

  // Behavior 3a
  it("selecting a column and clicking Confirm calls sendMlStep with stage target", async () => {
    // Mock target + all auto-triggered follow-ons so the test doesn't hang.
    mockMlStepSuccess("Target explanation");
    mockMlStepSuccess("features ok");
    mockMlStepSuccess("preprocessing ok");
    mockMlStepSuccess("model ok");
    mockMlStepSuccess("training ok", { stdout: "ok", figures: [] });

    const user = userEvent.setup();
    render(<ChatPanel />);
    await user.click(screen.getByRole("button", { name: /build a model/i }));
    await user.click(screen.getByRole("radio", { name: "price" }));
    await user.click(screen.getByRole("button", { name: /^confirm$/i }));

    await waitFor(() => {
      expect(vi.mocked(sendMlStep)).toHaveBeenCalledWith(
        "test-session",
        "target",
        "price",
        expect.any(Object),
      );
    });
  });
});

// ── Features stage ───────────────────────────────────────────────────────────

describe("Features stage", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  // Behavior 3b
  it("after target success, target collapses and features stage appears", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await advanceToFeatures(user, "price");

    // Features stage heading visible
    expect(screen.getByText(/select features/i)).toBeInTheDocument();
    // Target summary card visible (collapsed with selection)
    expect(screen.getByText(/target:.*price/i)).toBeInTheDocument();
  });

  // Behavior 4a
  it("features stage shows checkboxes and LLM explanation text", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await advanceToFeatures(user, "price");

    // Explanation from the target-stage LLM response is displayed
    expect(
      screen.getByText(/LLM target explanation for price/i),
    ).toBeInTheDocument();

    // Checkboxes for the non-target columns
    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes.length).toBeGreaterThan(0);
  });

  // Behavior 4b
  it("toggling a checkbox changes its checked state", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await advanceToFeatures(user, "price");

    const checkbox = screen.getByRole("checkbox", { name: "category" });
    expect(checkbox).toBeChecked();

    await user.click(checkbox);
    expect(checkbox).not.toBeChecked();

    await user.click(checkbox);
    expect(checkbox).toBeChecked();
  });

  // Behavior 8b
  it("Confirm button is enabled on features stage (features pre-selected)", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await advanceToFeatures(user, "price");

    expect(
      screen.getByRole("button", { name: /^confirm$/i }),
    ).toBeEnabled();
  });

  // Behavior 3c
  it("confirming features calls sendMlStep with stage features", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await advanceToFeatures(user, "price");

    mockMlStepSuccess("features explanation");
    mockMlStepSuccess("preprocessing ok");
    mockMlStepSuccess("model ok");
    mockMlStepSuccess("training ok", { stdout: "done", figures: [] });

    await user.click(screen.getByRole("button", { name: /^confirm$/i }));

    await waitFor(() => {
      const allCalls = vi.mocked(sendMlStep).mock.calls;
      const featuresCall = allCalls.find((c) => c[1] === "features");
      expect(featuresCall).toBeDefined();
    });
  });
});

// ── Stage navigation ─────────────────────────────────────────────────────────

describe("Stage navigation", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  // Behavior 14a
  it("Back on features stage returns to target with previous selection preserved", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await advanceToFeatures(user, "price");

    await user.click(screen.getByRole("button", { name: /back/i }));

    expect(screen.getByText(/select target column/i)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "price" })).toBeChecked();
  });

  // Behavior 10a
  it("Cancel removes the wizard and re-enables chat input", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.click(screen.getByRole("button", { name: /build a model/i }));
    expect(screen.getByPlaceholderText(/ask a question/i)).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(
      screen.queryByText(/select target column/i),
    ).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText(/ask a question/i)).toBeEnabled();
  });

  // Behavior 16a
  it("Confirm and Back are disabled while a stage request is streaming", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await advanceToFeatures(user, "price");

    // Hang the features request
    mockMlStepHanging();

    await user.click(screen.getByRole("button", { name: /^confirm$/i }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /^confirm$/i }),
      ).toBeDisabled();
    });
    expect(screen.getByRole("button", { name: /back/i })).toBeDisabled();
  });
});

// ── Training stage ───────────────────────────────────────────────────────────

describe("Training stage", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  // Behavior 9a
  it("shows a loading indicator while training is in progress", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await advanceToFeatures(user, "price");

    // features succeeds, then preprocessing hangs (still in training phase)
    mockMlStepSuccess("features explanation");
    mockMlStepHanging();

    await user.click(screen.getByRole("button", { name: /^confirm$/i }));

    await waitFor(() => {
      expect(screen.getByText(/training model/i)).toBeInTheDocument();
    });
  });
});

// ── Results stage ────────────────────────────────────────────────────────────

describe("Results stage", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  // Behavior 5a
  it("displays stdout metrics from the training response", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await advanceToResults(user);

    expect(screen.getByText(/Accuracy: 0\.95/)).toBeInTheDocument();
  });

  // Behavior 6a
  it("renders figure images from the training response", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await advanceToResults(user);

    const images = screen.getAllByRole("img");
    expect(images.length).toBeGreaterThan(0);
  });

  // Behavior 5b
  it("displays the LLM explanation text", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await advanceToResults(user);

    expect(screen.getByText(/Training complete/i)).toBeInTheDocument();
  });

  // Behavior 11a
  it("Done — return to chat removes wizard and re-enables chat input", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await advanceToResults(user);

    await user.click(
      screen.getByRole("button", { name: /done.*return to chat/i }),
    );

    expect(
      screen.queryByText(/select target column/i),
    ).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText(/ask a question/i)).toBeEnabled();
  });
});

// ── Error handling ───────────────────────────────────────────────────────────

describe("Error handling", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  // Behavior 7a
  it("shows error message when sendMlStep calls onError", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.click(screen.getByRole("button", { name: /build a model/i }));
    mockMlStepError("LLM call failed: rate limit");
    await user.click(screen.getByRole("radio", { name: "price" }));
    await user.click(screen.getByRole("button", { name: /^confirm$/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/LLM call failed: rate limit/i),
      ).toBeInTheDocument();
    });
  });

  // Behavior 7b
  it("Retry button re-sends the same stage request", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.click(screen.getByRole("button", { name: /build a model/i }));
    mockMlStepError("LLM call failed");
    await user.click(screen.getByRole("radio", { name: "price" }));
    await user.click(screen.getByRole("button", { name: /^confirm$/i }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /retry/i }),
      ).toBeInTheDocument();
    });

    // Retry succeeds; wizard advances to features (no auto-trigger after target)
    mockMlStepSuccess("Retry worked");
    await user.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => {
      const targetCalls = vi.mocked(sendMlStep).mock.calls.filter(
        (c) => c[1] === "target",
      );
      expect(targetCalls.length).toBe(2); // original attempt + retry
    });
  });
});

// ── Chat interaction during wizard ───────────────────────────────────────────

describe("Chat interaction during wizard", () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  // Behavior 12a
  it("chat input and Send button are disabled while wizard is active", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.click(screen.getByRole("button", { name: /build a model/i }));

    expect(screen.getByPlaceholderText(/ask a question/i)).toBeDisabled();
    expect(screen.getByRole("button", { name: /^send$/i })).toBeDisabled();
  });

  // Behavior 12b
  it("chat input is re-enabled when wizard exits via Cancel", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.click(screen.getByRole("button", { name: /build a model/i }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(
      screen.getByPlaceholderText(/ask a question/i),
    ).not.toBeDisabled();
  });
});
