"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { ErrorText, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function LoginForm() {
  const { user, loading, reload } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next");
  const target = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";

  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null);
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.authStatus().then((s) => setNeedsSetup(s.needs_setup)).catch(setError); }, []);
  useEffect(() => { if (!loading && user) router.replace(target); }, [loading, user, router, target]);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      if (mfaToken) {
        await api.loginMfa(mfaToken, String(f.get("code")));
      } else if (needsSetup) {
        if (f.get("password") !== f.get("password2")) throw new Error("Passwords do not match");
        await api.setup(String(f.get("email")), String(f.get("password")));
      } else {
        const r = await api.login(String(f.get("email")), String(f.get("password")));
        if ("mfa_required" in r) {
          setMfaToken(r.mfa_token);
          return;
        }
      }
      await reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (needsSetup === null && !error) return <Spinner label="Loading…" />;

  return (
    <form className="card auth-card" onSubmit={submit}>
      <h1>{mfaToken ? "Two-factor code" : needsSetup ? "Create the first account" : "Sign in"}</h1>
      {needsSetup && !mfaToken && (
        <p className="muted small">This first account becomes the super admin. Other accounts are created by admins.</p>
      )}
      {mfaToken ? (
        <label>6-digit code from your authenticator app
          <input name="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" required autoFocus />
        </label>
      ) : (
        <>
          <label>Email<input name="email" type="email" autoComplete="username" required autoFocus /></label>
          <label>Password
            <input name="password" type="password" minLength={needsSetup ? 10 : 1} required
              autoComplete={needsSetup ? "new-password" : "current-password"} />
          </label>
          {needsSetup && <label>Repeat password<input name="password2" type="password" minLength={10} required autoComplete="new-password" /></label>}
        </>
      )}
      <ErrorText error={error} />
      <button className="primary" style={{ width: "100%" }} disabled={busy}>
        {busy ? "Please wait…" : mfaToken ? "Verify" : needsSetup ? "Create account" : "Sign in"}
      </button>
      <p className="muted small" style={{ marginTop: 12 }}>
        Access is logged. Only use this system for lawful purposes with publicly available information.
      </p>
    </form>
  );
}

export default function LoginPage() {
  return (
    <div className="auth-wrap">
      <Suspense fallback={<Spinner label="Loading…" />}><LoginForm /></Suspense>
    </div>
  );
}
