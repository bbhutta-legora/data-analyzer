// api.ts
// Backend API client for the Smart Dataset Explainer frontend.
// All HTTP calls to /api go through this module — no raw fetch() elsewhere.
// Architecture ref: "Communication Protocol" in planning/architecture.md §5
//
// Endpoint-specific functions are added per step:
//   Step 6:  validateApiKey()          ← implemented here
//   Step 7:  uploadFile()
//   Step 9:  sendChatMessage() (SSE)
//   Step 10: applyCleaningAction()
//   Step 14: exportNotebook()

import type { Provider, DatasetMetadata, SummaryData, CleaningSuggestion } from "./store";

// API_BASE is empty — requests go to /api/* which Vite proxies to the backend.
// This avoids hardcoding the backend port in application code.
const API_BASE = "";

interface ApiErrorResponse {
  error: string;
  detail: string;
}

export class ApiError extends Error {
  constructor(
    public readonly statusCode: number,
    public readonly errorCode: string,
    public readonly detail: string
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

/**
 * Base fetch wrapper for all backend API calls.
 * Throws ApiError for non-2xx responses with a structured body,
 * or a plain Error for network failures.
 */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });

  if (!response.ok) {
    const body: ApiErrorResponse = await response.json().catch(() => ({
      error: "unknown_error",
      detail: response.statusText,
    }));
    throw new ApiError(response.status, body.error, body.detail);
  }

  return response.json() as Promise<T>;
}

// ── Step 6: BYOK ─────────────────────────────────────────────────────────────

export interface ModelInfo {
  model_id: string;
  label: string;
  tier: string;
  description: string;
  is_default: boolean;
}

/**
 * Fetch the curated list of available models per provider from the backend.
 * Called once on setup screen mount — the backend (providers.py) is the single
 * source of truth so the frontend never hardcodes model identifiers.
 */
export async function fetchAvailableModels(): Promise<
  Record<string, ModelInfo[]>
> {
  return apiFetch<Record<string, ModelInfo[]>>("/api/models", {
    method: "GET",
  });
}

/**
 * Validate a provider API key against the backend.
 *
 * Throws ApiError on network failure, empty key (400), or invalid key (401).
 * Returns {valid: true} on success — the caller stores the key, provider, and
 * model in Zustand and transitions to the upload screen.
 *
 * PRD ref: #8 (BYOK)
 */
export async function validateApiKey(
  apiKey: string,
  provider: Provider
): Promise<{ valid: boolean }> {
  return apiFetch<{ valid: boolean }>("/api/validate-key", {
    method: "POST",
    body: JSON.stringify({ api_key: apiKey, provider }),
  });
}

// ── Step 7: File Upload ───────────────────────────────────────────────────────

interface UploadResponse {
  session_id: string;
  datasets: Record<string, DatasetMetadata>;
  summary?: SummaryData;
}

/**
 * Upload a dataset file to the backend.
 *
 * Uses FormData (not JSON) because the endpoint accepts multipart/form-data.
 * The api_key, provider, and model are sent as form fields alongside the file
 * so the backend can store them on the session and call the LLM for summary.
 *
 * Does NOT use apiFetch — multipart uploads need the browser to set the
 * Content-Type header with the boundary automatically. The error handling
 * pattern (check response.ok → parse body → throw ApiError) is intentionally
 * duplicated from apiFetch for this reason.
 *
 * PRD ref: #1 (upload), #2 (initial summary)
 */
export async function uploadFile(
  file: File,
  apiKey: string,
  provider: Provider,
  model: string
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("api_key", apiKey);
  formData.append("provider", provider);
  formData.append("model", model);

  const response = await fetch(`${API_BASE}/api/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({
      error: "unknown_error",
      detail: response.statusText,
    }));
    throw new ApiError(response.status, body.error, body.detail);
  }

  return response.json() as Promise<UploadResponse>;
}

// ── Step 14: Export Notebook ──────────────────────────────────────────────────

/**
 * Download the session's Jupyter notebook export.
 *
 * Uses fetch instead of window.open() so we can detect HTTP errors (404, 500)
 * and surface them to the user rather than showing raw JSON in a new tab.
 *
 * On success: creates a Blob from the response, generates an object URL,
 * triggers a download via a temporary <a> element, then cleans up.
 *
 * On failure: rejects with an Error describing the problem.
 *
 * PRD ref: #7 (Export)
 */
export async function exportNotebook(sessionId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/export/${sessionId}`);

  if (!response.ok) {
    const body = await response.json().catch(() => ({
      detail: response.statusText,
    }));
    throw new Error(body.detail || `Export failed with status ${response.status}`);
  }

  const blob = await response.blob();

  // Extract filename from Content-Disposition header, fall back to a default.
  const disposition = response.headers.get("Content-Disposition") || "";
  const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
  const filename = filenameMatch ? filenameMatch[1] : "notebook_analysis.ipynb";

  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  } finally {
    URL.revokeObjectURL(url);
  }
}

// ── Step 9: Chat SSE Client ────────────────────────────────────────────────

export interface ChatCallbacks {
  onExplanation: (text: string) => void;
  onResult: (result: { stdout: string; figures: string[] }) => void;
  onCleaningSuggestions: (suggestions: CleaningSuggestion[]) => void;
  onError: (message: string) => void;
  onDone: () => void;
}

/**
 * Send a chat question to the backend and process the SSE response stream.
 *
 * Uses fetch + ReadableStream instead of EventSource because /api/chat is
 * a POST endpoint and EventSource only supports GET.
 *
 * Dispatches callbacks as SSE events arrive. Always calls onDone at the end,
 * even on error, so the caller can clean up streaming state.
 *
 * PRD ref: #3 (Conversational Q&A)
 */
export async function sendChatMessage(
  sessionId: string,
  question: string,
  callbacks: ChatCallbacks,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, question }),
    });
  } catch {
    callbacks.onError("Network error: could not reach the server.");
    callbacks.onDone();
    return;
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({
      detail: response.statusText,
    }));
    callbacks.onError(body.detail || "Request failed with status " + response.status);
    callbacks.onDone();
    return;
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Process complete SSE events (delimited by double newlines).
    const parts = buffer.split("\n\n");
    // The last element is either empty (if the buffer ended with \n\n)
    // or an incomplete event — keep it in the buffer.
    buffer = parts.pop()!;

    for (const part of parts) {
      if (!part.trim()) continue;

      let eventType = "";
      let data = "";
      for (const line of part.split("\n")) {
        if (line.startsWith("event: ")) {
          eventType = line.slice(7);
        } else if (line.startsWith("data: ")) {
          data = line.slice(6);
        }
      }

      switch (eventType) {
        case "explanation":
          callbacks.onExplanation(data);
          break;
        case "result":
          callbacks.onResult(JSON.parse(data));
          break;
        case "cleaning_suggestions":
          callbacks.onCleaningSuggestions(JSON.parse(data));
          break;
        case "error":
          callbacks.onError(data);
          break;
        case "done":
          callbacks.onDone();
          return;
      }
    }
  }

  // If the stream ended without a done event, still signal completion.
  callbacks.onDone();
}
