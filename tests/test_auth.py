from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from morning.auth import CookiePolicy, MorningSessionService, require_mutation_auth


async def mutate(request: Request) -> JSONResponse:
    gate = require_mutation_auth(request)
    if isinstance(gate, JSONResponse):
        return gate
    return JSONResponse({"principal_id": gate.principal_id})


def _client() -> tuple[TestClient, MorningSessionService]:
    service = MorningSessionService(
        secret="test-morning-session-secret-with-enough-entropy",
        cookie_policy=CookiePolicy(secure=False),
    )
    app = Starlette(routes=[Route("/mutate", mutate, methods=["POST"])])
    app.state.morning_auth = service

    class ActiveAccounts:
        @staticmethod
        def principal_for(principal_id: str):
            return {"id": principal_id, "status": "active"}

    app.state.morning_accounts = ActiveAccounts()
    return TestClient(app), service


def test_signed_session_round_trip() -> None:
    service = MorningSessionService(secret="secret", cookie_policy=CookiePolicy(secure=False))
    session = service.issue_session("principal-1")
    loaded = service.load_session(service.dump_session(session))
    assert loaded == session


def test_tampered_session_is_rejected() -> None:
    service = MorningSessionService(secret="secret", cookie_policy=CookiePolicy(secure=False))
    token = service.dump_session(service.issue_session("principal-1"))
    assert service.load_session(token + "tampered") is None


def test_mutation_requires_session_and_csrf() -> None:
    client, service = _client()
    assert client.post("/mutate").status_code == 401

    session = service.issue_session("principal-1")
    client.cookies.set("morning_session", service.dump_session(session))
    assert client.post("/mutate").status_code == 403
    response = client.post("/mutate", headers={"X-CSRF-Token": session.csrf_token})
    assert response.status_code == 200
    assert response.json()["principal_id"] == "principal-1"


def test_cookie_is_secure_in_production_policy() -> None:
    assert CookiePolicy.for_environment("production").secure is True
    assert CookiePolicy.for_environment("development").secure is False
