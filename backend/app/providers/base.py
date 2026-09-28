from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..schemas.identity import Candidate, IdentityInput, SourceRef


class ProviderError(RuntimeError):
    """The AI provider failed (quota, outage, bad response). `status` is the upstream HTTP status."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class SearchSnippet:
    text: str
    sources: list[SourceRef] = field(default_factory=list)


@dataclass
class SearchResult:
    query: str
    summary: str
    snippets: list[SearchSnippet]
    sources: list[SourceRef]


@dataclass
class Judgement:
    """LLM's contextual read of whether a candidate's cited evidence fits the target."""
    verdict: str  # supports | contradicts | unclear
    rationale: str


class Provider(Protocol):
    name: str
    # Cosine range used to turn embedding similarity into points: <= lo -> 0, >= hi -> full.
    embed_range: tuple[float, float]

    def search(self, query: str) -> SearchResult: ...

    def extract_candidates(self, identity: IdentityInput, results: list[SearchResult],
                           with_profiles: bool = False) -> list[Candidate]: ...

    def fetch_public_page(self, url: str) -> Optional[dict]: ...

    def archive_first_capture(self, url: str) -> Optional[str]: ...

    def expand_queries(self, identity: IdentityInput, tried: list[str]) -> list[str]: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def judge(self, identity: IdentityInput, cand: Candidate) -> Judgement: ...

    def classify_comment(self, text: str) -> Optional[dict]: ...

    def answer(self, question: str, chunks: list[dict]) -> str: ...
