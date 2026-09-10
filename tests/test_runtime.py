from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from morning.accounts import MorningAccounts
from morning.db import create_database_engine
from morning.models import AttendanceEntry
from morning.runtime import MorningRuntime
from morning.store import IncompleteReportError, InvalidTransitionError, MorningError, MorningStore

TZ = "Africa/Johannesburg"
ZONE = ZoneInfo(TZ)


def _config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["MORNING_DATABASE_URL"])
    return config


@pytest.fixture(scope="module", autouse=True)
def schema() -> None:
    if "MORNING_DATABASE_URL" not in os.environ:
        pytest.skip("MORNING_DATABASE_URL is required for runtime tests")
    command.upgrade(_config(), "head")


@pytest.fixture()
def runtime() -> tuple[MorningRuntime, MorningStore, object]:
    database_url = os.environ["MORNING_DATABASE_URL"]
    engine = create_database_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE morning_construction_levels, morning_construction_workstreams, morning_principals, morning_crews, morning_machines CASCADE"))
        connection.execute(text("DELETE FROM morning_shift_policy"))
    engine.dispose()
    store = MorningStore(database_url)
    store.set_shift_policy(timezone=TZ, morning_shift_start="06:00", afternoon_shift_start="14:00", night_shift_start="22:00")
    accounts = MorningAccounts(store)
    supervisor = accounts.register(username="jurie", password="correct-horse", display_name="Jurie Venter")
    return MorningRuntime(store, accounts, clock=lambda: datetime(2026, 3, 25, 23, 0, tzinfo=ZONE)), store, supervisor


def test_shift_draft_roster_and_submission_semantics(runtime) -> None:
    app, store, supervisor = runtime
    assert app.current_shift().shift_kind == "night"
    assert app.default_reporting_date() == "2026-03-24"
    crew = store.create_crew(name="Crew A")
    person = store.create_person(name="Jurie", employee_number=None, role="Supervisor", crew_id=crew.id)
    store.link_account_person(supervisor.principal_id, person.id)
    first = app.start_draft(supervisor.principal_id, shift_date="2026-03-25", shift_kind="night", crew_ids=(crew.id,))
    second = app.start_draft(supervisor.principal_id, shift_date="2026-03-25", shift_kind="night", crew_ids=(crew.id,))
    assert first.id == second.id
    assert first.crew_id == crew.id
    app.set_attendance(first.id, (AttendanceEntry(person.id, True),))
    app.set_brothers_keeper(first.id, "Improve workshop access lighting.")
    app.set_empty_section_reviewed(first.id, section="safety", reviewed=True)
    app.set_empty_section_reviewed(first.id, section="machine_activity", reviewed=True)
    app.set_empty_section_reviewed(first.id, section="other_activities", reviewed=True)
    submitted = app.submit_report(first.id)
    assert submitted.status == "submitted"
    with pytest.raises(InvalidTransitionError):
        app.add_other_activity(first.id, category=None, description="too late")


def test_machine_event_round_trip_keeps_operational_wall_clock_for_edits(runtime) -> None:
    app, store, supervisor = runtime
    crew = store.create_crew(name="Crew A")
    person = store.create_person(name="Jurie", employee_number=None, role="Supervisor", crew_id=crew.id)
    store.link_account_person(supervisor.principal_id, person.id)
    report = app.start_draft(supervisor.principal_id, shift_date="2026-03-25", shift_kind="night", crew_ids=(crew.id,))
    machine = store.create_machine(machine_id="RLH1", machine_type="LHD", section=None)
    updated = app.add_machine_event(
        report.id,
        machine_id=machine.id,
        start_hhmm="22:00",
        end_hhmm="22:40",
        issue="hydraulic hose",
        person_id=person.id,
    )
    event = updated.machine_events[0]
    corrected = app.update_machine_event(report.id, event.id, end_hhmm="22:45", issue="corrected")
    end = datetime.fromisoformat(corrected.machine_events[0].end_time).astimezone(ZONE)
    assert end.strftime("%H:%M") == "22:45"


