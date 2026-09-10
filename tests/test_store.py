from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from morning.db import create_database_engine
from morning.models import AttendanceEntry, CardObservation, ControlRoomObservation, MachineEvent, MachineStateDeclaration, OtherActivity, StopFixRecord
from morning.store import InvalidTransitionError, MorningError, MorningStore, UnknownRecordError, new_id


def _alembic_config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["MORNING_DATABASE_URL"])
    return config


@pytest.fixture(scope="module", autouse=True)
def schema() -> None:
    if "MORNING_DATABASE_URL" not in os.environ:
        pytest.skip("MORNING_DATABASE_URL is required for store tests")
    command.upgrade(_alembic_config(), "head")


@pytest.fixture()
def store() -> MorningStore:
    database_url = os.environ["MORNING_DATABASE_URL"]
    engine = create_database_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE morning_construction_levels, morning_construction_workstreams, morning_principals, morning_crews, morning_machines CASCADE"))
        connection.execute(text("DELETE FROM morning_shift_policy"))
    engine.dispose()
    return MorningStore(database_url)


def _principal(store: MorningStore, principal_id: str = "p1", role: str = "supervisor") -> str:
    store.create_principal(principal_id=principal_id, display_name=principal_id, role=role)
    return principal_id


def _draft(
    store: MorningStore,
    *,
    principal_id: str = "p1",
    shift_date: str = "2026-03-25",
    shift_kind: str = "morning",
    crew_id: str | None = None,
):
    if store.principal_by_id(principal_id) is None:
        _principal(store, principal_id)
    return store.get_or_create_draft(
        supervisor_principal_id=principal_id,
        shift_date=shift_date,
        shift_kind=shift_kind,
        crew_id=crew_id,
    )


def test_shift_policy_round_trips(store: MorningStore) -> None:
    assert store.get_shift_policy() is None
    saved = store.set_shift_policy(
        timezone="Africa/Johannesburg",
        morning_shift_start="06:00",
        afternoon_shift_start="14:00",
        night_shift_start="22:00",
    )
    assert saved.timezone == "Africa/Johannesburg"
    assert store.get_shift_policy().morning_shift_start == "06:00"
    assert store.get_shift_policy().afternoon_shift_start == "14:00"
    assert store.get_shift_policy().night_shift_start == "22:00"


def test_machine_identity_deactivate_and_control_room_scope(store: MorningStore) -> None:
    machine = store.create_machine(machine_id="RLH1", machine_type="LHD", section="Section 4")
    assert machine.active is True
    scoped = store.set_machine_control_room_scope(machine.id, in_scope=True)
    assert scoped.control_room_scope is True
    retired = store.set_machine_active(machine.id, active=False)
    assert retired.active is False
    assert retired.retired_at is not None
    assert retired.control_room_scope is True
    assert store.get_machine(machine.id).machine_id == "RLH1"


def test_duplicate_machine_id_is_rejected(store: MorningStore) -> None:
    store.create_machine(machine_id="RLH1", machine_type=None, section=None)
    with pytest.raises(MorningError, match="already exists"):
        store.create_machine(machine_id="RLH1", machine_type=None, section=None)


def test_roster_is_scoped_to_active_members_of_one_crew(store: MorningStore) -> None:
    crew_a = store.create_crew(name="Crew A")
    crew_b = store.create_crew(name="Crew B")
    lyle = store.create_person(name="Lyle", employee_number="E1", role="Supervisor", crew_id=crew_a.id)
    jurie = store.create_person(name="Jurie", employee_number="E2", role="Supervisor", crew_id=crew_b.id)
    inactive = store.create_person(name="Retired", employee_number="E3", role="Artisan", crew_id=crew_a.id)
    store.set_person_active(inactive.id, active=False)
    assert [person.id for person in store.roster_for_crew(crew_a.id)] == [lyle.id]
    assert [person.id for person in store.roster_for_crew(crew_b.id)] == [jurie.id]


def test_persons_by_ids_resolves_only_requested_history(store: MorningStore) -> None:
    crew = store.create_crew(name="Crew A")
    lyle = store.create_person(name="Lyle", employee_number=None, role="Supervisor", crew_id=crew.id)
    jan = store.create_person(name="Jan", employee_number=None, role="Artisan", crew_id=crew.id)
    store.create_person(name="Piet", employee_number=None, role="Artisan", crew_id=crew.id)
    assert {person.name for person in store.persons_by_ids((lyle.id, jan.id))} == {"Lyle", "Jan"}
    assert store.persons_by_ids(()) == ()


