"use client";
import type { ReactNode } from "react";

export function fmtTime(iso?: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

const TONE: Record<string, string> = {
  completed: "good", done: "good", open: "info", running: "mid", queued: "mid", failed: "bad", closed: "",
  under_review: "mid", resolved: "good", dismissed: "", acknowledged: "mid", approved: "good", denied: "bad",
  pending: "mid", none: "", low: "info", medium: "mid", high: "bad", critical: "crit", strong: "good",
  possible: "mid", weak: "bad", active: "good", disabled: "bad", SUCCESS: "good", DENIED: "bad", FAILED: "bad",
};

export function Badge({ value, tone }: { value: string; tone?: string }) {
  return <span className={`badge ${tone ?? TONE[value] ?? ""}`}>{value.replaceAll("_", " ")}</span>;
}

export function Spinner({ label }: { label?: string }) {
  return <span className="muted"><span className="spinner" /> {label}</span>;
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="error" role="alert">{error instanceof Error ? error.message : String(error)}</p>;
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return <div className="stat"><div className={`v ${tone ?? ""}`}>{value}</div><div className="l">{label}</div></div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="muted">{children}</p>;
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: [T, string][]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map(([key, label]) => (
        <button key={key} role="tab" aria-selected={value === key} className={value === key ? "active" : ""}
          onClick={() => onChange(key)}>{label}</button>
      ))}
    </div>
  );
}

export function Hash({ value }: { value: string }) {
  return <code title={value}>{value.slice(0, 12)}…{value.slice(-6)}</code>;
}
