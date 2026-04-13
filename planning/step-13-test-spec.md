# Step 13 — Guided ML Frontend: Test Spec

Confirmed test spec for Step 13. This is the output of Phase A (TEST-STRATEGY.md Steps 1–2), reviewed and approved via interactive HTML mockup.

**UI direction chosen:** Option A — inline in chat. Wizard stages render as structured message cards in the message stream. Completed stages collapse into summary cards. A "Build a Model" button in the chat header triggers the wizard.

---

## Behaviors

### High Risk

| # | Behavior | Why |
|---|----------|-----|
| 1 | Clicking "Build a Model" adds a wizard target stage to the message stream | If the entry point is broken, the entire ML feature is unreachable. |
| 2 | Target stage renders column names from `datasetInfo` as selectable radio options | Without columns to choose from, the user can't define what to predict. |
| 3 | Selecting a target and clicking Confirm sends the ML step request and advances to features | Core stage-transition loop. If it breaks, the wizard gets stuck. |
| 4 | Features stage renders the LLM's suggested features as toggleable checkboxes | If the user can't customize features, the model trains on whatever the LLM guessed. |
| 5 | Results stage displays evaluation metrics from the training response | Metrics are the primary output of the entire workflow. |
| 6 | Results stage renders figure images (charts) from the training response | Charts are key to understanding model quality. |
| 7 | When a stage errors, the wizard shows an error message instead of advancing | Without error display, the user sees a blank state with no feedback. |

### Medium Risk

| # | Behavior | Why |
|---|----------|-----|
| 8 | The wizard does not advance without the user clicking Confirm at each step | Auto-advancing removes user control over the ML workflow. |
| 9 | Training stage shows a loading indicator while waiting for the backend | Without feedback during multi-second training, the user thinks the app froze. |
| 10 | Cancel button exits the wizard and re-enables normal chat | If the user can't exit, they're trapped and must reload the page. |
| 11 | "Done — return to chat" exits the wizard after results and re-enables chat input | Same as cancel — user needs a way out after completing the flow. |
| 12 | Chat input is disabled while the wizard is active | Sending chat messages during an active wizard could confuse backend session state. |
| 13 | Build a Model button is disabled while the wizard is active or while streaming | Starting a second wizard would corrupt ML state. |
| 14 | Back button returns to the previous stage | Users need to correct target/feature choices without restarting. |

### Edge Cases

| # | Behavior | Why |
|---|----------|-----|
| 15 | Completed stages collapse into a summary card showing the choice made | Without collapse, the message stream gets very long and progress is unclear. |
| 16 | Confirm button is disabled while a stage's API request is streaming | Double-submitting would send duplicate requests and could corrupt session state. |

---

## Test Cases

### Wizard activation

- **1a.** When the user clicks "Build a Model," a wizard message with the title "Select Target Column" and radio options for each column in the dataset appears in the message stream.
- **13a.** When the wizard is active, the "Build a Model" button is disabled.
- **13b.** When `isStreaming` is true, the "Build a Model" button is disabled.

### Target stage

- **2a.** When the target stage renders, it shows one radio option for each column name in `datasetInfo.datasets` (e.g., "price", "category", "rating").
- **8a.** When the target stage renders, the Confirm button is disabled until the user selects a column.
- **3a.** When the user selects a column and clicks Confirm, `sendMlStep` is called with `stage: "target"` and `user_input` containing the selected column name.

### Features stage

- **3b.** When the target stage's API call succeeds, the target stage collapses into a summary card (showing the selected column) and the features stage appears.
- **3c.** When the user confirms features, `sendMlStep` is called with `stage: "features"` and the selected feature names as `user_input`, and the features stage collapses into a summary card.
- **4a.** When the features stage renders, it shows checkboxes. The LLM's explanation text is displayed above the checkboxes.
- **4b.** When the user toggles a checkbox, its checked state changes.
- **8b.** When the features stage renders, the Confirm button is enabled (features come pre-selected by the LLM).

### Stage navigation

- **14a.** When the user clicks Back on the features stage, the wizard returns to the target stage with the previous selection preserved.
- **10a.** When the user clicks Cancel at any stage, the wizard is removed and the chat input is re-enabled.
- **16a.** When a stage's API request is in progress (streaming), the Confirm and Back buttons are disabled.

### Training stage

- **9a.** When the training stage is active and streaming, a loading indicator and descriptive text (e.g., "Training model...") are visible.

### Results stage

- **5a.** When the results stage renders with a training result containing stdout, the metrics text is displayed.
- **6a.** When the results stage renders with figures, each figure is displayed as an image.
- **5b.** When the results stage renders, the LLM's explanation text is displayed.
- **11a.** When the user clicks "Done — return to chat," the wizard is removed and the chat input is re-enabled.

### Error handling

- **7a.** When `sendMlStep` calls `onError` during a stage, an error message is displayed in the current stage.
- **7b.** When an error is displayed, a "Retry" button is visible. Clicking it re-sends the same stage request.

### Chat interaction during wizard

- **12a.** When the wizard is active, the chat input field and Send button are disabled.
- **12b.** When the wizard exits (via Cancel or Done), the chat input field and Send button are re-enabled.

---

## Not Testing

- **Store setters** (`startMlWizard`, `resetMlWizard`) — simple set/get with no logic beyond assignment. Per TEST-STRATEGY: "test only if store logic goes beyond simple set/get."
- **`sendMlStep` SSE parsing directly** — mocked in component tests, following the same pattern as `sendChatMessage`.
- **Visual styling** — border colors, font sizes, spacing.

---

## Files

| File | Role |
|------|------|
| `frontend/src/components/__tests__/MLWizard.test.tsx` | Create — all test cases above |
| `frontend/src/components/MLWizard.tsx` | Create — wizard component |
| `frontend/src/store.ts` | Modify — add ML wizard state |
| `frontend/src/api.ts` | Modify — add `sendMlStep` SSE client |
| `frontend/src/components/ChatPanel.tsx` | Modify — add Build a Model button, render wizard, disable input during wizard |