def test_account_approval_linking_and_casefolded_username(store: MorningStore) -> None:
    _principal(store, "p1")
    crew = store.create_crew(name="Crew A")
    person = store.create_person(name="Lyle", employee_number=None, role="Supervisor", crew_id=crew.id)
    store.create_account(principal_id="p1", username="Lyle", password_hash="h", password_salt="s")
    assert store.account_by_username("LYLE")["principal_id"] == "p1"
    assert store.account_by_principal("p1")["approved_at"] is None
    linked = store.link_account_person("p1", person.id)
    assert linked["person_id"] == person.id
    approved = store.approve_account("p1")
    assert approved["approved_at"] is not None
    assert store.list_accounts(pending_only=True) == ()


def test_account_requires_existing_principal(store: MorningStore) -> None:
    with pytest.raises(UnknownRecordError):
        store.create_account(principal_id="missing", username="x", password_hash="h", password_salt="s")


def test_draft_is_idempotent_and_snapshots_crew(store: MorningStore) -> None:
    _principal(store, "p1")
    crew_a = store.create_crew(name="Crew A")
    crew_b = store.create_crew(name="Crew B")
    first = store.get_or_create_draft(
        supervisor_principal_id="p1", shift_date="2026-03-25", shift_kind="morning", crew_id=crew_a.id
    )
    resumed = store.get_or_create_draft(
        supervisor_principal_id="p1", shift_date="2026-03-25", shift_kind="morning", crew_id=crew_b.id
    )
    assert resumed.id == first.id
    assert resumed.crew_id == crew_a.id


def test_abandon_frees_slot_without_deleting_old_entries(store: MorningStore) -> None:
    draft = _draft(store)
    store.add_other_activity(draft.id, OtherActivity(id="activity-1", category=None, description="old work"))
    abandoned = store.abandon_report(draft.id)
    assert abandoned.status == "abandoned"
    fresh = store.get_or_create_draft(
        supervisor_principal_id="p1", shift_date="2026-03-25", shift_kind="morning", crew_id=None
    )
    assert fresh.id != draft.id
    assert fresh.other_activities == ()
    assert store.get_report(draft.id).other_activities[0].description == "old work"


def test_submit_freezes_report_mutations(store: MorningStore) -> None:
    crew = store.create_crew(name="Submission Crew")
    person = store.create_person(name="Reporter", employee_number=None, role="Supervisor", crew_id=crew.id)
    draft = _draft(store, crew_id=crew.id)
    store.replace_attendance(draft.id, (AttendanceEntry(person.id, True),))
    store.set_brothers_keeper(draft.id, "Improve workshop access lighting.")
    store.set_empty_section_reviewed(draft.id, "safety", True)
    store.set_empty_section_reviewed(draft.id, "machine_activity", True)
    store.set_empty_section_reviewed(draft.id, "other_activities", True)
    submitted = store.submit_report(draft.id)
    assert submitted.status == "submitted"
    assert submitted.submitted_at is not None
    with pytest.raises(InvalidTransitionError):
        store.replace_attendance(draft.id, ())
    with pytest.raises(InvalidTransitionError):
        store.submit_report(draft.id)


def test_attendance_safety_cards_and_other_activity_round_trip(store: MorningStore) -> None:
    draft = _draft(store)
    person = store.create_person(name="Artisan", employee_number="E1", role="Artisan", crew_id=None)
    updated = store.replace_attendance(draft.id, (AttendanceEntry(person.id, True),))
    assert updated.attendance[0].present is True

    stop = StopFixRecord(
        id=new_id("stopfix"),
        number="SF-001",
        issued_at="2026-03-25T08:00:00+02:00",
        area_of_concern="Support",
        location="STC14",
        reason="Loose hanging wall",
        instruction="Barr down and support",
        status="open",
    )
    updated = store.add_stop_fix(draft.id, stop)
    assert updated.stop_fix[0].number == "SF-001"
    updated = store.add_card(draft.id, CardObservation(id=new_id("card"), card_type="green", reason="Good housekeeping"))
    assert updated.cards[0].card_type == "green"
    updated = store.add_other_activity(
        draft.id,
        OtherActivity(id=new_id("activity"), category="housekeeping", description="Cleaned workshop"),
    )
    assert updated.other_activities[0].description == "Cleaned workshop"


