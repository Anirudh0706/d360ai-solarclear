"""Request bodies with validation rules (FastAPI returns 422 with details when they fail)."""
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,30}$")


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(max_length=120)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("Password must contain letters and digits")
        return v


class LoginIn(BaseModel):
    email: str
    password: str


def _code(v: str) -> str:
    v = v.strip().upper()
    if not CODE_RE.match(v):
        raise ValueError("Code must be 2-31 characters: letters, digits and dashes")
    return v


class FeederIn(BaseModel):
    substation_id: int
    code: str
    name: str = Field(min_length=2, max_length=80)
    voltage_kv: float = Field(default=11, gt=0, le=66)
    rating_kva: float = Field(gt=0, le=50000)

    @field_validator("code")
    @classmethod
    def valid_code(cls, v: str) -> str:
        return _code(v)


class DtrIn(BaseModel):
    feeder_id: int
    code: str
    name: str = Field(min_length=2, max_length=80)
    rating_kva: float = Field(gt=0, le=5000)
    area_type: Literal["urban", "rural", "agri"] = "urban"

    @field_validator("code")
    @classmethod
    def valid_code(cls, v: str) -> str:
        return _code(v)


class DtrUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    rating_kva: float | None = Field(default=None, gt=0, le=5000)
    area_type: Literal["urban", "rural", "agri"] | None = None


class ApplicationIn(BaseModel):
    dtr_id: int
    consumer_id: int | None = None
    applicant_name: str = Field(min_length=2, max_length=80)
    scheme: Literal["rooftop", "kusum"] = "rooftop"
    requested_kw: float = Field(gt=0, le=2000)


class ApplicationUpdate(BaseModel):
    applicant_name: str | None = Field(default=None, min_length=2, max_length=80)
    requested_kw: float | None = Field(default=None, gt=0, le=2000)
    scheme: Literal["rooftop", "kusum"] | None = None


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    approved_kw: float | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=300)


class FeasibilityIn(BaseModel):
    dtr_id: int
    kw: float = Field(gt=0, le=2000)
    scheme: Literal["rooftop", "kusum"] = "rooftop"


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


class ScanIn(BaseModel):
    with_brief: bool = False
