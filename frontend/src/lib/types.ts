// Mirrors backend/app/schemas. Keep in sync when the API changes.

export type Role = "admin" | "analyst" | "viewer";
export type Purpose = "self_check" | "harassment_report" | "professional_verification" | "research";
export type Verdict = "correct" | "wrong" | "insufficient";
export type Status = "queued" | "running" | "done" | "failed";

export interface User { id: number; email: string; role: Role; active: number; created_at: string }

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
export interface InvestigationResult {
  queries: string[]; search_errors: string[]; summaries: { query: string; summary: string }[];
  sources: SourceRef[]; candidates: Candidate[]; mock: boolean; agent_trace: TraceStep[]; indexed_chunks: number;
}
export interface Investigation {
  id: string; created_at: string; status: Status; stage: string; purpose: Purpose; provider: string;
  input: Identity; result: InvestigationResult | null; error: string | null; case_id: string | null;
  comment_id: string | null; feedback?: Record<string, Verdict>;
}

export interface GraphNode { id: string; type: string; label: string; score?: number; band?: string; url?: string }
export interface GraphEdge { source: string; target: string; type: string; sources: SourceRef[] }
export interface EvidenceGraph { nodes: GraphNode[]; edges: GraphEdge[] }

export interface Citation { text: string; source_url: string | null; source_title: string | null; candidate_id: string | null; score: number }
export interface Answer { answer: string; citations: Citation[] }

export interface CommentAnalysis {
  indicators: Record<string, boolean>; severity: "none" | "low" | "medium" | "high";
  rule_matches: Record<string, string[]>; llm: { rationale: string; severity: string | null } | null;
  mentions: string[]; disclaimer: string;
}
export interface Comment {
  id: string; case_id: string; created_at: string; text: string; platform: string | null;
  author_username: string | null; source_url: string | null; posted_at: string | null;
  analysis: CommentAnalysis; investigation_id: string | null;
}
export interface Attachment { id: string; created_at: string; filename: string; content_type: string; size: number; sha256: string }
export interface Case {
  id: string; created_at: string; updated_at: string; title: string; description: string | null;
  purpose: Purpose; status: "open" | "closed"; comment_count?: number;
  comments?: Comment[]; attachments?: Attachment[]; investigations?: Investigation[];
}

export interface Health { ok: boolean; mode: "mock" | "gemini"; model: string; embed_model: string; llm_judge: boolean }

export const PURPOSES: Record<Purpose, string> = {
  self_check: "Checking my own public footprint",
  professional_verification: "Professional verification (with consent)",
  harassment_report: "Documenting harassment for a platform/police report",
  research: "Research / testing",
};
