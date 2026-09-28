"""Public footprint: per-account identity resolution, platform status, history timeline, expansion leads.

Every account of every candidate gets its own explainable evidence score. Rules:
- A username match alone is never enough: FOUND needs two independent non-username evidence types
  (name, company, role, education, location), or a cross-link from an already-matched account.
- Fields a profile does not state are listed as missing evidence and do not lower the score.
- A cross-link (this account is linked from, or links to, an account already FOUND for the same
  candidate) is strong evidence; anchors are recomputed until they stop changing.
- A contradicting name marks the account as belonging to someone else; it is never merged.
The score is a heuristic evidence score, not a probability and not proof of identity.
"""
from urllib.parse import urlsplit

from ..schemas.identity import IdentityInput, Profile
from . import platforms
from .similarity import MATCH_AT, PARTIAL_AT, similarity

WEIGHTS = {"name": 25, "company": 15, "education": 12, "role": 8, "location": 5}
USERNAME_WEIGHT = 10
CROSS_LINK_WEIGHT = 20
FOUND_AT, POSSIBLE_AT = 70, 40
_SIM_FIELD = {"name": "name", "company": "company", "education": "college", "role": "role", "location": "location"}
_TARGET = {"name": "name", "company": "company", "education": "college", "role": "role", "location": "location"}
_VALUE = {"name": "display_name", "company": "public_company", "education": "public_education",
          "role": "public_role", "location": "public_location"}


def norm_url(url: str | None) -> str:
    if not url:
        return ""
    u = urlsplit(url.strip())
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    return f"{host}{u.path.rstrip('/').lower()}"


def _sig(field: str, status: str, points: int, detail: str, source: dict | None) -> dict:
    return {"field": field, "status": status, "points": points, "detail": detail,
            "sources": [source] if source else []}


