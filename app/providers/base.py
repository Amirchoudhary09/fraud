from dataclasses import dataclass, field
from typing import Protocol

from ..models import Candidate, IdentityInput, SourceRef


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


class Provider(Protocol):
    name: str

    def search(self, query: str) -> SearchResult: ...

    def extract_candidates(self, identity: IdentityInput, results: list[SearchResult]) -> list[Candidate]: ...
