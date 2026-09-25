"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Health } from "@/lib/types";
import { Spinner } from "./ui";

export default function AppShell({ children }: { children: ReactNode }) {
  const { user, loading, can, signOut } = useAuth();
  const router = useRouter();
  const path = usePathname();
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace(`/login?next=${encodeURIComponent(path)}`);
  }, [loading, user, router, path]);
  useEffect(() => { api.health().then(setHealth).catch(() => setHealth(null)); }, []);

  if (loading || !user) return <div className="auth-wrap"><Spinner label="Loading…" /></div>;

  const links: [string, string, boolean][] = [
    ["/", "Dashboard", true],
    ["/searches", "Searches", can("search.view_own")],
    ["/cases", "Cases", can("case.create") || can("case.view_all") || can("report.view")],
    ["/security", "Security", can("security.view") || can("audit.view")],
    ["/admin", "Admin", can("users.manage") || can("admin.evaluate")],
    ["/account", "Account", true],
  ];
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));

  return (
    <div className="shell">
      <nav className="nav" aria-label="Main">
        <div className="brand">Identity Evidence</div>
        {links.filter(([, , show]) => show).map(([href, label]) => (
          <Link key={href} href={href} className={active(href) ? "active" : ""}>{label}</Link>
        ))}
        <div className="spacer" />
        <div className="who">
          {user.email}<br /><span className="badge info">{user.role.replace("_", " ")}</span>
          {health && <div style={{ marginTop: 6 }}>
            {health.mode === "mock" ? <span className="badge mid">MOCK MODE</span> : <span className="badge good">Gemini</span>}
          </div>}
          <button style={{ marginTop: 8, width: "100%" }} onClick={async () => { await signOut(); router.replace("/login"); }}>
            Sign out
          </button>
        </div>
      </nav>
      <main className="main">
        {health?.mode === "mock" && (
          <div className="banner warn small">Mock mode: results are demo data. Add GEMINI_API_KEY to the backend for real public search.</div>
        )}
        {user.mfa_required && !user.mfa_enabled && (
          <div className="banner bad small">Your role requires MFA. <Link href="/account">Set it up now</Link>; the API is blocked until you do.</div>
        )}
        {children}
      </main>
    </div>
  );
}
