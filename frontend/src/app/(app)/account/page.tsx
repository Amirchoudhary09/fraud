"use client";
import QRCode from "qrcode";
import { useState, type FormEvent } from "react";
import { Badge, ErrorText, fmtTime } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AccountPage() {
  const { user, reload } = useAuth();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [qr, setQr] = useState<string | null>(null);

  async function startSetup() {
    try {
      const s = await api.mfaSetup();
      // QR is rendered locally in the browser; the secret is never sent to a third-party QR service.
      setQr(await QRCode.toDataURL(s.otpauth_uri, { margin: 1, width: 200 }).catch(() => null));
      setSetup(s);
    } catch (err) { setError(err); }
  }

  if (!user) return null;

  async function confirmCode(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    try {
      await api.mfaConfirm(String(new FormData(e.currentTarget).get("code")));
      setSetup(null);
      setMsg("Two-factor authentication is on. You will be asked for a code at every sign-in.");
      await reload();
    } catch (err) { setError(err); }
  }

  async function disable(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    try {
      await api.mfaDisable(String(new FormData(e.currentTarget).get("code")));
      setMsg("Two-factor authentication is off.");
      await reload();
    } catch (err) { setError(err); }
  }

  return (
    <>
      <h1>Account</h1>
      <div className="card">
        <p><b>{user.email}</b> <Badge value={user.role} tone="info" /></p>
        <p className="muted small">Last sign-in {fmtTime(user.last_login_at)} · member since {fmtTime(user.created_at)}</p>
        <details><summary>My permissions ({user.permissions?.length ?? 0})</summary>
          <p className="small">{user.permissions?.map((p) => <code key={p} style={{ marginRight: 8 }}>{p}</code>)}</p></details>
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Two-factor authentication (TOTP)</h2>
        {msg && <div className="banner info">{msg}</div>}
        <ErrorText error={error} />
        {user.mfa_enabled ? (
          <form className="row" onSubmit={disable} style={{ alignItems: "flex-end" }}>
            <Badge value="enabled" tone="good" />
            {user.mfa_required ? <span className="muted small">Required for your role; it cannot be turned off.</span> : <>
              <label style={{ maxWidth: 200 }}>Current code<input name="code" inputMode="numeric" pattern="[0-9]{6}" required /></label>
              <button className="danger" style={{ marginBottom: 8 }}>Turn off</button></>}
          </form>
        ) : !setup ? (
          <>
            <p className="muted">Protect your account with an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password…).</p>
            <button className="primary" onClick={startSetup}>Set up MFA</button>
          </>
        ) : (
          <form onSubmit={confirmCode}>
            <ol>
              <li>Scan this QR code with your authenticator app:
                {qr && <div style={{ margin: "8px 0" }}>
                  {/* eslint-disable-next-line @next/next/no-img-element -- data: URL generated locally */}
                  <img src={qr} alt="MFA QR code" width={200} height={200} style={{ background: "#fff", padding: 6, borderRadius: 6 }} />
                </div>}
                or choose <b>Enter a setup key</b>. Use account <code>{user.email}</code> and this key:
                <div style={{ margin: "6px 0" }}><code style={{ fontSize: 16, letterSpacing: 2 }}>{setup.secret.match(/.{1,4}/g)?.join(" ")}</code></div>
                <div className="muted small">Or open this link on your phone: <a href={setup.otpauth_uri}>otpauth link</a></div></li>
              <li>Enter the 6-digit code it shows:</li>
            </ol>
            <label style={{ maxWidth: 200 }}>Code<input name="code" inputMode="numeric" pattern="[0-9]{6}" required autoFocus /></label>
            <button className="primary">Confirm and enable</button>
          </form>
        )}
      </div>
    </>
  );
}
