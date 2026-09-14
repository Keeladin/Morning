from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import time as time_module
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from .models import ShiftReport

SCHEMA_NAME = "morning-atlas-weekly"
SCHEMA_VERSION = 1
DEFAULT_TIMEZONE = "Africa/Johannesburg"
DEFAULT_EXPORT_HOUR = 4
DEFAULT_EXPORT_MINUTE = 30


class WeeklyExportError(RuntimeError):
    pass


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_default)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(_canonical_json(row) + "\n")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _week_start(value: str | date) -> date:
    parsed = _parse_date(value)
    if parsed.weekday() != 0:
        raise WeeklyExportError("week_start must be a Monday")
    return parsed


def _week_id(start: date) -> str:
    iso = start.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _duration_seconds(start_value: str, end_value: str) -> float:
    start = datetime.fromisoformat(start_value)
    end = datetime.fromisoformat(end_value)
    return max(0.0, (end - start).total_seconds())


def latest_exportable_week_start(
    now: datetime,
    *,
    trigger_hour: int = DEFAULT_EXPORT_HOUR,
    trigger_minute: int = DEFAULT_EXPORT_MINUTE,
) -> date:
    local_date = now.date()
    current_monday = local_date - timedelta(days=local_date.weekday())
    latest = current_monday - timedelta(days=7)
    if local_date.weekday() == 0 and now.time().replace(tzinfo=None) < time(trigger_hour, trigger_minute):
        latest -= timedelta(days=7)
    return latest


def completed_week_starts(
    now: datetime,
    *,
    count: int,
    trigger_hour: int = DEFAULT_EXPORT_HOUR,
    trigger_minute: int = DEFAULT_EXPORT_MINUTE,
) -> tuple[date, ...]:
    if count < 1:
        return ()
    latest = latest_exportable_week_start(now, trigger_hour=trigger_hour, trigger_minute=trigger_minute)
    return tuple(latest - timedelta(days=7 * index) for index in range(count))


@dataclass(frozen=True)
class WeeklyExportResult:
    week_id: str
    week_start: str
    week_end: str
    output_dir: str
    source_fingerprint: str
    report_count: int
    changed: bool


