"use client";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import AccessPanel from "@/components/case/AccessPanel";
import EvidencePanel from "@/components/case/EvidencePanel";
import IncidentsPanel from "@/components/case/IncidentsPanel";
import ReportViewer from "@/components/ReportViewer";
import SearchForm from "@/components/SearchForm";
import { Badge, Empty, ErrorText, Hash, Spinner, Stat, Tabs, fmtTime } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Case, TimelineItem } from "@/lib/types";

type Tab = "incidents" | "evidence" | "searches" | "timeline" | "access" | "reports";

function BreakGlassRequest({ caseId }: { caseId: string }) {
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    try {
      await api.breakGlass(caseId, String(new FormData(e.currentTarget).get("reason")));
      setSent(true);
    } catch (err) { setError(err); }
  }
  if (sent) return <div className="banner info">Break-glass request sent. A security admin must approve it; you will get
    temporary read access, and the access is logged and alerted.</div>;
  return (
    <form className="card" onSubmit={submit}>
      <h3 style={{ marginTop: 0 }}>Emergency (break-glass) access</h3>
      <p className="muted small">Only for urgent situations. Your reason is logged and a high-priority security alert is raised.</p>
      <label>Reason (min 20 characters)<textarea name="reason" required minLength={20} maxLength={2000} /></label>
      <ErrorText error={error} />
      <button className="danger">Request break-glass access</button>
    </form>
  );
}

