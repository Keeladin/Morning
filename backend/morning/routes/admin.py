from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..accounts import AccountError
from ..auth import require_admin
from ..renderers import render_compact_report, render_detailed_report
from ..shift import ShiftError
from ..store import MorningError, UnknownRecordError


def _runtime(request: Request):
    return request.app.state.morning_runtime


def _gate(request: Request, *, mutation: bool = False):
    return require_admin(request, mutation=mutation)


def _error_status(exc: MorningError) -> int:
    return 404 if isinstance(exc, UnknownRecordError) else 400


def _account_view(runtime, account: dict[str, Any]) -> dict[str, Any]:
    principal = runtime.store.principal_by_id(account["principal_id"])
    display_name = principal.get("display_name") if principal else None
    role = principal.get("role") if principal else None
    status = principal.get("status") if principal else None
    person_id = account.get("person_id")
    person_name = None
    crew_id = None
    crew_name = None
    if person_id:
        try:
            person = runtime.store.get_person(person_id)
            person_name = person.name
            crew_id = person.crew_id
            if crew_id:
                crew_name = runtime.store.get_crew(crew_id).name
        except MorningError:
            person_id = None
    return {
        "principal_id": account["principal_id"],
        "username": account["username"],
        "display_name": display_name,
        "role": role,
        "status": status,
        "demo_mode": bool(principal.get("demo_mode", False)) if principal else False,
        "created_at": account["created_at"],
        "approved_at": account["approved_at"],
        "person_id": person_id,
        "person_name": person_name,
        "crew_id": crew_id,
        "crew_name": crew_name,
    }


async def list_machines(request: Request) -> JSONResponse:
    gate = _gate(request)
    if isinstance(gate, JSONResponse):
        return gate
    return JSONResponse({"machines": [machine.as_dict() for machine in _runtime(request).store.list_machines()]})


