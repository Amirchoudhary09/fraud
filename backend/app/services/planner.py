"""Search planner for broad, source-diverse public-web discovery.

Queries cover the open web rather than assuming every service has a dedicated API.
Search results are still limited to publicly accessible, source-cited information.
"""
from ..schemas.identity import IdentityInput

# Domain groups encourage Google Search grounding to look beyond one professional network.
# They are query hints, not a promise that every platform will return results.
SOURCE_GROUPS = (
    'site:linkedin.com OR site:github.com OR site:gitlab.com OR site:stackoverflow.com',
    'site:instagram.com OR site:facebook.com OR site:x.com OR site:twitter.com OR site:threads.net',
    'site:youtube.com OR site:tiktok.com OR site:reddit.com OR site:pinterest.com OR site:medium.com OR site:quora.com',
    'site:personal website OR site:blog OR site:news OR site:conference OR site:university',
)


def _unique(queries: list[str], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for query in queries:
        query = " ".join(query.split()).strip()
        if query and query not in seen:
            seen.add(query)
            out.append(query)
    return out if limit is None else out[:max(0, limit)]


def plan_queries(identity: IdentityInput, max_queries: int = 4) -> list[str]:
    """Build an initial mix of identity clues and broad source/domain coverage."""
    name = f'"{identity.name}"'
    anchors = [a for a in (identity.company, identity.college, identity.role, identity.location) if a]
    queries: list[str] = []

    if identity.username:
        queries.append(f'"{identity.username}"')
    if anchors:
        queries.append(name + " " + " ".join(f'"{a}"' if " " in a else a for a in anchors[:3]))

    # Keep some searches domain-agnostic: useful sources may be on sites not listed here.
    queries.append(name + " public profile OR portfolio OR biography")
    if identity.username:
        queries.append(f'"{identity.username}" public profile OR portfolio OR website')

    # Mix in different platform groups as the budget permits, instead of repeatedly searching
    # only LinkedIn/GitHub. Google Search grounding may return any additional relevant domains.
    queries.extend(f'{name} ({group})' for group in SOURCE_GROUPS)
    if identity.company:
        queries.append(f'{name} "{identity.company}" public profile')
    if identity.college:
        queries.append(f'{name} "{identity.college}" profile OR portfolio')

    return _unique(queries, max_queries)


def broaden_queries(identity: IdentityInput) -> list[str]:
    """Second-round queries broaden beyond the first round and diversify public sources."""
    name = f'"{identity.name}"'
    queries = [
        name,
        f'{name} public profile OR personal website OR portfolio OR blog',
        *(f'{name} ({group})' for group in SOURCE_GROUPS),
    ]
    if identity.username:
        queries.insert(0, f'"{identity.username}"')
    if identity.company:
        queries.append(f'{name} "{identity.company}"')
    if identity.college:
        queries.append(f'{name} "{identity.college}"')
    if identity.location:
        queries.append(f'{name} "{identity.location}"')
    return _unique(queries)
