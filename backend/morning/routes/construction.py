from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..auth import require_admin, require_session
from ..store import MorningError, UnknownRecordError


def _runtime(request: Request):
    return request.app.state.morning_runtime


def _status(exc: MorningError) -> int:
    return 404 if isinstance(exc, UnknownRecordError) else 400


def _account_view(runtime, account: dict[str, Any]) -> dict[str, Any]:
    principal = runtime.accounts.principal_for(account["principal_id"])
    person_id = account.get("person_id")
    person = None
    if person_id:
        try:
            person = runtime.store.get_person(person_id)
        except MorningError:
            person = None
    return {
        "principal_id": principal.principal_id,
        "username": account["username"],
        "display_name": principal.display_name,
        "role": principal.role,
        "approved_at": account.get("approved_at"),
        "person_id": person.id if person else None,
        "person_name": person.name if person else None,
        "crew_id": person.crew_id if person else None,
    }


async def get_construction_config(request: Request) -> JSONResponse:
    gate = require_session(request)
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    crew_id = runtime.supervisor_crew_id(gate.principal_id)
    crew = None
    if crew_id and runtime.store.is_active_construction_crew(crew_id):
        crew = runtime.store.get_construction_crew(crew_id)
    return JSONResponse({
        "levels": list(runtime.store.list_construction_levels(active_only=True)),
        "workstreams": list(runtime.store.list_construction_workstreams(active_only=True)),
        "crew": crew,
    })


async def get_admin_config(request: Request) -> JSONResponse:
    gate = require_admin(request, workspace="construction")
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    crew_ids = runtime.store.construction_crew_ids()
    persons = [person for person in runtime.store.list_persons() if person.crew_id in crew_ids]
    person_ids = {person.id for person in persons}
    accounts = []
    for account in runtime.store.list_accounts():
        view = _account_view(runtime, account)
        if view.get("role") != "supervisor":
            continue
        if account.get("approved_at") is None or account.get("person_id") in person_ids:
            accounts.append(view)
    return JSONResponse({
        "levels": list(runtime.store.list_construction_levels()),
        "workstreams": list(runtime.store.list_construction_workstreams()),
        "crews": list(runtime.store.list_construction_crews()),
        "persons": [person.as_dict() for person in persons],
        "accounts": accounts,
    })


async def create_level(request: Request) -> JSONResponse:
    gate = require_admin(request, mutation=True, workspace="construction")
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        row = _runtime(request).store.create_construction_level(level=str(body.get("level") or ""))
        return JSONResponse(row, status_code=201)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_status(exc))


async def update_level(request: Request) -> JSONResponse:
    gate = require_admin(request, mutation=True, workspace="construction")
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        row = _runtime(request).store.update_construction_level(
            request.path_params["level_id"], level=str(body.get("level") or "")
        )
        return JSONResponse(row)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_status(exc))


async def set_level_active(request: Request, active: bool) -> JSONResponse:
    gate = require_admin(request, mutation=True, workspace="construction")
    if isinstance(gate, JSONResponse):
        return gate
    try:
        row = _runtime(request).store.set_construction_level_active(request.path_params["level_id"], active=active)
        return JSONResponse(row)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_status(exc))


async def activate_level(request: Request) -> JSONResponse:
    return await set_level_active(request, True)


async def deactivate_level(request: Request) -> JSONResponse:
    return await set_level_active(request, False)


async def create_workstream(request: Request) -> JSONResponse:
    gate = require_admin(request, mutation=True, workspace="construction")
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        row = _runtime(request).store.create_construction_workstream(name=str(body.get("name") or ""))
        return JSONResponse(row, status_code=201)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_status(exc))


async def set_workstream_active(request: Request, active: bool) -> JSONResponse:
    gate = require_admin(request, mutation=True, workspace="construction")
    if isinstance(gate, JSONResponse):
        return gate
    try:
        row = _runtime(request).store.set_construction_workstream_active(request.path_params["workstream_id"], active=active)
        return JSONResponse(row)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_status(exc))