def test_machine_state_is_explicit_and_carry_keeps_provenance(runtime) -> None:
    app, store, supervisor = runtime
    crew = store.create_crew(name="Crew A")
    first = app.start_draft(supervisor.principal_id, shift_date="2026-03-25", shift_kind="morning", crew_ids=(crew.id,))
    machine = store.create_machine(machine_id="RLH1", machine_type="LHD", section=None)
    declared = app.declare_machine_state(
        first.id,
        machine_id=machine.id,
        declared_hhmm="17:55",
        state="not_tested",
        follow_up="Test next shift",
    )
    app.abandon_draft(first.id)
    second = app.start_draft(supervisor.principal_id, shift_date="2026-03-25", shift_kind="night", crew_ids=(crew.id,))
    carried = app.carry_machine_state(second.id, machine_id=machine.id, declared_hhmm="18:00")
    assert carried.provenance == "carried"
    assert carried.source_state_id == declared.id
    assert carried.state == "not_tested"


def test_other_machine_state_requires_note(runtime) -> None:
    app, store, supervisor = runtime
    crew = store.create_crew(name="Crew A")
    report = app.start_draft(supervisor.principal_id, shift_date="2026-03-25", shift_kind="night", crew_ids=(crew.id,))
    machine = store.create_machine(machine_id="RLH1", machine_type=None, section=None)
    with pytest.raises(MorningError, match="explanatory note"):
        app.declare_machine_state(
            report.id,
            machine_id=machine.id,
            declared_hhmm="22:00",
            state="other",
        )


def test_whatsapp_output_includes_explicit_handover_state(runtime) -> None:
    app, store, supervisor = runtime
    crew = store.create_crew(name="Crew A")
    person = store.create_person(name="Jurie", employee_number=None, role="Supervisor", crew_id=crew.id)
    store.link_account_person(supervisor.principal_id, person.id)
    report = app.start_draft(supervisor.principal_id, shift_date="2026-03-25", shift_kind="night", crew_ids=(crew.id,))
    machine = store.create_machine(machine_id="RLH1", machine_type=None, section=None)
    app.add_machine_event(
        report.id,
        machine_id=machine.id,
        start_hhmm="22:00",
        end_hhmm="22:40",
        issue="hydraulic hose",
        person_id=person.id,
    )
    app.add_machine_event(
        report.id,
        machine_id=machine.id,
        start_hhmm="23:00",
        end_hhmm="23:10",
        issue="inspection",
        person_id=person.id,
    )
    app.declare_machine_state(
        report.id,
        machine_id=machine.id,
        declared_hhmm="22:40",
        state="not_tested",
    )
    text_output = app.whatsapp_text(report.id)
    assert "*RLH1 — Total downtime: 50m*" in text_output
    assert "*22:00-22:40 (40m)*\nhydraulic hose · Assigned: Jurie" in text_output
    assert "*23:00-23:10 (10m)*\ninspection · Assigned: Jurie" in text_output
    assert "Machine State at Handover" in text_output
    assert "Not tested" in text_output


def test_whatsapp_consolidates_machine_events_without_double_counting_overlap(runtime) -> None:
    app, store, supervisor = runtime
    crew = store.create_crew(name="Crew A")
    person = store.create_person(name="Jurie", employee_number=None, role="Supervisor", crew_id=crew.id)
    store.link_account_person(supervisor.principal_id, person.id)
    report = app.start_draft(supervisor.principal_id, shift_date="2026-03-25", shift_kind="night", crew_ids=(crew.id,))
    machine = store.create_machine(machine_id="STC 09", machine_type="Scissor", section=None)
    app.add_machine_event(report.id, machine_id=machine.id, start_hhmm="22:45", end_hhmm="22:55", issue="battery", person_id=person.id)
    app.add_machine_event(report.id, machine_id=machine.id, start_hhmm="23:00", end_hhmm="01:10", issue="recover", person_id=person.id)
    app.add_machine_event(report.id, machine_id=machine.id, start_hhmm="00:30", end_hhmm="01:10", issue="steering", person_id=person.id)

    text_output = app.whatsapp_text(report.id)
    assert text_output.count("*STC 09 — Total downtime: 2h 20m*") == 1
    assert "*00:30-01:10 (40m, within above downtime)*" in text_output
    assert text_output.index("22:45-22:55") < text_output.index("23:00-01:10") < text_output.index("00:30-01:10")


