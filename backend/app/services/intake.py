"""Single entry point for starting a search (from the search form or from an incident).

Creates, in order: the ENTITY being searched, the SEARCH record (search history), the
USER ─SEARCHED→ ENTITY relationship, and a SEARCH_STARTED audit event, then queues the job.
"""
from fastapi import HTTPException

from ..agents.supervisor import run_investigation
from ..core import config, context, ratelimit
from ..core.privacy import find_blocked_terms
from ..repositories import entities, searches
from ..schemas.identity import IdentityInput
from ..workers import jobs
from . import audit


def start_search(identity: IdentityInput, purpose: str, user: dict, case_id: str | None = None,
                 incident_id: str | None = None, search_type: str = "PUBLIC_IDENTITY") -> str:
    text = " ".join(v for v in identity.model_dump().values() if v)
    blocked = find_blocked_terms(text)
    if blocked:
        audit.record("SEARCH_BLOCKED", result="DENIED", case_id=case_id, detail={"blocked_terms": blocked})
        raise HTTPException(400, "This tool only works with public professional information. "
                                 f"Requests for sensitive data are not allowed ({', '.join(blocked)}).")
    ratelimit.check(f"search:{user['id']}", config.RATE_LIMIT_PER_HOUR)

    etype, label = ("HANDLE", identity.username) if search_type == "INCIDENT_AUTHOR" and identity.username \
        else ("PERSON", identity.name)
    entity_id = entities.get_or_create(etype, label)
    provider = "mock" if config.MOCK_MODE else "gemini"
    sid = searches.create(identity.model_dump(exclude_none=True), purpose, provider, user["id"], search_type,
                          case_id=case_id, incident_id=incident_id, entity_id=entity_id)
    entities.relate("USER", user["id"], "SEARCHED", "ENTITY", entity_id, search_id=sid, case_id=case_id,
                    incident_id=incident_id)
    audit.record("SEARCH_STARTED", target_type="ENTITY", target_id=entity_id, search_id=sid, case_id=case_id,
                 detail={"search_type": search_type, "purpose": purpose, "provider": provider})

    jobs.submit(run_investigation, sid, identity, user["id"], context.request_id.get(), context.ip_hash.get())
    return sid
