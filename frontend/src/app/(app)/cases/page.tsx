"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { Badge, Empty, ErrorText, Spinner, fmtTime } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { PURPOSES, type Case, type Purpose } from "@/lib/types";

export default function CasesPage() {
  const { can } = useAuth();
  const router = useRouter();
  const [rows, setRows] = useState<Case[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.cases().then(setRows).catch(setError); }, []);

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      const c = await api.createCase(String(f.get("title")), String(f.get("description") || ""), f.get("purpose") as Purpose);
      router.push(`/cases/${c.id}`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Cases</h1>
      {can("case.create") && (
        <details className="card">
          <summary>New case</summary>
          <form onSubmit={create} style={{ marginTop: 10 }}>
            <label>Title *<input name="title" required minLength={3} maxLength={200} placeholder="Threatening replies on launch post" /></label>
            <label>Description<textarea name="description" maxLength={5000} /></label>
            <label>Purpose *
              <select name="purpose" defaultValue="harassment_report">
                {Object.entries(PURPOSES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <label className="check"><input type="checkbox" required />
              This case documents publicly available information for a lawful purpose. Findings will be reviewed by a
              human before any action.</label>
            <button className="primary" disabled={busy}>Create case</button>
          </form>
        </details>
      )}
      <ErrorText error={error} />
      <div className="card">
        {!rows ? <Spinner /> : rows.length === 0 ? <Empty>No cases you can access.</Empty> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Case</th><th>Title</th><th>Target</th><th>Searches</th><th>Incidents</th><th>Evidence</th><th>Reports</th><th>Opened</th><th>Status</th></tr></thead>
            <tbody>{rows.map((c) => (
              <tr key={c.id} className="click" onClick={() => router.push(`/cases/${c.id}`)}>
                <td><code>{c.id}</code></td><td>{c.title}</td><td>{c.target_entity ?? "-"}</td><td>{c.search_count}</td>
                <td>{c.incident_count}</td><td>{c.evidence_count}</td><td>{c.report_count}</td><td>{fmtTime(c.created_at)}</td>
                <td><Badge value={c.status} /></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
    </>
  );
}