def test_submission_reports_every_unresolved_section(runtime) -> None:
    app, store, supervisor = runtime
    crew = store.create_crew(name="Crew A")
    person = store.create_person(name="Jurie", employee_number=None, role="Supervisor", crew_id=crew.id)
    store.link_account_person(supervisor.principal_id, person.id)
    report = app.start_draft(supervisor.principal_id, shift_date="2026-03-25", shift_kind="morning", crew_ids=(crew.id,))
    with pytest.raises(IncompleteReportError) as raised:
        app.submit_report(report.id)
    assert raised.value.missing_sections == ("attendance", "safety", "brothers_keeper", "machine_activity", "other_activities")


def test_machine_assignee_can_be_any_active_tmm_person(runtime) -> None:
    app, store, supervisor = runtime
    crew = store.create_crew(name="Crew A")
    other_crew = store.create_crew(name="Crew B")
    supervisor_person = store.create_person(name="Jurie", employee_number=None, role="Supervisor", crew_id=crew.id)
    assisting_artisan = store.create_person(name="Assisting artisan", employee_number=None, role="Fitter", crew_id=other_crew.id)
    store.link_account_person(supervisor.principal_id, supervisor_person.id)
    report = app.start_draft(supervisor.principal_id, shift_date="2026-03-25", shift_kind="morning", crew_ids=(crew.id,))
    machine = store.create_machine(machine_id="RLH1", machine_type="LHD", section=None)
    updated = app.add_machine_event(report.id, machine_id=machine.id, start_hhmm="08:00", end_hhmm="09:00", issue="repair", person_id=assisting_artisan.id)
    assert updated.machine_events[0].person_id == assisting_artisan.id
    store.set_person_active(assisting_artisan.id, active=False)
    with pytest.raises(MorningError, match="active person registered under TMM"):
        app.add_machine_event(report.id, machine_id=machine.id, start_hhmm="09:15", end_hhmm="09:30", issue="follow-up", person_id=assisting_artisan.id)

def test_construction_report_coexists_with_tmm_and_renders_workfront(runtime) -> None:
    app, store, supervisor = runtime
    workstream = store.create_construction_workstream(name="Main Construction")
    crew = store.create_construction_crew(name="Construction Crew 1", workstream_id=workstream["id"])
    person = store.create_person(name="Jurie", employee_number=None, role="Supervisor", crew_id=crew["crew_id"])
    store.link_account_person(supervisor.principal_id, person.id)
    tmm_crew = store.create_crew(name="TMM Crew")
    tmm = app.start_draft(supervisor.principal_id, shift_date="2026-03-25", shift_kind="night", reporting_model="tmm", crew_ids=(tmm_crew.id,))
    construction = app.start_draft(
        supervisor.principal_id, shift_date="2026-03-25", shift_kind="night", reporting_model="construction"
    )
    assert tmm.id != construction.id
    assert construction.reporting_model == "construction"

    updated = app.add_construction_work(
        construction.id,
        kind="core",
        level="8 1 3",
        location="South Cells",
        task="Legal inspections",
        status="in_progress",
        progress_percent=60,
        update_text="Cells 1 to 6 inspected",
        constraint_text="Awaiting access to Cell 7",
        next_action="Complete remaining cells",
    )
    item = updated.construction_work[0]
    assert item.level == "813"
    assert item.location == "South Cells"
    output = app.whatsapp_text(construction.id)
    assert "Core Work" in output
    assert "Crew: Construction Crew 1" in output
    assert "Workstream: Main Construction" in output
    assert "813L · South Cells — Legal inspections" in output
    assert "60%" in output
    assert "Machine Activity" not in output


