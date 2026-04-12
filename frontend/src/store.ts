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

// Mirrors providers.py::SUPPORTED_PROVIDERS on the backend.
// Both must be kept in sync if a new provider is added.
export type Provider = "openai" | "anthropic";

interface AppState {
  sessionId: string | null;
  apiKey: string | null;
  // provider, model are set alongside apiKey after successful BYOK validation (Step 6).
  // All three are passed to the upload endpoint (Step 7) so the session stores them.
  provider: Provider | null;
  model: string | null;
  messages: unknown[];
  isStreaming: boolean;
  datasetInfo: unknown | null;
  currentScreen: Screen;

  // Step 7 adds setSessionId, setDatasetInfo, setMessages.
  setApiKey: (key: string) => void;
  setProvider: (provider: Provider) => void;
  setModel: (model: string) => void;
  setScreen: (screen: Screen) => void;
}

export const useStore = create<AppState>((set) => ({
  sessionId: null,
  apiKey: null,
  provider: null,
  model: null,
  messages: [],
  isStreaming: false,
  datasetInfo: null,
  currentScreen: "setup",

  setApiKey: (key) => set({ apiKey: key }),
  setProvider: (provider) => set({ provider }),
  setModel: (model) => set({ model }),
  setScreen: (screen) => set({ currentScreen: screen }),
}));