async def create_machine(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        machine = _runtime(request).store.create_machine(
            machine_id=str(body.get("machine_id") or ""),
            machine_type=body.get("machine_type"),
            section=body.get("section"),
            control_room_scope=bool(body.get("control_room_scope", False)),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(machine.as_dict(), status_code=201)


async def update_machine(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        kwargs: dict[str, Any] = {}
        for key in ("machine_id", "machine_type", "section"):
            if key in body:
                kwargs[key] = body[key]
        machine = _runtime(request).store.update_machine(request.path_params["machine_id"], **kwargs)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(machine.as_dict())


async def delete_machine(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        _runtime(request).store.delete_machine(request.path_params["machine_id"])
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse({"deleted": True})


async def set_machine_active(request: Request, *, active: bool) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        machine = _runtime(request).store.set_machine_active(request.path_params["machine_id"], active=active)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(machine.as_dict())


async def activate_machine(request: Request) -> JSONResponse:
    return await set_machine_active(request, active=True)


async def deactivate_machine(request: Request) -> JSONResponse:
    return await set_machine_active(request, active=False)


async def set_control_room_scope(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        machine = _runtime(request).store.set_machine_control_room_scope(
            request.path_params["machine_id"],
            in_scope=bool(body.get("in_scope")),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(machine.as_dict())


async def list_persons(request: Request) -> JSONResponse:
    gate = _gate(request)
    if isinstance(gate, JSONResponse):
        return gate
    return JSONResponse({"persons": [person.as_dict() for person in _runtime(request).store.list_persons()]})


async def create_person(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        person = _runtime(request).store.create_person(
            name=str(body.get("name") or ""),
            employee_number=body.get("employee_number"),
            role=body.get("role"),
            crew_id=body.get("crew_id"),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(person.as_dict(), status_code=201)


async def update_person(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        kwargs = {key: body[key] for key in ("name", "employee_number", "role", "crew_id") if key in body}
        person = _runtime(request).store.update_person(request.path_params["person_id"], **kwargs)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(person.as_dict())


async def delete_person(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        _runtime(request).store.delete_person(request.path_params["person_id"])
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse({"deleted": True})


async def set_person_active(request: Request, *, active: bool) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        person = _runtime(request).store.set_person_active(request.path_params["person_id"], active=active)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(person.as_dict())


async def activate_person(request: Request) -> JSONResponse:
    return await set_person_active(request, active=True)


async def deactivate_person(request: Request) -> JSONResponse:
    return await set_person_active(request, active=False)


async def list_crews(request: Request) -> JSONResponse:
    gate = _gate(request)
    if isinstance(gate, JSONResponse):
        return gate
    return JSONResponse({"crews": [crew.as_dict() for crew in _runtime(request).store.list_crews()]})


async def create_crew(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        crew = _runtime(request).store.create_crew(name=str(body.get("name") or ""))
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(crew.as_dict(), status_code=201)


async def update_crew(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        crew = _runtime(request).store.update_crew(request.path_params["crew_id"], name=body.get("name"))
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(crew.as_dict())


async def delete_crew(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        _runtime(request).store.delete_crew(request.path_params["crew_id"])
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse({"deleted": True})


async def list_accounts(request: Request) -> JSONResponse:
    gate = _gate(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    views = [_account_view(runtime, account) for account in runtime.store.list_accounts()]
    return JSONResponse({"accounts": [view for view in views if view.get("role") == "supervisor"]})


async def list_pending_accounts(request: Request) -> JSONResponse:
    gate = _gate(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    views = [_account_view(runtime, account) for account in runtime.accounts.list_pending()]
    return JSONResponse({"accounts": [view for view in views if view.get("role") == "supervisor"]})


async def update_supervisor_account(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    principal_id = request.path_params["principal_id"]
    try:
        body = await request.json() or {}
        principal = runtime.store.principal_by_id(principal_id)
        if principal is None or principal.get("role") != "supervisor":
            raise UnknownRecordError(f"unknown supervisor: {principal_id}")
        if "display_name" in body or "demo_mode" in body:
            runtime.store.update_principal(
                principal_id,
                display_name=(str(body["display_name"] or "") if "display_name" in body else None),
                demo_mode=(bool(body["demo_mode"]) if "demo_mode" in body else None),
            )
        if "username" in body:
            runtime.store.update_account_username(principal_id, str(body["username"] or ""))
        account = runtime.store.account_by_principal(principal_id)
        if account is None:
            raise UnknownRecordError(f"unknown morning account: {principal_id}")
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(_account_view(runtime, account))


async def set_supervisor_active(request: Request, *, active: bool) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    principal_id = request.path_params["principal_id"]
    try:
        principal = runtime.store.principal_by_id(principal_id)
        if principal is None or principal.get("role") != "supervisor":
            raise UnknownRecordError(f"unknown supervisor: {principal_id}")
        runtime.store.set_principal_status(principal_id, "active" if active else "suspended")
        account = runtime.store.account_by_principal(principal_id)
        if account is None:
            raise UnknownRecordError(f"unknown morning account: {principal_id}")
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(_account_view(runtime, account))


async def activate_supervisor(request: Request) -> JSONResponse:
    return await set_supervisor_active(request, active=True)


async def deactivate_supervisor(request: Request) -> JSONResponse:
    return await set_supervisor_active(request, active=False)


async def delete_supervisor(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    principal_id = request.path_params["principal_id"]
    try:
        principal = runtime.store.principal_by_id(principal_id)
        if principal is None or principal.get("role") != "supervisor":
            raise UnknownRecordError(f"unknown supervisor: {principal_id}")
        runtime.store.delete_principal(principal_id)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse({"deleted": True})


async def approve_account(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        principal = _runtime(request).accounts.approve(request.path_params["principal_id"])
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(
        {
            "principal_id": principal.principal_id,
            "display_name": principal.display_name,
            "role": principal.role,
        }
    )


async def link_account_person(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    try:
        body = await request.json() or {}
        account = runtime.store.link_account_person(request.path_params["principal_id"], body.get("person_id"))
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_error_status(exc))
    return JSONResponse(_account_view(runtime, account))


async def get_shift_policy(request: Request) -> JSONResponse:
    gate = _gate(request)
    if isinstance(gate, JSONResponse):
        return gate
    return JSONResponse(_runtime(request).shift_policy().as_dict())


async def set_shift_policy(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        policy = _runtime(request).store.set_shift_policy(
            timezone=str(body.get("timezone") or ""),
            morning_shift_start=str(body.get("morning_shift_start") or ""),
            afternoon_shift_start=str(body.get("afternoon_shift_start") or ""),
            night_shift_start=str(body.get("night_shift_start") or ""),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except (MorningError, ShiftError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(policy.as_dict())


def _workspace_admin_views(runtime, workspace: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for account in runtime.store.list_accounts():
        try:
            principal = runtime.accounts.principal_for(account["principal_id"])
        except (AccountError, MorningError):
            continue
        if principal.role == "admin" and principal.admin_workspace == workspace:
            rows.append({
                "principal_id": principal.principal_id,
                "username": account["username"],
                "display_name": principal.display_name,
                "admin_workspace": principal.admin_workspace,
                "status": principal.status,
            })
    return rows


async def list_workspace_admins(request: Request) -> JSONResponse:
    gate = _gate(request)
    if isinstance(gate, JSONResponse):
        return gate
    return JSONResponse({"admins": _workspace_admin_views(_runtime(request), "morning")})


async def create_workspace_admin(request: Request) -> JSONResponse:
    gate = _gate(request, mutation=True)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        principal = _runtime(request).accounts.create_admin(
            username=str(body.get("username") or ""),
            password=str(body.get("password") or ""),
            display_name=str(body.get("display_name") or ""),
            workspace="morning",
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except (AccountError, MorningError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({
        "principal_id": principal.principal_id,
        "display_name": principal.display_name,
        "admin_workspace": principal.admin_workspace,
    }, status_code=201)


async def get_daily_report(request: Request) -> JSONResponse:
    gate = _gate(request)
    if isinstance(gate, JSONResponse):
        return gate
    reporting_date = request.path_params["reporting_date"]
    require_control_room = request.query_params.get("require_control_room", "true").lower() not in {"0", "false", "no"}
    bundle = _runtime(request).daily_bundle(reporting_date, require_control_room=require_control_room)
    return JSONResponse(
        {
            "reporting_date": reporting_date,
            "status": bundle.status,
            "expected_inputs": [
                {"key": item.key, "label": item.label, "present": item.present} for item in bundle.expected_inputs
            ],
            "detailed_text": render_detailed_report(bundle),
            "compact_text": render_compact_report(bundle),
        }
    )


routes = [
    Route("/api/morning/admin/workspace-admins", list_workspace_admins, methods=["GET"]),
    Route("/api/morning/admin/workspace-admins", create_workspace_admin, methods=["POST"]),
    Route("/api/morning/admin/machines", list_machines, methods=["GET"]),
    Route("/api/morning/admin/machines", create_machine, methods=["POST"]),
    Route("/api/morning/admin/machines/{machine_id}", update_machine, methods=["PATCH"]),
    Route("/api/morning/admin/machines/{machine_id}", delete_machine, methods=["DELETE"]),
    Route("/api/morning/admin/machines/{machine_id}/activate", activate_machine, methods=["POST"]),
    Route("/api/morning/admin/machines/{machine_id}/deactivate", deactivate_machine, methods=["POST"]),
    Route("/api/morning/admin/machines/{machine_id}/control-room-scope", set_control_room_scope, methods=["POST"]),
    Route("/api/morning/admin/persons", list_persons, methods=["GET"]),
    Route("/api/morning/admin/persons", create_person, methods=["POST"]),
    Route("/api/morning/admin/persons/{person_id}", update_person, methods=["PATCH"]),
    Route("/api/morning/admin/persons/{person_id}", delete_person, methods=["DELETE"]),
    Route("/api/morning/admin/persons/{person_id}/activate", activate_person, methods=["POST"]),
    Route("/api/morning/admin/persons/{person_id}/deactivate", deactivate_person, methods=["POST"]),
    Route("/api/morning/admin/crews", list_crews, methods=["GET"]),
    Route("/api/morning/admin/crews", create_crew, methods=["POST"]),
    Route("/api/morning/admin/crews/{crew_id}", update_crew, methods=["PATCH"]),
    Route("/api/morning/admin/crews/{crew_id}", delete_crew, methods=["DELETE"]),
    Route("/api/morning/admin/accounts", list_accounts, methods=["GET"]),
    Route("/api/morning/admin/accounts/pending", list_pending_accounts, methods=["GET"]),
    Route("/api/morning/admin/accounts/{principal_id}", update_supervisor_account, methods=["PATCH"]),
    Route("/api/morning/admin/accounts/{principal_id}", delete_supervisor, methods=["DELETE"]),
    Route("/api/morning/admin/accounts/{principal_id}/activate", activate_supervisor, methods=["POST"]),
    Route("/api/morning/admin/accounts/{principal_id}/deactivate", deactivate_supervisor, methods=["POST"]),
    Route("/api/morning/admin/accounts/{principal_id}/approve", approve_account, methods=["POST"]),
    Route("/api/morning/admin/accounts/{principal_id}/link", link_account_person, methods=["POST"]),
    Route("/api/morning/admin/shift-policy", get_shift_policy, methods=["GET"]),
    Route("/api/morning/admin/shift-policy", set_shift_policy, methods=["PUT"]),
    Route("/api/morning/admin/reports/{reporting_date}", get_daily_report, methods=["GET"]),
]