export default function CaseDetail() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const router = useRouter();
  const [c, setC] = useState<Case | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState<Tab>("incidents");
  const [timeline, setTimeline] = useState<TimelineItem[] | null>(null);
  const [report, setReport] = useState(false);

  const load = useCallback(() => { api.case(id).then(setC).catch(setError); }, [id]);
  useEffect(load, [load]);
  useEffect(() => {
    if (tab === "timeline") api.timeline(id).then(setTimeline).catch(setError);
  }, [tab, id, c]);

  if (error instanceof ApiError && error.status === 403 && !c) {
    return <><h1>Case {id}</h1><div className="banner bad">{error.message}</div><BreakGlassRequest caseId={id} /></>;
  }
  if (error && !c) return <ErrorText error={error} />;
  if (!c) return <Spinner label="Loading case…" />;

  const access = c.my_access;
  const canEdit = access === "owner" || access === "editor" || access === "admin";
  const isOwner = access === "owner" || access === "admin";

  return (
    <>
      <div className="row between">
        <div><h1 style={{ margin: 0 }}>{c.title}</h1>
          <p className="muted small"><code>{c.id}</code> · created by {c.created_by_email} · {fmtTime(c.created_at)} ·
            purpose {c.purpose.replaceAll("_", " ")} · your access <Badge value={access ?? "none"} tone="info" /></p></div>
        <div className="row">
          {canEdit && (
            <select aria-label="Case status" value={c.status} style={{ width: "auto" }}
              onChange={async (e) => { await api.updateCase(id, { status: e.target.value as Case["status"] }).catch(setError); load(); }}>
              <option value="open">open</option><option value="under_review">under review</option><option value="closed">closed</option>
            </select>
          )}
          {can("report.view") && <button onClick={() => setReport(true)}>Case report</button>}
          {can("data.delete") && <button className="danger" onClick={async () => {
            if (confirm("Permanently delete this case, its incidents, evidence and searches? The audit log keeps a record.")) {
              await api.deleteCase(id); router.replace("/cases");
            }
          }}>Delete</button>}
        </div>
      </div>
      {access === "admin" && <div className="banner warn small">You are viewing this case as an administrator without
        membership. This access is logged and raised as a security event.</div>}
      {c.description && <p>{c.description}</p>}
      <div className="stats">
        <Stat label="Target entity" value={c.target_entity ?? "-"} />
        <Stat label="Searches" value={c.search_count} />
        <Stat label="Incidents" value={c.incident_count} />
        <Stat label="Evidence" value={c.evidence_count} />
        <Stat label="Reports" value={c.report_count} />
        <Stat label="Status" value={<Badge value={c.status} />} />
      </div>
      <ErrorText error={error} />

      <Tabs<Tab> value={tab} onChange={setTab} tabs={[["incidents", "Incidents"], ["evidence", "Evidence"],
        ["searches", "Searches"], ["timeline", "Timeline"], ["access", "Access"], ["reports", "Reports"]]} />

      {tab === "incidents" && <IncidentsPanel c={c} canEdit={canEdit && can("incident.create")} canSearch={canEdit && can("search.create")} reload={load} />}
      {tab === "evidence" && <EvidencePanel c={c} canEdit={canEdit && can("evidence.capture")} canExport={can("evidence.export")} reload={load} />}

      {tab === "searches" && (
        <>
          {canEdit && can("search.create") && (
            <details className="card"><summary>Run a search inside this case</summary>
              <div style={{ marginTop: 10 }}><SearchForm caseId={id} defaultPurpose={c.purpose} onStarted={(sid) => router.push(`/searches/${sid}`)} /></div>
            </details>
          )}
          {(c.searches ?? []).length === 0 ? <Empty>No searches in this case.</Empty> : (
            <div className="card table-wrap"><table>
              <thead><tr><th>Search</th><th>Target</th><th>Type</th><th>By</th><th>When</th><th>Status</th></tr></thead>
              <tbody>{c.searches!.map((s) => (
                <tr key={s.id} className="click" onClick={() => router.push(`/searches/${s.id}`)}>
                  <td><code>{s.id}</code></td><td>{s.input.username ? `@${s.input.username}` : s.input.name}</td>
                  <td className="small">{s.search_type.replaceAll("_", " ")}</td><td>#{s.user_id}</td>
                  <td className="small">{fmtTime(s.created_at)}</td><td><Badge value={s.status} /></td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
        </>
      )}

      {tab === "timeline" && (
        <div className="card">
          <p className="muted small">Built from the tamper-evident audit log.</p>
          {!timeline ? <Spinner /> : timeline.length === 0 ? <Empty>No events.</Empty> : (
            <ul className="timeline">{timeline.map((t) => (
              <li key={t.event_id} className={t.result !== "SUCCESS" ? "failed" : ""}>
                <div className="small muted">{fmtTime(t.ts)}</div>
                {t.text} {t.target_id && <code>{t.target_id}</code>} {t.result !== "SUCCESS" && <Badge value={t.result} />}
              </li>
            ))}</ul>
          )}
        </div>
      )}

      {tab === "access" && <AccessPanel c={c} isOwner={isOwner} canShare={can("case.share")}
        canSeeHistory={can("audit.view") || (can("audit.view_case") && isOwner)} reload={load} />}

      {tab === "reports" && (
        <div className="card">
          <p className="muted small">Every generated report is recorded with its SHA-256 so a copy can be checked later.</p>
          {(c.reports ?? []).length === 0 ? <Empty>No reports generated yet.</Empty> : (
            <div className="table-wrap"><table>
              <thead><tr><th>Report</th><th>Kind</th><th>Format</th><th>By</th><th>When</th><th>SHA-256</th></tr></thead>
              <tbody>{c.reports!.map((r) => (
                <tr key={r.id}><td><code>{r.id}</code></td><td>{r.kind}</td><td>{r.format}</td><td>{r.generated_by_email}</td>
                  <td className="small">{fmtTime(r.generated_at)}</td><td><Hash value={r.content_hash} /></td></tr>
              ))}</tbody>
            </table></div>
          )}
        </div>
      )}

      {report && <ReportViewer htmlPath={`/api/cases/${id}/report`} pdfPath={`/api/cases/${id}/report.pdf`}
        pdfName={`case-report-${id}.pdf`} canExport={can("evidence.export")} onClose={() => { setReport(false); load(); }} />}
    </>
  );
}
