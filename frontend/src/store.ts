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

// ── Store ────────────────────────────────────────────────────────────────────

interface AppState {
  sessionId: string | null;
  apiKey: string | null;
  provider: Provider | null;
  model: string | null;
  messages: unknown[];
  isStreaming: boolean;
  datasetInfo: DatasetInfo | null;
  currentScreen: Screen;

  setApiKey: (key: string) => void;
  setProvider: (provider: Provider) => void;
  setModel: (model: string) => void;
  setScreen: (screen: Screen) => void;
  setSessionId: (id: string) => void;
  setDatasetInfo: (info: DatasetInfo) => void;
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
  setSessionId: (id) => set({ sessionId: id }),
  setDatasetInfo: (info) => set({ datasetInfo: info }),
}));
