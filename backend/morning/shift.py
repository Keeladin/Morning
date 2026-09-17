from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import ShiftIdentity, ShiftPolicy


class ShiftError(ValueError):
    pass


def require_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(name).strip())
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ShiftError(f"unknown timezone: {name}") from exc


def _parse_hhmm(value: str, *, field: str) -> time:
    try:
        hour, minute = str(value).strip().split(":")
        return time(int(hour), int(minute))
    except (ValueError, TypeError) as exc:
        raise ShiftError(f"{field} must be an HH:MM time") from exc


def _boundaries(policy: ShiftPolicy) -> tuple[time, time, time]:
    morning = _parse_hhmm(policy.morning_shift_start, field="morning_shift_start")
    afternoon = _parse_hhmm(policy.afternoon_shift_start, field="afternoon_shift_start")
    night = _parse_hhmm(policy.night_shift_start, field="night_shift_start")
    if len({morning, afternoon, night}) != 3:
        raise ShiftError("morning, afternoon and night shift starts must all differ")
    if not (morning < afternoon < night):
        raise ShiftError("shift starts must be ordered morning < afternoon < night")
    return morning, afternoon, night


def shift_window(policy: ShiftPolicy, identity: ShiftIdentity) -> tuple[datetime, datetime]:
    """Return the [start, end) boundaries for one three-shift reporting slot."""
    zone = require_zone(policy.timezone)
    morning, afternoon, night = _boundaries(policy)
    reporting_date = date.fromisoformat(identity.shift_date)
    if identity.shift_kind == "morning":
        start_date, start_time, end_date, end_time = reporting_date, morning, reporting_date, afternoon
    elif identity.shift_kind == "afternoon":
        start_date, start_time, end_date, end_time = reporting_date, afternoon, reporting_date, night
    elif identity.shift_kind == "night":
        # Night belongs to the calendar day on which it finishes.
        start_date, start_time = reporting_date - timedelta(days=1), night
        end_date, end_time = reporting_date, morning
    else:
        raise ShiftError(f"unsupported shift kind: {identity.shift_kind}")
    return (
        datetime.combine(start_date, start_time, tzinfo=zone),
        datetime.combine(end_date, end_time, tzinfo=zone),
    )


def resolve_shift(policy: ShiftPolicy, *, at: datetime) -> ShiftIdentity:
    """Resolve an instant to Morning, Afternoon or Night shift automatically."""
    zone = require_zone(policy.timezone)
    morning, afternoon, night = _boundaries(policy)
    local = at.astimezone(zone) if at.tzinfo is not None else at.replace(tzinfo=zone)
    clock = local.timetz().replace(tzinfo=None)
    if morning <= clock < afternoon:
        kind, reporting_date = "morning", local.date()
    elif afternoon <= clock < night:
        kind, reporting_date = "afternoon", local.date()
    elif clock >= night:
        kind, reporting_date = "night", local.date() + timedelta(days=1)
    else:
        kind, reporting_date = "night", local.date()
    return ShiftIdentity(shift_date=reporting_date.isoformat(), shift_kind=kind)


def normalize_shift_override(current: ShiftIdentity, requested: ShiftIdentity) -> ShiftIdentity:
    """Map a day-shift override during Night back to the calendar day it actually belongs to.

    Night reports use the date on which the shift finishes. After 22:00 that means the
    current Night identity is already tomorrow, while a supervisor finishing Morning or
    Afternoon work is still reporting the calendar day that just ended.
    """
    if (
        current.shift_kind == "night"
        and requested.shift_kind in {"morning", "afternoon"}
        and requested.shift_date == current.shift_date
    ):
        prior_date = date.fromisoformat(requested.shift_date) - timedelta(days=1)
        return ShiftIdentity(shift_date=prior_date.isoformat(), shift_kind=requested.shift_kind)
    return requested


def anchor_time_to_shift(policy: ShiftPolicy, identity: ShiftIdentity, hhmm: str) -> datetime:
    """Anchor a bare HH:MM value to its calendar date inside the selected shift."""
    zone = require_zone(policy.timezone)
    clock = _parse_hhmm(hhmm, field="time")
    start, _end = shift_window(policy, identity)
    candidate = datetime.combine(start.date(), clock, tzinfo=zone)
    if candidate < start:
        candidate += timedelta(days=1)
    return candidate


def reporting_window(policy: ShiftPolicy, reporting_date: str) -> tuple[datetime, datetime]:
    """Return the 24h reporting day: prior Night start through current Night start."""
    zone = require_zone(policy.timezone)
    _morning, _afternoon, night = _boundaries(policy)
    report_date = date.fromisoformat(reporting_date)
    start = datetime.combine(report_date - timedelta(days=1), night, tzinfo=zone)
    end = datetime.combine(report_date, night, tzinfo=zone)
    return start, end
