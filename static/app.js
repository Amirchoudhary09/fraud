const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let current = null;
let pollTimer = null;

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = body.detail;
    throw new Error(Array.isArray(d) ? d.map((x) => x.msg).join("; ") : d || res.statusText);
  }
  return body;
}

async function loadHealth() {
  const h = await api("/api/health");
  const el = $("#mode");
  el.textContent = h.mode === "mock" ? "MOCK MODE — demo data (no GEMINI_API_KEY)" : `Gemini · ${h.model}`;
  el.classList.toggle("mock", h.mode === "mock");
}

async function loadCases() {
  const cases = await api("/api/investigations");
  $("#cases").innerHTML = cases.map((c) => `
    <li data-id="${esc(c.id)}" class="${c.id === current ? "active" : ""}">
      <span>${esc(c.input.name)}${c.input.company ? ` · <span class="muted">${esc(c.input.company)}</span>` : ""}</span>
      <span class="status-${esc(c.status)}">${esc(c.status)}</span>
    </li>`).join("") || '<li class="muted">No cases yet</li>';
}

$("#cases").addEventListener("click", (e) => {
  const li = e.target.closest("li[data-id]");
  if (li) openCase(li.dataset.id);
});

$("#form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const identity = {};
  for (const k of ["name", "company", "college", "role", "location", "username"]) identity[k] = f.get(k) || null;
  const err = $("#formError");
  err.hidden = true;
  try {
    const { id } = await api("/api/investigations", {
      method: "POST",
      body: JSON.stringify({ identity, purpose: f.get("purpose"), acknowledged: f.get("acknowledged") === "on" }),
    });
    await openCase(id);
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  }
});

async function openCase(id) {
  current = id;
  clearTimeout(pollTimer);
  const inv = await api(`/api/investigations/${id}`);
  render(inv);
  loadCases();
  if (inv.status === "queued" || inv.status === "running") {
    pollTimer = setTimeout(() => openCase(id), 1500);
  }
}

function render(inv) {
  const d = $("#detail");
  const who = Object.entries(inv.input).map(([k, v]) => `<b>${esc(k)}:</b> ${esc(v)}`).join(" · ");
  let body = "";
  if (inv.status === "queued" || inv.status === "running") {
    body = `<p><span class="spinner"></span> ${esc(inv.stage)}…</p>`;
  } else if (inv.status === "failed") {
    body = `<p class="error">Failed: ${esc(inv.error)}</p>`;
  } else {
    const r = inv.result;
    body = (r.mock ? '<div class="banner">Demo data generated in mock mode — add GEMINI_API_KEY to .env for real search.</div>' : "")
      + (r.search_errors.length ? `<div class="banner">Some searches failed: ${esc(r.search_errors.join(" | "))}</div>` : "")
      + `<p class="muted">Scores are heuristic evidence scores, not probabilities. A high score is not proof of identity — review the sources.</p>`
      + (r.candidates.map((c) => candidateCard(inv, c)).join("") || "<p>No candidates with cited public evidence were found.</p>")
      + `<details><summary>Search queries (${r.queries.length}) and sources (${r.sources.length})</summary>
          <ul>${r.queries.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>
          <ol>${r.sources.map((s) => `<li class="src"><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title || s.url)}</a></li>`).join("")}</ol>
        </details>
        <div class="actions">
          <button onclick="window.open('/api/investigations/${esc(inv.id)}/report','_blank')">Open report (print / save as PDF)</button>
          <button onclick="deleteCase('${esc(inv.id)}')">Delete case</button>
        </div>`;
  }
  d.innerHTML = `<h2>Case ${esc(inv.id)}</h2><p class="muted">${who} · purpose: ${esc(inv.purpose)} · ${esc(inv.created_at)}</p>${body}`;
}

function srcLinks(sources) {
  return sources.map((s) => `<div class="src">↳ <a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title || s.url)}</a></div>`).join("");
}

function candidateCard(inv, c) {
  const icon = { match: "✓", partial: "≈", mismatch: "✗", unknown: "?", corroboration: "+" };
  const signals = c.signals.map((s) => `<li class="st-${s.status}">${icon[s.status]} <b>${esc(s.field)}</b>
      <span class="muted">(${s.points >= 0 ? "+" : ""}${s.points})</span> ${esc(s.detail)}${srcLinks(s.sources)}</li>`).join("");
  const contra = c.contradictions.map((x) => `<li class="st-mismatch">⚠ ${esc(x.detail)} <span class="muted">(−5)</span>${srcLinks(x.sources)}</li>`).join("");
  const claims = c.claims.map((cl) => `<tr><td>${esc(cl.field)}</td><td>${esc(cl.value)}</td><td>${esc(cl.evidence)}</td>
      <td>${cl.source ? `<a href="${esc(cl.source.url)}" target="_blank" rel="noopener noreferrer">${esc(cl.source.title || "source")}</a>` : ""}</td></tr>`).join("");
  const fb = inv.feedback[c.candidate_id];
  const btn = (v, label) => `<button class="${fb === v ? "on" : ""}" onclick="sendFeedback('${esc(inv.id)}','${esc(c.candidate_id)}','${v}')">${label}</button>`;
  return `<div class="card band-${c.band}">
    <div class="card-head">
      <div><b style="color:var(--text)">${esc(c.display_name)}</b> <span class="muted">${esc(c.candidate_id)} · ${esc(c.platform)}</span></div>
      <div class="score">${c.score}<span class="muted" style="font-size:13px">/100 · ${esc(c.band)}</span></div>
    </div>
    <div class="bar"><div style="width:${c.score}%"></div></div>
    <details style="color:var(--text)"><summary>Why ${c.score}?</summary><ul class="signals">${signals}${contra}</ul></details>
    <details style="color:var(--text)"><summary>Evidence (${c.claims.length} cited claims)</summary>
      <div class="table-wrap"><table><tr><th>Field</th><th>Value</th><th>Evidence</th><th>Source</th></tr>${claims}</table></div></details>
    <div class="actions" style="color:var(--text)"><span class="muted">Your review:</span>
      ${btn("correct", "✓ Correct match")}${btn("wrong", "✗ Wrong match")}${btn("insufficient", "Insufficient evidence")}</div>
  </div>`;
}

async function sendFeedback(id, cid, verdict) {
  await api(`/api/investigations/${id}/candidates/${cid}/feedback`, { method: "POST", body: JSON.stringify({ verdict }) });
  openCase(id);
}

async function deleteCase(id) {
  if (!confirm("Delete this case and its evidence?")) return;
  await api(`/api/investigations/${id}`, { method: "DELETE" });
  current = null;
  $("#detail").innerHTML = '<p class="muted">Case deleted.</p>';
  loadCases();
}

loadHealth();
loadCases();
