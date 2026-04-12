// MLWizard.tsx
// Inline ML wizard rendered within the ChatPanel message stream.
// Guides the user through: target selection → feature selection →
// training (auto-triggers preprocessing + model + training backend stages) → results.
//
// Completed stages collapse to a one-line summary card so the stream doesn't
// grow unbounded. The active stage shows controls appropriate to that step.
//
// PRD ref: #5 (Guided ML)
// Architecture ref: "Guided ML frontend" in planning/architecture.md

import { useEffect, useState } from "react";
import { sendMlStep } from "../api";

// ── Types ─────────────────────────────────────────────────────────────────────

type WizardPhase = "target" | "features" | "training" | "results";

interface CompletedSummary {
  phase: WizardPhase;
  label: string;
}

interface TrainingResult {
  stdout: string;
  figures: string[];
}

export interface MLWizardProps {
  columns: string[];
  sessionId: string;
  onExit: () => void;
}

// ── Card shell ────────────────────────────────────────────────────────────────

function WizardCard({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        border: "1px solid #c7d2fe",
        borderRadius: 8,
        background: "#f5f3ff",
        padding: "16px 20px",
        marginBottom: 12,
      }}
    >
      {children}
    </div>
  );
}

function CollapsedCard({ label }: { label: string }) {
  return (
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        background: "#f9fafb",
        padding: "8px 16px",
        marginBottom: 8,
        fontSize: 13,
        color: "#6b7280",
        display: "flex",
        alignItems: "center",
        gap: 6,
      }}
    >
      <span style={{ color: "#22c55e" }}>✓</span>
      {label}
    </div>
  );
}

// ── Primary action buttons ────────────────────────────────────────────────────

const buttonBase: React.CSSProperties = {
  padding: "7px 16px",
  fontSize: 13,
  fontWeight: 500,
  border: "none",
  borderRadius: 6,
  cursor: "pointer",
};

function PrimaryButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        ...buttonBase,
        background: disabled ? "#d1d5db" : "#6d28d9",
        color: "#fff",
        cursor: disabled ? "not-allowed" : "pointer",
      }}
    >
      {children}
    </button>
  );
}

function SecondaryButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        ...buttonBase,
        background: "#fff",
        color: disabled ? "#9ca3af" : "#374151",
        border: "1px solid #d1d5db",
        cursor: disabled ? "not-allowed" : "pointer",
      }}
    >
      {children}
    </button>
  );
}

// ── MLWizard component ────────────────────────────────────────────────────────

