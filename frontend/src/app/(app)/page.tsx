"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Badge, Empty, ErrorText, Spinner, Stat, fmtTime } from "@/components/ui";
import { api } from "@/lib/api";
import type { MyDashboard } from "@/lib/types";

export default function Dashboard() {
  const [data, setData] = useState<MyDashboard | null>(null);
  const [error, setError] = useState<unknown>(null);
  const router = useRouter();

  useEffect(() => { api.myDashboard().then(setData).catch(setError); }, []);
  if (error) return <ErrorText error={error} />;
  if (!data) return <Spinner label="Loading dashboard…" />;

  const open = data.cases.filter((c) => c.status !== "closed").length;
  return (
    <>
      <h1>My dashboard</h1>
      <div className="stats">
        <Stat label="My searches" value={data.searches.length} />
        <Stat label="Cases I can access" value={data.cases.length} />
        <Stat label="Open cases" value={open} />
        <Stat label="People searched" value={new Set(data.relationships.filter((r) => r.relationship_type === "SEARCHED").map((r) => r.object_id)).size} />
      </div>

      <div className="card">
        <div className="row between"><h2 style={{ margin: 0 }}>My searches</h2><Link href="/searches">New search →</Link></div>
        <p className="muted small">Every search is recorded with who searched, whom, when, for which case, and why.</p>
        {data.searches.length === 0 ? <Empty>No searches yet.</Empty> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Search</th><th>Who → whom</th><th>When</th><th>Case</th><th>Purpose</th><th>Status</th></tr></thead>
            <tbody>
              {data.searches.map((s) => (
                <tr key={s.id} className="click" onClick={() => router.push(`/searches/${s.id}`)}>
                  <td><code>{s.id}</code></td>
                  <td>{data.user.email} → <b>{s.input.username ? `@${s.input.username}` : s.input.name}</b></td>
                  <td>{fmtTime(s.created_at)}</td>
                  <td>{s.case_id ? <code>{s.case_id}</code> : "-"}</td>
                  <td className="small">{s.purpose.replaceAll("_", " ")}</td>
                  <td><Badge value={s.status} /> {s.candidate_count != null && <span className="muted small">{s.candidate_count} candidates</span>}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </div>

      <div className="card">
        <div className="row between"><h2 style={{ margin: 0 }}>My cases</h2><Link href="/cases">All cases →</Link></div>
        {data.cases.length === 0 ? <Empty>No cases.</Empty> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Case</th><th>Title</th><th>Target</th><th>Incidents</th><th>Evidence</th><th>Status</th></tr></thead>
            <tbody>
              {data.cases.map((c) => (
                <tr key={c.id} className="click" onClick={() => router.push(`/cases/${c.id}`)}>
                  <td><code>{c.id}</code></td><td>{c.title}</td><td>{c.target_entity ?? "-"}</td>
                  <td>{c.incident_count}</td><td>{c.evidence_count}</td><td><Badge value={c.status} /></td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </div>
    </>
  );
}
