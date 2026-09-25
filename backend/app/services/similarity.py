"""Field-aware text similarity: fuzzy names, company suffixes, college acronyms, role synonyms."""
import re
from difflib import SequenceMatcher

MATCH_AT, PARTIAL_AT = 0.85, 0.6

_FILLER = {"pvt", "ltd", "private", "limited", "inc", "llc", "llp", "co", "corp", "the"}
_ACRONYM_SKIP = {"of", "and", "the", "for", "&"}
_ROLE_SYNONYMS = {
    "engineer": "dev", "developer": "dev", "programmer": "dev", "sde": "software dev",
    "swe": "software dev", "sr": "senior", "jr": "junior", "mgr": "manager",
}



def _tokens(s: str) -> list[str]:
    return [t for t in re.sub(r"[^a-z0-9]+", " ", s.lower()).split() if t]


def _acronym(tokens: list[str]) -> str:
    return "".join(t[0] for t in tokens if t not in _ACRONYM_SKIP)


def text_similarity(a: str, b: str) -> float:
    ta = [t for t in _tokens(a) if t not in _FILLER]
    tb = [t for t in _tokens(b) if t not in _FILLER]
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    # "GLBITM" vs "G L Bajaj Institute of Technology and Management"
    for short, long_ in ((ta, tb), (tb, ta)):
        if len(short) == 1 and len(long_) > 2 and short[0] == _acronym(long_):
            return 0.9
    sa, sb = set(ta), set(tb)
    if sa <= sb or sb <= sa:
        return 0.9
    jaccard = len(sa & sb) / len(sa | sb)
    ratio = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    return max(jaccard, ratio)


def name_similarity(target: str, other: str) -> float:
    """Fraction of the target's name tokens found (fuzzily) in the other name."""
    ta, tb = _tokens(target), _tokens(other)
    if not ta or not tb:
        return 0.0
    hits = sum(1 for t in ta if any(SequenceMatcher(None, t, u).ratio() >= 0.8 for u in tb))
    return hits / len(ta)


def role_similarity(a: str, b: str) -> float:
    def canon(s):
        return " ".join(_ROLE_SYNONYMS.get(t, t) for t in _tokens(s))
    return text_similarity(canon(a), canon(b))


def similarity(field: str, a: str, b: str) -> float:
    if field == "name":
        return name_similarity(a, b)
    if field == "role":
        return role_similarity(a, b)
    if field == "username":
        return 1.0 if a.lower().lstrip("@") == b.lower().lstrip("@") else text_similarity(a, b) * 0.8
    return text_similarity(a, b)
