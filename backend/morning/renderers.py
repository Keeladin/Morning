from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from .aggregate import MachineAggregate, ReportBundle
from .intervals import TimeInterval, merge_intervals, total_interval_seconds
from .models import Machine, MachineEvent, MachineStateDeclaration, Person, ShiftReport

STATE_LABELS = {
    "running": "Running / operational",
    "not_tested": "Not tested",
    "under_repair": "Still under repair / standing",
    "awaiting_parts": "Awaiting parts",
    "other": "Other",
}


def _construction_level_label(level: str) -> str:
    value = level.upper()
    if value.endswith("N") and value[:-1].isdigit():
        return f"{value[:-1]}L North"
    if value.endswith("S") and value[:-1].isdigit():
        return f"{value[:-1]}L South"
    return f"{value}L"


def _hhmm(value: str, timezone: str) -> str:
    try:
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is not None:
            moment = moment.astimezone(ZoneInfo(timezone))
        return moment.strftime("%H:%M")
    except (ValueError, KeyError):
        return value


def _duration_label(total_seconds: float) -> str:
    minutes = round(total_seconds / 60)
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def _interval_duration(start_value: str, end_value: str) -> str:
    try:
        start = datetime.fromisoformat(start_value)
        end = datetime.fromisoformat(end_value)
        return _duration_label((end - start).total_seconds())
    except ValueError:
        return "unknown"


def _event_interval(event: MachineEvent) -> TimeInterval | None:
    try:
        return TimeInterval(
            start=datetime.fromisoformat(event.start_time),
            end=datetime.fromisoformat(event.end_time),
            source=event.id,
        )
    except (ValueError, TypeError):
        return None


def _machine_total_duration(events: tuple[MachineEvent, ...]) -> str:
    intervals = tuple(interval for event in events if (interval := _event_interval(event)) is not None)
    if len(intervals) != len(events):
        return "unknown"
    return _duration_label(total_interval_seconds(intervals))


def _overlap_suffix(interval: TimeInterval | None, prior: tuple[TimeInterval, ...]) -> str:
    if interval is None or not prior:
        return ""
    merged = merge_intervals(prior)
    if any(item.start <= interval.start and item.end >= interval.end for item in merged):
        return ", within above downtime"
    if any(interval.start < item.end and interval.end > item.start for item in merged):
        return ", overlaps above downtime"
    return ""


def _shift_label(shift_kind: str) -> str:
    return {
        "morning": "Morning Shift",
        "afternoon": "Afternoon Shift",
        "night": "Night Shift",
    }.get(shift_kind, f"{shift_kind.title()} Shift")


def _state_label(state: MachineStateDeclaration) -> str:
    label = STATE_LABELS.get(state.state, state.state)
    if state.state == "other" and state.state_note:
        label = f"{label}: {state.state_note}"
    if state.provenance == "carried":
        label += " [carried from prior declaration]"
    return label


def _latest_states(states: tuple[MachineStateDeclaration, ...]) -> dict[str, MachineStateDeclaration]:
    latest: dict[str, MachineStateDeclaration] = {}
    for state in sorted(states, key=lambda item: (item.declared_at, item.created_at or "", item.id)):
        latest[state.machine_id] = state
    return latest


