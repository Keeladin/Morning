from __future__ import annotations

import json
from datetime import datetime, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..auth import require_mutation_auth, require_session
from ..models import AttendanceEntry
from ..shift import ShiftError, require_zone
from ..store import IncompleteReportError, MorningError, UnknownRecordError


def _runtime(request: Request):
    return request.app.state.morning_runtime


def _error_status(exc: MorningError) -> int:
    return 404 if isinstance(exc, UnknownRecordError) else 400


def _report_owned_by(runtime, report_id: str, principal_id: str):
    report = runtime.get_report(report_id)
    if report.supervisor_principal_id != principal_id:
        raise UnknownRecordError(f"unknown shift report: {report_id}")
    return report


def _operational_now(runtime) -> str:
    zone = require_zone(runtime.shift_policy().timezone)
    return datetime.now(timezone.utc).astimezone(zone).isoformat()


async def get_shift(request: Request) -> JSONResponse:
    gate = require_session(request)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        return JSONResponse(_runtime(request).current_shift().as_dict())
    except (ShiftError, MorningError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


async def get_me(request: Request) -> JSONResponse:
    gate = require_session(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    principal = runtime.accounts.principal_for(gate.principal_id)
    crew_id = runtime.supervisor_crew_id(gate.principal_id)
    crew_name = None
    if crew_id is not None:
        try:
            crew_name = runtime.store.get_crew(crew_id).name
        except UnknownRecordError:
            crew_id = None
    return JSONResponse(
        {
            "principal_id": principal.principal_id,
            "display_name": principal.display_name,
            "role": principal.role,
            "crew_id": crew_id,
            "crew_name": crew_name,
        }
    )


async def list_active_machines(request: Request) -> JSONResponse:
    gate = require_session(request)
    if isinstance(gate, JSONResponse):
        return gate
    machines = _runtime(request).store.list_machines(active_only=True)
    return JSONResponse({"machines": [machine.as_dict() for machine in machines]})


async def list_tmm_personnel(request: Request) -> JSONResponse:
    gate = require_session(request)
    if isinstance(gate, JSONResponse):
        return gate
    people = _runtime(request).tmm_personnel()
    return JSONResponse({"people": [person.as_dict() for person in people]})


async def list_tmm_crews(request: Request) -> JSONResponse:
    gate = require_session(request)
    if isinstance(gate, JSONResponse):
        return gate
    crews = _runtime(request).store.list_tmm_crews()
    return JSONResponse({"crews": [crew.as_dict() for crew in crews]})


async def get_home(request: Request) -> JSONResponse:
    gate = require_session(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    principal = runtime.accounts.principal_for(gate.principal_id)
    if principal.demo_mode:
        return JSONResponse({"recent_reports": [], "announcements": [], "messages": [], "unread_count": 0, "supervisors": []})
    supervisors = runtime.store.list_tmm_supervisors(active_only=True)
    supervisor_ids = {item["principal_id"] for item in supervisors}
    if gate.principal_id not in supervisor_ids:
        return JSONResponse({"error": "TMM supervisor access is required"}, status_code=403)
    reports = []
    for report in runtime.store.list_recent_submitted_reports(reporting_model="tmm", limit=5):
        principal = runtime.store.principal_by_id(report.supervisor_principal_id) or {}
        reports.append({
            "id": report.id, "shift_date": report.shift_date, "shift_kind": report.shift_kind,
            "supervisor_name": principal.get("display_name") or report.supervisor_principal_id,
            "submitted_at": report.submitted_at, "brothers_keeper": report.brothers_keeper,
            "summary_text": runtime.whatsapp_text(report.id),
        })
    announcements = runtime.store.list_announcements(limit=10)
    messages = runtime.store.list_direct_messages(gate.principal_id, limit=30)
    unread = sum(1 for item in messages if item["recipient_principal_id"] == gate.principal_id and not item.get("read_at"))
    return JSONResponse({
        "recent_reports": reports, "announcements": list(announcements), "messages": list(messages),
        "unread_count": unread,
        "supervisors": [item for item in supervisors if item["principal_id"] != gate.principal_id],
    })


async def send_direct_message(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    if runtime.accounts.principal_for(gate.principal_id).demo_mode:
        return JSONResponse({"error": "Demo Mode cannot send production messages"}, status_code=403)
    try:
        body = await request.json() or {}
        recipient = str(body.get("recipient_principal_id") or "")
        allowed = {item["principal_id"] for item in runtime.store.list_tmm_supervisors(active_only=True)}
        if gate.principal_id not in allowed or recipient not in allowed:
            raise MorningError("direct messages can only be sent between active TMM supervisors")
        message = runtime.store.create_message(
            sender_principal_id=gate.principal_id, recipient_principal_id=recipient,
            kind="direct", body=str(body.get("body") or ""),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(message, status_code=201)


async def post_announcement(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    if runtime.accounts.principal_for(gate.principal_id).demo_mode:
        return JSONResponse({"error": "Demo Mode cannot send production messages"}, status_code=403)
    try:
        body = await request.json() or {}
        allowed = {item["principal_id"] for item in runtime.store.list_tmm_supervisors(active_only=True)}
        if gate.principal_id not in allowed:
            raise MorningError("only active TMM supervisors can post TMM notices")
        message = runtime.store.create_message(
            sender_principal_id=gate.principal_id, kind="announcement", body=str(body.get("body") or ""),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(message, status_code=201)


async def mark_direct_message_read(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        message = _runtime(request).store.mark_message_read(request.path_params["message_id"], gate.principal_id)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(message)


async def get_roster(request: Request) -> JSONResponse:
    gate = require_session(request)
    if isinstance(gate, JSONResponse):
        return gate
    report_id = request.query_params.get("report_id") or ""
    runtime = _runtime(request)
    if not report_id:
        return JSONResponse({"people": []})
    try:
        report = _report_owned_by(runtime, report_id, gate.principal_id)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    if report.status != "draft":
        return JSONResponse({"error": "roster is only available for an active draft"}, status_code=409)
    return JSONResponse({"people": [person.as_dict() for person in runtime.expected_attendance_for_report(report)]})


async def get_report_participants(request: Request) -> JSONResponse:
    gate = require_session(request)
    if isinstance(gate, JSONResponse):
        return gate
    report_id = request.path_params["report_id"]
    runtime = _runtime(request)
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        people = runtime.report_participants(report_id)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse({"people": [person.as_dict() for person in people]})


async def get_current_draft(request: Request) -> JSONResponse:
    gate = require_session(request)
    if isinstance(gate, JSONResponse):
        return gate
    reporting_model = request.query_params.get("reporting_model") or None
    report = _runtime(request).current_draft(gate.principal_id, reporting_model=reporting_model)
    return JSONResponse({"report": report.as_dict() if report else None})


async def start_draft(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        shift_date = str(body.get("shift_date") or "")
        shift_kind = str(body.get("shift_kind") or "")
        if len(shift_date) != 10:
            return JSONResponse({"error": "shift_date (YYYY-MM-DD) is required"}, status_code=400)
        reporting_model = str(body.get("reporting_model") or "tmm")
        runtime = _runtime(request)
        if runtime.accounts.principal_for(gate.principal_id).demo_mode:
            return JSONResponse({"error": "Demo Mode reports are local-only"}, status_code=403)
        crew_ids_raw = body.get("crew_ids") or []
        if not isinstance(crew_ids_raw, list):
            return JSONResponse({"error": "crew_ids must be a list"}, status_code=400)
        report = runtime.start_draft(
            gate.principal_id, shift_date=shift_date, shift_kind=shift_kind, reporting_model=reporting_model,
            crew_ids=tuple(str(item) for item in crew_ids_raw),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(report.as_dict(), status_code=201)


async def list_my_reports(request: Request) -> JSONResponse:
    gate = require_session(request)
    if isinstance(gate, JSONResponse):
        return gate
    reports = _runtime(request).my_reports(gate.principal_id)
    return JSONResponse({"reports": [report.as_dict() for report in reports]})


async def get_my_report(request: Request) -> JSONResponse:
    gate = require_session(request)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        report = _report_owned_by(_runtime(request), request.path_params["report_id"], gate.principal_id)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(report.as_dict())


async def set_attendance(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        body = await request.json()
        entries = tuple(
            AttendanceEntry(person_id=str(item["person_id"]), present=bool(item["present"]))
            for item in (body or {}).get("entries") or []
        )
        report = runtime.set_attendance(report_id, entries)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "entries must be a list of {person_id, present}"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(report.as_dict())


async def set_brothers_keeper(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        body = await request.json() or {}
        report = runtime.set_brothers_keeper(report_id, str(body.get("contribution") or ""))
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(report.as_dict())


async def add_stop_fix(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        body = await request.json() or {}
        report = runtime.add_stop_fix(
            report_id,
            number=str(body.get("number") or ""),
            issued_at=_operational_now(runtime),
            area_of_concern=str(body.get("area_of_concern") or ""),
            location=str(body.get("location") or ""),
            reason=str(body.get("reason") or ""),
            instruction=str(body.get("instruction") or ""),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(report.as_dict(), status_code=201)


async def update_stop_fix(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        body = await request.json() or {}
        fields = {
            key: str(body[key])
            for key in ("number", "area_of_concern", "location", "reason", "instruction")
            if key in body
        }
        if "status" in body:
            status = str(body["status"])
            fields["status"] = status
            fields["rectified_at"] = _operational_now(runtime) if status == "rectified" else None
        report = runtime.update_stop_fix(report_id, request.path_params["stop_fix_id"], **fields)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(report.as_dict())


async def delete_stop_fix(request: Request) -> JSONResponse:
    return await _delete_owned(request, "stop_fix_id", lambda runtime, report_id, item_id: runtime.delete_stop_fix(report_id, item_id))


async def add_card(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        body = await request.json() or {}
        report = runtime.add_card(
            report_id,
            card_type=str(body.get("card_type") or ""),
            reason=str(body.get("reason") or ""),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(report.as_dict(), status_code=201)


async def delete_card(request: Request) -> JSONResponse:
    return await _delete_owned(request, "card_id", lambda runtime, report_id, item_id: runtime.delete_card(report_id, item_id))


async def add_machine_event(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        body = await request.json() or {}
        report = runtime.add_machine_event(
            report_id,
            machine_id=str(body.get("machine_id") or ""),
            start_hhmm=str(body.get("start_hhmm") or ""),
            end_hhmm=str(body.get("end_hhmm") or ""),
            issue=str(body.get("issue") or ""),
            person_id=str(body.get("person_id") or ""),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except (MorningError, ShiftError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(report.as_dict(), status_code=201)


async def update_machine_event(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        body = await request.json() or {}
        report = runtime.update_machine_event(
            report_id,
            request.path_params["event_id"],
            machine_id=body.get("machine_id"),
            start_hhmm=body.get("start_hhmm"),
            end_hhmm=body.get("end_hhmm"),
            issue=body.get("issue"),
            person_id=body.get("person_id"),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except (MorningError, ShiftError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(report.as_dict())


async def delete_machine_event(request: Request) -> JSONResponse:
    return await _delete_owned(request, "event_id", lambda runtime, report_id, item_id: runtime.delete_machine_event(report_id, item_id))


async def add_machine_state(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        body = await request.json() or {}
        state = runtime.declare_machine_state(
            report_id,
            machine_id=str(body.get("machine_id") or ""),
            declared_hhmm=str(body.get("declared_hhmm") or ""),
            state=str(body.get("state") or ""),
            state_note=body.get("state_note"),
            follow_up=body.get("follow_up"),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except (MorningError, ShiftError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(state.as_dict(), status_code=201)


async def list_machine_states(request: Request) -> JSONResponse:
    gate = require_session(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        states = runtime.machine_states_for_report(report_id)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse({"states": [state.as_dict() for state in states]})


async def add_construction_work(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        body = await request.json() or {}
        raw_progress = body.get("progress_percent")
        progress = None if raw_progress in (None, "") else int(raw_progress)
        report = runtime.add_construction_work(
            report_id, kind=str(body.get("kind") or "core"), level=str(body.get("level") or ""),
            location=str(body.get("location") or ""), task=str(body.get("task") or ""),
            status=str(body.get("status") or "in_progress"), progress_percent=progress,
            update_text=str(body.get("update_text") or ""), constraint_text=body.get("constraint_text"),
            next_action=body.get("next_action"),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except (TypeError, ValueError):
        return JSONResponse({"error": "progress_percent must be an integer from 0 to 100"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(report.as_dict(), status_code=201)


async def update_construction_work(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        body = await request.json() or {}
        fields = {key: body[key] for key in ("kind", "level", "location", "task", "status", "update_text", "constraint_text", "next_action") if key in body}
        if "progress_percent" in body:
            fields["progress_percent"] = None if body["progress_percent"] in (None, "") else int(body["progress_percent"])
        report = runtime.update_construction_work(report_id, request.path_params["item_id"], **fields)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except (TypeError, ValueError):
        return JSONResponse({"error": "progress_percent must be an integer from 0 to 100"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(report.as_dict())


async def delete_construction_work(request: Request) -> JSONResponse:
    return await _delete_owned(
        request, "item_id", lambda runtime, report_id, item_id: runtime.delete_construction_work(report_id, item_id)
    )


async def add_other_activity(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        body = await request.json() or {}
        report = runtime.add_other_activity(
            report_id,
            category=body.get("category"),
            description=str(body.get("description") or ""),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(report.as_dict(), status_code=201)


async def delete_other_activity(request: Request) -> JSONResponse:
    return await _delete_owned(request, "activity_id", lambda runtime, report_id, item_id: runtime.delete_other_activity(report_id, item_id))


async def set_section_resolution(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        body = await request.json() or {}
        report = runtime.set_empty_section_reviewed(
            report_id, section=str(body.get("section") or ""), reviewed=bool(body.get("reviewed")),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(report.as_dict())


async def sync_offline_report(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    if runtime.accounts.principal_for(gate.principal_id).demo_mode:
        return JSONResponse({"error": "Demo Mode reports are never synchronized"}, status_code=403)
    try:
        body = await request.json() or {}
        snapshot = body.get("report")
        if not isinstance(snapshot, dict):
            return JSONResponse({"error": "report snapshot is required"}, status_code=400)
        report = _runtime(request).sync_offline_snapshot(
            gate.principal_id, snapshot, submit=bool(body.get("submit"))
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except IncompleteReportError as exc:
        return JSONResponse(
            {"error": "shift report has unresolved sections", "missing_sections": list(exc.missing_sections)},
            status_code=409,
        )
    except (MorningError, ShiftError, TypeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(report.as_dict())


async def submit_report(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        report = runtime.submit_report(report_id)
    except IncompleteReportError as exc:
        return JSONResponse(
            {"error": "shift report has unresolved sections", "missing_sections": list(exc.missing_sections)},
            status_code=409,
        )
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(report.as_dict())


async def abandon_report(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        report = runtime.abandon_draft(report_id)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(report.as_dict())


async def get_whatsapp_text(request: Request) -> JSONResponse:
    gate = require_session(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        output = runtime.whatsapp_text(report_id)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse({"text": output})


async def _delete_owned(request: Request, item_key: str, action) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    report_id = request.path_params["report_id"]
    try:
        _report_owned_by(runtime, report_id, gate.principal_id)
        report = action(runtime, report_id, request.path_params[item_key])
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(report.as_dict())


routes = [
    Route("/api/morning/shift", get_shift, methods=["GET"]),
    Route("/api/morning/me", get_me, methods=["GET"]),
    Route("/api/morning/machines", list_active_machines, methods=["GET"]),
    Route("/api/morning/personnel", list_tmm_personnel, methods=["GET"]),
    Route("/api/morning/crews", list_tmm_crews, methods=["GET"]),
    Route("/api/morning/home", get_home, methods=["GET"]),
    Route("/api/morning/messages", send_direct_message, methods=["POST"]),
    Route("/api/morning/announcements", post_announcement, methods=["POST"]),
    Route("/api/morning/messages/{message_id}/read", mark_direct_message_read, methods=["POST"]),
    Route("/api/morning/roster", get_roster, methods=["GET"]),
    Route("/api/morning/reports/{report_id}/participants", get_report_participants, methods=["GET"]),
    Route("/api/morning/draft", get_current_draft, methods=["GET"]),
    Route("/api/morning/draft", start_draft, methods=["POST"]),
    Route("/api/morning/offline-sync", sync_offline_report, methods=["POST"]),
    Route("/api/morning/reports/mine", list_my_reports, methods=["GET"]),
    Route("/api/morning/reports/{report_id}", get_my_report, methods=["GET"]),
    Route("/api/morning/reports/{report_id}/attendance", set_attendance, methods=["POST"]),
    Route("/api/morning/reports/{report_id}/brothers-keeper", set_brothers_keeper, methods=["PUT"]),
    Route("/api/morning/reports/{report_id}/stop-fix", add_stop_fix, methods=["POST"]),
    Route("/api/morning/reports/{report_id}/stop-fix/{stop_fix_id}", update_stop_fix, methods=["PATCH"]),
    Route("/api/morning/reports/{report_id}/stop-fix/{stop_fix_id}", delete_stop_fix, methods=["DELETE"]),
    Route("/api/morning/reports/{report_id}/cards", add_card, methods=["POST"]),
    Route("/api/morning/reports/{report_id}/cards/{card_id}", delete_card, methods=["DELETE"]),
    Route("/api/morning/reports/{report_id}/machine-events", add_machine_event, methods=["POST"]),
    Route("/api/morning/reports/{report_id}/machine-events/{event_id}", update_machine_event, methods=["PATCH"]),
    Route("/api/morning/reports/{report_id}/machine-events/{event_id}", delete_machine_event, methods=["DELETE"]),
    Route("/api/morning/reports/{report_id}/machine-states", add_machine_state, methods=["POST"]),
    Route("/api/morning/reports/{report_id}/machine-states", list_machine_states, methods=["GET"]),
    Route("/api/morning/reports/{report_id}/construction-work", add_construction_work, methods=["POST"]),
    Route("/api/morning/reports/{report_id}/construction-work/{item_id}", update_construction_work, methods=["PATCH"]),
    Route("/api/morning/reports/{report_id}/construction-work/{item_id}", delete_construction_work, methods=["DELETE"]),
    Route("/api/morning/reports/{report_id}/other-activities", add_other_activity, methods=["POST"]),
    Route("/api/morning/reports/{report_id}/other-activities/{activity_id}", delete_other_activity, methods=["DELETE"]),
    Route("/api/morning/reports/{report_id}/section-resolution", set_section_resolution, methods=["PATCH"]),
    Route("/api/morning/reports/{report_id}/submit", submit_report, methods=["POST"]),
    Route("/api/morning/reports/{report_id}/abandon", abandon_report, methods=["POST"]),
    Route("/api/morning/reports/{report_id}/whatsapp", get_whatsapp_text, methods=["GET"]),
]
