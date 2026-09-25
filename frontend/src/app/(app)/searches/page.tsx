"use client";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import SearchForm from "@/components/SearchForm";
import { Badge, Empty, ErrorText, Spinner, fmtTime } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Search } from "@/lib/types";

export default function SearchesPage() {
  const { can } = useAuth();
  const router = useRouter();
  const [all, setAll] = useState(false);
  const [rows, setRows] = useState<Search[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => { api.searches({ all }).then(setRows).catch(setError); }, [all]);
  useEffect(load, [load]);

  return (
    <>
      <h1>Searches</h1>
      {can("search.create") && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>New public identity search</h2>
          <SearchForm onStarted={(id) => router.push(`/searches/${id}`)} />
        </div>
      )}
      <div className="card">
        <div className="row between">
          <h2 style={{ margin: 0 }}>{all ? "All users' searches" : "My search history"}</h2>
          {can("search.view_all") && (
            <button onClick={() => setAll(!all)}>{all ? "Show only mine" : "Show all users (audited)"}</button>
          )}
        </div>
        <ErrorText error={error} />
        {!rows ? <Spinner /> : rows.length === 0 ? <Empty>No searches yet.</Empty> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Search</th>{all && <th>User</th>}<th>Target</th><th>Type</th><th>When</th><th>Case</th><th>Status</th></tr></thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className="click" onClick={() => router.push(`/searches/${s.id}`)}>
                  <td><code>{s.id}</code></td>
                  {all && <td>#{s.user_id}</td>}
                  <td><b>{s.input.username ? `@${s.input.username}` : s.input.name}</b>
                    <div className="muted small">{[s.input.company, s.input.college, s.input.role].filter(Boolean).join(" · ")}</div></td>
                  <td className="small">{s.search_type.replaceAll("_", " ")}</td>
                  <td>{fmtTime(s.created_at)}</td>
                  <td>{s.case_id ? <code>{s.case_id}</code> : "-"}</td>
                  <td><Badge value={s.status} /></td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </div>
    </>
  );
}
