"""Search planner for broad, source-diverse public-web discovery."""
from ..schemas.identity import IdentityInput

# Domain groups are query hints, not dedicated integrations or coverage guarantees.
SOURCE_GROUPS = (
    'site:linkedin.com OR site:github.com OR site:gitlab.com OR site:stackoverflow.com',
    'site:instagram.com OR site:facebook.com OR site:x.com OR site:twitter.com OR site:threads.net',
    'site:youtube.com OR site:tiktok.com OR site:reddit.com OR site:pinterest.com OR site:medium.com OR site:quora.com',
    'portfolio OR "personal website" OR blog OR news OR conference OR university',
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
    """Mix identity clues with diverse public-web sources within the query budget."""
    name = f'"{identity.name}"'
    anchors = [a for a in (identity.company, identity.college, identity.role, identity.location) if a]
    queries: list[str] = []

    clue_parts = [f'"{identity.username}"' if identity.username else "", name]
    clue_parts.extend(f'"{a}"' if " " in a else a for a in anchors[:2])
    queries.append(" ".join(part for part in clue_parts if part))
    queries.append(f'{name} public profile OR portfolio OR biography')

    # Reserve early query slots for different kinds of sites; don't spend the full budget
    # repeatedly querying the same professional networks.
    queries.append(f'{name} ({SOURCE_GROUPS[0]})')
    queries.append(f'{name} ({SOURCE_GROUPS[1]})')
    queries.extend(f'{name} ({group})' for group in SOURCE_GROUPS[2:])
    if identity.username:
        queries.append(f'"{identity.username}" public profile OR portfolio OR website')
    if identity.company:
        queries.append(f'{name} "{identity.company}" public profile')
    if identity.college:
        queries.append(f'{name} "{identity.college}" profile OR portfolio')
    return _unique(queries, max_queries)


def broaden_queries(identity: IdentityInput) -> list[str]:
    """Second-round queries broaden the first round and include more public source types."""
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
