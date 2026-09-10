from __future__ import annotations

from dataclasses import dataclass

from .store import MorningStore, UnknownRecordError


class IdentityError(ValueError):
    pass


@dataclass(frozen=True)
class Principal:
    principal_id: str
    display_name: str
    role: str
    status: str
    admin_workspace: str | None = None
    demo_mode: bool = False

    @property
    def active(self) -> bool:
        return self.status == "active"


class MorningIdentity:
    """Morning-owned identity boundary.

    Standalone Morning no longer shares Atlas Work principals. Reports keep
    the stable principal id they already use, but the principal itself now
    belongs to Morning and carries the small rollout role set: admin or
    supervisor.
    """

    def __init__(self, store: MorningStore) -> None:
        self.store = store

    def create_principal(
        self, principal_id: str, display_name: str, *, role: str, admin_workspace: str | None = None, demo_mode: bool = False
    ) -> Principal:
        row = self.store.create_principal(
            principal_id=principal_id,
            display_name=display_name,
            role=role,
            status="active",
            admin_workspace=admin_workspace,
            demo_mode=demo_mode,
        )
        return self._from_row(row)

    def principal(self, principal_id: str, *, require_active: bool = True) -> Principal:
        row = self.store.principal_by_id(principal_id)
        if row is None:
            raise IdentityError(f"unknown principal: {principal_id}")
        principal = self._from_row(row)
        if require_active and not principal.active:
            raise IdentityError(f"principal is not active: {principal_id}")
        return principal

    def set_status(self, principal_id: str, status: str) -> Principal:
        try:
            row = self.store.set_principal_status(principal_id, status)
        except UnknownRecordError as exc:
            raise IdentityError(str(exc)) from exc
        return self._from_row(row)

    @staticmethod
    def _from_row(row: dict) -> Principal:
        return Principal(
            principal_id=row["id"],
            display_name=row["display_name"],
            role=row["role"],
            status=row["status"],
            admin_workspace=row.get("admin_workspace"),
            demo_mode=bool(row.get("demo_mode", False)),
        )
