from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .accounts import AccountError, MorningAccounts

SESSION_COOKIE = "morning_session"
CSRF_HEADER = "x-csrf-token"
SESSION_MAX_AGE = 60 * 60 * 24 * 7


@dataclass(frozen=True)
class CookiePolicy:
    secure: bool
    samesite: str = "lax"

    @classmethod
    def for_environment(cls, environment: str) -> "CookiePolicy":
        return cls(secure=environment == "production")


@dataclass(frozen=True)
class SessionData:
    principal_id: str
    csrf_token: str


class MorningSessionService:
    """Signed Morning session cookie plus same-origin CSRF token."""

    def __init__(
        self,
        *,
        secret: str,
        cookie_policy: CookiePolicy,
        max_age: int = SESSION_MAX_AGE,
    ) -> None:
        if not secret:
            raise ValueError("Morning session secret must not be empty")
        if max_age <= 0:
            raise ValueError("Morning session max_age must be positive")
        self.cookie_policy = cookie_policy
        self.max_age = max_age
        self._serializer = URLSafeTimedSerializer(secret, salt="morning-session")

    def issue_session(self, principal_id: str) -> SessionData:
        return SessionData(principal_id=principal_id, csrf_token=secrets.token_urlsafe(32))

    def dump_session(self, session: SessionData) -> str:
        return self._serializer.dumps({"principal_id": session.principal_id, "csrf": session.csrf_token})

    def load_session(self, token: str | None) -> SessionData | None:
        if not token:
            return None
        try:
            payload = self._serializer.loads(token, max_age=self.max_age)
        except (BadSignature, SignatureExpired, ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        principal_id = str(payload.get("principal_id") or "")
        csrf_token = str(payload.get("csrf") or "")
        if not principal_id or not csrf_token:
            return None
        return SessionData(principal_id=principal_id, csrf_token=csrf_token)

    def set_session_cookie(self, response: Response, session: SessionData) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            self.dump_session(session),
            httponly=True,
            secure=self.cookie_policy.secure,
            samesite=self.cookie_policy.samesite,
            max_age=self.max_age,
            path="/",
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(
            SESSION_COOKIE,
            path="/",
            secure=self.cookie_policy.secure,
            httponly=True,
            samesite=self.cookie_policy.samesite,
        )

    def session_from_request(self, request: Request) -> SessionData | None:
        return self.load_session(request.cookies.get(SESSION_COOKIE))

    def csrf_ok(self, request: Request, session: SessionData) -> bool:
        header = request.headers.get(CSRF_HEADER) or ""
        return hmac.compare_digest(header, session.csrf_token)


def unauthorized(detail: str = "authentication required") -> JSONResponse:
    return JSONResponse({"error": detail}, status_code=401)


def require_session(request: Request) -> SessionData | JSONResponse:
    service: MorningSessionService = request.app.state.morning_auth
    session = service.session_from_request(request)
    if session is None:
        return unauthorized()
    accounts: MorningAccounts = request.app.state.morning_accounts
    try:
        accounts.principal_for(session.principal_id)
    except AccountError:
        return unauthorized("account is not active")
    return session


def require_mutation_auth(request: Request) -> SessionData | JSONResponse:
    session = require_session(request)
    if isinstance(session, JSONResponse):
        return session
    service: MorningSessionService = request.app.state.morning_auth
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and not service.csrf_ok(request, session):
        return JSONResponse({"error": "csrf token missing or invalid"}, status_code=403)
    return session


def require_admin(
    request: Request, *, mutation: bool = False, workspace: str = "morning"
) -> SessionData | JSONResponse:
    session = require_mutation_auth(request) if mutation else require_session(request)
    if isinstance(session, JSONResponse):
        return session
    accounts: MorningAccounts = request.app.state.morning_accounts
    try:
        principal = accounts.principal_for(session.principal_id)
    except AccountError:
        return unauthorized()
    if principal.role != "admin":
        return JSONResponse({"error": "admin role required"}, status_code=403)
    if principal.admin_workspace != workspace:
        return JSONResponse(
            {"error": f"{workspace} administrator access required", "admin_workspace": principal.admin_workspace},
            status_code=403,
        )
    return session
