"""Deterministic offline provider used when no GEMINI_API_KEY is set.

It fabricates clearly-labelled demo data (example.com sources) derived from the input,
so the whole pipeline and UI can be exercised without network access.
"""
from ..models import Candidate, Claim, IdentityInput, SourceRef
from .base import SearchResult, SearchSnippet


def _src(slug: str, title: str) -> SourceRef:
    return SourceRef(url=f"https://example.com/mock/{slug}", title=f"[MOCK] {title}")


class MockProvider:
    name = "mock"

    def search(self, query: str) -> SearchResult:
        src = _src("search", "Mock search result")
        snippet = SearchSnippet(text=f"Mock result for {query}", sources=[src])
        return SearchResult(query=query, summary=f"[MOCK] Results for {query}", snippets=[snippet], sources=[src])

    def extract_candidates(self, identity: IdentityInput, results: list[SearchResult]) -> list[Candidate]:
        n = identity.name
        first = n.split()[0]
        company = identity.company or "Acme Corp"
        college = identity.college or "State University"
        role = identity.role or "Software Engineer"
        loc = identity.location or "Delhi"

        prof, code, blog = _src("profile-a", "Professional profile"), _src("code-a", "Code hosting profile"), _src("blog-a", "Personal portfolio")
        strong = Candidate(candidate_id="C001", display_name=n, platform="professional_profile",
                           profile_url=prof.url, claims=[
            Claim(field="name", value=n, evidence=f"{n} – {role} at {company}", source=prof),
            Claim(field="company", value=company, evidence=f"{role} at {company}", source=prof),
            Claim(field="college", value=college, evidence=f"B.Tech, {college}", source=prof),
            Claim(field="role", value=role.replace("Developer", "Engineer"), evidence=f"{role} at {company}", source=prof),
            Claim(field="location", value=loc, evidence=f"Based in {loc}", source=prof),
            Claim(field="name", value=n, evidence=f"Portfolio of {n}", source=blog),
            Claim(field="location", value="Bangalore", evidence="Currently in Bangalore", source=blog),
            Claim(field="other", value="Links to portfolio site", evidence="Website: portfolio", source=code),
        ])

        other = _src("profile-b", "Professional profile")
        same_name = Candidate(candidate_id="C002", display_name=n, platform="professional_profile",
                              profile_url=other.url, claims=[
            Claim(field="name", value=n, evidence=f"{n} – Sales Manager", source=other),
            Claim(field="company", value="Globex Industries", evidence="Sales Manager at Globex Industries", source=other),
            Claim(field="role", value="Sales Manager", evidence="Sales Manager", source=other),
            Claim(field="location", value="Mumbai", evidence="Mumbai, India", source=other),
        ])

        third = _src("news-c", "News article")
        weak = Candidate(candidate_id="C003", display_name=f"{first} Khan", platform="news",
                         profile_url=third.url, claims=[
            Claim(field="name", value=f"{first} Khan", evidence=f"{first} Khan, spokesperson", source=third),
            Claim(field="role", value="Spokesperson", evidence="spokesperson", source=third),
        ])
        return [strong, same_name, weak]