class WeeklyAtlasExporter:
    """Build a disposable, traceable weekly evidence package for Atlas.

    Morning remains canonical. The export intentionally contains raw evidence
    plus deterministic metrics and no model-generated interpretation.
    """

    def __init__(self, store, root_dir: str | Path, *, timezone_name: str = DEFAULT_TIMEZONE) -> None:
        self.store = store
        self.root_dir = Path(root_dir)
        self.timezone_name = timezone_name

    def _reports_for_week(self, start: date) -> tuple[ShiftReport, ...]:
        end = start + timedelta(days=6)
        reports = [
            report for report in self.store.list_reports()
            if report.status == "submitted" and start <= date.fromisoformat(report.shift_date) <= end
        ]
        return tuple(sorted(reports, key=lambda item: (item.shift_date, item.shift_kind, item.reporting_model, item.id)))

    def _source_snapshot(self, reports: tuple[ShiftReport, ...]) -> dict[str, Any]:
        person_ids = {
            item.person_id for report in reports for item in report.attendance
        } | {
            event.person_id for report in reports for event in report.machine_events if event.person_id
        }
        machine_ids = {event.machine_id for report in reports for event in report.machine_events}
        crew_ids = {crew_id for report in reports for crew_id in report.crew_ids}
        supervisor_ids = {report.supervisor_principal_id for report in reports}
        states = [
            state.as_dict() for report in reports for state in self.store.list_machine_states(report_id=report.id)
        ]
        persons = [person.as_dict() for person in self.store.list_persons() if person.id in person_ids]
        machines = [machine.as_dict() for machine in self.store.list_machines() if machine.id in machine_ids]
        crews = [crew.as_dict() for crew in self.store.list_crews() if crew.id in crew_ids]
        principals = []
        for principal_id in sorted(supervisor_ids):
            principal = self.store.principal_by_id(principal_id)
            if principal is not None:
                principals.append({
                    key: principal.get(key)
                    for key in ("id", "display_name", "role", "status", "created_at", "updated_at")
                    if key in principal
                })
        return {
            "reports": [report.as_dict() for report in reports],
            "machine_states": sorted(states, key=lambda item: (item["report_id"], item["declared_at"], item["id"])),
            "people": sorted(persons, key=lambda item: item["id"]),
            "machines": sorted(machines, key=lambda item: item["id"]),
            "crews": sorted(crews, key=lambda item: item["id"]),
            "supervisors": principals,
        }

    @staticmethod
    def _fingerprint(snapshot: dict[str, Any]) -> str:
        return sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()

    def _existing_manifest(self, start: date) -> dict[str, Any] | None:
        path = self.root_dir / "weekly" / _week_id(start) / "manifest.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def needs_export(self, week_start: str | date) -> bool:
        start = _week_start(week_start)
        reports = self._reports_for_week(start)
        snapshot = self._source_snapshot(reports)
        existing = self._existing_manifest(start)
        return existing is None or existing.get("source_fingerprint") != self._fingerprint(snapshot)

    def export_if_changed(self, week_start: str | date, *, skip_empty: bool = False) -> WeeklyExportResult | None:
        start = _week_start(week_start)
        reports = self._reports_for_week(start)
        if skip_empty and not reports and self._existing_manifest(start) is None:
            return None
        snapshot = self._source_snapshot(reports)
        fingerprint = self._fingerprint(snapshot)
        existing = self._existing_manifest(start)
        if existing is not None and existing.get("source_fingerprint") == fingerprint:
            target = self.root_dir / "weekly" / _week_id(start)
            return WeeklyExportResult(
                week_id=_week_id(start), week_start=start.isoformat(), week_end=(start + timedelta(days=6)).isoformat(),
                output_dir=str(target), source_fingerprint=fingerprint, report_count=len(reports), changed=False,
            )
        return self._publish(start, reports, snapshot, fingerprint)

    def export_week(self, week_start: str | date) -> WeeklyExportResult:
        start = _week_start(week_start)
        reports = self._reports_for_week(start)
        snapshot = self._source_snapshot(reports)
        return self._publish(start, reports, snapshot, self._fingerprint(snapshot))

    def _publish(
        self,
        start: date,
        reports: tuple[ShiftReport, ...],
        snapshot: dict[str, Any],
        fingerprint: str,
    ) -> WeeklyExportResult:
        week_end = start + timedelta(days=6)
        week_id = _week_id(start)
        weekly_root = self.root_dir / "weekly"
        weekly_root.mkdir(parents=True, exist_ok=True)
        temp_dir = weekly_root / f".{week_id}.tmp-{uuid4().hex}"
        target_dir = weekly_root / week_id
        temp_dir.mkdir(parents=True)
        try:
            payload = self._build_payload(start, week_end, reports, snapshot)
            for filename, rows in payload["jsonl"].items():
                _write_jsonl(temp_dir / filename, rows)
            _write_json(temp_dir / "metrics.json", payload["metrics"])
            _write_json(temp_dir / "data-quality.json", payload["data_quality"])
            (temp_dir / "summary.md").write_text(payload["summary"], encoding="utf-8")

            files = []
            for path in sorted(temp_dir.iterdir()):
                if path.is_file():
                    files.append({"name": path.name, "sha256": _sha256_file(path), "bytes": path.stat().st_size})
            generated_at = datetime.now(ZoneInfo(self.timezone_name)).isoformat()
            manifest = {
                "schema": SCHEMA_NAME,
                "schema_version": SCHEMA_VERSION,
                "reporting_week": week_id,
                "week_start": start.isoformat(),
                "week_end": week_end.isoformat(),
                "timezone": self.timezone_name,
                "generated_at": generated_at,
                "source_fingerprint": fingerprint,
                "report_count": len(reports),
                "files": files,
            }
            _write_json(temp_dir / "manifest.json", manifest)
            self._validate_package(temp_dir)

            old_dir = None
            if target_dir.exists():
                old_dir = weekly_root / f".{week_id}.old-{uuid4().hex}"
                os.replace(target_dir, old_dir)
            os.replace(temp_dir, target_dir)
            if old_dir is not None:
                shutil.rmtree(old_dir, ignore_errors=True)
            self._write_root_manifest()
            return WeeklyExportResult(
                week_id=week_id,
                week_start=start.isoformat(),
                week_end=week_end.isoformat(),
                output_dir=str(target_dir),
                source_fingerprint=fingerprint,
                report_count=len(reports),
                changed=True,
            )
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    def _build_payload(
        self,
        start: date,
        end: date,
        reports: tuple[ShiftReport, ...],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        people = {item["id"]: item for item in snapshot["people"]}
        machines = {item["id"]: item for item in snapshot["machines"]}
        crews = {item["id"]: item for item in snapshot["crews"]}
        supervisors = {item["id"]: item for item in snapshot["supervisors"]}
        states_by_report: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for state in snapshot["machine_states"]:
            states_by_report[state["report_id"]].append(state)

        report_rows: list[dict[str, Any]] = []
        attendance_rows: list[dict[str, Any]] = []
        brothers_rows: list[dict[str, Any]] = []
        safety_rows: list[dict[str, Any]] = []
        machine_event_rows: list[dict[str, Any]] = []
        machine_state_rows: list[dict[str, Any]] = []
        construction_rows: list[dict[str, Any]] = []
        activity_rows: list[dict[str, Any]] = []

        attendance_shift = defaultdict(lambda: {"present": 0, "absent": 0})
        attendance_total = {"present": 0, "absent": 0}
        report_models: Counter[str] = Counter()
        report_shifts: Counter[str] = Counter()
        stop_fix_status: Counter[str] = Counter()
        card_types: Counter[str] = Counter()
        machine_metrics: dict[str, dict[str, Any]] = {}

        for report in reports:
            supervisor = supervisors.get(report.supervisor_principal_id, {})
            report_rows.append({
                "report_id": report.id,
                "shift_date": report.shift_date,
                "shift_kind": report.shift_kind,
                "reporting_model": report.reporting_model,
                "supervisor_principal_id": report.supervisor_principal_id,
                "supervisor_name": supervisor.get("display_name"),
                "crew_ids": list(report.crew_ids),
                "crew_names": [crews.get(item, {}).get("name") for item in report.crew_ids],
                "created_at": report.created_at,
                "updated_at": report.updated_at,
                "submitted_at": report.submitted_at,
                "section_review_flags": {
                    "safety_reviewed_empty": report.safety_reviewed_empty,
                    "machine_activity_reviewed_empty": report.machine_activity_reviewed_empty,
                    "other_activities_reviewed_empty": report.other_activities_reviewed_empty,
                    "construction_work_reviewed_empty": report.construction_work_reviewed_empty,
                    "construction_outstanding_reviewed_empty": report.construction_outstanding_reviewed_empty,
                },
            })
            report_models[report.reporting_model] += 1
            report_shifts[report.shift_kind] += 1

            for entry in report.attendance:
                person = people.get(entry.person_id, {})
                attendance_rows.append({
                    "report_id": report.id, "shift_date": report.shift_date, "shift_kind": report.shift_kind,
                    "reporting_model": report.reporting_model, "person_id": entry.person_id,
                    "person_name": person.get("name"), "role": person.get("role"),
                    "person_current_crew_id": person.get("crew_id"), "present": entry.present,
                })
                key = "present" if entry.present else "absent"
                attendance_total[key] += 1
                attendance_shift[report.shift_kind][key] += 1

            if report.brothers_keeper:
                brothers_rows.append({
                    "report_id": report.id, "shift_date": report.shift_date, "shift_kind": report.shift_kind,
                    "supervisor_principal_id": report.supervisor_principal_id,
                    "supervisor_name": supervisor.get("display_name"), "text": report.brothers_keeper,
                })

            for item in report.stop_fix:
                safety_rows.append({
                    "record_type": "stop_fix", "report_id": report.id, "shift_date": report.shift_date,
                    "shift_kind": report.shift_kind, **item.as_dict(),
                })
                stop_fix_status[item.status] += 1
            for card in report.cards:
                safety_rows.append({
                    "record_type": "card", "report_id": report.id, "shift_date": report.shift_date,
                    "shift_kind": report.shift_kind, **card.as_dict(),
                })
                card_types[card.card_type] += 1

            for event in report.machine_events:
                machine = machines.get(event.machine_id, {})
                person = people.get(event.person_id or "", {})
                duration = _duration_seconds(event.start_time, event.end_time)
                display_id = machine.get("machine_id") or event.machine_id
                machine_event_rows.append({
                    "report_id": report.id, "shift_date": report.shift_date, "shift_kind": report.shift_kind,
                    **event.as_dict(), "machine_display_id": display_id,
                    "machine_type": machine.get("machine_type"), "section": machine.get("section"),
                    "assigned_person_name": person.get("name"), "assigned_person_role": person.get("role"),
                    "recorded_interval_seconds": duration,
                })
                metric = machine_metrics.setdefault(display_id, {
                    "machine_id": event.machine_id, "machine_display_id": display_id,
                    "event_count": 0, "recorded_interval_seconds": 0.0,
                })
                metric["event_count"] += 1
                metric["recorded_interval_seconds"] += duration

            for state in states_by_report.get(report.id, []):
                machine = machines.get(state["machine_id"], {})
                machine_state_rows.append({
                    "shift_date": report.shift_date, "shift_kind": report.shift_kind,
                    "machine_display_id": machine.get("machine_id") or state["machine_id"], **state,
                })

            for item in report.construction_work:
                construction_rows.append({
                    "report_id": report.id, "shift_date": report.shift_date, "shift_kind": report.shift_kind,
                    **item.as_dict(),
                })
            for item in report.other_activities:
                activity_rows.append({
                    "report_id": report.id, "shift_date": report.shift_date, "shift_kind": report.shift_kind,
                    **item.as_dict(),
                })

        tmm_slots = {(report.shift_date, report.shift_kind) for report in reports if report.reporting_model == "tmm"}
        expected_slots = [
            ((start + timedelta(days=day_index)).isoformat(), shift)
            for day_index in range(7) for shift in ("morning", "afternoon", "night")
        ]
        missing_tmm_slots = [
            {"shift_date": shift_date, "shift_kind": shift}
            for shift_date, shift in expected_slots if (shift_date, shift) not in tmm_slots
        ]
        attendance_opportunities = attendance_total["present"] + attendance_total["absent"]
        attendance_by_shift = {}
        for shift, counts in sorted(attendance_shift.items()):
            total = counts["present"] + counts["absent"]
            attendance_by_shift[shift] = {
                **counts, "opportunities": total,
                "attendance_percent": round(counts["present"] / total * 100, 1) if total else None,
            }

        metrics = {
            "schema": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "week_start": start.isoformat(),
            "week_end": end.isoformat(),
            "reports": {
                "submitted": len(reports),
                "by_reporting_model": dict(sorted(report_models.items())),
                "by_shift": dict(sorted(report_shifts.items())),
            },
            "attendance": {
                **attendance_total,
                "opportunities": attendance_opportunities,
                "attendance_percent": round(attendance_total["present"] / attendance_opportunities * 100, 1)
                if attendance_opportunities else None,
                "by_shift": attendance_by_shift,
            },
            "safety": {
                "stop_fix": dict(sorted(stop_fix_status.items())),
                "cards": dict(sorted(card_types.items())),
            },
            "brothers_keeper": {"contribution_count": len(brothers_rows)},
            "machine_activity": {
                "event_count": len(machine_event_rows),
                "recorded_interval_seconds": round(sum(row["recorded_interval_seconds"] for row in machine_event_rows), 3),
                "machine_count": len(machine_metrics),
                "by_machine": sorted(
                    machine_metrics.values(), key=lambda item: (-item["recorded_interval_seconds"], item["machine_display_id"])
                ),
                "state_declaration_count": len(machine_state_rows),
            },
            "construction": {"work_item_count": len(construction_rows)},
            "other_activities": {"count": len(activity_rows)},
        }

        data_quality = {
            "schema": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "week_start": start.isoformat(),
            "week_end": end.isoformat(),
            "tmm_shift_slots": {
                "expected_if_operating_all_shifts": len(expected_slots),
                "observed": len(tmm_slots),
                "missing": missing_tmm_slots,
                "note": "Missing slots are coverage signals, not proof that a report was required; planned non-reporting shifts are not yet modelled.",
            },
            "observability_gaps": [
                "Machine-event intervals are elapsed recorded engineering intervals, not canonical machine downtime.",
                "Morning does not yet separate active repair time from waiting, parts, assistance, testing, or other constraint time within an event.",
                "Availability, reliability, MTBF and MTTR must not be inferred without sufficient machine-state history and an agreed operating-time denominator.",
                "Current person and machine reference metadata is exported for context; it is not yet a historical snapshot of role, crew or machine attributes at event time.",
            ],
            "machine_state_evidence": {
                "declaration_count": len(machine_state_rows),
                "availability_metrics_supported": False,
                "note": "The weekly export deliberately does not calculate availability or reliability metrics.",
            },
        }

        top_machines = metrics["machine_activity"]["by_machine"][:5]
        attendance_text = (
            f"{metrics['attendance']['attendance_percent']}% ({attendance_total['present']}/{attendance_opportunities})"
            if attendance_opportunities else "No attendance observations"
        )
        lines = [
            f"# Morning weekly evidence summary — {_week_id(start)}",
            "",
            f"Reporting window: {start.isoformat()} to {end.isoformat()}",
            f"Submitted reports: {len(reports)}",
            f"Attendance: {attendance_text}",
            f"Machine events: {len(machine_event_rows)} across {len(machine_metrics)} machines",
            f"Brothers Keeper contributions: {len(brothers_rows)}",
            f"Stop & Fix records: {sum(stop_fix_status.values())}",
            f"Cards: {sum(card_types.values())}",
            "",
            "## Highest recorded machine-event intervals",
        ]
        if top_machines:
            for item in top_machines:
                hours = item["recorded_interval_seconds"] / 3600
                lines.append(f"- {item['machine_display_id']}: {item['event_count']} events, {hours:.1f} recorded interval hours")
        else:
            lines.append("- No machine events recorded.")
        lines.extend([
            "",
            "## Data quality",
            f"- Observed TMM shift slots: {len(tmm_slots)}/{len(expected_slots)} possible all-shift slots.",
            "- Recorded machine-event duration is not downtime or active wrench time.",
            "- This file contains deterministic facts only; interpretation belongs to Atlas.",
            "",
        ])

        return {
            "jsonl": {
                "reports.jsonl": report_rows,
                "attendance.jsonl": attendance_rows,
                "brothers-keeper.jsonl": brothers_rows,
                "safety.jsonl": safety_rows,
                "machine-events.jsonl": machine_event_rows,
                "machine-states.jsonl": machine_state_rows,
                "construction-work.jsonl": construction_rows,
                "other-activities.jsonl": activity_rows,
                "people.jsonl": snapshot["people"],
                "machines.jsonl": snapshot["machines"],
                "crews.jsonl": snapshot["crews"],
                "supervisors.jsonl": snapshot["supervisors"],
            },
            "metrics": metrics,
            "data_quality": data_quality,
            "summary": "\n".join(lines),
        }

    @staticmethod
    def _validate_package(path: Path) -> None:
        required = {
            "manifest.json", "reports.jsonl", "attendance.jsonl", "brothers-keeper.jsonl", "safety.jsonl",
            "machine-events.jsonl", "machine-states.jsonl", "construction-work.jsonl", "other-activities.jsonl",
            "people.jsonl", "machines.jsonl", "crews.jsonl", "supervisors.jsonl", "metrics.json",
            "data-quality.json", "summary.md",
        }
        missing = sorted(name for name in required if not (path / name).exists())
        # manifest is written after the evidence files, so validation before publish
        # accepts it only when the caller has completed the manifest write.
        if missing:
            raise WeeklyExportError(f"weekly export package is incomplete: {', '.join(missing)}")
        for name in ("metrics.json", "data-quality.json", "manifest.json"):
            json.loads((path / name).read_text(encoding="utf-8"))

    def _write_root_manifest(self) -> None:
        weekly_root = self.root_dir / "weekly"
        weeks = []
        if weekly_root.exists():
            for directory in sorted((item for item in weekly_root.iterdir() if item.is_dir() and not item.name.startswith("."))):
                manifest_path = directory / "manifest.json"
                if not manifest_path.exists():
                    continue
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                weeks.append({
                    "reporting_week": manifest.get("reporting_week"),
                    "week_start": manifest.get("week_start"),
                    "week_end": manifest.get("week_end"),
                    "generated_at": manifest.get("generated_at"),
                    "report_count": manifest.get("report_count"),
                    "path": f"weekly/{directory.name}",
                })
        weeks.sort(key=lambda item: item.get("week_start") or "")
        root_manifest = {
            "schema": "morning-atlas-export-index",
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(ZoneInfo(self.timezone_name)).isoformat(),
            "latest": weeks[-1] if weeks else None,
            "available_weeks": weeks,
        }
        self.root_dir.mkdir(parents=True, exist_ok=True)
        temp = self.root_dir / f".manifest.tmp-{uuid4().hex}"
        _write_json(temp, root_manifest)
        os.replace(temp, self.root_dir / "manifest.json")


def run_export_scheduler(
    store,
    root_dir: str | Path,
    *,
    timezone_name: str = DEFAULT_TIMEZONE,
    lookback_weeks: int = 4,
    poll_seconds: int = 900,
    trigger_hour: int = DEFAULT_EXPORT_HOUR,
    trigger_minute: int = DEFAULT_EXPORT_MINUTE,
) -> None:
    exporter = WeeklyAtlasExporter(store, root_dir, timezone_name=timezone_name)
    zone = ZoneInfo(timezone_name)
    while True:
        now = datetime.now(zone)
        for start in completed_week_starts(
            now, count=max(1, lookback_weeks), trigger_hour=trigger_hour, trigger_minute=trigger_minute
        ):
            result = exporter.export_if_changed(start, skip_empty=True)
            if result is not None and result.changed:
                print(f"Published Morning Atlas export {result.week_id} ({result.report_count} reports)", flush=True)
        time_module.sleep(max(60, poll_seconds))