def render_whatsapp_report(
    report: ShiftReport,
    *,
    supervisor_name: str,
    persons_by_id: dict[str, Person],
    machines_by_id: dict[str, Machine],
    timezone: str,
    machine_states: tuple[MachineStateDeclaration, ...] = (),
    construction_crew: dict[str, Any] | None = None,
) -> str:
    """Deterministic WhatsApp-ready text for one submitted or draft shift."""

    def person_name(person_id: str) -> str:
        person = persons_by_id.get(person_id)
        return person.name if person is not None else person_id

    def machine_label(machine_id: str) -> str:
        machine = machines_by_id.get(machine_id)
        return machine.machine_id if machine is not None else machine_id

    title = "Construction " if report.reporting_model == "construction" else ""
    lines: list[str] = [
        f"*{title}{_shift_label(report.shift_kind)} Report — {report.shift_date}*",
        f"Supervisor: {supervisor_name}",
    ]
    if report.reporting_model == "construction" and construction_crew:
        lines.append(f"Crew: {construction_crew['name']}")
        if construction_crew.get("workstream_name"):
            lines.append(f"Workstream: {construction_crew['workstream_name']}")
    lines += ["", "*Attendance*"]
    present = [person_name(entry.person_id) for entry in report.attendance if entry.present]
    absent = [person_name(entry.person_id) for entry in report.attendance if not entry.present]
    lines.append(f"Present: {len(present)}/{len(report.attendance)}")
    if absent:
        lines.append(f"Absent: {', '.join(absent)}")

    if report.reporting_model == "tmm":
        lines += ["", "*Brothers Keeper*", report.brothers_keeper or "Not recorded."]

    lines += ["", "*Safety*"]
    open_count = sum(1 for item in report.stop_fix if item.status == "open")
    rectified_count = sum(1 for item in report.stop_fix if item.status == "rectified")
    lines.append(f"Stop & Fix: {open_count} open, {rectified_count} rectified")
    for item in report.stop_fix:
        lines.append(f"  - {item.number} ({item.area_of_concern}) at {item.location}: {item.reason} [{item.status}]")
    green = sum(1 for card in report.cards if card.card_type == "green")
    red = sum(1 for card in report.cards if card.card_type == "red")
    lines.append(f"Cards: {green} green, {red} red")
    for card in report.cards:
        lines.append(f"  - {card.card_type.capitalize()}: {card.reason}")

    if report.reporting_model == "construction":
        labels = {"not_started": "Not started", "in_progress": "In progress", "held": "Held", "complete": "Complete"}
        core = [item for item in report.construction_work if item.kind == "core"]
        outstanding = [item for item in report.construction_work if item.kind == "outstanding"]
        lines += ["", "*Core Work*"]
        if not core:
            lines.append("No core work reported.")
        for item in core:
            progress = f" · {item.progress_percent}%" if item.progress_percent is not None else ""
            lines.append(f"{_construction_level_label(item.level)} · {item.location} — {item.task} [{labels.get(item.status, item.status)}{progress}]")
            if item.update_text:
                lines.append(f"  Update: {item.update_text}")
            if item.constraint_text:
                lines.append(f"  Constraint: {item.constraint_text}")
            if item.next_action:
                lines.append(f"  Next: {item.next_action}")
        lines += ["", "*Outstanding Work*"]
        if not outstanding:
            lines.append("None.")
        for item in outstanding:
            progress = f" · {item.progress_percent}%" if item.progress_percent is not None else ""
            lines.append(f"{_construction_level_label(item.level)} · {item.location} — {item.task} [{labels.get(item.status, item.status)}{progress}]")
            if item.update_text:
                lines.append(f"  Update: {item.update_text}")
            if item.constraint_text:
                lines.append(f"  Constraint: {item.constraint_text}")
            if item.next_action:
                lines.append(f"  Next: {item.next_action}")
    else:
        lines += ["", "*Machine Activity*"]
        if report.machine_events:
            events_by_machine: dict[str, list[MachineEvent]] = {}
            for event in report.machine_events:
                events_by_machine.setdefault(event.machine_id, []).append(event)

            for machine_index, (machine_id, machine_events) in enumerate(events_by_machine.items()):
                ordered_events = tuple(sorted(machine_events, key=lambda item: item.start_time))
                lines.append(
                    f"*{machine_label(machine_id)} — Total downtime: {_machine_total_duration(ordered_events)}*"
                )
                prior_intervals: list[TimeInterval] = []
                for event_index, event in enumerate(ordered_events):
                    interval = _event_interval(event)
                    suffix = _overlap_suffix(interval, tuple(prior_intervals))
                    person = persons_by_id.get(event.person_id or "")
                    assigned = f" · Assigned: {person.name}" if person is not None else ""
                    lines.append(
                        f"*{_hhmm(event.start_time, timezone)}-{_hhmm(event.end_time, timezone)} "
                        f"({_interval_duration(event.start_time, event.end_time)}{suffix})*"
                    )
                    lines.append(f"{event.issue}{assigned}")
                    if interval is not None:
                        prior_intervals.append(interval)
                    if event_index < len(ordered_events) - 1:
                        lines.append("")
                if machine_index < len(events_by_machine) - 1:
                    lines.append("")
        else:
            lines.append("No machine activity reported.")

        latest = _latest_states(machine_states)
        if latest:
            lines += ["", "*Machine State at Handover*"]
            for machine_id in sorted(latest, key=machine_label):
                lines.append(f"{machine_label(machine_id)}: {_state_label(latest[machine_id])}")

        lines += ["", "*Other Activities*"]
        if report.other_activities:
            for activity in report.other_activities:
                prefix = f"{activity.category}: " if activity.category else ""
                lines.append(f"- {prefix}{activity.description}")
        else:
            lines.append("None.")
    return "\n".join(lines)


