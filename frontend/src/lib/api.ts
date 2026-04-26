/**
 * Thin fetch wrapper against the qontext FastAPI backend (api/server.py).
 *
 * Base URL is read from VITE_API_BASE_URL and defaults to the dev server
 * (`http://127.0.0.1:8000`) so this file works out of the box when both
 * `python run_qontext_api.py` and `npm run dev` are running locally.
 *
 * Mocks remain available behind VITE_USE_MOCKS=true (see useConflicts.ts).
 */

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  "http://127.0.0.1:8000";

export const USE_MOCKS: boolean =
  (import.meta.env.VITE_USE_MOCKS as string | undefined) === "true";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    throw new ApiError(`${init?.method ?? "GET"} ${path} -> ${res.status}`, res.status);
  }
  return (await res.json()) as T;
}

/** Raw conflict shape as returned by the qontext backend graph. */
export interface BackendConflict {
  entity_id?: string;
  field?: string;
  existing_value?: unknown;
  new_value?: unknown;
  source_existing?: string;
  source_new?: string;
  confidence?: number;
  reason?: string;
  resolution?: {
    status?: "pending_review" | "auto_resolved" | "manually_resolved";
    winner?: "existing" | "new";
    reason?: string;
  };
  // Pass through everything else without losing fidelity.
  [key: string]: unknown;
}

export interface ListConflictsResponse {
  total: number;
  conflicts: BackendConflict[];
}

export function listConflicts(status?: string) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return request<ListConflictsResponse>(`/conflicts${qs}`);
}

/**
 * Resolve a conflict via the backend.
 *
 * Backend signature: POST /conflicts/{index}/resolve?winner=existing|new&reason=...
 * The "index" is the position in the conflict list returned by GET /conflicts.
 */
export function resolveConflict(
  index: number,
  winner: "existing" | "new",
  reason: string,
) {
  const qs = `?winner=${winner}&reason=${encodeURIComponent(reason)}`;
  return request<{ status: string; conflict: BackendConflict }>(
    `/conflicts/${index}/resolve${qs}`,
    { method: "POST" },
  );
}
