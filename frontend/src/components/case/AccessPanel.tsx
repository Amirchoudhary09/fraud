"use client";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import type { Case, TimelineItem } from "@/lib/types";
import { Badge, ErrorText, Spinner, fmtTime } from "../ui";

export default function AccessPanel({ c, isOwner, canShare, canSeeHistory, reload }: {
  c: Case; isOwner: boolean; canShare: boolean; canSeeHistory: boolean; reload: () => void;
}) {
  const [history, setHistory] = useState<TimelineItem[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (canSeeHistory) api.accessHistory(c.id).then(setHistory).catch(setError);
  }, [c.id, canSeeHistory]);

  async function grant(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    const hours = Number(f.get("hours")) || undefined;
    try {
      await api.grant(c.id, String(f.get("email")), f.get("access") as "viewer" | "editor", hours);
      form.reset();
      reload();
    } catch (err) { setError(err); }
  }

  const active = (c.members ?? []).filter((m) => !m.revoked_at && (!m.expires_at || m.expires_at > new Date().toISOString()));
  return (
    <>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Who can access this case</h3>
        <div className="table-wrap"><table>
          <thead><tr><th>User</th><th>Access</th><th>Via</th><th>Granted</th><th>Expires</th><th /></tr></thead>
          <tbody>{active.map((m) => (
            <tr key={m.id}>
              <td>{m.email}</td><td><Badge value={m.access} tone="info" /></td>
              <td>{m.via === "break_glass" ? <Badge value="break glass" tone="crit" /> : m.via}</td>
              <td className="small">{fmtTime(m.granted_at)}</td><td className="small">{m.expires_at ? fmtTime(m.expires_at) : "never"}</td>
              <td>{isOwner && canShare && m.via !== "owner" &&
                <button className="danger" onClick={() => api.revoke(c.id, m.id).then(reload).catch(setError)}>Revoke</button>}</td>
            </tr>
          ))}</tbody>
        </table></div>
        {isOwner && canShare && (
          <form className="row" onSubmit={grant} style={{ marginTop: 10, alignItems: "flex-end" }}>
            <label style={{ flex: 2, minWidth: 180 }}>User email<input name="email" type="email" required /></label>
            <label style={{ flex: 1, minWidth: 110 }}>Access<select name="access"><option value="viewer">viewer</option><option value="editor">editor</option></select></label>
            <label style={{ flex: 1, minWidth: 110 }}>Expires in (hours)<input name="hours" type="number" min={1} max={8760} placeholder="never" /></label>
            <button className="primary" style={{ marginBottom: 8 }}>Grant</button>
          </form>
        )}
        <ErrorText error={error} />
      </div>
      {canSeeHistory && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Access history</h3>
          {!history ? <Spinner /> : (
            <div className="table-wrap"><table>
              <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Target</th><th>Result</th></tr></thead>
              <tbody>{history.slice().reverse().map((h) => (
                <tr key={h.event_id}><td className="small">{fmtTime(h.ts)}</td><td>{h.actor}</td>
                  <td>{h.event_type.replaceAll("_", " ")}</td><td className="small">{h.target_type} {h.target_id}</td>
                  <td><Badge value={h.result} /></td></tr>
              ))}</tbody>
            </table></div>
          )}
        </div>
      )}
    </>
  );
}
