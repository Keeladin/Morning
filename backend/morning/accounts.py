from __future__ import annotations

import hashlib
import hmac
import os
from uuid import uuid4

from .identity import IdentityError, MorningIdentity, Principal
from .store import MorningError, MorningStore

PBKDF2_ITERATIONS = 210_000


class AccountError(MorningError):
    pass


class PendingApprovalError(AccountError):
    """Credentials are correct but an admin has not approved this account."""


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS).hex()


class MorningAccounts:
    """Morning-owned login and account approval.

    Public registration always creates an unapproved supervisor. Admin
    creation is a separate operator-only bootstrap operation and is never
    exposed through the public registration endpoint.
    """

    def __init__(self, store: MorningStore, identities: MorningIdentity | None = None) -> None:
        self.store = store
        self.identities = identities or MorningIdentity(store)

    @staticmethod
    def _validate_credentials(*, username: str, password: str, display_name: str) -> tuple[str, str]:
        username = username.strip()
        display_name = display_name.strip()
        if not username:
            raise AccountError("username is required")
        if len(password) < 8:
            raise AccountError("password must be at least 8 characters")
        if not display_name:
            raise AccountError("display name is required")
        return username, display_name

    def _create_account(
        self,
        *,
        username: str,
        password: str,
        display_name: str,
        role: str,
        approve: bool,
        admin_workspace: str | None = None,
    ) -> Principal:
        username, display_name = self._validate_credentials(
            username=username,
            password=password,
            display_name=display_name,
        )
        if self.store.account_by_username(username) is not None:
            raise AccountError("username is already registered")
        if role == "supervisor" and self.store.supervisor_principal_by_display_name(display_name) is not None:
            raise AccountError(
                "a supervisor account is already registered for this full name; "
                "ask a Morning administrator to correct or reset the existing account"
            )

        principal_id = f"principal_{uuid4().hex}"
        salt = os.urandom(16)
        password_hash = _hash_password(password, salt)
        principal = self.identities.create_principal(
            principal_id, display_name, role=role, admin_workspace=admin_workspace
        )
        try:
            self.store.create_account(
                principal_id=principal_id,
                username=username,
                password_hash=password_hash,
                password_salt=salt.hex(),
            )
            if approve:
                self.store.approve_account(principal_id)
        except MorningError:
            self.identities.set_status(principal_id, "suspended")
            raise
        return principal

    def register(self, *, username: str, password: str, display_name: str) -> Principal:
        return self._create_account(
            username=username,
            password=password,
            display_name=display_name,
            role="supervisor",
            approve=False,
            admin_workspace=None,
        )

    def create_admin(
        self, *, username: str, password: str, display_name: str, workspace: str = "morning"
    ) -> Principal:
        """Create an approved administrator scoped to exactly one Morning workspace."""

        workspace = workspace.strip().casefold()
        if not workspace:
            raise AccountError("admin workspace is required")
        return self._create_account(
            username=username,
            password=password,
            display_name=display_name,
            role="admin",
            approve=True,
            admin_workspace=workspace,
        )

    def list_admins(self, *, workspace: str) -> tuple[Principal, ...]:
        return tuple(
            self.identities._from_row(row) for row in self.store.list_admin_principals(workspace=workspace)
        )

    def authenticate(self, *, username: str, password: str) -> Principal:
        account = self.store.account_by_username(username)
        if account is None:
            raise AccountError("invalid username or password")
        salt = bytes.fromhex(account["password_salt"])
        candidate = _hash_password(password, salt)
        if not hmac.compare_digest(candidate, account["password_hash"]):
            raise AccountError("invalid username or password")
        if account["approved_at"] is None:
            raise PendingApprovalError("account is registered but not yet approved by an admin")
        try:
            return self.identities.principal(account["principal_id"])
        except IdentityError as exc:
            raise AccountError("account is not active") from exc

    def approve(self, principal_id: str) -> Principal:
        self.store.approve_account(principal_id)
        try:
            return self.identities.principal(principal_id)
        except IdentityError as exc:
            raise AccountError(str(exc)) from exc

    def list_pending(self) -> tuple[dict, ...]:
        return self.store.list_accounts(pending_only=True)

    def principal_for(self, principal_id: str) -> Principal:
        try:
            return self.identities.principal(principal_id)
        except IdentityError as exc:
            raise AccountError(str(exc)) from exc
