"use client";
import { useCallback, useEffect, useState } from "react";
import { Badge, Empty, ErrorText, Hash, Spinner, Stat, Tabs, fmtTime } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AdminDashboard, AuditEvent, BreakGlass, SecurityEvent } from "@/lib/types";

type Tab = "alerts" | "breakglass" | "audit";

export default function SecurityPage() {
  const { can } = useAuth();
  const [dash, setDash] = useState<AdminDashboard | null>(null);
  const [events, setEvents] = useState<SecurityEvent[] | null>(null);
  const [bg, setBg] = useState<BreakGlass[] | null>(null);
  const [audit, setAudit] = useState<AuditEvent[] | null>(null);
  const [filter, setFilter] = useState("");
  const [verify, setVerify] = useState<{ ok: boolean; events_checked: number; broken_at?: string } | null>(null);
  const [tab, setTab] = useState<Tab>(can("security.view") ? "alerts" : "audit");
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    if (can("security.view")) {
      api.adminDashboard().then(setDash).catch(setError);
      api.securityEvents().then(setEvents).catch(setError);
    }
    if (can("break_glass.approve")) api.breakGlassRequests().then(setBg).catch(setError);
  }, [can]);
  useEffect(load, [load]);
  useEffect(() => {
    if (tab === "audit" && can("audit.view")) api.audit({ event_type: filter || undefined }).then(setAudit).catch(setError);
  }, [tab, filter, can]);

  return (
    <>
      <h1>Security</h1>
      <ErrorText error={error} />
      {dash && (
        <div className="stats">
          <Stat label="Active users" value={dash.active_users} />
          <Stat label="Active cases" value={dash.active_cases} />
          <Stat label="Searches (24h)" value={dash.searches_24h} />
          <Stat label="Incidents (24h)" value={dash.incidents_24h} />
          <Stat label="Evidence captured (24h)" value={dash.evidence_captured_24h} />
          <Stat label="Failed logins (24h)" value={dash.failed_logins_24h} tone={dash.failed_logins_24h ? "band-possible" : ""} />
          <Stat label="Denied requests (24h)" value={dash.authz_denied_24h} />
          <Stat label="Open security events" value={dash.open_security_events} tone={dash.open_security_events ? "band-weak" : ""} />
          <Stat label="Pending break-glass" value={dash.pending_break_glass} />
          <Stat label="API errors (since start)" value={Object.values(dash.api_errors).reduce((a, b) => a + b, 0)} />
          <Stat label="Audit integrity" value={dash.audit_integrity.ok
            ? <Badge value={`intact (${dash.audit_integrity.events_checked})`} tone="good" /> : <Badge value="BROKEN" tone="crit" />} />
        </div>
      )}
      <Tabs<Tab> value={tab} onChange={setTab} tabs={([
        ["alerts", "Security events"], ["breakglass", "Break-glass"], ["audit", "Audit log"],
      ] as [Tab, string][]).filter(([t]) => t === "alerts" ? can("security.view") : t === "breakglass" ? can("break_glass.approve") : can("audit.view"))} />

      {tab === "alerts" && (
        <div className="card">
          <p className="muted small">Raised by detectors on the audit stream (failed-login bursts, search bursts, many unrelated
            targets, mass export, repeated denials, privilege escalation, break-glass, integrity failures). A single
            event is not proof of misuse; review the context.</p>
          {!events ? <Spinner /> : events.length === 0 ? <Empty>No security events.</Empty> : (
            <div className="table-wrap"><table>
              <thead><tr><th>When</th><th>Severity</th><th>Type</th><th>User</th><th>Detail</th><th>Status</th><th /></tr></thead>
              <tbody>{events.map((e) => (
                <tr key={e.id}><td className="small">{fmtTime(e.ts)}</td><td><Badge value={e.severity} /></td>
                  <td>{e.type.replaceAll("_", " ")}</td><td className="small">{e.email ?? "-"}</td><td className="small">{e.detail}</td>
                  <td><Badge value={e.status} /></td>
                  <td className="row" style={{ gap: 4 }}>{can("security.manage") && e.status !== "resolved" && <>
                    {e.status === "open" && <button onClick={() => api.setSecurityEvent(e.id, "acknowledged").then(load)}>Ack</button>}
                    <button onClick={() => api.setSecurityEvent(e.id, "resolved").then(load)}>Resolve</button></>}</td></tr>
              ))}</tbody>
            </table></div>
          )}
        </div>
      )}

      {tab === "breakglass" && (
        <div className="card">
          {!bg ? <Spinner /> : bg.length === 0 ? <Empty>No break-glass requests.</Empty> : (
            <div className="table-wrap"><table>
              <thead><tr><th>Requested</th><th>User</th><th>Case</th><th>Reason</th><th>Status</th><th /></tr></thead>
              <tbody>{bg.map((b) => (
                <tr key={b.id}><td className="small">{fmtTime(b.created_at)}</td><td>{b.email}</td>
                  <td><code>{b.case_id}</code><div className="muted small">{b.case_title}</div></td><td className="small">{b.reason}</td>
                  <td><Badge value={b.status} />{b.expires_at && <div className="muted small">until {fmtTime(b.expires_at)}</div>}</td>
                  <td className="row" style={{ gap: 4 }}>{b.status === "pending" && <>
                    <button className="primary" onClick={() => api.decideBreakGlass(b.id, true, 4).then(load).catch(setError)}>Approve 4h</button>
                    <button className="danger" onClick={() => api.decideBreakGlass(b.id, false).then(load).catch(setError)}>Deny</button></>}</td></tr>
              ))}</tbody>
            </table></div>
          )}
        </div>
      )}

      {tab === "audit" && (
        <div className="card">
          <div className="row between">
            <input placeholder="Filter by event type, e.g. SEARCH_STARTED" value={filter} style={{ maxWidth: 360 }}
              onChange={(e) => setFilter(e.target.value.toUpperCase().trim())} />
            {can("audit.verify") && <button onClick={() => api.verifyAudit().then(setVerify).catch(setError)}>Verify hash chain</button>}
          </div>
          {verify && <div className={`banner ${verify.ok ? "info" : "bad"}`}>{verify.ok
            ? `Chain intact: ${verify.events_checked} events verified.` : `CHAIN BROKEN at ${verify.broken_at}. Investigate immediately.`}</div>}
          <p className="muted small">Append-only and hash-chained. Nobody (including admins) can edit or delete events through the app.</p>
          {!audit ? <Spinner /> : (
            <div className="table-wrap"><table>
              <thead><tr><th>#</th><th>When</th><th>Event</th><th>Actor</th><th>Target</th><th>Case / search</th><th>Result</th><th>Request</th><th>Hash</th></tr></thead>
              <tbody>{audit.map((e) => (
                <tr key={e.event_id} title={e.detail ?? ""}><td>{e.seq}</td><td className="small">{fmtTime(e.ts)}</td>
                  <td>{e.event_type}</td><td>{e.actor_user_id ?? "-"}</td><td className="small">{e.target_type} {e.target_id}</td>
                  <td className="small">{e.case_id ?? ""} {e.search_id ?? ""}</td><td><Badge value={e.result} /></td>
                  <td><code>{e.request_id}</code></td><td><Hash value={e.hash} /></td></tr>
              ))}</tbody>
            </table></div>
          )}
        </div>
      )}
    </>
  );
}
