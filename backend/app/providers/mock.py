"""Deterministic offline provider used when no GEMINI_API_KEY is set.

It fabricates clearly-labelled demo data (example.com sources) derived from the input,
so the whole pipeline and UI can be exercised without network access.
"""
from ..services.embeddings import hash_embed
from ..services.similarity import MATCH_AT, similarity
from ..schemas.identity import Candidate, Claim, IdentityInput, Profile, SourceRef, TimelineEvent
from .base import Judgement, SearchResult, SearchSnippet


def _src(slug: str, title: str) -> SourceRef:
    return SourceRef(url=f"https://example.com/mock/{slug}", title=f"[MOCK] {title}")


class MockProvider:
    name = "mock"
    embed_range = (0.1, 0.6)

    def expand_queries(self, identity: IdentityInput, tried: list[str]) -> list[str]:
        return []

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [hash_embed(t) for t in texts]

    def judge(self, identity: IdentityInput, cand: Candidate) -> Judgement:
        # Stand-in for the LLM: compares the anchors the user supplied with the claims.
        hits, misses = [], []
        for field in ("company", "college"):
            target = getattr(identity, field)
            claims = [c for c in cand.claims if c.field == field]
            if not target or not claims:
                continue
            ok = any(similarity(field, target, c.value) >= MATCH_AT for c in claims)
            (hits if ok else misses).append(field)
        if hits and not misses:
            return Judgement("supports", f"[MOCK] Cited {', '.join(hits)} fit the target profile.")
        if misses and not hits:
            return Judgement("contradicts", f"[MOCK] Cited {', '.join(misses)} point to a different person.")
        return Judgement("unclear", "[MOCK] Not enough distinguishing evidence either way.")

    def classify_comment(self, text: str):
        return None  # rule-based indicators only

    def answer(self, question: str, chunks: list[dict]) -> str:
        if not chunks:
            return "[MOCK] No stored evidence is relevant to this question."
        lines = [f"[{i}] {c['text']}" for i, c in enumerate(chunks, 1)]
        return "[MOCK] Most relevant stored evidence:\n" + "\n".join(lines)

    def search(self, query: str) -> SearchResult:
        src = _src("search", "Mock search result")
        snippet = SearchSnippet(text=f"Mock result for {query}", sources=[src])
        return SearchResult(query=query, summary=f"[MOCK] Results for {query}", snippets=[snippet], sources=[src])

    def extract_candidates(self, identity: IdentityInput, results: list[SearchResult],
                           with_profiles: bool = False) -> list[Candidate]:
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
        if with_profiles:
            strong.profiles, same_name.profiles, weak.profiles = _demo_profiles(n, first, company, college, role, loc)
        return [strong, same_name, weak]

    # --- footprint expansion (offline fixtures) -------------------------------------------------

    def fetch_public_page(self, url: str) -> dict | None:
        """Only the demo portfolio exists offline; it links to one more account (found by expansion)."""
        if url.rstrip("/") == DEMO_SITE:
            html = (f'<title>[MOCK] Portfolio</title><a href="{DEMO_LINKEDIN}">LinkedIn</a>'
                    f'<a href="https://github.com/iedemo">GitHub</a><a href="https://www.youtube.com/@iedemo">YouTube</a>')
            return {"final_url": url, "status": 200, "content_type": "text/html", "body": html.encode()}
        return None

    def archive_first_capture(self, url: str) -> str | None:
        return "20210315" if url.rstrip("/") == DEMO_SITE else None


DEMO_SITE = "https://portfolio.example.com/iedemo"
DEMO_LINKEDIN = "https://www.linkedin.com/in/iedemo-target"


def _demo_profiles(n, first, company, college, role, loc):
    """[MOCK] public accounts: clearly fake 'iedemo' handles, example.com sites."""
    li = SourceRef(url=DEMO_LINKEDIN, title="[MOCK] linkedin.com")
    gh = SourceRef(url="https://github.com/iedemo", title="[MOCK] github.com")
    site = SourceRef(url=DEMO_SITE, title="[MOCK] portfolio.example.com")
    rd = SourceRef(url="https://www.reddit.com/user/iedemo", title="[MOCK] reddit.com")
    target = [
        Profile(platform="linkedin", username="iedemo-target", display_name=n, profile_url=li.url,
                account_type="personal", public_bio=f"{role} at {company}", public_company=company,
                public_role=role, public_education=college, public_location=loc, source=li,
                public_links=[DEMO_SITE],
                events=[TimelineEvent(date="2023-01", platform="linkedin", event=f"Public role listed: {role} at {company}",
                                      source=li)]),
        Profile(platform="github", username="iedemo", display_name=n, profile_url=gh.url, account_type="personal",
                public_bio=f"Building things at {company}", public_company=company, public_location=loc,
                public_links=[DEMO_SITE], publicly_documented_creation_date="2019-06", source=gh,
                events=[TimelineEvent(date="2022-04", platform="github", event="Public repository created: demo-app",
                                      source=gh)]),
        Profile(platform="website", display_name=n, profile_url=DEMO_SITE, public_bio=f"Portfolio of {n}",
                public_role=role, public_links=[DEMO_LINKEDIN, "https://github.com/iedemo"], source=site),
        Profile(platform="reddit", username="iedemo", profile_url=rd.url, source=rd),  # username only
    ]
    ig = SourceRef(url="https://www.instagram.com/iedemo", title="[MOCK] instagram.com")
    other_person = [Profile(platform="instagram", username="iedemo", display_name=n, profile_url=ig.url,
                            public_company="Globex Industries", public_role="Sales Manager",
                            public_location="Mumbai", source=ig)]
    tt = SourceRef(url="https://www.tiktok.com/@iedemo", title="[MOCK] tiktok.com")
    third = [Profile(platform="tiktok", username="iedemo", display_name=f"{first} Khan", profile_url=tt.url,
                     public_location="Lahore", source=tt)]
    return target, other_person, third
