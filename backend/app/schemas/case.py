from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .identity import Purpose

IncidentType = Literal["HARASSMENT", "THREAT", "ABUSE", "IMPERSONATION", "SCAM_INDICATOR", "SPAM",
                       "HATEFUL_CONTENT", "PRIVACY_CONCERN", "OTHER"]


class CaseCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    purpose: Purpose = "harassment_report"
    acknowledged: bool

    @field_validator("acknowledged")
    @classmethod
    def must_ack(cls, v):
        if not v:
            raise ValueError("You must accept the responsible-use statement.")
        return v


class CaseUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[Literal["open", "under_review", "closed"]] = None


class IncidentCreate(BaseModel):
    incident_type: Optional[IncidentType] = None  # None = use the analyzer's suggestion
    description: Optional[str] = Field(default=None, max_length=5000)
    target_name: Optional[str] = Field(default=None, max_length=100)
    author_handle: Optional[str] = Field(default=None, max_length=60)
    source_platform: Optional[str] = Field(default=None, max_length=60)
    source_url: Optional[str] = Field(default=None, max_length=1000)
    content_id: Optional[str] = Field(default=None, max_length=200)
    comment_text: Optional[str] = Field(default=None, max_length=5000)
    posted_at: Optional[str] = Field(default=None, max_length=60)


class IncidentUpdate(BaseModel):
    incident_type: Optional[IncidentType] = None
    status: Optional[Literal["open", "under_review", "resolved", "dismissed"]] = None
    severity: Optional[Literal["none", "low", "medium", "high"]] = None
    description: Optional[str] = Field(default=None, max_length=5000)


class IncidentInvestigate(BaseModel):
    """Optional public hints about the author, e.g. a display name shown on their public profile."""
    name: Optional[str] = Field(default=None, max_length=100)
    company: Optional[str] = Field(default=None, max_length=100)
    college: Optional[str] = Field(default=None, max_length=100)
    location: Optional[str] = Field(default=None, max_length=100)


class EvidenceText(BaseModel):
    incident_id: Optional[str] = Field(default=None, max_length=40)
    text: str = Field(min_length=1, max_length=20000)
    type: Literal["PUBLIC_COMMENT", "DOCUMENT"] = "PUBLIC_COMMENT"
    source_url: Optional[str] = Field(default=None, max_length=1000)


class EvidenceUrl(BaseModel):
    incident_id: Optional[str] = Field(default=None, max_length=40)
    url: str = Field(min_length=8, max_length=2000)


class MemberGrant(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    access: Literal["editor", "viewer"] = "viewer"
    expires_hours: Optional[int] = Field(default=None, ge=1, le=24 * 365)


class BreakGlassCreate(BaseModel):
    reason: str = Field(min_length=20, max_length=2000)


class BreakGlassDecision(BaseModel):
    approve: bool
    hours: Optional[int] = Field(default=None, ge=1, le=72)
