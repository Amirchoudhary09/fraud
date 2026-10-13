"use client";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { PURPOSES, type Identity, type Purpose } from "@/lib/types";
import { ErrorText } from "./ui";

const FIELDS: [keyof Identity, string][] = [
  ["name", "Name"], ["company", "Company"], ["college", "College / university"],
  ["role", "Role"], ["location", "Location"], ["username", "Public username"],
];

export default function SearchForm({ caseId, defaultPurpose, onStarted }: {
  caseId?: string; defaultPurpose?: Purpose; onStarted: (id: string) => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [purpose, setPurpose] = useState<Purpose>(defaultPurpose ?? "self_check");
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function extract(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const parsed = await api.parseSearchPrompt(prompt);
      setIdentity(parsed);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function startSearch() {
    if (!identity || !acknowledged) return;
    setBusy(true);
    setError(null);
    try {
      const { id } = await api.createSearch(identity, purpose, caseId);
      onStarted(id);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={extract}>
      {!identity ? (
        <>
          <label htmlFor="search-prompt">Describe who you want to find</label>
          <textarea
            id="search-prompt"
            name="prompt"
            required
            minLength={3}
            maxLength={1000}
            rows={4}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Example: Find public professional profiles for Amir Choudhary, a software developer at WASP3D who studied at GLBITM and is based in Noida."
          />
          <p className="muted small">One field is enough. AI will extract any name, company, college, role, location or public username you mention.</p>
          <label>Purpose *
            <select value={purpose} onChange={(e) => setPurpose(e.target.value as Purpose)} required>
              {Object.entries(PURPOSES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="check"><input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} required />
            I will only use public information for a lawful purpose. Results are possible matches, not proof of identity,
            and I will not use them to contact, expose or harass anyone. This search is logged.</label>
          <ErrorText error={error} />
          <button className="primary" disabled={busy || !acknowledged}>{busy ? "Extracting details with AI…" : "Understand my search"}</button>
        </>
      ) : (
        <>
          <h3>AI extracted these search details</h3>
          <p className="muted small">Review the extracted details before the search starts. Missing details are left blank; AI does not guess them.</p>
          <dl className="details-list">
            {FIELDS.filter(([key]) => identity[key]).map(([key, label]) => (
              <div key={key} className="row between"><dt>{label}</dt><dd>{identity[key]}</dd></div>
            ))}
          </dl>
          <p><b>Original request:</b> {prompt}</p>
          <ErrorText error={error} />
          <div className="row">
            <button type="button" onClick={() => { setIdentity(null); setError(null); }}>Edit request</button>
            <button type="button" className="primary" disabled={busy} onClick={startSearch}>{busy ? "Starting search…" : "Confirm and start search"}</button>
          </div>
        </>
      )}
    </form>
  );
}