export function MLWizard({ columns, sessionId, onExit }: MLWizardProps) {
  const [phase, setPhase] = useState<WizardPhase>("target");
  const [completedPhases, setCompletedPhases] = useState<CompletedSummary[]>([]);

  // Selections carried across stages
  const [selectedTarget, setSelectedTarget] = useState("");
  const [selectedFeatures, setSelectedFeatures] = useState<string[]>([]);

  // Per-stage transient state
  const [isStageStreaming, setIsStageStreaming] = useState(false);
  const [stageExplanation, setStageExplanation] = useState<string | null>(null);
  const [stageError, setStageError] = useState<string | null>(null);
  const [trainingResult, setTrainingResult] = useState<TrainingResult | null>(null);

  // Stored so Retry can re-send the exact same call
  const [lastStage, setLastStage] = useState("");
  const [lastUserInput, setLastUserInput] = useState("");

  // ── Training auto-sequence ─────────────────────────────────────────────────
  // When phase changes to "training" the wizard auto-calls preprocessing → model
  // → training without additional user interaction. isStageStreaming stays true
  // throughout so the loading indicator remains visible.

  useEffect(() => {
    if (phase !== "training") return;

    const featuresInput = selectedFeatures.join(", ");

    async function runTrainingSequence() {
      setIsStageStreaming(true);
      setStageError(null);

      let hadError = false;

      // Preprocessing (auto, no user input needed)
      await sendMlStep(sessionId, "preprocessing", featuresInput, {
        onExplanation: () => {},
        onResult: () => {},
        onMlState: () => {},
        onError: (msg) => {
          hadError = true;
          setStageError(msg);
        },
        onDone: () => {},
      });

      if (hadError) {
        setIsStageStreaming(false);
        return;
      }

      // Model selection (auto)
      await sendMlStep(sessionId, "model", "auto", {
        onExplanation: () => {},
        onResult: () => {},
        onMlState: () => {},
        onError: (msg) => {
          hadError = true;
          setStageError(msg);
        },
        onDone: () => {},
      });

      if (hadError) {
        setIsStageStreaming(false);
        return;
      }

      // Training (auto)
      let explanation = "";
      let result: TrainingResult | null = null;

      await sendMlStep(sessionId, "training", featuresInput, {
        onExplanation: (text) => {
          explanation = text;
        },
        onResult: (r) => {
          result = r;
        },
        onMlState: () => {},
        onError: (msg) => {
          hadError = true;
          setStageError(msg);
        },
        onDone: () => {},
      });

      if (hadError) {
        setIsStageStreaming(false);
        return;
      }

      setStageExplanation(explanation);
      setTrainingResult(result);
      setCompletedPhases((prev) => [
        ...prev,
        { phase: "training", label: "Training: finished" },
      ]);
      setPhase("results");
      setIsStageStreaming(false);
    }

    runTrainingSequence().catch((err: unknown) => {
      const message =
        err instanceof Error ? err.message : "An unexpected error occurred.";
      setStageError(message);
      setIsStageStreaming(false);
    });
    // Phase is the only trigger; selectedFeatures is captured correctly at the
    // moment phase transitions to "training" (right after features confirm).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  // ── Stage submission ───────────────────────────────────────────────────────

  function submitStage(stage: string, userInput: string) {
    setLastStage(stage);
    setLastUserInput(userInput);
    setIsStageStreaming(true);
    setStageError(null);

    let explanation = "";
    let hadError = false;

    sendMlStep(sessionId, stage, userInput, {
      onExplanation: (text) => {
        explanation = text;
      },
      onResult: () => {},
      onMlState: () => {},
      onError: (msg) => {
        hadError = true;
        setStageError(msg);
        setIsStageStreaming(false);
      },
      onDone: () => {
        // Don't advance phases if the stream signalled an error.
        if (hadError) return;

        setStageExplanation(explanation);
        setIsStageStreaming(false);

        if (stage === "target") {
          setCompletedPhases((prev) => [
            ...prev,
            { phase: "target", label: `Target: ${userInput}` },
          ]);
          // Pre-select all non-target columns for the features stage.
          setSelectedFeatures(columns.filter((c) => c !== userInput));
          setPhase("features");
        } else if (stage === "features") {
          setCompletedPhases((prev) => [
            ...prev,
            { phase: "features", label: `Features: ${userInput}` },
          ]);
          // Transition triggers the training useEffect.
          setPhase("training");
        }
      },
    }).catch((err: unknown) => {
      const message =
        err instanceof Error ? err.message : "An unexpected error occurred.";
      setStageError(message);
      setIsStageStreaming(false);
    });
  }

  function handleRetry() {
    submitStage(lastStage, lastUserInput);
  }

  function handleBack() {
    // Return to target: remove its completed summary, restore phase.
    setCompletedPhases((prev) => prev.filter((s) => s.phase !== "target"));
    setStageError(null);
    setPhase("target");
  }

  // ── Render helpers ─────────────────────────────────────────────────────────

  function renderTargetStage() {
    return (
      <WizardCard>
        <div style={{ fontWeight: 600, marginBottom: 12, color: "#4c1d95" }}>
          Select Target Column
        </div>
        {stageExplanation && (
          <p style={{ fontSize: 13, color: "#374151", marginBottom: 12 }}>
            {stageExplanation}
          </p>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 16 }}>
          {columns.map((col) => (
            <label key={col} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
              <input
                type="radio"
                name="target-column"
                value={col}
                checked={selectedTarget === col}
                onChange={() => setSelectedTarget(col)}
                aria-label={col}
              />
              {col}
            </label>
          ))}
        </div>
        {stageError && (
          <p style={{ color: "#dc2626", fontSize: 13, marginBottom: 10 }}>
            {stageError}
          </p>
        )}
        <div style={{ display: "flex", gap: 8 }}>
          {stageError ? (
            <PrimaryButton onClick={handleRetry} disabled={isStageStreaming}>
              Retry
            </PrimaryButton>
          ) : (
            <PrimaryButton
              onClick={() => submitStage("target", selectedTarget)}
              disabled={!selectedTarget || isStageStreaming}
            >
              Confirm
            </PrimaryButton>
          )}
          <SecondaryButton onClick={onExit} disabled={isStageStreaming}>
            Cancel
          </SecondaryButton>
        </div>
      </WizardCard>
    );
  }

  function renderFeaturesStage() {
    function toggleFeature(col: string) {
      setSelectedFeatures((prev) =>
        prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col],
      );
    }

    const nonTargetColumns = columns.filter((c) => c !== selectedTarget);

    return (
      <WizardCard>
        <div style={{ fontWeight: 600, marginBottom: 12, color: "#4c1d95" }}>
          Select Features
        </div>
        {stageExplanation && (
          <p style={{ fontSize: 13, color: "#374151", marginBottom: 12 }}>
            {stageExplanation}
          </p>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 16 }}>
          {nonTargetColumns.map((col) => (
            <label key={col} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
              <input
                type="checkbox"
                checked={selectedFeatures.includes(col)}
                onChange={() => toggleFeature(col)}
                aria-label={col}
              />
              {col}
            </label>
          ))}
        </div>
        {stageError && (
          <p style={{ color: "#dc2626", fontSize: 13, marginBottom: 10 }}>
            {stageError}
          </p>
        )}
        <div style={{ display: "flex", gap: 8 }}>
          {stageError ? (
            <PrimaryButton onClick={handleRetry} disabled={isStageStreaming}>
              Retry
            </PrimaryButton>
          ) : (
            <PrimaryButton
              onClick={() => submitStage("features", selectedFeatures.join(", "))}
              disabled={isStageStreaming}
            >
              Confirm
            </PrimaryButton>
          )}
          <SecondaryButton onClick={handleBack} disabled={isStageStreaming}>
            Back
          </SecondaryButton>
          <SecondaryButton onClick={onExit} disabled={isStageStreaming}>
            Cancel
          </SecondaryButton>
        </div>
      </WizardCard>
    );
  }

  function renderTrainingStage() {
    return (
      <WizardCard>
        <div style={{ fontWeight: 600, marginBottom: 12, color: "#4c1d95" }}>
          Running Training
        </div>
        {stageError ? (
          <>
            <p style={{ color: "#dc2626", fontSize: 13, marginBottom: 10 }}>
              {stageError}
            </p>
            <div style={{ display: "flex", gap: 8 }}>
              <PrimaryButton onClick={handleRetry}>Retry</PrimaryButton>
              <SecondaryButton onClick={onExit}>Cancel</SecondaryButton>
            </div>
          </>
        ) : (
          <p style={{ fontSize: 13, color: "#6b7280" }}>Training model...</p>
        )}
      </WizardCard>
    );
  }

  function renderResultsStage() {
    return (
      <WizardCard>
        <div style={{ fontWeight: 600, marginBottom: 12, color: "#4c1d95" }}>
          Results
        </div>
        {stageExplanation && (
          <p style={{ fontSize: 13, color: "#374151", marginBottom: 12 }}>
            {stageExplanation}
          </p>
        )}
        {trainingResult?.stdout && (
          <pre
            style={{
              background: "#1f2937",
              color: "#f9fafb",
              borderRadius: 6,
              padding: "10px 14px",
              fontSize: 12,
              overflowX: "auto",
              marginBottom: 12,
            }}
          >
            {trainingResult.stdout}
          </pre>
        )}
        {trainingResult?.figures?.map((fig, i) => (
          <img
            key={i}
            src={`data:image/png;base64,${fig}`}
            alt={`Training figure ${i + 1}`}
            style={{ maxWidth: "100%", borderRadius: 6, marginBottom: 8 }}
          />
        ))}
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <PrimaryButton onClick={onExit}>Done — return to chat</PrimaryButton>
        </div>
      </WizardCard>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div>
      {completedPhases.map((s) => (
        <CollapsedCard key={s.phase} label={s.label} />
      ))}

      {phase === "target" && renderTargetStage()}
      {phase === "features" && renderFeaturesStage()}
      {phase === "training" && renderTrainingStage()}
      {phase === "results" && renderResultsStage()}
    </div>
  );
}
