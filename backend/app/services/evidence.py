"""Evidence capture and integrity (spec sections 11-12).

Original evidence -> canonicalization -> SHA-256 -> encrypted storage. verify() recomputes
the hash from the stored content; a mismatch raises EVIDENCE_INTEGRITY_FAILED.
"""
import hashlib
import unicodedata

from ..core import crypto
from ..core.database import new_id
from ..repositories import entities
from ..repositories import evidence as repo
from . import audit, safe_fetch, storage

TYPES = ("PUBLIC_COMMENT", "SCREENSHOT", "WEB_PAGE", "DOCUMENT")


def canonical_text(text: str) -> bytes:
    """Unicode NFC, LF line endings, trailing whitespace trimmed: the same text always hashes the same."""
    t = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in t.strip().split("\n")).encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record(case_id, incident_id, type_, method, user, content_hash, **kw) -> dict:
    eid = repo.create(case_id, incident_id, type_, method, user["id"], content_hash, **kw)
    if incident_id:
        entities.relate("INCIDENT", incident_id, "CONTAINS", "EVIDENCE", eid, case_id=case_id, incident_id=incident_id)
    audit.record("EVIDENCE_CAPTURED", target_type="EVIDENCE", target_id=eid, case_id=case_id,
                 detail={"type": type_, "method": method, "sha256": content_hash, "incident_id": incident_id})
    return repo.get(eid)


def capture_text(case_id: str, incident_id: str | None, text: str, user: dict, type_: str = "PUBLIC_COMMENT",
                 source_url: str | None = None, metadata: dict | None = None,
                 method: str = "USER_SUBMITTED_TEXT") -> dict:
    canon = canonical_text(text)
    return _record(case_id, incident_id, type_, method, user, sha256(canon),
                   content_enc=crypto.encrypt_text(canon.decode()), source_url=source_url,
                   mime_type="text/plain", size=len(canon), metadata=metadata)


def capture_file(case_id: str, incident_id: str | None, data: bytes, content_type: str, filename: str,
                 user: dict, type_: str = "SCREENSHOT", source_url: str | None = None) -> dict:
    storage.check(data, content_type)
    path = storage.save(new_id("OBJ"), data)
    return _record(case_id, incident_id, type_, "FILE_UPLOAD", user, sha256(data), storage_path=path,
                   source_url=source_url, mime_type=content_type, size=len(data), metadata={"filename": filename})


def capture_url(case_id: str, incident_id: str | None, url: str, user: dict) -> dict:
    """Fetches a public page through the SSRF-safe fetcher and stores its visible text."""
    page = safe_fetch.fetch(url)
    ctype = page["content_type"].split(";")[0].strip().lower()
    raw = page["body"]
    if ctype in ("text/html", "application/xhtml+xml", ""):
        title, text = safe_fetch.html_to_text(raw.decode("utf-8", errors="replace"))
    elif ctype.startswith("text/"):
        title, text = "", raw.decode("utf-8", errors="replace")
    else:
        raise safe_fetch.FetchBlocked(f"Content type {ctype} cannot be captured as a web page")
    meta = {"title": title, "final_url": page["final_url"], "http_status": page["status"],
            "raw_sha256": sha256(raw), "raw_bytes": len(raw)}
    return capture_text(case_id, incident_id, text[:200_000], user, "WEB_PAGE", url, meta, method="SAFE_FETCH")


def read(evidence_id: str) -> tuple[dict, bytes]:
    ev = repo.get_private(evidence_id)
    if ev is None:
        raise KeyError(evidence_id)
    if ev["storage_path"]:
        data = storage.load(ev["storage_path"])
    else:
        data = crypto.decrypt_text(ev["content_enc"]).encode() if ev["content_enc"] else b""
    return ev, data


def verify(evidence_id: str) -> dict:
    try:
        ev, data = read(evidence_id)
        current = sha256(data)
        ok = current == ev["content_hash"]
    except KeyError:
        raise
    except Exception as e:  # decryption failure = content was altered or key changed
        ev = repo.get(evidence_id)
        current, ok = f"unreadable: {type(e).__name__}", False
    out = {"evidence_id": evidence_id, "ok": ok, "original_hash": ev["content_hash"], "current_hash": current}
    audit.record("EVIDENCE_INTEGRITY_VERIFIED" if ok else "EVIDENCE_INTEGRITY_FAILED", target_type="EVIDENCE",
                 target_id=evidence_id, case_id=ev["case_id"], result="SUCCESS" if ok else "FAILED",
                 detail={"original": ev["content_hash"], "current": current})
    return out
