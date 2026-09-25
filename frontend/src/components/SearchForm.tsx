"use client";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { PURPOSES, type Identity, type Purpose } from "@/lib/types";
import { ErrorText } from "./ui";

const FIELDS: [keyof Identity, string, string][] = [
  ["name", "Name *", "Amir Choudhary"], ["company", "Company", "WASP3D"], ["college", "College", "GLBITM"],
  ["role", "Role", "Software Developer"], ["location", "City", "Delhi"], ["username", "Public username", "optional"],
];

export default function SearchForm({ caseId, defaultPurpose, onStarted }: {
  caseId?: string; defaultPurpose?: Purpose; onStarted: (id: string) => void;
}) {
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const identity = Object.fromEntries(FIELDS.map(([k]) => [k, String(f.get(k) ?? "").trim() || null])) as unknown as Identity;
    setBusy(true);
    setError(null);
    try {
      const { id } = await api.createSearch(identity, f.get("purpose") as Purpose, caseId);
      onStarted(id);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="form-grid">
        {FIELDS.map(([k, label, ph]) => (
          <label key={k}>{label}
            <input name={k} required={k === "name"} minLength={k === "name" ? 2 : undefined} maxLength={100} placeholder={ph} />
          </label>
        ))}
      </div>
      <label>Purpose *
        <select name="purpose" defaultValue={defaultPurpose ?? "self_check"} required>
          {Object.entries(PURPOSES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </label>
      <label className="check"><input type="checkbox" required />
        I will only use public information for a lawful purpose. Results are possible matches, not proof of identity,
        and I will not use them to contact, expose or harass anyone. This search is logged.</label>
      <ErrorText error={error} />
      <button className="primary" disabled={busy}>{busy ? "Starting…" : "Start search"}</button>
    </form>
  );
}
