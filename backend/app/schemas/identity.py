from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Purpose = Literal["self_check", "harassment_report", "professional_verification", "research"]


class IdentityInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    company: Optional[str] = Field(default=None, max_length=100)
    college: Optional[str] = Field(default=None, max_length=100)
    role: Optional[str] = Field(default=None, max_length=100)
    location: Optional[str] = Field(default=None, max_length=100)
    username: Optional[str] = Field(default=None, max_length=60)

    @field_validator("*", mode="before")
    @classmethod
    def strip_blank(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v


class InvestigationRequest(BaseModel):
    identity: IdentityInput
    purpose: Purpose
    case_id: Optional[str] = Field(default=None, max_length=40)
    # "footprint" maps every public profile of the person; allowed only for self-checks, consented
    # verification, or harassment cases (see services/intake.py).
    mode: Literal["standard", "footprint"] = "standard"
    self_attestation: bool = False          # "this search is about me" (self_check footprint)
    consent_reference: Optional[str] = Field(default=None, max_length=200)  # professional_verification footprint
    # User must confirm the lawful-use statement shown in the UI.
    acknowledged: bool

    @field_validator("acknowledged")
    @classmethod
    def must_ack(cls, v):
        if not v:
            raise ValueError("You must accept the responsible-use statement.")
        return v


class SourceRef(BaseModel):
    url: str
    title: str = ""


class Claim(BaseModel):
    field: Literal["name", "company", "college", "role", "location", "username", "other"]
    value: str
    evidence: str = ""
    source: Optional[SourceRef] = None


class TimelineEvent(BaseModel):
    date: str = Field(max_length=20)            # YYYY, YYYY-MM or YYYY-MM-DD, as published
    platform: str = Field(max_length=40)
    event: str = Field(max_length=300)
    source: Optional[SourceRef] = None
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"


class Profile(BaseModel):
    """One public account/page. Only fields that a cited public source states are filled."""
    platform: str = Field(max_length=40)
    username: Optional[str] = Field(default=None, max_length=100)
    display_name: Optional[str] = Field(default=None, max_length=200)
    profile_url: Optional[str] = Field(default=None, max_length=500)
    account_type: Literal["personal", "organisation", "unknown"] = "unknown"
    verification_status: Literal["platform_verified", "unverified"] = "unverified"
    public_bio: Optional[str] = Field(default=None, max_length=600)
    public_links: list[str] = []
    public_company: Optional[str] = Field(default=None, max_length=200)
    public_role: Optional[str] = Field(default=None, max_length=200)
    public_education: Optional[str] = Field(default=None, max_length=200)
    public_location: Optional[str] = Field(default=None, max_length=200)
    public_follower_count: Optional[str] = Field(default=None, max_length=40)
    publicly_documented_creation_date: Optional[str] = Field(default=None, max_length=20)
    source: Optional[SourceRef] = None
    events: list[TimelineEvent] = []
    discovered_via: Literal["search", "cross_link", "website"] = "search"
    linked_from: Optional[str] = Field(default=None, max_length=500)


class Candidate(BaseModel):
    candidate_id: str
    display_name: str
    platform: str = "web"
    profile_url: Optional[str] = None
    claims: list[Claim] = []
    profiles: list[Profile] = []


class Signal(BaseModel):
    field: str
    status: Literal["match", "partial", "mismatch", "unknown", "corroboration"]
    points: int
    detail: str
    sources: list[SourceRef] = []


class Contradiction(BaseModel):
    field: str
    values: list[str]
    detail: str
    sources: list[SourceRef] = []


class ScoredCandidate(Candidate):
    score: int
    band: Literal["strong", "possible", "weak"]
    signals: list[Signal]
    contradictions: list[Contradiction]
    # Only set once a calibration model has been fitted on enough reviewed labels.
    calibrated: Optional[float] = None


class FeedbackRequest(BaseModel):
    verdict: Literal["correct", "wrong", "insufficient"]
    note: Optional[str] = Field(default=None, max_length=500)


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)
