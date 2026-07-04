"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field, computed_field, field_validator

from app.services.outreach import extract_variables


def _no_header_newlines(v: str | None) -> str | None:
    """Reject CR/LF in values that end up in email HEADERS (subject, or variables
    substituted into it) — defense-in-depth against SMTP header injection."""
    if v is not None and ("\n" in v or "\r" in v):
        raise ValueError("must not contain line breaks")
    return v


# ---- Templates ----
class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="generic", max_length=50)  # official_company | startup | generic
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20_000)  # any {variable}, e.g. {company} {role}
    attach_resume: bool = True  # attach the configured file to sends of this template

    _subject_single_line = field_validator("subject")(_no_header_newlines)


class TemplateOut(BaseModel):
    id: int
    name: str
    kind: str
    subject: str
    body: str
    attach_resume: bool = True
    is_active: bool
    created_at: datetime

    @computed_field
    @property
    def variables(self) -> list[str]:
        """The {placeholders} this template uses, for the Add-contact form to render."""
        return extract_variables(self.subject, self.body)


# ---- Contacts / outreach ----
class ContactCreate(BaseModel):
    name: str = Field(default="", max_length=200)  # optional — template may say "there"
    company: str = Field(min_length=1, max_length=200)
    email: EmailStr
    template_id: int
    # per-application fills for the template's extra {placeholders} (role, hr_name, …).
    # recruiter_name/company come from name/company and need not be repeated here.
    variables: dict[str, str] = Field(default_factory=dict)
    # override the per-contact cooldown for a deliberate re-contact (does NOT override
    # the suppression list — that's a hard stop).
    force: bool = False

    # name/company/variable values can be substituted into the SUBJECT -> keep them
    # header-safe and bounded (OWASP injection + resource-consumption hygiene).
    _single_line = field_validator("name", "company")(_no_header_newlines)

    @field_validator("variables")
    @classmethod
    def _bounded_vars(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 50:
            raise ValueError("too many template variables (max 50)")
        for key, val in v.items():
            if len(key) > 64 or len(val) > 2000:
                raise ValueError(f"variable '{key[:64]}' is too long")
            _no_header_newlines(val)
        return v


class SendEdit(BaseModel):
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=20_000)
    # letting the user directly fix a draft's send time — approving/unapproving
    # never recomputes it, so this is the only way to correct one queued under
    # settings that have since changed.
    scheduled_at: datetime | None = None

    _subject_single_line = field_validator("subject")(_no_header_newlines)

    @field_validator("scheduled_at")
    @classmethod
    def _must_be_future(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("scheduled_at must include a timezone offset")
        return v


class SendOut(BaseModel):
    id: int
    thread_id: int
    type: str
    subject: str
    body: str
    scheduled_at: datetime | None
    sent_at: datetime | None
    status: str
    error: str | None
    attempts: int = 0                     # retry count (Phase 8 audit)
    gmail_message_id: str | None = None   # delivered Gmail Message-Id


class ThreadOut(BaseModel):
    id: int
    recruiter_id: int
    recruiter_name: str
    company: str
    email: str
    template_id: int
    status: str
    gmail_thread_id: str | None
    ooo_return_date: date | None
    created_at: datetime
    latest_send: SendOut | None = None


# ---- Replies ----
class ReplyOut(BaseModel):
    id: int
    thread_id: int
    snippet: str | None
    received_at: datetime
    label: str | None


class ReplyLabel(BaseModel):
    label: str = Field(pattern="^(positive|negative|out_of_office)$")
    # required only when label == "out_of_office": the recruiter's return date,
    # to which the paused follow-up is rescheduled.
    return_date: date | None = None
