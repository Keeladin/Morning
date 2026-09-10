from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .intervals import TimeInterval, total_interval_seconds
from .models import (
    ControlRoomObservation,
    ExpectedInputStatus,
    Machine,
    MachineStateDeclaration,
    Person,
    ShiftReport,
    StopFixRecord,
)


@dataclass(frozen=True)
class MachineEventSource:
    origin: Literal["shift_report", "control_room"]
    source_id: str
    report_id: str | None
    start: datetime | None
    end: datetime | None
    description: str


@dataclass(frozen=True)
class MachineAggregate:
    machine_internal_id: str | None
    machine_display_id: str
    matched: bool
    total_work_interval_seconds: float
    total_control_room_delay_seconds: float
    work_event_count: int
    control_room_event_count: int
    event_count: int
    key_issues: tuple[str, ...]
    events: tuple[MachineEventSource, ...]


def _unmatched_key(raw_label: str) -> str:
    return f"unmatched:{raw_label.strip().casefold()}"


def aggregate_machines(
    *,
    machines_by_id: dict[str, Machine],
    shift_reports: tuple[ShiftReport, ...],
    observations: tuple[ControlRoomObservation, ...],
) -> tuple[MachineAggregate, ...]:
    """Preserve supervisor and control-room evidence by machine.

    Supervisor ``MachineEvent`` intervals are engineering-work intervals.
    Control-room observations come from the Production Delays source and are
    therefore exposed separately as *control-room delay* duration. Neither is
    silently promoted into canonical machine-state downtime. Availability and
    reliability calculations must still be derived from explicit machine-state
    history and an agreed denominator.
    """

    buckets: dict[str, list[MachineEventSource]] = {}
    display_for: dict[str, str] = {}
    matched_for: dict[str, bool] = {}

    for report in shift_reports:
        for event in report.machine_events:
            machine = machines_by_id.get(event.machine_id)
            key = event.machine_id
            display_for[key] = machine.machine_id if machine is not None else event.machine_id
            matched_for[key] = machine is not None
            buckets.setdefault(key, []).append(
                MachineEventSource(
                    origin="shift_report",
                    source_id=event.id,
                    report_id=report.id,
                    start=datetime.fromisoformat(event.start_time),
                    end=datetime.fromisoformat(event.end_time),
                    description=event.issue,
                )
            )

    for observation in observations:
        if observation.machine_id is not None and observation.machine_id in machines_by_id:
            key = observation.machine_id
            display_for[key] = machines_by_id[key].machine_id
            matched_for[key] = True
        else:
            key = _unmatched_key(observation.raw_machine_label)
            display_for[key] = observation.raw_machine_label
            matched_for[key] = False
        buckets.setdefault(key, []).append(
            MachineEventSource(
                origin="control_room",
                source_id=observation.id,
                report_id=None,
                start=datetime.fromisoformat(observation.start_time) if observation.start_time else None,
                end=datetime.fromisoformat(observation.end_time) if observation.end_time else None,
                description=observation.description,
            )
        )

    aggregates: list[MachineAggregate] = []
    for key, events in buckets.items():
        events_sorted = tuple(sorted(events, key=lambda event: event.start.isoformat() if event.start else ""))
        work_events = tuple(event for event in events if event.origin == "shift_report")
        control_room_events = tuple(event for event in events if event.origin == "control_room")
        work_intervals = tuple(
            TimeInterval(start=event.start, end=event.end, source=event.source_id)
            for event in work_events
            if event.start is not None and event.end is not None
        )
        control_room_intervals = tuple(
            TimeInterval(start=event.start, end=event.end, source=event.source_id)
            for event in control_room_events
            if event.start is not None and event.end is not None
        )
        key_issues = tuple(dict.fromkeys(event.description.strip() for event in events if event.description.strip()))[:5]
        aggregates.append(
            MachineAggregate(
                machine_internal_id=key if matched_for[key] else None,
                machine_display_id=display_for[key],
                matched=matched_for[key],
                total_work_interval_seconds=total_interval_seconds(work_intervals),
                total_control_room_delay_seconds=total_interval_seconds(control_room_intervals),
                work_event_count=len(work_events),
                control_room_event_count=len(control_room_events),
                event_count=len(events),
                key_issues=key_issues,
                events=events_sorted,
            )
        )
    return tuple(sorted(aggregates, key=lambda aggregate: aggregate.machine_display_id))


