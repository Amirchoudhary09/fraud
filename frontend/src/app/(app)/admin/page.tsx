"use client";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Badge, ErrorText, Spinner, fmtTime } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ROLES, type Role, type User } from "@/lib/types";

export default function AdminPage() {
  const { can, user: me } = useAuth();
  const [users, setUsers] = useState<User[] | null>(null);
  const [evalData, setEvalData] = useState<Record<string, unknown> | null>(null);
  const [threshold, setThreshold] = useState(75);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  const loadUsers = useCallback(() => { if (can("users.manage")) api.users().then(setUsers).catch(setError); }, [can]);
  useEffect(loadUsers, [loadUsers]);
  useEffect(() => { if (can("admin.evaluate")) api.evaluation(threshold).then(setEvalData).catch(setError); }, [can, threshold]);

  async function createUser(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    try {
      await api.createUser(String(f.get("email")), String(f.get("password")), f.get("role") as Role);
      form.reset();
      loadUsers();
    } catch (err) { setError(err); }
  }

  const act = (p: Promise<unknown>) => p.then(loadUsers).catch(setError);

  return (
    <>
      <h1>Administration</h1>
      <ErrorText error={error} />
      {msg && <div className="banner info">{msg}</div>}

      {can("users.manage") && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Users & roles</h2>
          <form className="row" onSubmit={createUser} style={{ alignItems: "flex-end" }}>
            <label style={{ flex: 2, minWidth: 180 }}>Email<input name="email" type="email" required /></label>
            <label style={{ flex: 2, minWidth: 160 }}>Initial password (min 10)<input name="password" type="password" minLength={10} required autoComplete="new-password" /></label>
            <label style={{ flex: 1, minWidth: 140 }}>Role<select name="role" defaultValue="analyst">
              {ROLES.filter((r) => r !== "super_admin" || me?.role === "super_admin").map((r) => <option key={r}>{r}</option>)}</select></label>
            <button className="primary" style={{ marginBottom: 8 }}>Create user</button>
          </form>
          {!users ? <Spinner /> : (
            <div className="table-wrap"><table>
              <thead><tr><th>User</th><th>Role</th><th>Status</th><th>MFA</th><th>Last login</th><th /></tr></thead>
              <tbody>{users.map((u) => (
                <tr key={u.id}>
                  <td>{u.email}<div className="muted small">#{u.id} · since {fmtTime(u.created_at)}</div></td>
                  <td>{u.id === me?.id ? <Badge value={u.role} tone="info" /> : (
                    <select aria-label="Role" value={u.role} style={{ width: "auto" }}
                      onChange={(e) => act(api.updateUser(u.id, { role: e.target.value as Role }))}>
                      {ROLES.map((r) => <option key={r}>{r}</option>)}</select>)}</td>
                  <td><Badge value={u.status} /></td>
                  <td>{u.mfa_enabled ? <Badge value="on" tone="good" /> : <Badge value="off" />}</td>
                  <td className="small">{fmtTime(u.last_login_at)}</td>
                  <td className="row" style={{ gap: 4 }}>{u.id !== me?.id && <>
                    <button onClick={() => act(api.updateUser(u.id, { status: u.status === "active" ? "disabled" : "active" }))}>
                      {u.status === "active" ? "Disable" : "Enable"}</button>
                    {!!u.mfa_enabled && <button onClick={() => confirm(`Reset MFA for ${u.email}? Their sessions will be revoked.`) && act(api.resetMfa(u.id))}>Reset MFA</button>}
                  </>}</td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
          <p className="muted small">Role, status and MFA changes are audited. Disabling a user revokes all their sessions.</p>
        </div>
      )}

      {can("admin.evaluate") && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Evaluation & calibration</h2>
          <p className="muted small">Ground truth = reviewer verdicts (correct / wrong). Numbers are only meaningful on a
            representative, audited set of labels. Suggested weights are never applied automatically.</p>
          <label style={{ maxWidth: 240 }}>Match threshold
            <input type="number" min={1} max={100} value={threshold} onChange={(e) => setThreshold(Number(e.target.value) || 75)} /></label>
          {!evalData ? <Spinner /> : <pre className="answer small" style={{ maxHeight: 360, overflow: "auto" }}>{JSON.stringify(evalData, null, 2)}</pre>}
          <div className="row">
            {(["platt", "isotonic"] as const).map((m) => (
              <button key={m} onClick={() => api.calibrate(m).then((r) => setMsg(String(r.message ?? `Calibration (${m}) saved and active.`))).catch(setError)}>
                Fit {m} calibration</button>
            ))}
            {can("data.delete") && <button className="danger" onClick={() => confirm("Purge cases and searches older than the retention period?") &&
              api.purge().then((r) => setMsg(`Purged ${r.cases} cases and ${r.searches} searches (retention ${r.retention_days} days).`)).catch(setError)}>
              Run retention purge</button>}
          </div>
        </div>
      )}
    </>
  );
}
