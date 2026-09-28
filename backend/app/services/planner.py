"""Search planner: turns the input identity into a small set of targeted queries."""
from ..schemas.identity import IdentityInput


def plan_queries(identity: IdentityInput, max_queries: int = 4) -> list[str]:
    name = f'"{identity.name}"'
    queries: list[str] = []

    anchors = [a for a in (identity.company, identity.college, identity.role) if a]
    if anchors:
        queries.append(f"{name} " + " ".join(f'"{a}"' if " " in a else a for a in anchors))
    for anchor in anchors:
        queries.append(f'{name} "{anchor}"')
    if identity.username:
        queries.append(f'"{identity.username}" {identity.name}')
    queries.append(f"{name} professional profile" + (f" {identity.location}" if identity.location else ""))

    # de-duplicate, keep order
    seen, out = set(), []
    for q in queries:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out[:max_queries]


def broaden_queries(identity: IdentityInput) -> list[str]:
    """Second-round queries when the first round found no candidates: fewer anchors, public profile sites."""
    name = f'"{identity.name}"'
    out = [name, f"{name} linkedin", f"{name} github"]
    if identity.username:
        out.insert(0, f'"{identity.username}"')
    if identity.location:
        out.append(f"{name} {identity.location}")
    return out