async def activate_workstream(request: Request) -> JSONResponse:
    return await set_workstream_active(request, True)


async def deactivate_workstream(request: Request) -> JSONResponse:
    return await set_workstream_active(request, False)


async def create_crew(request: Request) -> JSONResponse:
    gate = require_admin(request, mutation=True, workspace="construction")
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        row = _runtime(request).store.create_construction_crew(
            name=str(body.get("name") or ""),
            workstream_id=body.get("workstream_id") or None,
        )
        return JSONResponse(row, status_code=201)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_status(exc))


async def update_crew(request: Request) -> JSONResponse:
    gate = require_admin(request, mutation=True, workspace="construction")
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        kwargs: dict[str, Any] = {}
        if "name" in body:
            kwargs["name"] = str(body["name"])
        if "workstream_id" in body:
            kwargs["workstream_id"] = body["workstream_id"] or None
        row = _runtime(request).store.update_construction_crew(request.path_params["crew_id"], **kwargs)
        return JSONResponse(row)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_status(exc))


async def set_crew_active(request: Request, active: bool) -> JSONResponse:
    gate = require_admin(request, mutation=True, workspace="construction")
    if isinstance(gate, JSONResponse):
        return gate
    try:
        row = _runtime(request).store.set_construction_crew_active(request.path_params["crew_id"], active=active)
        return JSONResponse(row)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_status(exc))


async def activate_crew(request: Request) -> JSONResponse:
    return await set_crew_active(request, True)


async def deactivate_crew(request: Request) -> JSONResponse:
    return await set_crew_active(request, False)


async def create_person(request: Request) -> JSONResponse:
    gate = require_admin(request, mutation=True, workspace="construction")
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    try:
        body = await request.json() or {}
        crew_id = str(body.get("crew_id") or "")
        if crew_id not in runtime.store.construction_crew_ids(active_only=True):
            raise MorningError("person must be assigned to an active Construction crew")
        person = runtime.store.create_person(
            name=str(body.get("name") or ""), employee_number=body.get("employee_number"),
            role=body.get("role"), crew_id=crew_id,
        )
        return JSONResponse(person.as_dict(), status_code=201)
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_status(exc))


async def update_person(request: Request) -> JSONResponse:
    gate = require_admin(request, mutation=True, workspace="construction")
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    try:
        body = await request.json() or {}
        kwargs = {key: body[key] for key in ("name", "employee_number", "role") if key in body}
        if "crew_id" in body:
            crew_id = str(body.get("crew_id") or "")
            if crew_id not in runtime.store.construction_crew_ids():
                raise MorningError("person must remain assigned to a Construction crew")
            kwargs["crew_id"] = crew_id
        person = runtime.store.update_person(request.path_params["person_id"], **kwargs)
        return JSONResponse(person.as_dict())
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_status(exc))


async def set_person_active(request: Request, active: bool) -> JSONResponse:
    gate = require_admin(request, mutation=True, workspace="construction")
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    try:
        person = runtime.store.get_person(request.path_params["person_id"])
        if person.crew_id not in runtime.store.construction_crew_ids():
            raise UnknownRecordError(f"unknown Construction person: {person.id}")
        person = runtime.store.set_person_active(person.id, active=active)
        return JSONResponse(person.as_dict())
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=_status(exc))


async def activate_person(request: Request) -> JSONResponse:
    return await set_person_active(request, True)


async def deactivate_person(request: Request) -> JSONResponse:
    return await set_person_active(request, False)


