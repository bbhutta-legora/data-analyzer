// api.ts
// Backend API client for the Smart Dataset Explainer frontend.
// All HTTP calls to /api go through this module — no raw fetch() elsewhere.
// Architecture ref: "Communication Protocol" in planning/architecture.md §5
//
// Endpoint-specific functions are added per step:
//   Step 6:  validateApiKey()
//   Step 7:  uploadFile()
//   Step 8:  streamChatQuestion() (SSE)
//   Step 10: applyCleaningAction()
//   Step 14: exportNotebook()

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
