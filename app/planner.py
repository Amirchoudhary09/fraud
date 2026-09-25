"""Search planner: turns the input identity into a small set of targeted queries."""
from .models import IdentityInput


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
