// store.ts
// Global Zustand store for the Smart Dataset Explainer frontend.
// Holds session state, UI navigation state, and dataset metadata.
// Architecture ref: "State Shape (Zustand)" in planning/architecture.md §4.2
//
// Type placeholders (messages: Message[], datasetInfo: DatasetInfo) will be
// tightened in Steps 7–9 once the LLM response and upload response shapes are
// defined. Using `unknown` here rather than `any` so TypeScript flags misuse.

import { create } from "zustand";

// The three top-level screens in the app.
// Transition order: setup → upload → chat.
type Screen = "setup" | "upload" | "chat";

interface AppState {
  sessionId: string | null;
  apiKey: string | null;
  messages: unknown[];
  isStreaming: boolean;
  datasetInfo: unknown | null;
  currentScreen: Screen;

  // Actions — Step 6 adds setSessionId; Step 7 adds setDatasetInfo, setMessages.
  setApiKey: (key: string) => void;
  setScreen: (screen: Screen) => void;
}

export const useStore = create<AppState>((set) => ({
  sessionId: null,
  apiKey: null,
  messages: [],
  isStreaming: false,
  datasetInfo: null,
  currentScreen: "setup",

  setApiKey: (key) => set({ apiKey: key }),
  setScreen: (screen) => set({ currentScreen: screen }),
}));
