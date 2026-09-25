// Typed API client. All calls go to /api/* on this origin (proxied to the backend).
import type {
  Answer, Attachment, Case, Comment, EvidenceGraph, Health, Identity, Investigation, Purpose, Role, User, Verdict,
} from "./types";

const TOKEN_KEY = "ie_token";

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* storage unavailable: token lives only for this page */ }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401 && token) {
    setToken(null);
    window.dispatchEvent(new Event("ie:logout"));
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const d = body.detail;
    throw new ApiError(res.status, Array.isArray(d) ? d.map((x: { msg: string }) => x.msg).join("; ") : d || res.statusText);
  }
  return res.json() as Promise<T>;
}

const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

/** Fetches an authenticated file and returns it as a Blob (for reports and evidence files). */
export async function fetchBlob(path: string): Promise<Blob> {
  const token = getToken();
  const res = await fetch(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).detail || res.statusText);
  return res.blob();
}

export async function download(path: string, filename: string) {
  const url = URL.createObjectURL(await fetchBlob(path));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

type Session = { token: string; user: User };

export const api = {
  health: () => request<Health>("/api/health"),

  authStatus: () => request<{ needs_setup: boolean }>("/api/auth/status"),
  setup: (email: string, password: string) => request<Session>("/api/auth/setup", json("POST", { email, password })),
  login: (email: string, password: string) => request<Session>("/api/auth/login", json("POST", { email, password })),
  me: () => request<User>("/api/auth/me"),
  users: () => request<User[]>("/api/users"),
  createUser: (email: string, password: string, role: Role) => request<User>("/api/users", json("POST", { email, password, role })),
  updateUser: (id: number, patch: { role?: Role; active?: boolean }) => request<User>(`/api/users/${id}`, json("PATCH", patch)),

  investigations: (caseId?: string) => request<Investigation[]>(`/api/investigations${caseId ? `?case_id=${caseId}` : ""}`),
  investigation: (id: string) => request<Investigation>(`/api/investigations/${id}`),
  createInvestigation: (identity: Identity, purpose: Purpose) =>
    request<{ id: string }>("/api/investigations", json("POST", { identity, purpose, acknowledged: true })),
  deleteInvestigation: (id: string) => request(`/api/investigations/${id}`, json("DELETE")),
  feedback: (id: string, cid: string, verdict: Verdict) =>
    request(`/api/investigations/${id}/candidates/${cid}/feedback`, json("POST", { verdict })),
  graph: (id: string) => request<EvidenceGraph>(`/api/investigations/${id}/graph`),
  ask: (id: string, question: string) => request<Answer>(`/api/investigations/${id}/ask`, json("POST", { question })),

  cases: () => request<Case[]>("/api/cases"),
  case: (id: string) => request<Case>(`/api/cases/${id}`),
  createCase: (title: string, description: string, purpose: Purpose) =>
    request<Case>("/api/cases", json("POST", { title, description, purpose, acknowledged: true })),
  updateCase: (id: string, patch: Partial<Pick<Case, "title" | "description" | "status">>) =>
    request<Case>(`/api/cases/${id}`, json("PATCH", patch)),
  deleteCase: (id: string) => request(`/api/cases/${id}`, json("DELETE")),
  addComment: (id: string, c: { text: string; author_username?: string; source_url?: string; platform?: string; posted_at?: string }) =>
    request<Comment>(`/api/cases/${id}/comments`, json("POST", c)),
  investigateComment: (id: string, commentId: string, hints: Partial<Identity>) =>
    request<{ id: string }>(`/api/cases/${id}/comments/${commentId}/investigate`, json("POST", hints)),
  upload: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<Attachment>(`/api/cases/${id}/attachments`, { method: "POST", body: fd });
  },

  audit: () => request<Record<string, string | number | null>[]>("/api/admin/audit"),
  evaluation: (threshold: number) => request<Record<string, unknown>>(`/api/admin/evaluation?threshold=${threshold}`),
  calibrate: (method: "platt" | "isotonic") => request<Record<string, unknown>>("/api/admin/calibrate", json("POST", { method })),
  purge: () => request<Record<string, number>>("/api/admin/retention/purge", json("POST")),
};