def _construction_admin_views(runtime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for account in runtime.store.list_accounts():
        try:
            principal = runtime.accounts.principal_for(account["principal_id"])
        except MorningError:
            continue
        if principal.role == "admin" and principal.admin_workspace == "construction":
            rows.append({
                "principal_id": principal.principal_id,
                "username": account["username"],
                "display_name": principal.display_name,
                "admin_workspace": principal.admin_workspace,
                "status": principal.status,
            })
    return rows


async def list_construction_admins(request: Request) -> JSONResponse:
    gate = require_admin(request, workspace="construction")
    if isinstance(gate, JSONResponse):
        return gate
    return JSONResponse({"admins": _construction_admin_views(_runtime(request))})


async def create_construction_admin(request: Request) -> JSONResponse:
    gate = require_admin(request, mutation=True, workspace="construction")
    if isinstance(gate, JSONResponse):
        return gate
    try:
        body = await request.json() or {}
        principal = _runtime(request).accounts.create_admin(
            username=str(body.get("username") or ""),
            password=str(body.get("password") or ""),
            display_name=str(body.get("display_name") or ""),
            workspace="construction",
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({
        "principal_id": principal.principal_id,
        "display_name": principal.display_name,
        "admin_workspace": principal.admin_workspace,
    }, status_code=201)


async def construction_bootstrap_status(request: Request) -> JSONResponse:
    gate = require_admin(request, workspace="morning")
    if isinstance(gate, JSONResponse):
        return gate
    exists = bool(_construction_admin_views(_runtime(request)))
    return JSONResponse({"available": not exists})


async def bootstrap_construction_admin(request: Request) -> JSONResponse:
    gate = require_admin(request, mutation=True, workspace="morning")
    if isinstance(gate, JSONResponse):
        return gate
    runtime = _runtime(request)
    if _construction_admin_views(runtime):
        return JSONResponse({"error": "Construction administrator already exists"}, status_code=409)
    try:
        body = await request.json() or {}
        principal = runtime.accounts.create_admin(
            username=str(body.get("username") or ""),
            password=str(body.get("password") or ""),
            display_name=str(body.get("display_name") or ""),
            workspace="construction",
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except MorningError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({
        "principal_id": principal.principal_id,
        "display_name": principal.display_name,
        "admin_workspace": principal.admin_workspace,
    }, status_code=201)


routes = [
    Route("/api/morning/admin/construction/admins", list_construction_admins, methods=["GET"]),
    Route("/api/morning/admin/construction/admins", create_construction_admin, methods=["POST"]),
    Route("/api/morning/admin/construction/bootstrap-status", construction_bootstrap_status, methods=["GET"]),
    Route("/api/morning/admin/construction/bootstrap", bootstrap_construction_admin, methods=["POST"]),
    Route("/api/morning/construction/config", get_construction_config, methods=["GET"]),
    Route("/api/morning/admin/construction/config", get_admin_config, methods=["GET"]),
    Route("/api/morning/admin/construction/levels", create_level, methods=["POST"]),
    Route("/api/morning/admin/construction/levels/{level_id}", update_level, methods=["PATCH"]),
    Route("/api/morning/admin/construction/levels/{level_id}/activate", activate_level, methods=["POST"]),
    Route("/api/morning/admin/construction/levels/{level_id}/deactivate", deactivate_level, methods=["POST"]),
    Route("/api/morning/admin/construction/workstreams", create_workstream, methods=["POST"]),
    Route("/api/morning/admin/construction/workstreams/{workstream_id}/activate", activate_workstream, methods=["POST"]),
    Route("/api/morning/admin/construction/workstreams/{workstream_id}/deactivate", deactivate_workstream, methods=["POST"]),
    Route("/api/morning/admin/construction/crews", create_crew, methods=["POST"]),
    Route("/api/morning/admin/construction/crews/{crew_id}", update_crew, methods=["PATCH"]),
    Route("/api/morning/admin/construction/crews/{crew_id}/activate", activate_crew, methods=["POST"]),
    Route("/api/morning/admin/construction/crews/{crew_id}/deactivate", deactivate_crew, methods=["POST"]),
    Route("/api/morning/admin/construction/persons", create_person, methods=["POST"]),
    Route("/api/morning/admin/construction/persons/{person_id}", update_person, methods=["PATCH"]),
    Route("/api/morning/admin/construction/persons/{person_id}/activate", activate_person, methods=["POST"]),
    Route("/api/morning/admin/construction/persons/{person_id}/deactivate", deactivate_person, methods=["POST"]),
]
