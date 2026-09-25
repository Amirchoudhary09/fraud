"""Comment analyzer: abuse / threat / harassment / spam indicators.

These are content-moderation indicators to help a human reviewer, NOT legal or criminal
findings. Rule matches are always shown with the phrase that triggered them; when an LLM
is available its classification is combined with the rules (either can raise a flag).
"""
import logging
import re
from urllib.parse import urlparse

log = logging.getLogger(__name__)

CATEGORIES = ("abuse", "threat", "harassment", "spam", "hate", "scam", "impersonation")

# Controlled incident types (spec section 9) and the indicator that suggests each one.
INCIDENT_TYPES = ("HARASSMENT", "THREAT", "ABUSE", "IMPERSONATION", "SCAM_INDICATOR", "SPAM",
                  "HATEFUL_CONTENT", "PRIVACY_CONCERN", "OTHER")
SUGGESTED_TYPE = [("threat", "THREAT"), ("harassment", "HARASSMENT"), ("hate", "HATEFUL_CONTENT"),
                  ("scam", "SCAM_INDICATOR"), ("impersonation", "IMPERSONATION"), ("abuse", "ABUSE"),
                  ("spam", "SPAM")]

_RULES: dict[str, list[str]] = {
    "threat": [
        r"\b(i|we)('ll| will| am going to|'m going to|'m gonna| gonna)\s+(kill|hurt|beat|find|shoot|stab|attack)\b",
        r"\bkill (you|u)\b", r"\byou('re| are) dead\b", r"\bwatch your back\b",
        r"\bi know where you (live|work|study)\b", r"\bmaar (dunga|denge|daalunga)\b", r"\bjaan se maar\b",
        r"\bdekh lunga\b", r"\bnahi chhodunga\b",
    ],
    "harassment": [
        r"\bkill yourself\b", r"\bkys\b", r"\bgo die\b", r"\bnobody (likes|loves|wants) you\b",
        r"\b(expose|leak) (you|your)\b", r"\bi('ll| will) (make your life|ruin you)\b", r"\bstalk(ing)? you\b",
        r"\bugly\b", r"\bloser\b",
    ],
    "abuse": [
        r"\b(idiot|stupid|moron|dumb|bastard|bitch|asshole|shit|fuck\w*|f\*+k)\b",
        r"\b(chutiya|madarchod|bhenchod|behenchod|harami|kamina|kutta|kutte|gadha|saala)\b",
    ],
    "scam": [
        r"\b(send|share) (me )?(the |your )?(otp|pin|cvv)\b", r"\bgift ?cards?\b", r"\bdouble your (money|investment)\b",
        r"\b(guaranteed|assured) returns?\b", r"\bpay (a )?(small )?(fee|deposit) to (claim|receive)\b",
        r"\byou (have )?won\b.*\b(prize|lottery|reward)\b",
    ],
    "impersonation": [
        r"\b(this is|i am|i'm) the (real|official)\b", r"\bofficial (support|account|helpdesk)\b.*\b(dm|message|verify)\b",
        r"\bverify your account\b", r"\bmy (old|previous) account (got|was) (hacked|banned)\b",
    ],
    "spam": [
        r"\b(buy now|click here|free money|limited offer|dm (me )?for promo|crypto giveaway|earn \S+ (daily|per day))\b",
        r"\b(whatsapp|telegram) (me|us) (for|to)\b",
    ],
}
_COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in _RULES.items()}
_URL = re.compile(r"https?://\S+")
_HANDLE = re.compile(r"(?<![\w@])@([A-Za-z0-9_.]{2,30})")

# Hosts whose first path segment is a public username.
_PROFILE_HOSTS = {"twitter.com": "x", "x.com": "x", "instagram.com": "instagram", "github.com": "github",
                  "threads.net": "threads", "tiktok.com": "tiktok", "medium.com": "medium"}


def rule_indicators(text: str) -> dict:
    out = {}
    for cat, patterns in _COMPILED.items():
        hits = sorted({m.group(0) for p in patterns for m in p.finditer(text)})
        out[cat] = hits
    if len(_URL.findall(text)) >= 3:
        out["spam"] = out["spam"] + ["3+ links"]
    return out


def severity(flags: dict[str, bool]) -> str:
    if flags.get("threat"):
        return "high"
    if flags.get("harassment") or flags.get("hate") or flags.get("scam") or flags.get("impersonation"):
        return "medium"
    if flags.get("abuse") or flags.get("spam"):
        return "low"
    return "none"


def public_handle(author_username: str | None, source_url: str | None) -> tuple[str | None, str | None]:
    """The commenter's public username and platform, from the form or the comment URL."""
    platform = None
    if source_url:
        u = urlparse(source_url)
        host = u.netloc.lower().removeprefix("www.").removeprefix("m.")
        platform = _PROFILE_HOSTS.get(host) or host or None
        if not author_username and host in _PROFILE_HOSTS:
            seg = [s for s in u.path.split("/") if s]
            if seg and seg[0] not in ("status", "p", "reel", "explore", "search", "i"):
                author_username = seg[0].lstrip("@")
    return (author_username.lstrip("@") if author_username else None), platform


def analyze(text: str, provider=None) -> dict:
    rules = rule_indicators(text)
    llm = None
    if provider is not None:
        try:
            llm = provider.classify_comment(text)
        except Exception as e:  # classification must never block saving the comment
            log.warning("LLM comment classification failed: %s", e)
    flags = {}
    for cat in CATEGORIES:
        flags[cat] = bool(rules.get(cat)) or bool(llm and llm.get(cat) is True)
    return {
        "indicators": {f"{c}_indicator": flags[c] for c in CATEGORIES},
        "severity": severity(flags),
        "rule_matches": {k: v for k, v in rules.items() if v},
        "llm": {"rationale": str(llm.get("rationale", ""))[:400], "severity": llm.get("severity")} if llm else None,
        "mentions": sorted(set(_HANDLE.findall(text))),
        "suggested_incident_type": next((it for cat, it in SUGGESTED_TYPE if flags[cat]), "OTHER"),
        "disclaimer": "Content indicators for human review only; not a legal or criminal finding.",
    }
