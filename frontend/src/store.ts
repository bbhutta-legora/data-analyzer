// store.ts
// Global Zustand store for the Smart Dataset Explainer frontend.
// Holds session state, UI navigation state, and dataset metadata.
// Architecture ref: "State Shape (Zustand)" in planning/architecture.md §4.2
//
// Types for DatasetInfo and SummaryData mirror the backend response shapes
// from /api/upload. Changes to the backend response must be reflected here.

import { create } from "zustand";

// The three top-level screens in the app.
// Transition order: setup → upload → chat.
type Screen = "setup" | "upload" | "chat";

// Mirrors providers.py::SUPPORTED_PROVIDERS on the backend.
// Both must be kept in sync if a new provider is added.
export type Provider = "openai" | "anthropic";

// ── Response types from /api/upload ─────────────────────────────────────────
// These mirror the JSON structure returned by build_dataset_metadata() in main.py.

export interface DatasetMetadata {
  row_count: number;
  column_count: number;
  columns: string[];
  dtypes: Record<string, string>;
  missing_values: Record<string, number>;
}

export interface CleaningSuggestion {
  description: string;
  options: string[];
  dataset_name?: string;
}

export interface SummaryData {
  explanation: string;
  cleaning_suggestions: CleaningSuggestion[];
  suggested_questions: string[];
  error?: string;
}

export interface DatasetInfo {
  datasets: Record<string, DatasetMetadata>;
  summary: SummaryData | null;
}

// ── Message type for Q&A chat (Step 9) ──────────────────────────────────────
// Each entry in the messages array is either a user question or an assistant
// response. Assistant messages accumulate fields as SSE events arrive.

export interface Message {
  role: "user" | "assistant";
  content: string;
  code?: string;
  figures?: string[];
  stdout?: string;
  cleaningSuggestions?: CleaningSuggestion[];
  error?: string;
}

// ── Store ────────────────────────────────────────────────────────────────────

interface AppState {
  sessionId: string | null;
  apiKey: string | null;
  provider: Provider | null;
  model: string | null;
  messages: Message[];
  isStreaming: boolean;
  datasetInfo: DatasetInfo | null;
  currentScreen: Screen;
  hasAppliedCleaning: boolean;

  setApiKey: (key: string) => void;
  setProvider: (provider: Provider) => void;
  setModel: (model: string) => void;
  setScreen: (screen: Screen) => void;
  setSessionId: (id: string) => void;
  setDatasetInfo: (info: DatasetInfo) => void;
  updateDatasetMetadata: (datasetName: string, metadata: DatasetMetadata) => void;
  setHasAppliedCleaning: (value: boolean) => void;
  addMessage: (message: Message) => void;
  updateLastAssistantMessage: (fields: Partial<Message>) => void;
  setStreaming: (streaming: boolean) => void;
}

export const useStore = create<AppState>((set, get) => ({
  sessionId: null,
  apiKey: null,
  provider: null,
  model: null,
  messages: [],
  isStreaming: false,
  datasetInfo: null,
  currentScreen: "setup",
  hasAppliedCleaning: false,

  setApiKey: (key) => set({ apiKey: key }),
  setProvider: (provider) => set({ provider }),
  setModel: (model) => set({ model }),
  setScreen: (screen) => set({ currentScreen: screen }),
  setSessionId: (id) => set({ sessionId: id }),
  setDatasetInfo: (info) => set({ datasetInfo: info }),
  setHasAppliedCleaning: (value) => set({ hasAppliedCleaning: value }),

  updateDatasetMetadata: (datasetName, metadata) =>
    set((state) => {
      if (!state.datasetInfo) return state;
      return {
        datasetInfo: {
          ...state.datasetInfo,
          datasets: {
            ...state.datasetInfo.datasets,
            [datasetName]: metadata,
          },
        },
      };
    }),

  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),

  updateLastAssistantMessage: (fields) => {
    const { messages } = get();
    if (messages.length === 0) return;

    const lastIndex = messages.length - 1;
    const last = messages[lastIndex];
    if (last.role !== "assistant") return;

    const updated = [...messages];
    updated[lastIndex] = { ...last, ...fields };
    set({ messages: updated });
  },

  setStreaming: (streaming) => set({ isStreaming: streaming }),
}));