def test_machine_events_require_real_machine_and_round_trip(store: MorningStore) -> None:
    draft = _draft(store, shift_kind="night")
    machine = store.create_machine(machine_id="RLH1", machine_type="LHD", section=None)
    event = MachineEvent(
        id=new_id("event"),
        machine_id=machine.id,
        start_time="2026-03-25T22:00:00+02:00",
        end_time="2026-03-25T22:40:00+02:00",
        issue="hydraulic hose",
    )
    updated = store.add_machine_event(draft.id, event)
    assert updated.machine_events[0].machine_id == machine.id
    corrected = MachineEvent(**{**event.__dict__, "issue": "hydraulic hose - corrected"})
    updated = store.update_machine_event(draft.id, corrected)
    assert updated.machine_events[0].issue == "hydraulic hose - corrected"


def test_machine_state_preserves_declared_vs_carried_provenance(store: MorningStore) -> None:
    draft = _draft(store)
    machine = store.create_machine(machine_id="RLH1", machine_type="LHD", section=None)
    declared = store.add_machine_state(
        MachineStateDeclaration(
            id="state-1",
            machine_id=machine.id,
            report_id=draft.id,
            declared_at="2026-03-25T17:55:00+02:00",
            state="not_tested",
            provenance="declared",
            follow_up="Test next shift",
        )
    )
    carried = store.add_machine_state(
        MachineStateDeclaration(
            id="state-2",
            machine_id=machine.id,
            report_id=draft.id,
            declared_at="2026-03-25T18:00:00+02:00",
            state="not_tested",
            provenance="carried",
            source_state_id=declared.id,
            follow_up="Awaiting test",
        )
    )
    assert carried.provenance == "carried"
    assert carried.source_state_id == declared.id
    assert store.latest_machine_state(machine.id).id == carried.id


def test_control_room_observations_scope_to_reporting_date(store: MorningStore) -> None:
    observation = ControlRoomObservation(
        id=new_id("cro"),
        reporting_date="2026-03-25",
        machine_id=None,
        raw_machine_label="RLH1",
        start_time="2026-03-25T22:00:00+02:00",
        end_time="2026-03-25T23:00:00+02:00",
        description="Hydraulic failure per control room",
        source_message_id="msg-1",
        source_artifact_id=None,
        extracted_at="",
    )
    saved = store.add_observation(observation)
    assert saved.extracted_at
    assert len(store.list_observations(reporting_date="2026-03-25")) == 1
    assert store.list_observations(reporting_date="2026-03-26") == ()


def test_unknown_report_raises(store: MorningStore) -> None:
    with pytest.raises(UnknownRecordError):
        store.get_report("shiftreport_does_not_exist")


def test_brothers_keeper_round_trip_and_delete_history_protection(store: MorningStore) -> None:
    crew = store.create_crew(name="BK Crew")
    person = store.create_person(name="BK Artisan", employee_number="BK1", role="Fitter", crew_id=crew.id)
    machine = store.create_machine(machine_id="BK-RLH", machine_type="LHD", section=None)
    report = _draft(store, crew_id=crew.id)
    updated = store.set_brothers_keeper(report.id, "Repair the damaged pedestrian barrier.")
    assert updated.brothers_keeper == "Repair the damaged pedestrian barrier."
    store.replace_attendance(report.id, (AttendanceEntry(person.id, True),))
    store.add_machine_event(report.id, MachineEvent(id=new_id("event"), machine_id=machine.id, start_time="2026-03-25T08:00:00+02:00", end_time="2026-03-25T08:20:00+02:00", issue="Inspection", person_id=person.id))
    with pytest.raises(MorningError, match="operational history"):
        store.delete_person(person.id)
    with pytest.raises(MorningError, match="operational history"):
        store.delete_machine(machine.id)


def test_direct_messages_are_private_and_announcements_are_separate(store: MorningStore) -> None:
    for principal_id, name in (("s1", "Supervisor One"), ("s2", "Supervisor Two"), ("s3", "Supervisor Three")):
        store.create_principal(principal_id=principal_id, display_name=name, role="supervisor")
        store.create_account(principal_id=principal_id, username=principal_id, password_hash="h", password_salt="s")
        store.approve_account(principal_id)
    direct = store.create_message(sender_principal_id="s1", recipient_principal_id="s2", kind="direct", body="Private handover")
    store.create_message(sender_principal_id="s1", kind="announcement", body="General notice")
    assert [item["body"] for item in store.list_direct_messages("s2")] == ["Private handover"]
    assert store.list_direct_messages("s3") == ()
    assert [item["body"] for item in store.list_announcements()] == ["General notice"]
    read = store.mark_message_read(direct["id"], "s2")
    assert read["read_at"] is not None
