"""Single entry point for starting a search (from the search form or from an incident).

Creates, in order: the ENTITY being searched, the SEARCH record (search history), the
USER ─SEARCHED→ ENTITY relationship, and a SEARCH_STARTED audit event, then queues the job.
"""
from fastapi import HTTPException

from ..core import config, context, permissions, ratelimit
from ..core.privacy import find_blocked_terms
from ..repositories import entities, searches
from ..schemas.identity import IdentityInput
from ..workers import jobs
from . import audit


def check_footprint_policy(purpose: str, user: dict, incident_id: str | None, self_attestation: bool,
                           consent_reference: str | None, case_id: str | None):
    """Mapping every public account of a person is only allowed for: the searcher's own footprint,
    consented professional verification, or the author of a reported incident in a case."""
    reason = None
    if purpose == "self_check":
        if not self_attestation:
            reason = "Footprint self-checks require confirming that you are the person searched."
    elif purpose == "professional_verification":
        if not permissions.has(user["role"], "search.footprint"):
            reason = "Your role cannot run footprint searches on other people."
        elif not consent_reference or len(consent_reference.strip()) < 5:
            reason = "Professional verification footprints require a consent reference."
    elif purpose == "harassment_report":
        if not incident_id:
            reason = "Harassment footprints must start from a reported incident in a case."
    else:
        reason = f"The '{purpose}' purpose does not allow mapping all of a person's public accounts."
    if reason:
        audit.record("FOOTPRINT_DENIED", result="DENIED", case_id=case_id, detail={"purpose": purpose, "reason": reason})
        raise HTTPException(403, reason)
    ratelimit.check(f"footprint:{user['id']}", config.FOOTPRINT_RATE_PER_DAY, window=86400)


def start_search(identity: IdentityInput, purpose: str, user: dict, case_id: str | None = None,
                 incident_id: str | None = None, search_type: str = "PUBLIC_IDENTITY", mode: str = "standard",
                 self_attestation: bool = False, consent_reference: str | None = None) -> str:
    text = " ".join(v for v in identity.model_dump().values() if v)
    blocked = find_blocked_terms(text)
    if blocked:
        audit.record("SEARCH_BLOCKED", result="DENIED", case_id=case_id, detail={"blocked_terms": blocked})
        raise HTTPException(400, "This tool only works with public professional information. "
                                 f"Requests for sensitive data are not allowed ({', '.join(blocked)}).")
    if mode == "footprint":
        check_footprint_policy(purpose, user, incident_id, self_attestation, consent_reference, case_id)
        search_type += "_FOOTPRINT"
    ratelimit.check(f"search:{user['id']}", config.RATE_LIMIT_PER_HOUR)

    etype, label = ("HANDLE", identity.username) if search_type.startswith("INCIDENT_AUTHOR") and identity.username \
        else ("PERSON", identity.name)
    entity_id = entities.get_or_create(etype, label)
    provider = "mock" if config.MOCK_MODE else "gemini"
    sid = searches.create(identity.model_dump(exclude_none=True), purpose, provider, user["id"], search_type,
                          case_id=case_id, incident_id=incident_id, entity_id=entity_id)
    entities.relate("USER", user["id"], "SEARCHED", "ENTITY", entity_id, search_id=sid, case_id=case_id,
                    incident_id=incident_id)
    audit.record("SEARCH_STARTED", target_type="ENTITY", target_id=entity_id, search_id=sid, case_id=case_id,
                 detail={"search_type": search_type, "purpose": purpose, "provider": provider, "mode": mode,
                         "self_attestation": self_attestation if mode == "footprint" else None,
                         "consent_reference": consent_reference if mode == "footprint" else None})

    jobs.submit("run_search", sid, identity.model_dump(), user["id"], context.request_id.get(), context.ip_hash.get(), mode)
    return sid
