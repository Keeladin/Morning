from __future__ import annotations

from morning.aggregate import aggregate_machines, build_report_bundle
from morning.models import ControlRoomObservation, Machine, MachineEvent, MachineStateDeclaration, ShiftReport
from morning.renderers import render_compact_report, render_detailed_report


def _machine() -> Machine:
    return Machine(id="machine-1", machine_id="RLH1", machine_type="LHD", section=None, active=True, created_at="now")


def _report(*events: MachineEvent, shift_kind: str = "night") -> ShiftReport:
    return ShiftReport(
        id=f"report-{shift_kind}",
        shift_date="2026-03-25",
        shift_kind=shift_kind,
        supervisor_principal_id="p1",
        crew_id=None,
        reporting_model="tmm",
        status="submitted",
        attendance=(),
        stop_fix=(),
        cards=(),
        machine_events=events,
        construction_work=(),
        other_activities=(),
        created_at="now",
        updated_at="now",
        submitted_at="now",
    )


def test_supervisor_work_interval_is_not_named_or_mixed_as_downtime() -> None:
    machine = _machine()
    event = MachineEvent(
        "event-1",
        machine.id,
        "2026-03-25T20:00:00+00:00",
        "2026-03-25T21:00:00+00:00",
        "hydraulic hose",
    )
    control_room = ControlRoomObservation(
        id="cro-1",
        reporting_date="2026-03-25",
        machine_id=machine.id,
        raw_machine_label="RLH1",
        start_time="2026-03-25T20:30:00+00:00",
        end_time="2026-03-25T22:00:00+00:00",
        description="Machine unavailable per control room",
        source_message_id="msg-1",
        source_artifact_id=None,
        extracted_at="now",
    )
    aggregate = aggregate_machines(
        machines_by_id={machine.id: machine},
        shift_reports=(_report(event),),
        observations=(control_room,),
    )[0]
    assert aggregate.total_work_interval_seconds == 3600
    assert aggregate.work_event_count == 1
    assert aggregate.event_count == 2


def test_report_renderer_uses_explicit_state_and_never_calls_work_time_downtime() -> None:
    machine = _machine()
    event = MachineEvent(
        "event-1",
        machine.id,
        "2026-03-25T20:00:00+00:00",
        "2026-03-25T21:00:00+00:00",
        "hydraulic hose",
    )
    state = MachineStateDeclaration(
        id="state-1",
        machine_id=machine.id,
        report_id="report-night",
        declared_at="2026-03-25T21:00:00+00:00",
        state="not_tested",
        provenance="declared",
    )
    bundle = build_report_bundle(
        reporting_date="2026-03-25",
        timezone="Africa/Johannesburg",
        shift_reports=(_report(event),),
        observations=(),
        machine_states=(state,),
        machines_by_id={machine.id: machine},
        persons_by_id={},
        require_control_room=False,
    )
    detailed = render_detailed_report(bundle)
    compact = render_compact_report(bundle)
    assert "Engineering work time recorded: 1h" in detailed
    assert "Reported state: Not tested" in detailed
    assert "state Not tested" in compact
    assert "downtime" not in detailed.casefold()
    assert "downtime" not in compact.casefold()


def test_expected_inputs_still_drive_waiting_vs_complete() -> None:
    morning = _report(shift_kind="morning")
    bundle = build_report_bundle(
        reporting_date="2026-03-25",
        timezone="Africa/Johannesburg",
        shift_reports=(morning,),
        observations=(),
        machine_states=(),
        machines_by_id={},
        persons_by_id={},
        require_control_room=True,
    )
    assert bundle.status == "waiting"
    assert {item.key for item in bundle.expected_inputs if not item.present} == {"afternoon_shift_report", "night_shift_report", "control_room_report"}
