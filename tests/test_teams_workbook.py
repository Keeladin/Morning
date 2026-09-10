from __future__ import annotations

from morning.aggregate import AttendanceSummary, MachineAggregate, ReportBundle, SafetySummary
from morning.models import ExpectedInputStatus, StopFixRecord
from morning.teams_workbook import render_teams_workbook_projection


def _bundle(*, work_seconds: float, delay_seconds: float) -> ReportBundle:
    aggregate = MachineAggregate(
        machine_internal_id="machine-stc14",
        machine_display_id="STC14",
        matched=True,
        total_work_interval_seconds=work_seconds,
        total_control_room_delay_seconds=delay_seconds,
        work_event_count=1 if work_seconds else 0,
        control_room_event_count=1 if delay_seconds else 0,
        event_count=(1 if work_seconds else 0) + (1 if delay_seconds else 0),
        key_issues=("Brake repair",),
        events=(),
    )
    stop_fix = StopFixRecord(
        id="sf-1",
        number="123",
        issued_at="2026-08-28T07:00:00+02:00",
        area_of_concern="Transport and Tramming",
        location="Workshop",
        reason="Unsafe condition",
        instruction="Rectify",
        status="open",
    )
    return ReportBundle(
        reporting_date="2026-08-28",
        timezone="Africa/Johannesburg",
        shift_reports=(),
        observations=(),
        machine_states=(),
        machine_aggregates=(aggregate,),
        attendance=AttendanceSummary(present_count=0, absent_count=0, absent_names=()),
        safety=SafetySummary(
            stop_fix_open=1,
            stop_fix_rectified=0,
            green_cards=1,
            red_cards=0,
            card_reasons=(("green", "Good lockout practice"),),
            stop_fix_records=(stop_fix,),
        ),
        other_activities=(),
        expected_inputs=(ExpectedInputStatus(key="morning_shift_report", label="Morning shift report", present=True),),
        status="complete",
    )


def _cell_map(bundle: ReportBundle) -> dict[str, str]:
    projection = render_teams_workbook_projection(bundle)
    return {item.cell: item.value for item in projection.machine_cells}


def test_engineering_work_interval_is_not_written_as_production_delay_duration() -> None:
    cells = _cell_map(_bundle(work_seconds=7200, delay_seconds=0))
    assert cells["J114"] == "Brake repair"
    assert "L114" not in cells


def test_control_room_delay_interval_is_written_to_duration_cell() -> None:
    cells = _cell_map(_bundle(work_seconds=7200, delay_seconds=3600))
    assert cells["L114"] == f"{3600 / 86400:.6f}"


def test_safety_projection_preserves_established_workbook_cells() -> None:
    projection = render_teams_workbook_projection(_bundle(work_seconds=0, delay_seconds=0))
    assert projection.stop_fix_cells[0].cell == "A36"
    assert "#123 Workshop Unsafe condition (Pending)" == projection.stop_fix_cells[0].value
    assert projection.engineering_hse_cell.cell == "A52"
    assert projection.engineering_hse_cell.value == "Engineering: 1x Green card - Good lockout practice"
