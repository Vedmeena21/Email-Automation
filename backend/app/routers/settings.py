"""User-configurable app settings: timezone, send windows, working days, holidays.

Lets each deployment localize the app instead of being hardcoded to one region.
"""
from pathlib import Path

import pytz
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.services import app_settings, audit

router = APIRouter(prefix="/settings", tags=["settings"])

_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class SettingsIn(BaseModel):
    timezone: str
    window_a_start: str = Field(pattern=_HHMM)
    window_a_end: str = Field(pattern=_HHMM)
    window_b_start: str = Field(pattern=_HHMM)
    window_b_end: str = Field(pattern=_HHMM)
    working_days: list[int] = Field(min_length=1)   # ISO 1=Mon…7=Sun
    followup_after_working_days: int = Field(ge=1, le=30)
    holiday_mode: str = Field(pattern="^(none|country)$")
    holiday_country: str = Field(default="IN", pattern="^[A-Za-z]{2}$")  # ISO 3166 alpha-2
    sender_name: str = Field(default="", max_length=200)
    signature: str = Field(default="", max_length=2000)

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        if v not in pytz.all_timezones_set:
            raise ValueError(f"unknown timezone: {v}")
        return v

    @field_validator("working_days")
    @classmethod
    def _valid_days(cls, v: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in v):
            raise ValueError("working_days must be ISO weekday numbers 1..7")
        return sorted(set(v))

    @field_validator("window_a_end", "window_b_end")
    @classmethod
    def _end_after_start(cls, v, info):
        start_key = info.field_name.replace("_end", "_start")
        start = info.data.get(start_key)
        if start and v <= start:
            raise ValueError(f"{info.field_name} must be after {start_key}")
        return v


def _resume_info() -> dict:
    """Whether a resume attachment is configured and present, for the profile widget."""
    path = Path(get_settings().resume_path)
    return {"resume_filename": path.name if path.exists() else None}


@router.get("")
def get_settings_row(db: Session = Depends(get_db)):
    row = db.execute(text("SELECT * FROM app_settings WHERE id=1")).mappings().first()
    if not row:
        raise HTTPException(404, "settings not initialized; run migration 003")
    return {**dict(row), **_resume_info()}


@router.put("")
def update_settings(payload: SettingsIn, db: Session = Depends(get_db)):
    db.execute(
        text(
            """
            UPDATE app_settings SET
              timezone=:timezone,
              window_a_start=:window_a_start, window_a_end=:window_a_end,
              window_b_start=:window_b_start, window_b_end=:window_b_end,
              working_days=:working_days,
              followup_after_working_days=:followup_after_working_days,
              holiday_mode=:holiday_mode, holiday_country=:holiday_country,
              sender_name=:sender_name, signature=:signature,
              updated_at=now()
            WHERE id=1
            """
        ),
        payload.model_dump(),
    )
    # timezone/windows/etc are policy, not secrets — safe to record verbatim
    audit.record(db, "settings.update", entity="app_settings", entity_id=1,
                detail={"timezone": payload.timezone, "holiday_mode": payload.holiday_mode})
    db.commit()
    app_settings.invalidate()  # scheduling picks up the change immediately
    return dict(
        db.execute(text("SELECT * FROM app_settings WHERE id=1")).mappings().first()
    )


@router.get("/timezones")
def list_timezones() -> list[dict]:
    """All IANA timezone names plus their ISO country code, for the Settings-page
    picker (e.g. so it can show "India" next to "Kolkata", Calendar-style)."""
    zone_to_country = {
        zone: cc for cc, zones in pytz.country_timezones.items() for zone in zones
    }
    # pytz.common_timezones is a lazily-built LazyList, not a plain list —
    # FastAPI's response validation silently serializes it as empty, so cast it.
    return [
        {"zone": z, "country_code": zone_to_country.get(z)}
        for z in list(pytz.common_timezones)
    ]


@router.get("/setup")
def setup_status(db: Session = Depends(get_db)) -> dict:
    """Live onboarding state for the Overview checklist — real checks, not flags."""
    env = get_settings()
    gmail_connected = bool(
        env.gmail_client_id and env.gmail_client_secret and env.gmail_refresh_token
    )
    row = db.execute(
        text("SELECT sender_name FROM app_settings WHERE id=1")
    ).first()
    identity_set = bool(row and (row[0] or "").strip())
    first_send_sent = bool(
        db.execute(text("SELECT 1 FROM sends WHERE status='sent' LIMIT 1")).first()
    )
    # No "create a template" step: the seeded starter examples are fully
    # functional (one of them is how the very first email gets sent), so
    # requiring a hand-authored template on top of that is friction, not signal.
    steps = {
        "gmail_connected": gmail_connected,
        "identity_set": identity_set,
        "first_send_sent": first_send_sent,
    }
    return {**steps, "complete": all(steps.values())}
