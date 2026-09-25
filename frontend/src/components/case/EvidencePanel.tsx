"use client";
import { useState, type FormEvent } from "react";
import { api, download } from "@/lib/api";
import type { Case, Evidence } from "@/lib/types";
import { Badge, Empty, ErrorText, Hash, fmtTime } from "../ui";

type Mode = "text" | "url" | "file";

export default function EvidencePanel({ c, canEdit, canExport, reload }: {
  c: Case; canEdit: boolean; canExport: boolean; reload: () => void;
}) {
  const [mode, setMode] = useState<Mode>("text");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [opened, setOpened] = useState<Evidence | null>(null);
  const [checks, setChecks] = useState<Record<string, boolean>>({});

  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    const incident = String(f.get("incident_id") || "") || undefined;
    setBusy(true);
    setError(null);
    try {
      if (mode === "text") await api.addTextEvidence(c.id, String(f.get("text")), incident, String(f.get("source_url") || "") || undefined);
      if (mode === "url") await api.addUrlEvidence(c.id, String(f.get("url")), incident);
      if (mode === "file") await api.addFileEvidence(c.id, f.get("file") as File, incident);
      form.reset();
      reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function verify(ev: Evidence) {
    try {
      const r = await api.verifyEvidence(c.id, ev.id);
      setChecks((x) => ({ ...x, [ev.id]: r.ok }));
    } catch (err) { setError(err); }
  }

  return (
    <>
      <p className="muted small">Each item has its own ID, a SHA-256 of the canonical original taken at capture, and is
        encrypted at rest. Viewing, downloading and verifying are audited.</p>
      {canEdit && (
        <form className="card" onSubmit={add}>
          <div className="row">
            {(["text", "url", "file"] as Mode[]).map((m) => (
              <button type="button" key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>
                {m === "text" ? "Comment / text" : m === "url" ? "Public web page" : "Screenshot / file"}</button>
            ))}
          </div>
          <label style={{ marginTop: 10 }}>Incident (optional)
            <select name="incident_id" defaultValue="">
              <option value="">None</option>
              {(c.incidents ?? []).map((i) => <option key={i.id} value={i.id}>{i.id} · {i.incident_type}</option>)}
            </select>
          </label>
          {mode === "text" && <>
            <label>Text<textarea name="text" required maxLength={20000} /></label>
            <label>Source URL<input name="source_url" type="url" maxLength={1000} /></label>
          </>}
          {mode === "url" && <label>Public URL (fetched by the server with SSRF protection; private/internal addresses are refused)
            <input name="url" type="url" required maxLength={2000} placeholder="https://…" /></label>}
          {mode === "file" && <label>PNG, JPEG, WEBP, PDF or TXT, max 10 MB
            <input name="file" type="file" required accept="image/png,image/jpeg,image/webp,application/pdf,text/plain" /></label>}
          <ErrorText error={error} />
          <button className="primary" disabled={busy}>{busy ? "Capturing…" : "Capture evidence"}</button>
        </form>
      )}
      {!canEdit && <ErrorText error={error} />}
      {(c.evidence ?? []).length === 0 ? <Empty>No evidence captured.</Empty> : (
        <div className="card table-wrap"><table>
          <thead><tr><th>Evidence</th><th>Type</th><th>Captured</th><th>Method</th><th>SHA-256</th><th>Integrity</th><th /></tr></thead>
          <tbody>{c.evidence!.map((ev) => (
            <tr key={ev.id}>
              <td><code>{ev.id}</code>{ev.incident_id && <div className="muted small">{ev.incident_id}</div>}</td>
              <td>{ev.type.replaceAll("_", " ")}{typeof ev.metadata.filename === "string" && <div className="muted small">{ev.metadata.filename}</div>}
                {typeof ev.metadata.title === "string" && <div className="muted small">{ev.metadata.title}</div>}</td>
              <td className="small">{fmtTime(ev.captured_at)}</td>
              <td className="small">{ev.capture_method.replaceAll("_", " ")}</td>
              <td><Hash value={ev.content_hash} /></td>
              <td>{ev.id in checks ? <Badge value={checks[ev.id] ? "verified" : "TAMPERED"} tone={checks[ev.id] ? "good" : "crit"} />
                : <button onClick={() => verify(ev)}>Verify</button>}</td>
              <td className="row" style={{ gap: 6 }}>
                {!ev.has_file && <button onClick={() => api.viewEvidence(c.id, ev.id).then(setOpened).catch(setError)}>View</button>}
                {canExport && <button onClick={() => download(`/api/cases/${c.id}/evidence/${ev.id}/download`,
                  (ev.metadata.filename as string) || `${ev.id}.txt`).catch(setError)}>Download</button>}
              </td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      {opened && (
        <div className="card">
          <div className="row between"><b>{opened.id}</b><button onClick={() => setOpened(null)}>Close</button></div>
          {opened.source_url && <div className="small"><a href={opened.source_url} target="_blank" rel="noopener noreferrer nofollow">{opened.source_url}</a></div>}
          <pre className="answer">{opened.text}</pre>
        </div>
      )}
    </>
  );
}
