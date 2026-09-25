// Typed API client. Data calls go to /api/* (proxied to the backend); session calls go to /bff/*,
// which keeps the refresh token in an httpOnly cookie. The access token lives in memory only.
import type {
  AdminDashboard, Answer, AuditEvent, BreakGlass, Case, Evidence, EvidenceGraph, Health, Identity, Incident,
  IncidentType, LoginResult, Member, MyDashboard, Purpose, Role, Search, SecurityEvent, Session, TimelineItem,
  User, Verdict,
} from "./types";

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function parseError(res: Response): Promise<ApiError> {
  const body = await res.json().catch(() => ({}));
  const d = body.detail;
  return new ApiError(res.status, Array.isArray(d) ? d.map((x: { msg: string }) => x.msg).join("; ") : d || res.statusText);
}

async function bff<T>(action: string, body?: unknown): Promise<T> {
  const res = await fetch(`/bff/${action}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin",
  });
  if (!res.ok) throw await parseError(res);
  const data = await res.json();
  if (data.access_token) accessToken = data.access_token;
  return data as T;
}

/** Uses the httpOnly refresh cookie to get a new access token. Concurrent callers share one refresh. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= bff<Session>("refresh").then(() => true, () => { accessToken = null; return false; })
    .finally(() => { refreshing = null; });
  return refreshing;
}

async function send(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401 && retry && (await refreshSession())) return send(path, init, false);
  if (res.status === 401) window.dispatchEvent(new Event("ie:logout"));
  return res;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await send(path, init);
  if (!res.ok) throw await parseError(res);
  return res.json() as Promise<T>;
}

const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

/** Fetches an authenticated file (report, evidence) as a Blob. */
export async function fetchBlob(path: string): Promise<Blob> {
  const res = await send(path);
  if (!res.ok) throw await parseError(res);
  return res.blob();
}

export async function download(path: string, filename: string) {
  const url = URL.createObjectURL(await fetchBlob(path));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export const api = {
  health: () => request<Health>("/api/health"),

  // session
  authStatus: () => request<{ needs_setup: boolean; mfa_required_roles: string[] }>("/api/auth/status"),
  setup: (email: string, password: string) => bff<Session>("setup", { email, password }),
  login: (email: string, password: string) => bff<LoginResult>("login", { email, password }),
  loginMfa: (mfa_token: string, code: string) => bff<Session>("mfa", { mfa_token, code }),
  logout: async () => { await bff("logout").catch(() => undefined); accessToken = null; },
  me: () => request<User>("/api/auth/me"),
  mfaSetup: () => request<{ secret: string; otpauth_uri: string }>("/api/auth/mfa/setup", json("POST")),
  mfaConfirm: (code: string) => request<{ mfa_enabled: boolean }>("/api/auth/mfa/confirm", json("POST", { code })),
  mfaDisable: (code: string) => request<{ mfa_enabled: boolean }>("/api/auth/mfa/disable", json("POST", { code })),

  // users
  users: () => request<User[]>("/api/users"),
  createUser: (email: string, password: string, role: Role) => request<User>("/api/users", json("POST", { email, password, role })),
  updateUser: (id: number, patch: { role?: Role; status?: "active" | "disabled" }) => request<User>(`/api/users/${id}`, json("PATCH", patch)),
  resetMfa: (id: number) => request(`/api/users/${id}/reset-mfa`, json("POST")),
  myDashboard: () => request<MyDashboard>("/api/me/dashboard"),

  // searches
  searches: (opts: { caseId?: string; all?: boolean } = {}) =>
    request<Search[]>(`/api/searches${opts.caseId ? `?case_id=${opts.caseId}` : opts.all ? "?scope=all" : ""}`),
  search: (id: string) => request<Search>(`/api/searches/${id}`),
  createSearch: (identity: Identity, purpose: Purpose, caseId?: string) =>
    request<{ id: string }>("/api/searches", json("POST", { identity, purpose, acknowledged: true, case_id: caseId })),
  deleteSearch: (id: string) => request(`/api/searches/${id}`, json("DELETE")),
  viewCandidate: (id: string, cid: string) => request(`/api/searches/${id}/candidates/${cid}`),
  feedback: (id: string, cid: string, verdict: Verdict) =>
    request(`/api/searches/${id}/candidates/${cid}/feedback`, json("POST", { verdict })),
  graph: (id: string) => request<EvidenceGraph>(`/api/searches/${id}/graph`),
  ask: (id: string, question: string) => request<Answer>(`/api/searches/${id}/ask`, json("POST", { question })),

  // cases
  cases: () => request<Case[]>("/api/cases"),
  case: (id: string) => request<Case>(`/api/cases/${id}`),
  createCase: (title: string, description: string, purpose: Purpose) =>
    request<Case>("/api/cases", json("POST", { title, description, purpose, acknowledged: true })),
  updateCase: (id: string, patch: Partial<Pick<Case, "title" | "description" | "status">>) =>
    request<Case>(`/api/cases/${id}`, json("PATCH", patch)),
  deleteCase: (id: string) => request(`/api/cases/${id}`, json("DELETE")),
  timeline: (id: string) => request<TimelineItem[]>(`/api/cases/${id}/timeline`),
  accessHistory: (id: string) => request<TimelineItem[]>(`/api/cases/${id}/access-history`),
  grant: (id: string, email: string, access: "viewer" | "editor", expires_hours?: number) =>
    request<Member[]>(`/api/cases/${id}/members`, json("POST", { email, access, expires_hours })),
  revoke: (id: string, memberId: number) => request<Member[]>(`/api/cases/${id}/members/${memberId}`, json("DELETE")),
  breakGlass: (id: string, reason: string) => request<BreakGlass>(`/api/cases/${id}/break-glass`, json("POST", { reason })),

  createIncident: (caseId: string, body: {
    incident_type?: IncidentType; description?: string; target_name?: string; author_handle?: string;
    source_url?: string; content_id?: string; comment_text?: string; posted_at?: string;
  }) => request<Incident>(`/api/cases/${caseId}/incidents`, json("POST", body)),
  updateIncident: (caseId: string, id: string, patch: Partial<Pick<Incident, "incident_type" | "status" | "severity">>) =>
    request<Incident>(`/api/cases/${caseId}/incidents/${id}`, json("PATCH", patch)),
  investigateIncident: (caseId: string, id: string, hints: Partial<Identity>) =>
    request<{ id: string }>(`/api/cases/${caseId}/incidents/${id}/investigate`, json("POST", hints)),

  addTextEvidence: (caseId: string, text: string, incident_id?: string, source_url?: string) =>
    request<Evidence>(`/api/cases/${caseId}/evidence/text`, json("POST", { text, incident_id, source_url })),
  addUrlEvidence: (caseId: string, url: string, incident_id?: string) =>
    request<Evidence>(`/api/cases/${caseId}/evidence/url`, json("POST", { url, incident_id })),
  addFileEvidence: (caseId: string, file: File, incident_id?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (incident_id) fd.append("incident_id", incident_id);
    return request<Evidence>(`/api/cases/${caseId}/evidence/file`, { method: "POST", body: fd });
  },
  viewEvidence: (caseId: string, id: string) => request<Evidence>(`/api/cases/${caseId}/evidence/${id}`),
  verifyEvidence: (caseId: string, id: string) =>
    request<{ ok: boolean; original_hash: string; current_hash: string }>(`/api/cases/${caseId}/evidence/${id}/verify`, json("POST")),

  // admin / security
  adminDashboard: () => request<AdminDashboard>("/api/admin/dashboard"),
  audit: (params: { event_type?: string; case_id?: string } = {}) =>
    request<AuditEvent[]>(`/api/admin/audit?${new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][])}`),
  verifyAudit: () => request<{ ok: boolean; events_checked: number; broken_at?: string; head_hash?: string }>("/api/admin/audit/verify", json("POST")),
  securityEvents: (status?: string) => request<SecurityEvent[]>(`/api/admin/security-events${status ? `?status=${status}` : ""}`),
  setSecurityEvent: (id: string, status: "acknowledged" | "resolved") =>
    request(`/api/admin/security-events/${id}`, json("PATCH", { status })),
  breakGlassRequests: (status?: string) => request<BreakGlass[]>(`/api/admin/break-glass${status ? `?status=${status}` : ""}`),
  decideBreakGlass: (id: string, approve: boolean, hours?: number) =>
    request<BreakGlass>(`/api/admin/break-glass/${id}`, json("POST", { approve, hours })),
  evaluation: (threshold: number) => request<Record<string, unknown>>(`/api/admin/evaluation?threshold=${threshold}`),
  calibrate: (method: "platt" | "isotonic") => request<Record<string, unknown>>("/api/admin/calibrate", json("POST", { method })),
  purge: () => request<Record<string, number>>("/api/admin/retention/purge", json("POST")),
};
