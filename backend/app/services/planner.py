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


def footprint_queries(identity: IdentityInput, max_queries: int) -> list[tuple[str, list[str]]]:
    """Queries for the public-footprint mode: (query, platform keys it covers).

    Platforms are bundled into `site:` groups so the whole registry fits a small query budget;
    a public username (if given) gets its own query. The standard anchored queries still run first.
    """
    from . import platforms
    name = f'"{identity.name}"'
    out: list[tuple[str, list[str]]] = []
    if identity.username:
        out.append((f'"{identity.username}" {name}', []))
    groups = platforms.site_groups(max(1, max_queries - len(out)))
    anchor = next((a for a in (identity.company, identity.college, identity.role) if a), None)
    for keys, sites in groups:
        out.append((f"{name} {sites}" + (f' "{anchor}"' if anchor and len(groups) <= 2 else ""), keys))
    return out[:max_queries]