def render_detailed_report(bundle: ReportBundle) -> str:
    lines: list[str] = [f"*24-Hour Departmental Report — {bundle.reporting_date}*", "", "Expected inputs:"]
    for item in bundle.expected_inputs:
        lines.append(f"  - {item.label}: {'present' if item.present else 'MISSING'}")

    lines += ["", f"Attendance: {bundle.attendance.present_count} present, {bundle.attendance.absent_count} absent"]
    if bundle.attendance.absent_names:
        lines.append(f"  Absent: {', '.join(bundle.attendance.absent_names)}")

    lines += ["", "Brothers Keeper:"]
    contributions = [report for report in bundle.shift_reports if report.brothers_keeper]
    if not contributions:
        lines.append("  None recorded.")
    for report in contributions:
        lines.append(f"  [{_shift_label(report.shift_kind)}] {report.brothers_keeper}")

    lines += [
        "",
        "Safety:",
        f"  Stop & Fix: {bundle.safety.stop_fix_open} open, {bundle.safety.stop_fix_rectified} rectified",
        f"  Cards issued: {bundle.safety.green_cards} green, {bundle.safety.red_cards} red",
    ]
    for card_type, reason in bundle.safety.card_reasons:
        lines.append(f"    - {card_type.capitalize()}: {reason}")

    latest_states = _latest_states(bundle.machine_states)
    lines += ["", "Machine activity:"]
    if not bundle.machine_aggregates:
        lines.append("  No machine activity reported.")
    for aggregate in bundle.machine_aggregates:
        flag = "" if aggregate.matched else "  [unmatched machine label - needs review]"
        lines.append(f"  {aggregate.machine_display_id}{flag}")
        if aggregate.work_event_count:
            lines.append(
                f"    Engineering work time recorded: {_duration_label(aggregate.total_work_interval_seconds)} "
                f"across {aggregate.work_event_count} work event(s)"
            )
        if aggregate.machine_internal_id and aggregate.machine_internal_id in latest_states:
            lines.append(f"    Reported state: {_state_label(latest_states[aggregate.machine_internal_id])}")
        else:
            lines.append("    Reported state: not declared")
        for event in aggregate.events:
            origin = "shift report" if event.origin == "shift_report" else "control room"
            when = (
                f"{event.start.astimezone(ZoneInfo(bundle.timezone)).strftime('%H:%M')}-"
                f"{event.end.astimezone(ZoneInfo(bundle.timezone)).strftime('%H:%M')}"
                if event.start and event.end
                else "no times given"
            )
            lines.append(f"    - [{origin}] {when}: {event.description}")

    lines += ["", "Other activities:"]
    if not bundle.other_activities:
        lines.append("  None reported.")
    for activity in bundle.other_activities:
        prefix = f"{activity.category}: " if activity.category else ""
        lines.append(f"  [{_shift_label(activity.shift_kind)}] {prefix}{activity.description}")

    if bundle.observations:
        lines += ["", "Control-room observations:"]
        for observation in bundle.observations:
            lines.append(f"  {observation.raw_machine_label}: {observation.description}")
    return "\n".join(lines)


@dataclass(frozen=True)
class CompactMachineRow:
    machine_display_id: str
    matched: bool
    work_time_label: str
    key_issues: str
    status: str


def compact_rows(bundle: ReportBundle) -> tuple[CompactMachineRow, ...]:
    latest_states = _latest_states(bundle.machine_states)

    def status_for(aggregate: MachineAggregate) -> str:
        if aggregate.machine_internal_id and aggregate.machine_internal_id in latest_states:
            return _state_label(latest_states[aggregate.machine_internal_id])
        return "No machine state declared."

    return tuple(
        CompactMachineRow(
            machine_display_id=aggregate.machine_display_id,
            matched=aggregate.matched,
            work_time_label=_duration_label(aggregate.total_work_interval_seconds),
            key_issues="; ".join(aggregate.key_issues) if aggregate.key_issues else "No issues logged.",
            status=status_for(aggregate),
        )
        for aggregate in bundle.machine_aggregates
    )


def render_compact_report(bundle: ReportBundle) -> str:
    """Brief meeting projection without inventing downtime from engineering activity."""

    lines = [f"*Department Meeting Summary — {bundle.reporting_date}*"]
    if bundle.status != "complete":
        missing = [item.label for item in bundle.expected_inputs if not item.present]
        lines += ["", f"INCOMPLETE - missing: {', '.join(missing)}"]
    lines.append("")
    contributions = [report for report in bundle.shift_reports if report.brothers_keeper]
    if contributions:
        lines.append("Brothers Keeper:")
        for report in contributions:
            lines.append(f"  {_shift_label(report.shift_kind)}: {report.brothers_keeper}")
        lines.append("")
    rows = compact_rows(bundle)
    if not rows:
        lines.append("No machine activity reported.")
    for row in rows:
        flag = "" if row.matched else " [unmatched]"
        lines.append(
            f"{row.machine_display_id}{flag}: work recorded {row.work_time_label}; "
            f"state {row.status}; {row.key_issues}"
        )
    return "\n".join(lines)
