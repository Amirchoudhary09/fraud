// Mirrors backend/app/schemas and API responses. Keep in sync when the API changes.

export type Role = "super_admin" | "security_admin" | "investigator" | "analyst" | "auditor" | "user";
export type Purpose = "self_check" | "harassment_report" | "professional_verification" | "research";
export type Verdict = "correct" | "wrong" | "insufficient";
export type SearchStatus = "queued" | "running" | "completed" | "failed";
export type Severity = "none" | "low" | "medium" | "high";

export interface User {
  id: number; email: string; role: Role; status: "active" | "disabled"; mfa_enabled: number;
  created_at: string; last_login_at: string | null; permissions?: string[]; mfa_required?: boolean;
}
export interface Session { access_token: string; expires_in: number; user: User }
export type LoginResult = Session | { mfa_required: true; mfa_token: string };

export interface Identity {
  name: string; company?: string | null; college?: string | null; role?: string | null;
  location?: string | null; username?: string | null;
}

export interface SourceRef { url: string; title: string }
export interface Claim { field: string; value: string; evidence: string; source: SourceRef | null }
export interface Signal {
  field: string; status: "match" | "partial" | "mismatch" | "unknown" | "corroboration";
  points: number; detail: string; sources: SourceRef[];
}
export interface Contradiction { field: string; values: string[]; detail: string; sources: SourceRef[] }
export interface Candidate {
  candidate_id: string; display_name: string; platform: string; profile_url: string | null;
  claims: Claim[]; score: number; band: "strong" | "possible" | "weak"; signals: Signal[];
  contradictions: Contradiction[]; calibrated: number | null;
}

export interface TraceStep { agent: string; detail: string; ts: string }
export interface SearchResult {
  queries: string[]; search_errors: string[]; summaries: { query: string; summary: string }[];
  sources: SourceRef[]; candidates: Candidate[]; mock: boolean; agent_trace: TraceStep[]; indexed_chunks: number;
}
export interface Search {
  id: string; user_id: number; case_id: string | null; incident_id: string | null; entity_id: string | null;
  search_type: "PUBLIC_IDENTITY" | "INCIDENT_AUTHOR"; input: Identity; normalized_query: string;
  purpose: Purpose; provider: string; status: SearchStatus; stage: string; candidate_count: number | null;
  created_at: string; started_at: string | null; completed_at: string | null;
  result?: SearchResult | null; error?: string | null; sources_used?: string[] | null;
  feedback?: Record<string, Verdict>;
}

export interface GraphNode { id: string; type: string; label: string; score?: number; band?: string; url?: string }
export interface GraphEdge { source: string; target: string; type: string; sources: SourceRef[] }
export interface EvidenceGraph { nodes: GraphNode[]; edges: GraphEdge[] }

export interface Citation { text: string; source_url: string | null; source_title: string | null; candidate_id: string | null; score: number }
export interface Answer { answer: string; citations: Citation[] }

export interface Analysis {
  id?: string; indicators: Record<string, boolean>; severity: Severity;
  rule_matches: Record<string, string[]>; llm: { rationale: string; severity: string | null } | null;
  mentions: string[]; suggested_incident_type: string; disclaimer: string;
}
export interface AnalysisRecord {
  id: string; evidence_id: string; incident_id: string | null; analysis_type: string; model: string;
  status: string; result: Analysis | null; started_at: string; completed_at: string | null;
}
export const INCIDENT_TYPES = ["HARASSMENT", "THREAT", "ABUSE", "IMPERSONATION", "SCAM_INDICATOR", "SPAM",
  "HATEFUL_CONTENT", "PRIVACY_CONCERN", "OTHER"] as const;
export type IncidentType = (typeof INCIDENT_TYPES)[number];

export interface Incident {
  id: string; case_id: string; reported_by: number; target_entity_id: string | null; target_entity: string | null;
  incident_type: IncidentType; source_platform: string | null; source_url: string | null; content_id: string | null;
  author_handle: string | null; description: string | null; severity: Severity;
  status: "open" | "under_review" | "resolved" | "dismissed"; created_at: string; analysis?: Analysis | null;
}
export interface Evidence {
  id: string; case_id: string; incident_id: string | null; type: string; source_url: string | null;
  capture_method: string; captured_by: number; captured_at: string; content_hash: string;
  mime_type: string | null; size: number | null; metadata: Record<string, unknown>; has_file: number;
  text?: string;
}
export interface Member {
  id: number; user_id: number; email: string; access: "owner" | "editor" | "viewer";
  via: "owner" | "grant" | "break_glass"; granted_at: string; expires_at: string | null; revoked_at: string | null;
}
export interface ReportRecord { id: string; kind: string; format: string; content_hash: string; generated_at: string; generated_by_email: string }
export interface Case {
  id: string; title: string; description: string | null; purpose: Purpose;
  status: "open" | "under_review" | "closed"; target_entity: string | null; created_by: number;
  created_by_email?: string; created_at: string; updated_at: string;
  incident_count?: number; evidence_count?: number; search_count?: number; report_count?: number;
  my_access?: "owner" | "editor" | "viewer" | "admin" | null;
  incidents?: Incident[]; evidence?: Evidence[]; analyses?: AnalysisRecord[]; searches?: Search[];
  reports?: ReportRecord[]; members?: Member[];
}
export interface TimelineItem {
  ts: string; event_type: string; actor: string; text?: string; target_type: string | null;
  target_id: string | null; result: string; event_id: string;
}
export interface Relationship {
  id: string; subject_type: string; subject_id: string; relationship_type: string; object_type: string;
  object_id: string; object_label: string | null; search_id: string | null; case_id: string | null; created_at: string;
}
export interface MyDashboard { user: User; searches: Search[]; cases: Case[]; relationships: Relationship[] }

export interface AuditEvent {
  seq: number; event_id: string; ts: string; event_type: string; actor_user_id: number | null;
  target_type: string | null; target_id: string | null; case_id: string | null; search_id: string | null;
  request_id: string | null; ip_hash: string | null; result: string; detail: string | null; prev_hash: string; hash: string;
}
export interface SecurityEvent {
  id: string; ts: string; severity: "low" | "medium" | "high" | "critical"; type: string; user_id: number | null;
  email: string | null; detail: string; status: "open" | "acknowledged" | "resolved";
}
export interface BreakGlass {
  id: string; case_id: string; case_title?: string; user_id: number; email: string; reason: string;
  status: "pending" | "approved" | "denied"; created_at: string; expires_at: string | null;
}
export interface AdminDashboard {
  active_users: number; active_cases: number; searches_24h: number; incidents_24h: number;
  evidence_captured_24h: number; failed_logins_24h: number; authz_denied_24h: number;
  open_security_events: number; pending_break_glass: number; api_errors: Record<string, number>;
  audit_integrity: { ok: boolean; events_checked: number; broken_at?: string };
}

export interface Health { ok: boolean; mode: "mock" | "gemini"; model: string; embed_model: string; llm_judge: boolean }

export const PURPOSES: Record<Purpose, string> = {
  self_check: "Checking my own public footprint",
  professional_verification: "Professional verification (with consent)",
  harassment_report: "Documenting harassment for a platform/police report",
  research: "Research / testing",
};
export const ROLES: Role[] = ["super_admin", "security_admin", "investigator", "analyst", "auditor", "user"];
