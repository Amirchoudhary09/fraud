"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import CandidateCard from "@/components/CandidateCard";
import EvidenceGraph from "@/components/EvidenceGraph";
import ReportViewer from "@/components/ReportViewer";
import { Badge, ErrorText, Spinner, Tabs, fmtTime } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Answer, EvidenceGraph as Graph, Search } from "@/lib/types";

type Tab = "candidates" | "graph" | "ask" | "trace";

export default function SearchDetail() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const router = useRouter();
  const [s, setS] = useState<Search | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState<Tab>("candidates");
  const [graph, setGraph] = useState<Graph | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [asking, setAsking] = useState(false);
  const [report, setReport] = useState(false);

  const load = useCallback(() => api.search(id).then(setS).catch(setError), [id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (s && (s.status === "queued" || s.status === "running")) {
      const t = setTimeout(load, 1500);
      return () => clearTimeout(t);
    }
  }, [s, load]);
  useEffect(() => {
    if (tab === "graph" && !graph && s?.status === "completed") api.graph(id).then(setGraph).catch(setError);
  }, [tab, graph, s, id]);

  async function ask(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const q = String(new FormData(e.currentTarget).get("q"));
    setAsking(true);
    setError(null);
    try { setAnswer(await api.ask(id, q)); } catch (err) { setError(err); } finally { setAsking(false); }
  }

  if (error && !s) return <ErrorText error={error} />;
  if (!s) return <Spinner label="Loading search…" />;
  const r = s.result;

  return (
    <>
      <div className="row between">
        <h1 style={{ margin: 0 }}>{s.input.username ? `@${s.input.username}` : s.input.name}</h1>
        <div className="row">
          {s.status === "completed" && can("report.view") && <button onClick={() => setReport(true)}>Report</button>}
          {can("data.delete") && <button className="danger" onClick={async () => {
            if (confirm("Delete this search and its evidence index?")) { await api.deleteSearch(id); router.replace("/searches"); }
          }}>Delete</button>}
        </div>
      </div>
      <p className="muted small">
        <code>{s.id}</code> · {s.search_type.replaceAll("_", " ")} · {fmtTime(s.created_at)} · purpose: {s.purpose.replaceAll("_", " ")}
        {s.case_id && <> · case <Link href={`/cases/${s.case_id}`}>{s.case_id}</Link></>}
        {" · "}{Object.entries(s.input).filter(([k]) => k !== "name").map(([k, v]) => `${k}: ${v}`).join(" · ")}
      </p>

      {(s.status === "queued" || s.status === "running") && <div className="card"><Spinner label={`${s.stage}…`} /></div>}
      {s.status === "failed" && <div className="banner bad">Search failed: {s.error}</div>}

      {r && (
        <>
          {r.mock && <div className="banner warn">Demo data generated in mock mode.</div>}
          {r.search_errors.length > 0 && <div className="banner warn">Some searches failed: {r.search_errors.join(" | ")}</div>}
          <div className="banner info small">Scores are heuristic evidence scores, not probabilities. A high score is not
            proof of identity. Review the sources before acting.</div>
          <Tabs<Tab> value={tab} onChange={setTab} tabs={[["candidates", `Candidates (${r.candidates.length})`],
            ["graph", "Evidence graph"], ["ask", "Ask the evidence"], ["trace", "Agents & sources"]]} />

          {tab === "candidates" && (r.candidates.length === 0
            ? <p>No candidates with cited public evidence were found.</p>
            : r.candidates.map((c) => (
              <CandidateCard key={c.candidate_id} searchId={id} c={c} verdict={s.feedback?.[c.candidate_id]}
                canReview={can("feedback.submit")} onReviewed={load} />
            )))}

          {tab === "graph" && <div className="card">{graph ? <EvidenceGraph graph={graph} /> : <Spinner />}</div>}

          {tab === "ask" && (
            <div className="card">
              <p className="muted small">Answers come only from the {r.indexed_chunks} evidence chunks already collected, with
                citations. Questions about private data are blocked.</p>
              <form className="row" onSubmit={ask}>
                <input name="q" required minLength={3} maxLength={500} placeholder="e.g. Which sources mention WASP3D?" style={{ flex: 1, minWidth: 200 }} />
                <button className="primary" disabled={asking}>{asking ? "Thinking…" : "Ask"}</button>
              </form>
              <ErrorText error={error} />
              {answer && <>
                <pre className="answer">{answer.answer}</pre>
                <h3>Citations</h3>
                <ol className="small">{answer.citations.map((c, i) => (
                  <li key={i}>{c.text} <span className="muted">({c.score.toFixed(2)})</span>
                    {c.source_url && <> · <a href={c.source_url} target="_blank" rel="noopener noreferrer nofollow">{c.source_title || "source"}</a></>}</li>
                ))}</ol>
              </>}
            </div>
          )}

          {tab === "trace" && (
            <div className="grid2">
              <div className="card">
                <h3 style={{ marginTop: 0 }}>Supervisor trace</h3>
                <ul className="timeline">{r.agent_trace.map((t, i) => (
                  <li key={i}><Badge value={t.agent} tone="info" /> {t.detail} <div className="muted small">{fmtTime(t.ts)}</div></li>
                ))}</ul>
                <h3>Queries</h3>
                <ul className="small">{r.queries.map((q) => <li key={q}><code>{q}</code></li>)}</ul>
              </div>
              <div className="card">
                <h3 style={{ marginTop: 0 }}>Sources ({r.sources.length})</h3>
                <ol className="small">{r.sources.map((x) => (
                  <li key={x.url} className="src" style={{ marginLeft: 0 }}>
                    <a href={x.url} target="_blank" rel="noopener noreferrer nofollow">{x.title || x.url}</a></li>
                ))}</ol>
              </div>
            </div>
          )}
        </>
      )}
      {report && <ReportViewer htmlPath={`/api/searches/${id}/report`} pdfPath={`/api/searches/${id}/report.pdf`}
        pdfName={`search-report-${id}.pdf`} canExport={can("evidence.export")} onClose={() => setReport(false)} />}
    </>
  );
}