def test_construction_requires_active_construction_crew(runtime) -> None:
    app, store, supervisor = runtime
    crew = store.create_crew(name="TMM Crew")
    person = store.create_person(name="Jurie", employee_number=None, role="Supervisor", crew_id=crew.id)
    store.link_account_person(supervisor.principal_id, person.id)
    with pytest.raises(MorningError, match="active Construction crew"):
        app.start_draft(supervisor.principal_id, shift_date="2026-03-25", shift_kind="morning", reporting_model="construction")


def test_construction_configuration_round_trip(runtime) -> None:
    _app, store, _supervisor = runtime
    level = store.create_construction_level(level="8 1 3")
    stream = store.create_construction_workstream(name="C-Cut")
    crew = store.create_construction_crew(name="C-Cut Crew", workstream_id=stream["id"])
    assert [item["level"] for item in store.list_construction_levels(active_only=True)] == ["813"]
    assert store.get_construction_crew(crew["crew_id"])["workstream_name"] == "C-Cut"
    store.set_construction_level_active(level["id"], active=False)
    assert store.list_construction_levels(active_only=True) == ()


def test_construction_levels_accept_north_and_south_suffixes(runtime) -> None:
    app, store, supervisor = runtime
    north = store.create_construction_level(level="8 1 3 n")
    south = store.create_construction_level(level="813S")
    assert north["level"] == "813N"
    assert south["level"] == "813S"
    assert [item["level"] for item in store.list_construction_levels(active_only=True)] == ["813N", "813S"]

    stream = store.create_construction_workstream(name="Main Construction")
    crew = store.create_construction_crew(name="Construction Crew", workstream_id=stream["id"])
    person = store.create_person(name="Jurie", employee_number=None, role="Supervisor", crew_id=crew["crew_id"])
    store.link_account_person(supervisor.principal_id, person.id)
    report = app.start_draft(supervisor.principal_id, shift_date="2026-03-26", shift_kind="morning", reporting_model="construction")
    report = app.add_construction_work(
        report.id, kind="core", level="8 1 3 n", location="T97", task="Legal inspection",
        status="in_progress", progress_percent=None, update_text="Started", constraint_text=None, next_action=None,
    )
    assert report.construction_work[0].level == "813N"
    assert "813L North · T97 — Legal inspection" in app.whatsapp_text(report.id)


def test_construction_offline_snapshot_sync(runtime) -> None:
    app, store, supervisor = runtime
    stream = store.create_construction_workstream(name="C-Cut")
    crew = store.create_construction_crew(name="Construction Crew", workstream_id=stream["id"])
    person = store.create_person(name="Jurie", employee_number=None, role="Supervisor", crew_id=crew["crew_id"])
    store.link_account_person(supervisor.principal_id, person.id)
    snapshot = {
        "shift_date": "2026-03-25", "shift_kind": "night", "reporting_model": "construction",
        "attendance": [{"person_id": person.id, "present": True}],
        "stop_fix": [], "cards": [], "machine_events": [], "other_activities": [],
        "construction_work": [{
            "id": "offline-construction-1", "kind": "core", "level": "813s", "location": "T97",
            "task": "Install steel", "status": "in_progress", "progress_percent": 50,
            "update_text": "Half complete", "constraint_text": None, "next_action": "Complete installation",
        }],
        "safety_reviewed_empty": True, "machine_activity_reviewed_empty": False,
        "other_activities_reviewed_empty": False, "construction_work_reviewed_empty": False,
        "construction_outstanding_reviewed_empty": True,
    }
    synced = app.sync_offline_snapshot(supervisor.principal_id, snapshot, submit=True)
    assert synced.status == "submitted"
    assert synced.construction_work[0].level == "813S"
    assert synced.construction_work[0].location == "T97"
    assert "813L South · T97" in app.whatsapp_text(synced.id)
