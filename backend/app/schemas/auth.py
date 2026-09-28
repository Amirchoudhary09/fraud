from typing import Literal, Optional

from pydantic import BaseModel, Field

Role = Literal["super_admin", "security_admin", "investigator", "analyst", "auditor", "user"]


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=10, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class NewUser(Credentials):
    role: Role = "analyst"


class UserUpdate(BaseModel):
    role: Optional[Role] = None
    status: Optional[Literal["active", "disabled"]] = None


class MfaLogin(BaseModel):
    mfa_token: str = Field(max_length=2000)
    code: str = Field(min_length=6, max_length=8)


class MfaCode(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class OidcCallback(BaseModel):
    code: str = Field(min_length=1, max_length=4000)
    state: str = Field(min_length=10, max_length=200)