def score_account(identity: IdentityInput, prof: Profile, anchor_urls: set[str], anchor_links: set[str],
                  known_usernames: set[str]) -> dict:
    src = prof.source.model_dump() if prof.source else None
    signals, contradictions, raw, possible = [], [], 0, 0
    for field, weight in WEIGHTS.items():
        target = getattr(identity, _TARGET[field])
        if not target:
            continue
        value = getattr(prof, _VALUE[field])
        if not value:  # missing evidence: shown, but does not lower the score
            signals.append(_sig(field, "unknown", 0, f"The public profile does not state {'an' if field[0] in 'aeiou' else 'a'} {field}.", None))
            continue
        possible += weight
        sim = similarity(_SIM_FIELD[field], target, value)
        if sim >= MATCH_AT:
            raw += weight
            signals.append(_sig(field, "match", weight, f'"{value}" matches "{target}".', src))
        elif sim >= PARTIAL_AT:
            raw += weight // 2
            signals.append(_sig(field, "partial", weight // 2, f'"{value}" partially matches "{target}".', src))
        else:
            pts = -weight if field == "name" else -round(weight * 0.6)
            raw += pts
            signals.append(_sig(field, "mismatch", pts, f'Profile says "{value}", not "{target}".', src))
            contradictions.append(f"{field}: profile says \"{value}\", expected \"{target}\"")

    targets = {u.lower().lstrip("@") for u in ({identity.username} | known_usernames) if u}
    if prof.username and targets:
        possible += USERNAME_WEIGHT
        if prof.username.lower().lstrip("@") in targets:
            raw += USERNAME_WEIGHT
            signals.append(_sig("username", "match", USERNAME_WEIGHT,
                                f'Username "{prof.username}" matches a known handle (not proof on its own).', src))

    possible += CROSS_LINK_WEIGHT
    me = norm_url(prof.profile_url)
    linked_by_anchor = bool(me) and me in anchor_links
    links_to_anchor = any(norm_url(link) in anchor_urls for link in prof.public_links)
    if linked_by_anchor or links_to_anchor:
        raw += CROSS_LINK_WEIGHT
        how = "is linked from" if linked_by_anchor else "links to"
        signals.append(_sig("cross_link", "match", CROSS_LINK_WEIGHT,
                            f"This account {how} another account already matched to this person"
                            + (f" ({prof.linked_from})." if prof.linked_from else "."), src))

    score = max(0, min(100, round(100 * raw / possible))) if possible else 0
    positive = {s["field"] for s in signals if s["points"] > 0}
    independent = positive - {"username"}
    name_contradicts = any(s["field"] == "name" and s["status"] == "mismatch" for s in signals)
    if name_contradicts:
        status = "INSUFFICIENT EVIDENCE"
    elif score >= FOUND_AT and (len(independent) >= 2 or "cross_link" in independent):
        # a link published by an already-matched account of the person counts as strong on its own
        status = "FOUND"
    elif score >= POSSIBLE_AT and independent:
        status = "POSSIBLE MATCH"
    else:
        status = "INSUFFICIENT EVIDENCE"

    why = [s["detail"] for s in signals if s["points"] > 0]
    why_not = [s["detail"] for s in signals if s["points"] < 0] + \
              [s["detail"] for s in signals if s["status"] == "unknown"]
    if positive == {"username"}:
        why_not.insert(0, "Only the username matches; the same handle is often used by different people.")
    if name_contradicts:
        why_not.insert(0, "The public name differs: this is likely a different person with a similar handle.")
    confidence = "HIGH" if status == "FOUND" else "MEDIUM" if status == "POSSIBLE MATCH" else "LOW"
    return {**prof.model_dump(), "score": score, "status": status, "confidence": confidence, "evidence": signals,
            "contradictions": contradictions,
            "explanation": {"why_match": why, "why_it_may_not_match": why_not,
                            "supporting_sources": sorted({s["sources"][0]["url"] for s in signals
                                                          if s["points"] > 0 and s["sources"]}),
                            "contradicting_sources": sorted({s["sources"][0]["url"] for s in signals
                                                             if s["points"] < 0 and s["sources"]})}}


def score_candidate_accounts(identity: IdentityInput, profiles: list[Profile]) -> list[dict]:
    """Scores one candidate's accounts, re-anchoring on cross-links until the FOUND set is stable."""
    anchors: set[int] = set()
    for _ in range(4):
        found = [profiles[i] for i in anchors]
        anchor_urls = {norm_url(p.profile_url) for p in found if p.profile_url}
        anchor_links = {norm_url(link) for p in found for link in p.public_links}
        known = {p.username for p in found if p.username}
        scored = [score_account(identity, p, anchor_urls - {norm_url(p.profile_url)}, anchor_links, known)
                  for p in profiles]
        new = {i for i, s in enumerate(scored) if s["status"] == "FOUND"}
        if new == anchors:
            break
        anchors = new
    return scored


def timeline(accounts: list[dict]) -> list[dict]:
    """Dated public events of HIGH-confidence accounts only, oldest first."""
    rows = []
    for a in accounts:
        if a["status"] != "FOUND":
            continue
        label = platforms.BY_KEY[a["platform"]].name if a["platform"] in platforms.BY_KEY else a["platform"]
        if a.get("publicly_documented_creation_date"):
            rows.append({"date": a["publicly_documented_creation_date"], "platform": label,
                         "event": "Account created (publicly documented)", "source": a.get("source"),
                         "confidence": "HIGH"})
        for e in a.get("events", []):
            own = e.get("source") and a.get("profile_url") and norm_url(e["source"]["url"]) == norm_url(a["profile_url"])
            rows.append({**e, "platform": label, "confidence": "HIGH" if own else e.get("confidence", "MEDIUM")})
    return sorted(rows, key=lambda r: (r["date"], r["platform"]))


STATUS_ORDER = ["FOUND", "POSSIBLE MATCH", "INSUFFICIENT EVIDENCE"]


def platform_status(accounts: list[dict], searched: set[str], target_candidates: set[str]) -> list[dict]:
    """One row per known platform (+ websites), including platforms where nothing was found."""
    rows = []
    for p in (*platforms.PLATFORMS, platforms.Platform("website", "Personal websites", (), None)):
        mine = [a for a in accounts if a["platform"] == p.key]
        of_target = [a for a in mine if a["candidate_id"] in target_candidates]
        pool = of_target or mine
        if pool:
            best = min(pool, key=lambda a: STATUS_ORDER.index(a["status"]))
            status = best["status"] if of_target else "INSUFFICIENT EVIDENCE"
            detail = f"{len(pool)} account(s); best: {best.get('username') or best.get('profile_url')}"
        elif not p.searchable:
            status, detail = "NOT SEARCHABLE", "Profiles are login-walled or not indexed by search engines."
        elif p.key in searched or p.key == "website":
            status, detail = "NOT FOUND", "Not found / not reliably verified."
        else:
            status, detail = "NOT SEARCHABLE", "Not searched (query budget)."
        rows.append({"platform": p.key, "name": p.name, "status": status, "detail": detail,
                     "accounts": [{"candidate_id": a["candidate_id"], "username": a.get("username"),
                                   "profile_url": a.get("profile_url"), "status": a["status"], "score": a["score"]}
                                  for a in pool]})
    return rows


def leads(accounts: list[dict], known_urls: set[str]) -> list[dict]:
    """Outbound public links of FOUND accounts that are not yet part of the graph."""
    out, seen = [], set(known_urls)
    for a in accounts:
        if a["status"] != "FOUND":
            continue
        for link in a.get("public_links", []):
            n = norm_url(link)
            if n and n not in seen:
                seen.add(n)
                out.append({"url": link, "candidate_id": a["candidate_id"], "from": a.get("profile_url")})
    return out


def profiles_from_claims(cand) -> list[Profile]:
    """Deterministic profiles for cited sources whose real URL is a known platform profile, so an
    account is never missed just because the model did not list it. Fields come only from claims
    that cite that exact source."""
    have = {norm_url(p.profile_url) for p in cand.profiles}
    by_url: dict[str, list] = {}
    for cl in cand.claims:
        if cl.source:
            by_url.setdefault(cl.source.url, []).append(cl)
    out = []
    for url, claims in by_url.items():
        key, user = platforms.classify_url(url)
        if key == "website" or norm_url(url) in have or not user:
            continue
        val = {c.field: c.value for c in claims}
        out.append(Profile(platform=key, username=user, display_name=val.get("name"), profile_url=url,
                           public_company=val.get("company"), public_role=val.get("role"),
                           public_education=val.get("college"), public_location=val.get("location"),
                           source=claims[0].source))
    return out


def links_in_html(html: str, base_url: str) -> tuple[str, list[str]]:
    """(page title, outbound absolute http(s) links) from a fetched public page."""
    import re
    from urllib.parse import urljoin

    from .safe_fetch import html_to_text
    title, _ = html_to_text(html)
    links = []
    for href in re.findall(r"""href\s*=\s*["']([^"'#]+)["']""", html, re.I):
        u = urljoin(base_url, href.strip())
        if u.startswith(("http://", "https://")) and norm_url(u) != norm_url(base_url) and u not in links:
            links.append(u)
    return title, links[:100]
