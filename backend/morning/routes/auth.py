from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..accounts import AccountError, PendingApprovalError
from ..store import MorningError


def _accounts(request: Request):
    return request.app.state.morning_accounts


async def register(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        principal = _accounts(request).register(
            username=str((body or {}).get("username") or ""),
            password=str((body or {}).get("password") or ""),
            display_name=str((body or {}).get("display_name") or ""),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except (AccountError, MorningError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(
        {
            "pending_approval": True,
            "principal": {
                "principal_id": principal.principal_id,
                "display_name": principal.display_name,
                "role": principal.role,
                "admin_workspace": principal.admin_workspace,
                "demo_mode": principal.demo_mode,
            },
        },
        status_code=201,
    )


async def login(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        principal = _accounts(request).authenticate(
            username=str((body or {}).get("username") or ""),
            password=str((body or {}).get("password") or ""),
        )
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    except PendingApprovalError as exc:
        return JSONResponse({"error": str(exc), "pending_approval": True}, status_code=403)
    except (AccountError, MorningError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=401)

    session = request.app.state.morning_auth.issue_session(principal.principal_id)
    response = JSONResponse(
        {
            "principal": {
                "principal_id": principal.principal_id,
                "display_name": principal.display_name,
                "role": principal.role,
                "admin_workspace": principal.admin_workspace,
                "demo_mode": principal.demo_mode,
            },
            "csrf_token": session.csrf_token,
        }
    )
    request.app.state.morning_auth.set_session_cookie(response, session)
    return response


async def logout(request: Request) -> JSONResponse:
    service = request.app.state.morning_auth
    current = service.session_from_request(request)
    if current is not None and not service.csrf_ok(request, current):
        return JSONResponse({"error": "csrf token missing or invalid"}, status_code=403)
    response = JSONResponse({})
    service.clear_session_cookie(response)
    return response


async def session(request: Request) -> JSONResponse:
    current = request.app.state.morning_auth.session_from_request(request)
    if current is None:
        return JSONResponse({"authenticated": False})
    try:
        principal = _accounts(request).principal_for(current.principal_id)
    except AccountError:
        return JSONResponse({"authenticated": False})
    return JSONResponse(
        {
            "authenticated": True,
            "principal": {
                "principal_id": principal.principal_id,
                "display_name": principal.display_name,
                "role": principal.role,
                "admin_workspace": principal.admin_workspace,
                "demo_mode": principal.demo_mode,
            },
            "csrf_token": current.csrf_token,
        }
    )


routes = [
    Route("/api/morning/auth/register", register, methods=["POST"]),
    Route("/api/morning/auth/login", login, methods=["POST"]),
    Route("/api/morning/auth/logout", logout, methods=["POST"]),
    Route("/api/morning/auth/session", session, methods=["GET"]),
]
