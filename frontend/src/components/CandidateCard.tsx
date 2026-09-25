"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import type { Candidate, SourceRef, Verdict } from "@/lib/types";
import { ErrorText } from "./ui";

const ICON = { match: "✓", partial: "≈", mismatch: "✗", unknown: "?", corroboration: "+" } as const;

function Sources({ sources }: { sources: SourceRef[] }) {
  return <>{sources.map((s) => (
    <div className="src" key={s.url}>↳ <a href={s.url} target="_blank" rel="noopener noreferrer nofollow">{s.title || s.url}</a></div>
  ))}</>;
}

export default function CandidateCard({ searchId, c, verdict, canReview, onReviewed }: {
  searchId: string; c: Candidate; verdict?: Verdict; canReview: boolean; onReviewed: () => void;
}) {
  const [showEvidence, setShowEvidence] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function openEvidence(open: boolean) {
    setShowEvidence(open);
    // Opening a candidate's evidence is recorded in the audit log (EVIDENCE_VIEWED).
    if (open) api.viewCandidate(searchId, c.candidate_id).catch(setError);
  }

  async function review(v: Verdict) {
    try {
      await api.feedback(searchId, c.candidate_id, v);
      onReviewed();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <div className="card">
      <div className="row between">
        <div>
          <b>{c.display_name}</b> <span className="muted small">{c.candidate_id} · {c.platform}</span>
          {c.profile_url && <div className="src" style={{ marginLeft: 0 }}>
            <a href={c.profile_url} target="_blank" rel="noopener noreferrer nofollow">{c.profile_url}</a></div>}
        </div>
        <div className={`band-${c.band}`} style={{ textAlign: "right" }}>
          <span className="score">{c.score}</span><span className="muted small">/100 · {c.band}</span>
          {c.calibrated != null && <div className="small">calibrated ≈ {Math.round(c.calibrated * 100)}% match</div>}
        </div>
      </div>
      <div className="bar"><div className={`bg-${c.band}`} style={{ width: `${c.score}%` }} /></div>

      <details>
        <summary>Why {c.score}?</summary>
        <ul className="signals">
          {c.signals.map((s, i) => (
            <li key={i} className={`st-${s.status}`}>
              {ICON[s.status]} <b>{s.field}</b> <span className="muted">({s.points >= 0 ? "+" : ""}{s.points})</span>{" "}
              <span style={{ color: "var(--text)" }}>{s.detail}</span>
              <Sources sources={s.sources} />
            </li>
          ))}
          {c.contradictions.map((x, i) => (
            <li key={`c${i}`} className="st-mismatch">⚠ <b>contradiction</b> <span className="muted">(−5)</span>{" "}
              <span style={{ color: "var(--text)" }}>{x.detail}</span><Sources sources={x.sources} /></li>
          ))}
        </ul>
      </details>

      <details onToggle={(e) => openEvidence((e.target as HTMLDetailsElement).open)}>
        <summary>Evidence ({c.claims.length} cited claims)</summary>
        {showEvidence && (
          <div className="table-wrap"><table>
            <thead><tr><th>Field</th><th>Value</th><th>Evidence</th><th>Source</th></tr></thead>
            <tbody>{c.claims.map((cl, i) => (
              <tr key={i}><td>{cl.field}</td><td>{cl.value}</td><td>{cl.evidence}</td>
                <td>{cl.source && <a href={cl.source.url} target="_blank" rel="noopener noreferrer nofollow">{cl.source.title || "source"}</a>}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </details>

      {canReview && (
        <div className="row" style={{ marginTop: 10 }}>
          <span className="muted small">Your review:</span>
          {([["correct", "✓ Correct match"], ["wrong", "✗ Wrong match"], ["insufficient", "Insufficient evidence"]] as [Verdict, string][])
            .map(([v, label]) => <button key={v} className={verdict === v ? "on" : ""} onClick={() => review(v)}>{label}</button>)}
        </div>
      )}
      <ErrorText error={error} />
    </div>
  );
}
