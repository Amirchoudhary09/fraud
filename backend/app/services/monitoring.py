"""Security monitoring: rule-based detectors run on each audit event and raise security_events.

Thresholds come from config. A single search is never treated as malicious; alerts fire on
volume/pattern thresholds and go to a human (security_admin) for review.
"""
import logging

from ..core import audit_store, config
from ..core.database import ago
from ..repositories import security_events

log = logging.getLogger(__name__)

ALWAYS_ALERT = {
    "BREAK_GLASS_REQUESTED": ("high", "Break-glass access requested"),
    "BREAK_GLASS_APPROVED": ("high", "Break-glass access approved"),
    "ADMIN_CASE_ACCESS": ("medium", "Administrator opened a case they are not a member of"),
    "REFRESH_TOKEN_REUSE": ("high", "A rotated refresh token was reused; session revoked"),
    "AUDIT_CHAIN_BROKEN": ("critical", "Audit log integrity check failed"),
    "EVIDENCE_INTEGRITY_FAILED": ("critical", "Evidence integrity check failed"),
}


def _threshold(event: dict, types: list[str], limit: int, minutes: int, alert: str, severity: str, what: str,
               by_ip: bool = False, distinct: str | None = None):
    actor, iph = event.get("actor_user_id"), event.get("ip_hash")
    if by_ip and not iph:
        return
    if not by_ip and actor is None:
        return
    n = audit_store.count(event_types=types, since=ago(minutes=minutes),
                          actor_user_id=None if by_ip else actor, ip_hash=iph if by_ip else None, distinct=distinct)
    if n >= limit:
        key = f"{alert}:{iph if by_ip else actor}"
        security_events.raise_event(alert, severity, f"{n} {what} in {minutes} min (threshold {limit}).",
                                    user_id=None if by_ip else actor, dedupe_key=key, dedupe_minutes=minutes)


def check(event: dict):
    try:
        t = event["event_type"]
        if t in ALWAYS_ALERT:
            sev, text = ALWAYS_ALERT[t]
            security_events.raise_event(t, sev, f"{text}. {event.get('detail') or ''}".strip(),
                                        user_id=event.get("actor_user_id"))
        elif t == "AUTH_LOGIN_FAILED":
            _threshold(event, [t], config.ALERT_FAILED_LOGINS_PER_15MIN, 15, "REPEATED_FAILED_LOGINS", "high",
                       "failed logins from one client", by_ip=True)
        elif t == "SEARCH_STARTED":
            _threshold(event, [t], config.ALERT_SEARCHES_PER_5MIN, 5, "SEARCH_BURST", "medium", "searches by one user")
            _threshold(event, [t], config.ALERT_DISTINCT_TARGETS_PER_HOUR, 60, "MANY_UNRELATED_TARGETS", "medium",
                       "different people searched by one user", distinct="target_id")
        elif t in ("REPORT_EXPORTED", "EVIDENCE_DOWNLOADED"):
            _threshold(event, ["REPORT_EXPORTED", "EVIDENCE_DOWNLOADED"], config.ALERT_EXPORTS_PER_HOUR, 60,
                       "MASS_EXPORT", "high", "exports/downloads by one user")
        elif t == "AUTHZ_DENIED":
            _threshold(event, [t], config.ALERT_AUTHZ_DENIED_PER_15MIN, 15, "REPEATED_AUTHZ_DENIED", "medium",
                       "denied requests by one user")
        elif t == "USER_ROLE_CHANGED" and '"super_admin"' in (event.get("detail") or ""):
            security_events.raise_event("PRIVILEGE_ESCALATION", "high", f"User granted super_admin. {event['detail']}",
                                        user_id=event.get("actor_user_id"))
    except Exception:  # monitoring must never break the request that produced the event
        log.exception("security monitoring failed for %s", event.get("event_type"))
