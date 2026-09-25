"use client";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { INCIDENT_TYPES, type AnalysisRecord, type Case, type Incident, type IncidentType } from "@/lib/types";
import { Badge, Empty, ErrorText, fmtTime } from "../ui";

function Indicators({ a }: { a: AnalysisRecord["result"] }) {
  if (!a) return null;
  const on = Object.entries(a.indicators).filter(([, v]) => v).map(([k]) => k.replace("_indicator", ""));
  return (
    <div className="small">
      <b>AI indicators:</b> {on.length ? on.map((k) => <Badge key={k} value={k} tone="bad" />) : <span className="muted">none</span>}{" "}
      severity <Badge value={a.severity} />
      {Object.keys(a.rule_matches).length > 0 && <div className="muted">matched: {Object.entries(a.rule_matches)
        .map(([k, v]) => `${k}: ${v.join(", ")}`).join("; ")}</div>}
      {a.llm?.rationale && <div className="muted">LLM: {a.llm.rationale}</div>}
      <div className="muted"><i>{a.disclaimer}</i></div>
    </div>
  );
}

export default function IncidentsPanel({ c, canEdit, canSearch, reload }: {
  c: Case; canEdit: boolean; canSearch: boolean; reload: () => void;
}) {
  const router = useRouter();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const analysesByIncident = new Map<string, AnalysisRecord[]>();
  for (const a of c.analyses ?? []) {
    if (a.incident_id) analysesByIncident.set(a.incident_id, [...(analysesByIncident.get(a.incident_id) ?? []), a]);
  }

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    const v = (k: string) => String(f.get(k) ?? "").trim() || undefined;
    setBusy(true);
    setError(null);
    try {
      await api.createIncident(c.id, {
        incident_type: v("incident_type") as IncidentType | undefined, description: v("description"),
        target_name: v("target_name"), author_handle: v("author_handle"), source_url: v("source_url"),
        content_id: v("content_id"), comment_text: v("comment_text"), posted_at: v("posted_at"),
      });
      form.reset();
      reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function investigate(inc: Incident) {
    const name = prompt("Optional: public display name shown on the author's profile (leave empty to search by handle only)") ?? undefined;
    try {
      const { id } = await api.investigateIncident(c.id, inc.id, name ? { name } : {});
      router.push(`/searches/${id}`);
    } catch (err) {
      setError(err);
    }
  }

  return (
    <>
      <p className="muted small">An incident records that a user reported a potentially harmful interaction. It is kept
        separate from searches, and the original content is stored as hashed, encrypted evidence.</p>
      {canEdit && (
        <details className="card">
          <summary>Report an incident</summary>
          <form onSubmit={create} style={{ marginTop: 10 }}>
            <label>Original comment text (stored as evidence and analysed)
              <textarea name="comment_text" maxLength={5000} placeholder="Paste the public comment exactly as posted" /></label>
            <div className="form-grid">
              <label>Comment / profile URL<input name="source_url" type="url" maxLength={1000} placeholder="https://x.com/handle/status/123" /></label>
              <label>Author public handle<input name="author_handle" maxLength={60} placeholder="@handle (taken from URL if empty)" /></label>
              <label>Person reported (if known)<input name="target_name" maxLength={100} /></label>
              <label>Content ID<input name="content_id" maxLength={200} /></label>
              <label>Posted at<input name="posted_at" type="datetime-local" /></label>
              <label>Incident type
                <select name="incident_type" defaultValue="">
                  <option value="">Suggest from analysis</option>
                  {INCIDENT_TYPES.map((t) => <option key={t} value={t}>{t.replaceAll("_", " ")}</option>)}
                </select>
              </label>
            </div>
            <label>Your description<textarea name="description" maxLength={5000} /></label>
            <button className="primary" disabled={busy}>{busy ? "Saving…" : "Create incident"}</button>
          </form>
        </details>
      )}
      <ErrorText error={error} />
      {(c.incidents ?? []).length === 0 ? <Empty>No incidents yet.</Empty> : c.incidents!.map((inc) => (
        <div className="card" key={inc.id}>
          <div className="row between">
            <div><Badge value={inc.incident_type} tone="bad" /> <Badge value={inc.severity} /> <Badge value={inc.status} />{" "}
              <code>{inc.id}</code></div>
            <div className="row">
              {canEdit && (
                <select aria-label="Incident status" value={inc.status} style={{ width: "auto" }}
                  onChange={async (e) => { await api.updateIncident(c.id, inc.id, { status: e.target.value as Incident["status"] }).catch(setError); reload(); }}>
                  {["open", "under_review", "resolved", "dismissed"].map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
                </select>
              )}
              {canSearch && inc.author_handle && <button onClick={() => investigate(inc)}>Find public profile of @{inc.author_handle}</button>}
            </div>
          </div>
          <div className="small" style={{ marginTop: 6 }}>
            {inc.target_entity && <>Target entity: <b>{inc.target_entity}</b> · </>}
            {inc.source_platform && <>Platform: {inc.source_platform} · </>}
            {inc.source_url && <><a href={inc.source_url} target="_blank" rel="noopener noreferrer nofollow">source</a> · </>}
            reported {fmtTime(inc.created_at)}
          </div>
          {inc.description && <p>{inc.description}</p>}
          {(analysesByIncident.get(inc.id) ?? []).map((a) => <Indicators key={a.id} a={a.result} />)}
        </div>
      ))}
    </>
  );
}
