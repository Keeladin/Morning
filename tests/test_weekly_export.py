from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
import json

from morning.models import (
    AttendanceEntry, CardObservation, Crew, Machine, MachineEvent, MachineStateDeclaration,
    OtherActivity, Person, ShiftReport, StopFixRecord,
)
from morning.weekly_export import WeeklyAtlasExporter, completed_week_starts, latest_exportable_week_start


class FakeStore:
    def __init__(self, reports):
        self.reports = tuple(reports)
        self.people = (
            Person(id="person-1", name="Artisan One", employee_number="1", role="Artisan", active=True, crew_id="crew-1", created_at="2026-09-01T00:00:00+02:00"),
        )
        self.machines = (
            Machine(id="machine-1", machine_id="STC 14", machine_type="STC", section="TMM", active=True, created_at="2026-09-01T00:00:00+02:00"),
        )
        self.crews = (Crew(id="crew-1", name="Crew 1", created_at="2026-09-01T00:00:00+02:00"),)
        self.states = {
            "report-1": (
                MachineStateDeclaration(
                    id="state-1", machine_id="machine-1", report_id="report-1",
                    declared_at="2026-09-10T13:50:00+02:00", state="under_repair", provenance="declared",
                ),
            )
        }

    def list_reports(self):
        return self.reports

    def list_persons(self):
        return self.people

    def list_machines(self):
        return self.machines

    def list_crews(self):
        return self.crews

    def list_machine_states(self, *, report_id):
        return self.states.get(report_id, ())

    def principal_by_id(self, principal_id):
        return {"id": principal_id, "display_name": "Supervisor One", "role": "supervisor", "status": "active"}


def sample_report(*, updated_at="2026-09-10T14:00:00+02:00"):
    return ShiftReport(
        id="report-1", shift_date="2026-09-10", shift_kind="morning", supervisor_principal_id="supervisor-1",
        crew_id="crew-1", crew_ids=("crew-1",), reporting_model="tmm", status="submitted",
        attendance=(AttendanceEntry(person_id="person-1", present=True),),
        stop_fix=(StopFixRecord(id="sf-1", number="SF1", issued_at="2026-09-10T09:00:00+02:00", area_of_concern="Lifting", location="8L", reason="Test", instruction="Rectify", status="open"),),
        cards=(CardObservation(id="card-1", card_type="green", reason="Good teamwork"),),
        machine_events=(MachineEvent(id="event-1", machine_id="machine-1", start_time="2026-09-10T10:00:00+02:00", end_time="2026-09-10T11:30:00+02:00", issue="Repair oil leak", person_id="person-1"),),
        construction_work=(), other_activities=(OtherActivity(id="act-1", category="Support", description="Assisted production"),),
        created_at="2026-09-10T06:00:00+02:00", updated_at=updated_at, submitted_at="2026-09-10T14:00:00+02:00",
        brothers_keeper="Communication and teamwork around breakdowns.",
    )


def test_weekly_export_writes_traceable_operational_dataset(tmp_path):
    exporter = WeeklyAtlasExporter(FakeStore((sample_report(),)), tmp_path)
    result = exporter.export_week(date(2026, 9, 7))
    assert result.changed is True
    target = tmp_path / "weekly" / "2026-W37"
    manifest = json.loads((target / "manifest.json").read_text())
    metrics = json.loads((target / "metrics.json").read_text())
    quality = json.loads((target / "data-quality.json").read_text())
    assert manifest["schema"] == "morning-atlas-weekly"
    assert metrics["attendance"]["attendance_percent"] == 100.0
    assert metrics["machine_activity"]["event_count"] == 1
    assert metrics["brothers_keeper"]["contribution_count"] == 1
    assert quality["machine_state_evidence"]["availability_metrics_supported"] is False
    assert "Communication and teamwork" in (target / "brothers-keeper.jsonl").read_text()
    assert "STC 14" in (target / "machine-events.jsonl").read_text()
    root = json.loads((tmp_path / "manifest.json").read_text())
    assert root["latest"]["reporting_week"] == "2026-W37"


def test_export_if_changed_is_idempotent_and_detects_source_change(tmp_path):
    store = FakeStore((sample_report(),))
    exporter = WeeklyAtlasExporter(store, tmp_path)
    first = exporter.export_if_changed(date(2026, 9, 7))
    second = exporter.export_if_changed(date(2026, 9, 7))
    assert first is not None and first.changed is True
    assert second is not None and second.changed is False
    store.reports = (replace(sample_report(), updated_at="2026-09-10T15:00:00+02:00"),)
    third = exporter.export_if_changed(date(2026, 9, 7))
    assert third is not None and third.changed is True
    assert third.source_fingerprint != first.source_fingerprint


def test_scheduler_waits_until_monday_0430_for_new_completed_week():
    before = datetime.fromisoformat("2026-09-14T04:29:00+02:00")
    after = datetime.fromisoformat("2026-09-14T04:30:00+02:00")
    assert latest_exportable_week_start(before) == date(2026, 8, 31)
    assert latest_exportable_week_start(after) == date(2026, 9, 7)
    assert completed_week_starts(after, count=2) == (date(2026, 9, 7), date(2026, 8, 31))