@dataclass(frozen=True)
class AttendanceSummary:
    present_count: int
    absent_count: int
    absent_names: tuple[str, ...]


@dataclass(frozen=True)
class SafetySummary:
    stop_fix_open: int
    stop_fix_rectified: int
    green_cards: int
    red_cards: int
    card_reasons: tuple[tuple[str, str], ...]
    stop_fix_records: tuple[StopFixRecord, ...]


@dataclass(frozen=True)
class OtherActivityView:
    shift_kind: str
    category: str | None
    description: str


@dataclass(frozen=True)
class ReportBundle:
    reporting_date: str
    timezone: str
    shift_reports: tuple[ShiftReport, ...]
    observations: tuple[ControlRoomObservation, ...]
    machine_states: tuple[MachineStateDeclaration, ...]
    machine_aggregates: tuple[MachineAggregate, ...]
    attendance: AttendanceSummary
    safety: SafetySummary
    other_activities: tuple[OtherActivityView, ...]
    expected_inputs: tuple[ExpectedInputStatus, ...]
    status: Literal["waiting", "complete"]


def build_report_bundle(
    *,
    reporting_date: str,
    timezone: str,
    shift_reports: tuple[ShiftReport, ...],
    observations: tuple[ControlRoomObservation, ...],
    machine_states: tuple[MachineStateDeclaration, ...],
    machines_by_id: dict[str, Machine],
    persons_by_id: dict[str, Person],
    require_control_room: bool = True,
) -> ReportBundle:
    machine_aggregates = aggregate_machines(
        machines_by_id=machines_by_id,
        shift_reports=shift_reports,
        observations=observations,
    )

    present_count = 0
    absent_names: list[str] = []
    for report in shift_reports:
        for entry in report.attendance:
            person = persons_by_id.get(entry.person_id)
            if entry.present:
                present_count += 1
            else:
                absent_names.append(person.name if person is not None else entry.person_id)
    attendance = AttendanceSummary(
        present_count=present_count,
        absent_count=len(absent_names),
        absent_names=tuple(absent_names),
    )

    safety = SafetySummary(
        stop_fix_open=sum(1 for report in shift_reports for item in report.stop_fix if item.status == "open"),
        stop_fix_rectified=sum(1 for report in shift_reports for item in report.stop_fix if item.status == "rectified"),
        green_cards=sum(1 for report in shift_reports for card in report.cards if card.card_type == "green"),
        red_cards=sum(1 for report in shift_reports for card in report.cards if card.card_type == "red"),
        card_reasons=tuple((card.card_type, card.reason) for report in shift_reports for card in report.cards),
        stop_fix_records=tuple(item for report in shift_reports for item in report.stop_fix),
    )

    other_activities = tuple(
        OtherActivityView(shift_kind=report.shift_kind, category=activity.category, description=activity.description)
        for report in shift_reports
        for activity in report.other_activities
    )

    expected = [
        ExpectedInputStatus(
            key="morning_shift_report", label="Morning shift report",
            present=any(report.shift_kind == "morning" for report in shift_reports),
        ),
        ExpectedInputStatus(
            key="afternoon_shift_report", label="Afternoon shift report",
            present=any(report.shift_kind == "afternoon" for report in shift_reports),
        ),
        ExpectedInputStatus(
            key="night_shift_report", label="Night shift report",
            present=any(report.shift_kind == "night" for report in shift_reports),
        ),
    ]
    if require_control_room:
        expected.append(
            ExpectedInputStatus(
                key="control_room_report",
                label="Control-room report",
                present=bool(observations),
            )
        )
    status: Literal["waiting", "complete"] = "complete" if all(item.present for item in expected) else "waiting"

    return ReportBundle(
        reporting_date=reporting_date,
        timezone=timezone,
        shift_reports=shift_reports,
        observations=observations,
        machine_states=machine_states,
        machine_aggregates=machine_aggregates,
        attendance=attendance,
        safety=safety,
        other_activities=other_activities,
        expected_inputs=tuple(expected),
        status=status,
    )
