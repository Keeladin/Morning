from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time
import re
from typing import Any, Iterator
from uuid import uuid4

import psycopg
from psycopg import Connection
from psycopg.errors import ForeignKeyViolation, UniqueViolation
from psycopg.rows import dict_row

from .models import (
    AttendanceEntry,
    CardObservation,
    ControlRoomObservation,
    ConstructionWorkItem,
    Crew,
    Machine,
    MachineEvent,
    MachineStateDeclaration,
    OtherActivity,
    Person,
    ShiftPolicy,
    ShiftReport,
    StopFixRecord,
)


class MorningError(ValueError):
    pass


class UnknownRecordError(MorningError):
    pass


def _normalize_construction_level(value: str) -> str:
    clean = "".join(str(value).split()).upper()
    if re.fullmatch(r"\d+(?:[NS])?", clean) is None:
        raise MorningError("construction level must be numeric with optional N or S, for example 813, 813N or 813S")
    return clean


class InvalidTransitionError(MorningError):
    pass


class IncompleteReportError(MorningError):
    def __init__(self, missing_sections: tuple[str, ...]) -> None:
        super().__init__("shift report has unresolved sections")
        self.missing_sections = missing_sections


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _psycopg_dsn(database_url: str) -> str:
    """Accept the SQLAlchemy-style URL used by Alembic/CI as a psycopg DSN."""

    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _hhmm(value: Any) -> str:
    if isinstance(value, time):
        return value.strftime("%H:%M")
    text = str(value)
    return text[:5]


def _json_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _iso(value) if isinstance(value, (datetime, date, time)) else value for key, value in row.items()}


class MorningStore:
    """Morning-owned PostgreSQL persistence.

    The public method contract deliberately follows the proven SQLite
    MorningStore so MorningRuntime can move without a business-logic rewrite.
    The database itself launches fresh; this class contains no legacy-data
    migration path.
    """

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("database_url is required")
        self.database_url = database_url
        self._dsn = _psycopg_dsn(database_url)

    def _connect(self) -> Connection[dict[str, Any]]:
        return psycopg.connect(self._dsn, row_factory=dict_row)

    @contextmanager
    def _db(self) -> Iterator[Connection[dict[str, Any]]]:
        with self._connect() as db:
            with db.transaction():
                yield db

    # -- principals -------------------------------------------------------

    def create_principal(
        self,
        *,
        principal_id: str,
        display_name: str,
        role: str = "supervisor",
        status: str = "active",
        admin_workspace: str | None = None,
        demo_mode: bool = False,
    ) -> dict[str, Any]:
        try:
            with self._db() as db:
                row = db.execute(
                    """INSERT INTO morning_principals (id, display_name, role, status, admin_workspace, demo_mode)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       RETURNING *""",
                    (principal_id, display_name, role, status, admin_workspace, demo_mode),
                ).fetchone()
        except (UniqueViolation, psycopg.errors.CheckViolation) as exc:
            raise MorningError(f"invalid or duplicate principal: {principal_id}") from exc
        return _json_safe_row(row)

    def principal_by_id(self, principal_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM morning_principals WHERE id=%s", (principal_id,)).fetchone()
        return None if row is None else _json_safe_row(row)

    def supervisor_principal_by_display_name(self, display_name: str) -> dict[str, Any] | None:
        clean = display_name.strip()
        if not clean:
            return None
        with self._db() as db:
            row = db.execute(
                """SELECT * FROM morning_principals
                   WHERE role='supervisor' AND lower(btrim(display_name))=lower(btrim(%s))
                   ORDER BY created_at LIMIT 1""",
                (clean,),
            ).fetchone()
        return None if row is None else _json_safe_row(row)

    def update_principal(
        self, principal_id: str, *, display_name: str | None = None, demo_mode: bool | None = None
    ) -> dict[str, Any]:
        current = self.principal_by_id(principal_id)
        if current is None:
            raise UnknownRecordError(f"unknown principal: {principal_id}")
        name = (display_name if display_name is not None else current["display_name"]).strip()
        if not name:
            raise MorningError("display name is required")
        next_demo = bool(current.get("demo_mode", False)) if demo_mode is None else bool(demo_mode)
        with self._db() as db:
            row = db.execute(
                """UPDATE morning_principals SET display_name=%s, demo_mode=%s, updated_at=CURRENT_TIMESTAMP
                   WHERE id=%s RETURNING *""",
                (name, next_demo, principal_id),
            ).fetchone()
        return _json_safe_row(row)

    def delete_principal(self, principal_id: str) -> None:
        current = self.principal_by_id(principal_id)
        if current is None:
            raise UnknownRecordError(f"unknown principal: {principal_id}")
        with self._db() as db:
            report_count = db.execute(
                "SELECT count(*) AS count FROM morning_reports WHERE supervisor_principal_id=%s", (principal_id,)
            ).fetchone()["count"]
            message_count = db.execute(
                "SELECT count(*) AS count FROM morning_messages WHERE sender_principal_id=%s OR recipient_principal_id=%s",
                (principal_id, principal_id),
            ).fetchone()["count"]
            if report_count or message_count:
                raise MorningError("supervisor has historical records and cannot be deleted; deactivate the account instead")
            db.execute("DELETE FROM morning_principals WHERE id=%s", (principal_id,))

    def list_admin_principals(self, *, workspace: str) -> tuple[dict[str, Any], ...]:
        with self._db() as db:
            rows = db.execute(
                """SELECT * FROM morning_principals
                   WHERE role='admin' AND admin_workspace=%s
                   ORDER BY display_name, id""",
                (workspace,),
            ).fetchall()
        return tuple(_json_safe_row(row) for row in rows)

    def set_principal_status(self, principal_id: str, status: str) -> dict[str, Any]:
        with self._db() as db:
            row = db.execute(
                """UPDATE morning_principals
                   SET status=%s, updated_at=CURRENT_TIMESTAMP
                   WHERE id=%s RETURNING *""",
                (status, principal_id),
            ).fetchone()
        if row is None:
            raise UnknownRecordError(f"unknown principal: {principal_id}")
        return _json_safe_row(row)

    # -- shift policy -----------------------------------------------------

    def get_shift_policy(self) -> ShiftPolicy | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM morning_shift_policy WHERE id='default'").fetchone()
        return None if row is None else self._policy_from_row(row)

    def set_shift_policy(
        self, *, timezone: str, morning_shift_start: str, afternoon_shift_start: str, night_shift_start: str
    ) -> ShiftPolicy:
        with self._db() as db:
            row = db.execute(
                """INSERT INTO morning_shift_policy
                       (id, timezone, morning_shift_start, afternoon_shift_start, night_shift_start, updated_at)
                   VALUES ('default', %s, %s, %s, %s, CURRENT_TIMESTAMP)
                   ON CONFLICT (id) DO UPDATE SET
                       timezone=EXCLUDED.timezone,
                       morning_shift_start=EXCLUDED.morning_shift_start,
                       afternoon_shift_start=EXCLUDED.afternoon_shift_start,
                       night_shift_start=EXCLUDED.night_shift_start,
                       updated_at=CURRENT_TIMESTAMP
                   RETURNING *""",
                (timezone, morning_shift_start, afternoon_shift_start, night_shift_start),
            ).fetchone()
        return self._policy_from_row(row)

    @staticmethod
    def _policy_from_row(row: dict[str, Any]) -> ShiftPolicy:
        return ShiftPolicy(
            timezone=row["timezone"],
            morning_shift_start=_hhmm(row["morning_shift_start"]),
            afternoon_shift_start=_hhmm(row["afternoon_shift_start"]),
            night_shift_start=_hhmm(row["night_shift_start"]),
            updated_at=_iso(row["updated_at"]) or "",
        )

    # -- machines ---------------------------------------------------------

    def create_machine(
        self,
        *,
        machine_id: str,
        machine_type: str | None,
        section: str | None,
        control_room_scope: bool = False,
    ) -> Machine:
        row_id = new_id("machine")
        try:
            with self._db() as db:
                row = db.execute(
                    """INSERT INTO morning_machines
                       (id, machine_id, machine_type, section, active, control_room_scope)
                       VALUES (%s, %s, %s, %s, true, %s)
                       RETURNING *""",
                    (row_id, machine_id, machine_type, section, control_room_scope),
                ).fetchone()
        except UniqueViolation as exc:
            raise MorningError(f"machine_id already exists: {machine_id}") from exc
        return self._machine_from_row(row)

    def update_machine(
        self,
        machine_id_internal: str,
        *,
        machine_id: str | None = None,
        machine_type: str | None = ...,
        section: str | None = ...,
    ) -> Machine:
        current = self.get_machine(machine_id_internal)
        try:
            with self._db() as db:
                db.execute(
                    "UPDATE morning_machines SET machine_id=%s, machine_type=%s, section=%s WHERE id=%s",
                    (
                        machine_id if machine_id is not None else current.machine_id,
                        current.machine_type if machine_type is ... else machine_type,
                        current.section if section is ... else section,
                        machine_id_internal,
                    ),
                )
        except UniqueViolation as exc:
            raise MorningError(f"machine_id already exists: {machine_id}") from exc
        return self.get_machine(machine_id_internal)

    def set_machine_active(self, machine_id_internal: str, *, active: bool) -> Machine:
        self.get_machine(machine_id_internal)
        with self._db() as db:
            if active:
                db.execute(
                    "UPDATE morning_machines SET active=true, retired_at=NULL WHERE id=%s",
                    (machine_id_internal,),
                )
            else:
                db.execute(
                    "UPDATE morning_machines SET active=false, retired_at=CURRENT_TIMESTAMP WHERE id=%s",
                    (machine_id_internal,),
                )
        return self.get_machine(machine_id_internal)

    def delete_machine(self, machine_id_internal: str) -> None:
        self.get_machine(machine_id_internal)
        with self._db() as db:
            event_count = db.execute(
                "SELECT count(*) AS count FROM morning_machine_events WHERE machine_id=%s", (machine_id_internal,)
            ).fetchone()["count"]
            state_count = db.execute(
                "SELECT count(*) AS count FROM morning_machine_state_declarations WHERE machine_id=%s", (machine_id_internal,)
            ).fetchone()["count"]
            observation_count = db.execute(
                "SELECT count(*) AS count FROM morning_control_room_observations WHERE machine_id=%s", (machine_id_internal,)
            ).fetchone()["count"]
            if event_count or state_count or observation_count:
                raise MorningError("machine has operational history and cannot be deleted; deactivate it instead")
            db.execute("DELETE FROM morning_machines WHERE id=%s", (machine_id_internal,))

    def set_machine_control_room_scope(self, machine_id_internal: str, *, in_scope: bool) -> Machine:
        self.get_machine(machine_id_internal)
        with self._db() as db:
            db.execute(
                "UPDATE morning_machines SET control_room_scope=%s WHERE id=%s",
                (in_scope, machine_id_internal),
            )
        return self.get_machine(machine_id_internal)

    def get_machine(self, machine_id_internal: str) -> Machine:
        with self._db() as db:
            row = db.execute("SELECT * FROM morning_machines WHERE id=%s", (machine_id_internal,)).fetchone()
        if row is None:
            raise UnknownRecordError(f"unknown machine: {machine_id_internal}")
        return self._machine_from_row(row)

    def list_machines(
        self,
        *,
        active_only: bool = False,
        control_room_scope_only: bool = False,
    ) -> tuple[Machine, ...]:
        clauses: list[str] = []
        if active_only:
            clauses.append("active=true")
        if control_room_scope_only:
            clauses.append("control_room_scope=true")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._db() as db:
            rows = db.execute(f"SELECT * FROM morning_machines{where} ORDER BY machine_id").fetchall()
        return tuple(self._machine_from_row(row) for row in rows)

    @staticmethod
    def _machine_from_row(row: dict[str, Any]) -> Machine:
        return Machine(
            id=row["id"],
            machine_id=row["machine_id"],
            machine_type=row["machine_type"],
            section=row["section"],
            active=bool(row["active"]),
            created_at=_iso(row["created_at"]) or "",
            retired_at=_iso(row["retired_at"]),
            control_room_scope=bool(row["control_room_scope"]),
        )

    # -- crews ------------------------------------------------------------

    def create_crew(self, *, name: str) -> Crew:
        row_id = new_id("crew")
        with self._db() as db:
            row = db.execute(
                "INSERT INTO morning_crews (id, name) VALUES (%s, %s) RETURNING *",
                (row_id, name),
            ).fetchone()
        return self._crew_from_row(row)

    def update_crew(self, crew_id: str, *, name: str | None = None) -> Crew:
        current = self.get_crew(crew_id)
        with self._db() as db:
            db.execute(
                "UPDATE morning_crews SET name=%s WHERE id=%s",
                (name if name is not None else current.name, crew_id),
            )
        return self.get_crew(crew_id)

    def get_crew(self, crew_id: str) -> Crew:
        with self._db() as db:
            row = db.execute("SELECT * FROM morning_crews WHERE id=%s", (crew_id,)).fetchone()
        if row is None:
            raise UnknownRecordError(f"unknown crew: {crew_id}")
        return self._crew_from_row(row)

    def list_crews(self) -> tuple[Crew, ...]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM morning_crews ORDER BY name").fetchall()
        return tuple(self._crew_from_row(row) for row in rows)

    def list_tmm_crews(self) -> tuple[Crew, ...]:
        with self._db() as db:
            rows = db.execute(
                """SELECT c.* FROM morning_crews c
                   WHERE NOT EXISTS (SELECT 1 FROM morning_construction_crews cc WHERE cc.crew_id=c.id)
                   ORDER BY c.name"""
            ).fetchall()
        return tuple(self._crew_from_row(row) for row in rows)

    def delete_crew(self, crew_id: str) -> None:
        crew = self.get_crew(crew_id)
        with self._db() as db:
            people = db.execute("SELECT count(*) AS count FROM morning_persons WHERE crew_id=%s", (crew_id,)).fetchone()["count"]
            reports = db.execute(
                """SELECT count(*) AS count FROM morning_reports r
                   WHERE r.crew_id=%s OR EXISTS (SELECT 1 FROM morning_report_crews rc WHERE rc.report_id=r.id AND rc.crew_id=%s)""",
                (crew_id, crew_id),
            ).fetchone()["count"]
            construction = db.execute("SELECT count(*) AS count FROM morning_construction_crews WHERE crew_id=%s", (crew_id,)).fetchone()["count"]
            if people:
                raise MorningError(f"{crew.name} still has personnel assigned; reassign or remove them before deleting the crew")
            if reports:
                raise MorningError(f"{crew.name} has report history and cannot be deleted")
            if construction:
                raise MorningError(f"{crew.name} is configured for Construction and cannot be deleted here")
            db.execute("DELETE FROM morning_crews WHERE id=%s", (crew_id,))

    @staticmethod
    def _crew_from_row(row: dict[str, Any]) -> Crew:
        return Crew(id=row["id"], name=row["name"], created_at=_iso(row["created_at"]) or "")


    # -- Construction configuration --------------------------------------

    def create_construction_level(self, *, level: str) -> dict[str, Any]:
        clean = _normalize_construction_level(level)
        try:
            with self._db() as db:
                row = db.execute(
                    "INSERT INTO morning_construction_levels (id, level) VALUES (%s, %s) RETURNING *",
                    (new_id("construction_level"), clean),
                ).fetchone()
        except UniqueViolation as exc:
            raise MorningError(f"construction level already exists: {clean}") from exc
        return _json_safe_row(row)

    def update_construction_level(self, level_id: str, *, level: str) -> dict[str, Any]:
        clean = _normalize_construction_level(level)
        try:
            with self._db() as db:
                row = db.execute(
                    "UPDATE morning_construction_levels SET level=%s WHERE id=%s RETURNING *",
                    (clean, level_id),
                ).fetchone()
        except UniqueViolation as exc:
            raise MorningError(f"construction level already exists: {clean}") from exc
        if row is None:
            raise UnknownRecordError(f"unknown construction level: {level_id}")
        return _json_safe_row(row)

    def list_construction_levels(self, *, active_only: bool = False) -> tuple[dict[str, Any], ...]:
        where = " WHERE active=true" if active_only else ""
        with self._db() as db:
            rows = db.execute(
                f"SELECT * FROM morning_construction_levels{where} ORDER BY regexp_replace(level, '[^0-9]', '', 'g')::integer, level"
            ).fetchall()
        return tuple(_json_safe_row(row) for row in rows)

    def set_construction_level_active(self, level_id: str, *, active: bool) -> dict[str, Any]:
        with self._db() as db:
            row = db.execute(
                """UPDATE morning_construction_levels
                   SET active=%s, retired_at=CASE WHEN %s THEN NULL ELSE CURRENT_TIMESTAMP END
                   WHERE id=%s RETURNING *""",
                (active, active, level_id),
            ).fetchone()
        if row is None:
            raise UnknownRecordError(f"unknown construction level: {level_id}")
        return _json_safe_row(row)

    def create_construction_workstream(self, *, name: str) -> dict[str, Any]:
        clean = name.strip()
        if not clean:
            raise MorningError("construction workstream name is required")
        try:
            with self._db() as db:
                row = db.execute(
                    "INSERT INTO morning_construction_workstreams (id, name) VALUES (%s, %s) RETURNING *",
                    (new_id("construction_workstream"), clean),
                ).fetchone()
        except UniqueViolation as exc:
            raise MorningError(f"construction workstream already exists: {clean}") from exc
        return _json_safe_row(row)

    def list_construction_workstreams(self, *, active_only: bool = False) -> tuple[dict[str, Any], ...]:
        where = " WHERE active=true" if active_only else ""
        with self._db() as db:
            rows = db.execute(f"SELECT * FROM morning_construction_workstreams{where} ORDER BY name").fetchall()
        return tuple(_json_safe_row(row) for row in rows)

    def set_construction_workstream_active(self, workstream_id: str, *, active: bool) -> dict[str, Any]:
        with self._db() as db:
            row = db.execute(
                """UPDATE morning_construction_workstreams
                   SET active=%s, retired_at=CASE WHEN %s THEN NULL ELSE CURRENT_TIMESTAMP END
                   WHERE id=%s RETURNING *""",
                (active, active, workstream_id),
            ).fetchone()
        if row is None:
            raise UnknownRecordError(f"unknown construction workstream: {workstream_id}")
        return _json_safe_row(row)

    def create_construction_crew(self, *, name: str, workstream_id: str | None = None) -> dict[str, Any]:
        clean = name.strip()
        if not clean:
            raise MorningError("construction crew name is required")
        crew_id = new_id("crew")
        try:
            with self._db() as db:
                db.execute("INSERT INTO morning_crews (id, name) VALUES (%s, %s)", (crew_id, clean))
                db.execute(
                    "INSERT INTO morning_construction_crews (crew_id, workstream_id) VALUES (%s, %s)",
                    (crew_id, workstream_id),
                )
        except ForeignKeyViolation as exc:
            raise UnknownRecordError(f"unknown construction workstream: {workstream_id}") from exc
        return self.get_construction_crew(crew_id)

    def get_construction_crew(self, crew_id: str) -> dict[str, Any]:
        with self._db() as db:
            row = db.execute(
                """SELECT c.id AS crew_id, c.name, cc.workstream_id, cc.active, cc.created_at,
                          ws.name AS workstream_name
                   FROM morning_construction_crews cc
                   JOIN morning_crews c ON c.id=cc.crew_id
                   LEFT JOIN morning_construction_workstreams ws ON ws.id=cc.workstream_id
                   WHERE cc.crew_id=%s""",
                (crew_id,),
            ).fetchone()
        if row is None:
            raise UnknownRecordError(f"unknown construction crew: {crew_id}")
        return _json_safe_row(row)

    def list_construction_crews(self, *, active_only: bool = False) -> tuple[dict[str, Any], ...]:
        active_clause = " WHERE cc.active=true" if active_only else ""
        with self._db() as db:
            rows = db.execute(
                f"""SELECT c.id AS crew_id, c.name, cc.workstream_id, cc.active, cc.created_at,
                           ws.name AS workstream_name
                    FROM morning_construction_crews cc
                    JOIN morning_crews c ON c.id=cc.crew_id
                    LEFT JOIN morning_construction_workstreams ws ON ws.id=cc.workstream_id
                    {active_clause} ORDER BY c.name"""
            ).fetchall()
        return tuple(_json_safe_row(row) for row in rows)

    def update_construction_crew(
        self, crew_id: str, *, name: str | None = None, workstream_id: str | None | object = ...
    ) -> dict[str, Any]:
        current = self.get_construction_crew(crew_id)
        next_name = current["name"] if name is None else name.strip()
        next_workstream = current["workstream_id"] if workstream_id is ... else workstream_id
        if not next_name:
            raise MorningError("construction crew name is required")
        try:
            with self._db() as db:
                db.execute("UPDATE morning_crews SET name=%s WHERE id=%s", (next_name, crew_id))
                db.execute(
                    "UPDATE morning_construction_crews SET workstream_id=%s WHERE crew_id=%s",
                    (next_workstream, crew_id),
                )
        except ForeignKeyViolation as exc:
            raise UnknownRecordError(f"unknown construction workstream: {next_workstream}") from exc
        return self.get_construction_crew(crew_id)

    def set_construction_crew_active(self, crew_id: str, *, active: bool) -> dict[str, Any]:
        with self._db() as db:
            row = db.execute(
                "UPDATE morning_construction_crews SET active=%s WHERE crew_id=%s RETURNING crew_id",
                (active, crew_id),
            ).fetchone()
        if row is None:
            raise UnknownRecordError(f"unknown construction crew: {crew_id}")
        return self.get_construction_crew(crew_id)

    def construction_crew_ids(self, *, active_only: bool = False) -> frozenset[str]:
        where = " WHERE active=true" if active_only else ""
        with self._db() as db:
            rows = db.execute(f"SELECT crew_id FROM morning_construction_crews{where}").fetchall()
        return frozenset(row["crew_id"] for row in rows)

    def is_active_construction_crew(self, crew_id: str | None) -> bool:
        if not crew_id:
            return False
        with self._db() as db:
            row = db.execute(
                "SELECT 1 FROM morning_construction_crews WHERE crew_id=%s AND active=true",
                (crew_id,),
            ).fetchone()
        return row is not None

    # -- personnel --------------------------------------------------------

    def create_person(
        self,
        *,
        name: str,
        employee_number: str | None,
        role: str | None,
        crew_id: str | None,
    ) -> Person:
        row_id = new_id("person")
        try:
            with self._db() as db:
                row = db.execute(
                    """INSERT INTO morning_persons (id, name, employee_number, role, active, crew_id)
                       VALUES (%s, %s, %s, %s, true, %s) RETURNING *""",
                    (row_id, name, employee_number, role, crew_id),
                ).fetchone()
        except ForeignKeyViolation as exc:
            raise UnknownRecordError(f"unknown crew: {crew_id}") from exc
        return self._person_from_row(row)

    def update_person(
        self,
        person_id: str,
        *,
        name: str | None = None,
        employee_number: str | None = ...,
        role: str | None = ...,
        crew_id: str | None = ...,
    ) -> Person:
        current = self.get_person(person_id)
        try:
            with self._db() as db:
                db.execute(
                    "UPDATE morning_persons SET name=%s, employee_number=%s, role=%s, crew_id=%s WHERE id=%s",
                    (
                        name if name is not None else current.name,
                        current.employee_number if employee_number is ... else employee_number,
                        current.role if role is ... else role,
                        current.crew_id if crew_id is ... else crew_id,
                        person_id,
                    ),
                )
        except ForeignKeyViolation as exc:
            raise UnknownRecordError(f"unknown crew: {crew_id}") from exc
        return self.get_person(person_id)

    def set_person_active(self, person_id: str, *, active: bool) -> Person:
        self.get_person(person_id)
        with self._db() as db:
            db.execute("UPDATE morning_persons SET active=%s WHERE id=%s", (active, person_id))
        return self.get_person(person_id)

    def get_person(self, person_id: str) -> Person:
        with self._db() as db:
            row = db.execute("SELECT * FROM morning_persons WHERE id=%s", (person_id,)).fetchone()
        if row is None:
            raise UnknownRecordError(f"unknown person: {person_id}")
        return self._person_from_row(row)

    def list_persons(self, *, active_only: bool = False) -> tuple[Person, ...]:
        where = " WHERE active=true" if active_only else ""
        with self._db() as db:
            rows = db.execute(f"SELECT * FROM morning_persons{where} ORDER BY name").fetchall()
        return tuple(self._person_from_row(row) for row in rows)

    def list_tmm_persons(self, *, active_only: bool = False) -> tuple[Person, ...]:
        clauses = [
            "NOT EXISTS (SELECT 1 FROM morning_construction_crews cc WHERE cc.crew_id=p.crew_id AND cc.active=true)"
        ]
        if active_only:
            clauses.append("p.active=true")
        with self._db() as db:
            rows = db.execute(
                f"SELECT p.* FROM morning_persons p WHERE {' AND '.join(clauses)} ORDER BY p.name"
            ).fetchall()
        return tuple(self._person_from_row(row) for row in rows)

    def delete_person(self, person_id: str) -> None:
        self.get_person(person_id)
        with self._db() as db:
            attendance_count = db.execute(
                "SELECT count(*) AS count FROM morning_attendance WHERE person_id=%s", (person_id,)
            ).fetchone()["count"]
            assignment_count = db.execute(
                "SELECT count(*) AS count FROM morning_machine_events WHERE person_id=%s", (person_id,)
            ).fetchone()["count"]
            if attendance_count or assignment_count:
                raise MorningError("person has operational history and cannot be deleted; deactivate them instead")
            db.execute("DELETE FROM morning_persons WHERE id=%s", (person_id,))

    def persons_by_ids(self, person_ids: tuple[str, ...]) -> tuple[Person, ...]:
        if not person_ids:
            return ()
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM morning_persons WHERE id = ANY(%s) ORDER BY name",
                (list(person_ids),),
            ).fetchall()
        return tuple(self._person_from_row(row) for row in rows)

    def roster_for_crew(self, crew_id: str) -> tuple[Person, ...]:
        return self.roster_for_crews((crew_id,))

    def roster_for_crews(self, crew_ids: tuple[str, ...]) -> tuple[Person, ...]:
        if not crew_ids:
            return ()
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM morning_persons WHERE active=true AND crew_id = ANY(%s) ORDER BY name",
                (list(crew_ids),),
            ).fetchall()
        return tuple(self._person_from_row(row) for row in rows)

    @staticmethod
    def _report_crew_ids(
        db: Connection[dict[str, Any]], report_id: str, fallback_crew_id: str | None
    ) -> tuple[str, ...]:
        rows = db.execute(
            "SELECT crew_id FROM morning_report_crews WHERE report_id=%s ORDER BY position, crew_id",
            (report_id,),
        ).fetchall()
        if rows:
            return tuple(row["crew_id"] for row in rows)
        return (fallback_crew_id,) if fallback_crew_id else ()

    def roster_for_report(self, report: ShiftReport) -> tuple[Person, ...]:
        with self._db() as db:
            crew_ids = self._report_crew_ids(db, report.id, report.crew_id)
            if not crew_ids:
                return ()
            rows = db.execute(
                "SELECT * FROM morning_persons WHERE active=true AND crew_id = ANY(%s) ORDER BY name",
                (list(crew_ids),),
            ).fetchall()
        return tuple(self._person_from_row(row) for row in rows)

    @staticmethod
    def _person_from_row(row: dict[str, Any]) -> Person:
        return Person(
            id=row["id"],
            name=row["name"],
            employee_number=row["employee_number"],
            role=row["role"],
            active=bool(row["active"]),
            crew_id=row["crew_id"],
            created_at=_iso(row["created_at"]) or "",
        )

    # -- accounts ---------------------------------------------------------

    def create_account(self, *, principal_id: str, username: str, password_hash: str, password_salt: str) -> None:
        try:
            with self._db() as db:
                db.execute(
                    """INSERT INTO morning_accounts (principal_id, username, password_hash, password_salt)
                       VALUES (%s, %s, %s, %s)""",
                    (principal_id, username.strip().casefold(), password_hash, password_salt),
                )
        except UniqueViolation as exc:
            raise MorningError(f"username already registered: {username}") from exc
        except ForeignKeyViolation as exc:
            raise UnknownRecordError(f"unknown principal: {principal_id}") from exc

    def account_by_username(self, username: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM morning_accounts WHERE username=%s",
                (username.strip().casefold(),),
            ).fetchone()
        return None if row is None else _json_safe_row(row)

    def account_by_principal(self, principal_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM morning_accounts WHERE principal_id=%s", (principal_id,)).fetchone()
        return None if row is None else _json_safe_row(row)

    def update_account_username(self, principal_id: str, username: str) -> dict[str, Any]:
        clean = username.strip().casefold()
        if not clean:
            raise MorningError("username is required")
        try:
            with self._db() as db:
                row = db.execute(
                    "UPDATE morning_accounts SET username=%s WHERE principal_id=%s RETURNING *",
                    (clean, principal_id),
                ).fetchone()
        except UniqueViolation as exc:
            raise MorningError(f"username already registered: {username}") from exc
        if row is None:
            raise UnknownRecordError(f"unknown morning account: {principal_id}")
        return _json_safe_row(row)

    def approve_account(self, principal_id: str) -> dict[str, Any]:
        with self._db() as db:
            row = db.execute(
                """UPDATE morning_accounts SET approved_at=CURRENT_TIMESTAMP
                   WHERE principal_id=%s RETURNING *""",
                (principal_id,),
            ).fetchone()
        if row is None:
            raise UnknownRecordError(f"unknown morning account: {principal_id}")
        return _json_safe_row(row)

    def link_account_person(self, principal_id: str, person_id: str | None) -> dict[str, Any]:
        if person_id is not None:
            self.get_person(person_id)
        with self._db() as db:
            row = db.execute(
                "UPDATE morning_accounts SET person_id=%s WHERE principal_id=%s RETURNING *",
                (person_id, principal_id),
            ).fetchone()
        if row is None:
            raise UnknownRecordError(f"unknown morning account: {principal_id}")
        return _json_safe_row(row)

    def list_accounts(self, *, pending_only: bool = False) -> tuple[dict[str, Any], ...]:
        where = " WHERE approved_at IS NULL" if pending_only else ""
        with self._db() as db:
            rows = db.execute(f"SELECT * FROM morning_accounts{where} ORDER BY created_at").fetchall()
        return tuple(_json_safe_row(row) for row in rows)

    # -- supervisor communication ----------------------------------------

    def list_tmm_supervisors(self, *, active_only: bool = True) -> tuple[dict[str, Any], ...]:
        active_clause = " AND p.status='active'" if active_only else ""
        with self._db() as db:
            rows = db.execute(
                f"""SELECT p.id AS principal_id, p.display_name, p.status, a.username, a.person_id
                    FROM morning_principals p
                    JOIN morning_accounts a ON a.principal_id=p.id
                    LEFT JOIN morning_persons person ON person.id=a.person_id
                    WHERE p.role='supervisor' AND p.demo_mode=false AND a.approved_at IS NOT NULL{active_clause}
                      AND NOT EXISTS (
                        SELECT 1 FROM morning_construction_crews cc
                        WHERE cc.crew_id=person.crew_id AND cc.active=true
                      )
                    ORDER BY p.display_name, p.id"""
            ).fetchall()
        return tuple(_json_safe_row(row) for row in rows)

    def create_message(
        self, *, sender_principal_id: str, body: str, recipient_principal_id: str | None = None, kind: str = "direct"
    ) -> dict[str, Any]:
        clean = body.strip()
        if not clean:
            raise MorningError("message text is required")
        if kind not in {"direct", "announcement"}:
            raise MorningError("unsupported message kind")
        if kind == "direct" and not recipient_principal_id:
            raise MorningError("direct message recipient is required")
        if kind == "announcement":
            recipient_principal_id = None
        try:
            with self._db() as db:
                row = db.execute(
                    """INSERT INTO morning_messages (id, sender_principal_id, recipient_principal_id, kind, body)
                       VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                    (new_id("message"), sender_principal_id, recipient_principal_id, kind, clean),
                ).fetchone()
        except ForeignKeyViolation as exc:
            raise UnknownRecordError("message sender or recipient does not exist") from exc
        return _json_safe_row(row)

    def list_announcements(self, *, limit: int = 10) -> tuple[dict[str, Any], ...]:
        with self._db() as db:
            rows = db.execute(
                """SELECT m.*, p.display_name AS sender_name FROM morning_messages m
                   JOIN morning_principals p ON p.id=m.sender_principal_id
                   WHERE m.kind='announcement' ORDER BY m.created_at DESC, m.id DESC LIMIT %s""",
                (max(1, min(limit, 50)),),
            ).fetchall()
        return tuple(_json_safe_row(row) for row in rows)

    def list_direct_messages(self, principal_id: str, *, limit: int = 30) -> tuple[dict[str, Any], ...]:
        with self._db() as db:
            rows = db.execute(
                """SELECT m.*, sender.display_name AS sender_name, recipient.display_name AS recipient_name
                   FROM morning_messages m
                   JOIN morning_principals sender ON sender.id=m.sender_principal_id
                   JOIN morning_principals recipient ON recipient.id=m.recipient_principal_id
                   WHERE m.kind='direct' AND (m.sender_principal_id=%s OR m.recipient_principal_id=%s)
                   ORDER BY m.created_at DESC, m.id DESC LIMIT %s""",
                (principal_id, principal_id, max(1, min(limit, 100))),
            ).fetchall()
        return tuple(_json_safe_row(row) for row in rows)

    def mark_message_read(self, message_id: str, principal_id: str) -> dict[str, Any]:
        with self._db() as db:
            row = db.execute(
                """UPDATE morning_messages SET read_at=COALESCE(read_at, CURRENT_TIMESTAMP)
                   WHERE id=%s AND kind='direct' AND recipient_principal_id=%s RETURNING *""",
                (message_id, principal_id),
            ).fetchone()
        if row is None:
            raise UnknownRecordError(f"unknown direct message: {message_id}")
        return _json_safe_row(row)

    # -- shift reports ----------------------------------------------------

    def get_or_create_draft(
        self,
        *,
        supervisor_principal_id: str,
        shift_date: str,
        shift_kind: str,
        crew_id: str | None,
        reporting_model: str = "tmm",
        crew_ids: tuple[str, ...] = (),
    ) -> ShiftReport:
        row_id = new_id("shiftreport")
        try:
            with self._db() as db:
                db.execute(
                    """INSERT INTO morning_reports
                       (id, shift_date, shift_kind, supervisor_principal_id, crew_id, reporting_model, status)
                       VALUES (%s, %s, %s, %s, %s, %s, 'draft')
                       ON CONFLICT (shift_date, shift_kind, supervisor_principal_id, reporting_model)
                       WHERE status <> 'abandoned'
                       DO NOTHING""",
                    (row_id, shift_date, shift_kind, supervisor_principal_id, crew_id, reporting_model),
                )
                row = db.execute(
                    """SELECT id FROM morning_reports
                       WHERE shift_date=%s AND shift_kind=%s AND supervisor_principal_id=%s
                         AND reporting_model=%s AND status <> 'abandoned'""",
                    (shift_date, shift_kind, supervisor_principal_id, reporting_model),
                ).fetchone()
                if row is not None:
                    existing_ids = self._report_crew_ids(db, row["id"], crew_id)
                    requested_ids = tuple(crew_ids) or ((crew_id,) if crew_id else ())
                    report_exists = row["id"] != row_id
                    if report_exists and requested_ids and existing_ids != requested_ids:
                        raise MorningError(
                            "an existing draft already owns a different crew selection; continue that draft or abandon it first"
                        )
                    if not report_exists and crew_ids:
                        with db.cursor() as cursor:
                            cursor.executemany(
                                "INSERT INTO morning_report_crews (report_id, crew_id, position) VALUES (%s, %s, %s)",
                                [(row["id"], selected, position) for position, selected in enumerate(crew_ids)],
                            )
        except ForeignKeyViolation as exc:
            raise MorningError("supervisor principal or crew does not exist") from exc
        if row is None:
            raise MorningError("could not create or resolve shift report")
        return self._load_report(row["id"])

    def current_draft(self, supervisor_principal_id: str, *, reporting_model: str | None = None) -> ShiftReport | None:
        model_clause = " AND reporting_model=%s" if reporting_model is not None else ""
        args: tuple[Any, ...] = (supervisor_principal_id, reporting_model) if reporting_model is not None else (supervisor_principal_id,)
        with self._db() as db:
            row = db.execute(
                f"""SELECT id FROM morning_reports
                   WHERE supervisor_principal_id=%s AND status='draft'{model_clause}
                   ORDER BY updated_at DESC, created_at DESC, id DESC LIMIT 1""",
                args,
            ).fetchone()
        return None if row is None else self._load_report(row["id"])

    def get_report(self, report_id: str) -> ShiftReport:
        return self._load_report(report_id)

    def list_reports(
        self,
        *,
        shift_date: str | None = None,
        status: str | None = None,
        supervisor_principal_id: str | None = None,
    ) -> tuple[ShiftReport, ...]:
        clauses: list[str] = []
        args: list[Any] = []
        if shift_date is not None:
            clauses.append("shift_date=%s")
            args.append(shift_date)
        if status is not None:
            clauses.append("status=%s")
            args.append(status)
        if supervisor_principal_id is not None:
            clauses.append("supervisor_principal_id=%s")
            args.append(supervisor_principal_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._db() as db:
            rows = db.execute(
                f"SELECT id FROM morning_reports{where} ORDER BY shift_date DESC, shift_kind, created_at DESC",
                args,
            ).fetchall()
        return tuple(self._load_report(row["id"]) for row in rows)

    def list_recent_submitted_reports(self, *, reporting_model: str = "tmm", limit: int = 5) -> tuple[ShiftReport, ...]:
        with self._db() as db:
            rows = db.execute(
                """SELECT id FROM morning_reports WHERE status='submitted' AND reporting_model=%s
                   ORDER BY submitted_at DESC NULLS LAST, shift_date DESC, created_at DESC LIMIT %s""",
                (reporting_model, max(1, min(limit, 20))),
            ).fetchall()
        return tuple(self._load_report(row["id"]) for row in rows)

    def _require_draft(self, db: Connection[dict[str, Any]], report_id: str) -> dict[str, Any]:
        row = db.execute("SELECT * FROM morning_reports WHERE id=%s FOR UPDATE", (report_id,)).fetchone()
        if row is None:
            raise UnknownRecordError(f"unknown shift report: {report_id}")
        if row["status"] != "draft":
            raise InvalidTransitionError("shift report is already submitted and can no longer be edited")
        return row

    @staticmethod
    def _touch_report(db: Connection[dict[str, Any]], report_id: str) -> None:
        db.execute("UPDATE morning_reports SET updated_at=CURRENT_TIMESTAMP WHERE id=%s", (report_id,))

    def set_brothers_keeper(self, report_id: str, contribution: str) -> ShiftReport:
        clean = contribution.strip()
        if not clean:
            raise MorningError("Brothers Keeper contribution is required")
        with self._db() as db:
            self._require_draft(db, report_id)
            db.execute(
                "UPDATE morning_reports SET brothers_keeper=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                (clean, report_id),
            )
        return self._load_report(report_id)

    def replace_attendance(self, report_id: str, entries: tuple[AttendanceEntry, ...]) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            db.execute("DELETE FROM morning_attendance WHERE report_id=%s", (report_id,))
            if entries:
                with db.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO morning_attendance (report_id, person_id, present) VALUES (%s, %s, %s)",
                        [(report_id, item.person_id, item.present) for item in entries],
                    )
            self._touch_report(db, report_id)
        return self._load_report(report_id)

    def replace_report_snapshot(
        self,
        report_id: str,
        *,
        attendance: tuple[AttendanceEntry, ...],
        stop_fix: tuple[StopFixRecord, ...],
        cards: tuple[CardObservation, ...],
        machine_events: tuple[MachineEvent, ...],
        construction_work: tuple[ConstructionWorkItem, ...],
        other_activities: tuple[OtherActivity, ...],
        brothers_keeper: str | None,
        safety_reviewed_empty: bool,
        machine_activity_reviewed_empty: bool,
        other_activities_reviewed_empty: bool,
        construction_work_reviewed_empty: bool,
        construction_outstanding_reviewed_empty: bool,
    ) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            for table in (
                "morning_attendance", "morning_stop_fix", "morning_cards", "morning_machine_events",
                "morning_construction_work", "morning_other_activities",
            ):
                db.execute(f"DELETE FROM {table} WHERE report_id=%s", (report_id,))
            if attendance:
                with db.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO morning_attendance (report_id, person_id, present) VALUES (%s, %s, %s)",
                        [(report_id, item.person_id, item.present) for item in attendance],
                    )
            if stop_fix:
                with db.cursor() as cursor:
                    cursor.executemany(
                        """INSERT INTO morning_stop_fix
                           (id, report_id, number, issued_at, area_of_concern, location, reason, instruction, status, rectified_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [(item.id, report_id, item.number, item.issued_at, item.area_of_concern, item.location,
                          item.reason, item.instruction, item.status, item.rectified_at) for item in stop_fix],
                    )
            if cards:
                with db.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO morning_cards (id, report_id, card_type, reason) VALUES (%s, %s, %s, %s)",
                        [(item.id, report_id, item.card_type, item.reason) for item in cards],
                    )
            if machine_events:
                with db.cursor() as cursor:
                    cursor.executemany(
                        """INSERT INTO morning_machine_events
                           (id, report_id, machine_id, start_time, end_time, issue, person_id)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        [(item.id, report_id, item.machine_id, item.start_time, item.end_time, item.issue, item.person_id)
                         for item in machine_events],
                    )
            if construction_work:
                with db.cursor() as cursor:
                    cursor.executemany(
                        """INSERT INTO morning_construction_work
                           (id, report_id, kind, level, location, task, status, progress_percent, update_text, constraint_text, next_action)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [(item.id, report_id, item.kind, item.level, item.location, item.task, item.status,
                          item.progress_percent, item.update_text, item.constraint_text, item.next_action)
                         for item in construction_work],
                    )
            if other_activities:
                with db.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO morning_other_activities (id, report_id, category, description) VALUES (%s, %s, %s, %s)",
                        [(item.id, report_id, item.category, item.description) for item in other_activities],
                    )
            db.execute(
                """UPDATE morning_reports SET
                   brothers_keeper=%s, safety_reviewed_empty=%s, machine_activity_reviewed_empty=%s, other_activities_reviewed_empty=%s,
                   construction_work_reviewed_empty=%s, construction_outstanding_reviewed_empty=%s,
                   updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
                ((brothers_keeper or "").strip() or None, safety_reviewed_empty, machine_activity_reviewed_empty, other_activities_reviewed_empty,
                 construction_work_reviewed_empty, construction_outstanding_reviewed_empty, report_id),
            )
        return self._load_report(report_id)

    def add_stop_fix(self, report_id: str, record: StopFixRecord) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            db.execute(
                """INSERT INTO morning_stop_fix
                   (id, report_id, number, issued_at, area_of_concern, location, reason, instruction, status, rectified_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    record.id,
                    report_id,
                    record.number,
                    record.issued_at,
                    record.area_of_concern,
                    record.location,
                    record.reason,
                    record.instruction,
                    record.status,
                    record.rectified_at,
                ),
            )
            self._touch_report(db, report_id)
            db.execute("UPDATE morning_reports SET safety_reviewed_empty=false WHERE id=%s", (report_id,))
        return self._load_report(report_id)

    def update_stop_fix(self, report_id: str, record: StopFixRecord) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            cursor = db.execute(
                """UPDATE morning_stop_fix SET number=%s, issued_at=%s, area_of_concern=%s, location=%s,
                   reason=%s, instruction=%s, status=%s, rectified_at=%s
                   WHERE id=%s AND report_id=%s""",
                (
                    record.number,
                    record.issued_at,
                    record.area_of_concern,
                    record.location,
                    record.reason,
                    record.instruction,
                    record.status,
                    record.rectified_at,
                    record.id,
                    report_id,
                ),
            )
            if cursor.rowcount == 0:
                raise UnknownRecordError(f"unknown stop & fix record: {record.id}")
            self._touch_report(db, report_id)
        return self._load_report(report_id)

    def delete_stop_fix(self, report_id: str, stop_fix_id: str) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            db.execute("DELETE FROM morning_stop_fix WHERE id=%s AND report_id=%s", (stop_fix_id, report_id))
            self._touch_report(db, report_id)
        return self._load_report(report_id)

    def add_card(self, report_id: str, record: CardObservation) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            db.execute(
                "INSERT INTO morning_cards (id, report_id, card_type, reason) VALUES (%s, %s, %s, %s)",
                (record.id, report_id, record.card_type, record.reason),
            )
            self._touch_report(db, report_id)
            db.execute("UPDATE morning_reports SET safety_reviewed_empty=false WHERE id=%s", (report_id,))
        return self._load_report(report_id)

    def delete_card(self, report_id: str, card_id: str) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            db.execute("DELETE FROM morning_cards WHERE id=%s AND report_id=%s", (card_id, report_id))
            self._touch_report(db, report_id)
        return self._load_report(report_id)

    def add_machine_event(self, report_id: str, record: MachineEvent) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            db.execute(
                """INSERT INTO morning_machine_events (id, report_id, machine_id, start_time, end_time, issue, person_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (record.id, report_id, record.machine_id, record.start_time, record.end_time, record.issue, record.person_id),
            )
            self._touch_report(db, report_id)
            db.execute("UPDATE morning_reports SET machine_activity_reviewed_empty=false WHERE id=%s", (report_id,))
        return self._load_report(report_id)

    def update_machine_event(self, report_id: str, record: MachineEvent) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            cursor = db.execute(
                """UPDATE morning_machine_events SET machine_id=%s, start_time=%s, end_time=%s, issue=%s, person_id=%s
                   WHERE id=%s AND report_id=%s""",
                (record.machine_id, record.start_time, record.end_time, record.issue, record.person_id, record.id, report_id),
            )
            if cursor.rowcount == 0:
                raise UnknownRecordError(f"unknown machine event: {record.id}")
            self._touch_report(db, report_id)
        return self._load_report(report_id)

    def delete_machine_event(self, report_id: str, event_id: str) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            db.execute("DELETE FROM morning_machine_events WHERE id=%s AND report_id=%s", (event_id, report_id))
            self._touch_report(db, report_id)
        return self._load_report(report_id)

    def add_construction_work(self, report_id: str, record: ConstructionWorkItem) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            db.execute(
                """INSERT INTO morning_construction_work
                   (id, report_id, kind, level, location, task, status, progress_percent, update_text, constraint_text, next_action)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (record.id, report_id, record.kind, record.level, record.location, record.task, record.status,
                 record.progress_percent, record.update_text, record.constraint_text, record.next_action),
            )
            self._touch_report(db, report_id)
            column = "construction_work_reviewed_empty" if record.kind == "core" else "construction_outstanding_reviewed_empty"
            db.execute(f"UPDATE morning_reports SET {column}=false WHERE id=%s", (report_id,))
        return self._load_report(report_id)

    def update_construction_work(self, report_id: str, record: ConstructionWorkItem) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            cursor = db.execute(
                """UPDATE morning_construction_work SET kind=%s, level=%s, location=%s, task=%s, status=%s,
                   progress_percent=%s, update_text=%s, constraint_text=%s, next_action=%s
                   WHERE id=%s AND report_id=%s""",
                (record.kind, record.level, record.location, record.task, record.status, record.progress_percent,
                 record.update_text, record.constraint_text, record.next_action, record.id, report_id),
            )
            if cursor.rowcount == 0:
                raise UnknownRecordError(f"unknown construction work item: {record.id}")
            self._touch_report(db, report_id)
        return self._load_report(report_id)

    def delete_construction_work(self, report_id: str, item_id: str) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            db.execute("DELETE FROM morning_construction_work WHERE id=%s AND report_id=%s", (item_id, report_id))
            self._touch_report(db, report_id)
        return self._load_report(report_id)

    def add_other_activity(self, report_id: str, record: OtherActivity) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            db.execute(
                "INSERT INTO morning_other_activities (id, report_id, category, description) VALUES (%s, %s, %s, %s)",
                (record.id, report_id, record.category, record.description),
            )
            self._touch_report(db, report_id)
            db.execute("UPDATE morning_reports SET other_activities_reviewed_empty=false WHERE id=%s", (report_id,))
        return self._load_report(report_id)

    def set_empty_section_reviewed(self, report_id: str, section: str, reviewed: bool) -> ShiftReport:
        columns = {
            "safety": "safety_reviewed_empty",
            "machine_activity": "machine_activity_reviewed_empty",
            "other_activities": "other_activities_reviewed_empty",
            "construction_work": "construction_work_reviewed_empty",
            "construction_outstanding": "construction_outstanding_reviewed_empty",
        }
        column = columns.get(section)
        if column is None:
            raise MorningError(f"unsupported report section: {section}")
        with self._db() as db:
            self._require_draft(db, report_id)
            db.execute(f"UPDATE morning_reports SET {column}=%s, updated_at=CURRENT_TIMESTAMP WHERE id=%s", (reviewed, report_id))
        return self._load_report(report_id)

    def delete_other_activity(self, report_id: str, activity_id: str) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            db.execute(
                "DELETE FROM morning_other_activities WHERE id=%s AND report_id=%s",
                (activity_id, report_id),
            )
            self._touch_report(db, report_id)
        return self._load_report(report_id)

    def submit_report(self, report_id: str) -> ShiftReport:
        with self._db() as db:
            report = self._require_draft(db, report_id)
            attendance_ids = {
                row["person_id"] for row in db.execute(
                    "SELECT person_id FROM morning_attendance WHERE report_id=%s", (report_id,)
                ).fetchall()
            }
            crew_ids = self._report_crew_ids(db, report_id, report["crew_id"])
            expected_ids = {
                row["id"] for row in db.execute(
                    "SELECT id FROM morning_persons WHERE active=true AND crew_id = ANY(%s)",
                    (list(crew_ids),),
                ).fetchall()
            } if crew_ids else set()
            missing: list[str] = []
            if not expected_ids or attendance_ids != expected_ids:
                missing.append("attendance")
            safety_count = db.execute(
                "SELECT (SELECT count(*) FROM morning_stop_fix WHERE report_id=%s) + "
                "(SELECT count(*) FROM morning_cards WHERE report_id=%s) AS count",
                (report_id, report_id),
            ).fetchone()["count"]
            if not safety_count and not report["safety_reviewed_empty"]:
                missing.append("safety")
            if (report.get("reporting_model") or "tmm") == "tmm" and not str(report.get("brothers_keeper") or "").strip():
                missing.append("brothers_keeper")
            if (report.get("reporting_model") or "tmm") == "construction":
                core_count = db.execute(
                    "SELECT count(*) AS count FROM morning_construction_work WHERE report_id=%s AND kind='core'", (report_id,)
                ).fetchone()["count"]
                if not core_count and not report["construction_work_reviewed_empty"]:
                    missing.append("construction_work")
                outstanding_count = db.execute(
                    "SELECT count(*) AS count FROM morning_construction_work WHERE report_id=%s AND kind='outstanding'", (report_id,)
                ).fetchone()["count"]
                if not outstanding_count and not report["construction_outstanding_reviewed_empty"]:
                    missing.append("construction_outstanding")
            else:
                machine_count = db.execute(
                    "SELECT count(*) AS count FROM morning_machine_events WHERE report_id=%s", (report_id,)
                ).fetchone()["count"]
                if not machine_count and not report["machine_activity_reviewed_empty"]:
                    missing.append("machine_activity")
                other_count = db.execute(
                    "SELECT count(*) AS count FROM morning_other_activities WHERE report_id=%s", (report_id,)
                ).fetchone()["count"]
                if not other_count and not report["other_activities_reviewed_empty"]:
                    missing.append("other_activities")
            if missing:
                raise IncompleteReportError(tuple(missing))
            db.execute(
                """UPDATE morning_reports SET status='submitted', submitted_at=CURRENT_TIMESTAMP,
                   updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
                (report_id,),
            )
        return self._load_report(report_id)

    def abandon_report(self, report_id: str) -> ShiftReport:
        with self._db() as db:
            self._require_draft(db, report_id)
            db.execute(
                "UPDATE morning_reports SET status='abandoned', updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                (report_id,),
            )
        return self._load_report(report_id)

    def _load_report(self, report_id: str) -> ShiftReport:
        with self._db() as db:
            row = db.execute("SELECT * FROM morning_reports WHERE id=%s", (report_id,)).fetchone()
            if row is None:
                raise UnknownRecordError(f"unknown shift report: {report_id}")
            attendance_rows = db.execute(
                "SELECT * FROM morning_attendance WHERE report_id=%s ORDER BY person_id",
                (report_id,),
            ).fetchall()
            stop_fix_rows = db.execute(
                "SELECT * FROM morning_stop_fix WHERE report_id=%s ORDER BY issued_at, id",
                (report_id,),
            ).fetchall()
            card_rows = db.execute(
                "SELECT * FROM morning_cards WHERE report_id=%s ORDER BY created_at, id",
                (report_id,),
            ).fetchall()
            machine_event_rows = db.execute(
                "SELECT * FROM morning_machine_events WHERE report_id=%s ORDER BY start_time, id",
                (report_id,),
            ).fetchall()
            construction_rows = db.execute(
                "SELECT * FROM morning_construction_work WHERE report_id=%s ORDER BY created_at, id",
                (report_id,),
            ).fetchall()
            other_rows = db.execute(
                "SELECT * FROM morning_other_activities WHERE report_id=%s ORDER BY created_at, id",
                (report_id,),
            ).fetchall()
            crew_rows = db.execute(
                "SELECT crew_id FROM morning_report_crews WHERE report_id=%s ORDER BY position, crew_id",
                (report_id,),
            ).fetchall()

        attendance = tuple(
            AttendanceEntry(person_id=item["person_id"], present=bool(item["present"])) for item in attendance_rows
        )
        stop_fix = tuple(
            StopFixRecord(
                id=item["id"],
                number=item["number"],
                issued_at=_iso(item["issued_at"]) or "",
                area_of_concern=item["area_of_concern"],
                location=item["location"],
                reason=item["reason"],
                instruction=item["instruction"],
                status=item["status"],
                rectified_at=_iso(item["rectified_at"]),
            )
            for item in stop_fix_rows
        )
        cards = tuple(
            CardObservation(id=item["id"], card_type=item["card_type"], reason=item["reason"])
            for item in card_rows
        )
        machine_events = tuple(
            MachineEvent(
                id=item["id"],
                machine_id=item["machine_id"],
                start_time=_iso(item["start_time"]) or "",
                end_time=_iso(item["end_time"]) or "",
                issue=item["issue"],
                person_id=item.get("person_id"),
            )
            for item in machine_event_rows
        )
        construction_work = tuple(
            ConstructionWorkItem(
                id=item["id"], kind=item["kind"], level=item["level"], location=item["location"],
                task=item["task"], status=item["status"], progress_percent=item["progress_percent"],
                update_text=item["update_text"], constraint_text=item["constraint_text"], next_action=item["next_action"],
            )
            for item in construction_rows
        )
        other_activities = tuple(
            OtherActivity(id=item["id"], category=item["category"], description=item["description"])
            for item in other_rows
        )
        return ShiftReport(
            id=row["id"],
            shift_date=_iso(row["shift_date"]) or "",
            shift_kind=row["shift_kind"],
            supervisor_principal_id=row["supervisor_principal_id"],
            crew_id=row["crew_id"],
            reporting_model=row.get("reporting_model") or "tmm",
            status=row["status"],
            attendance=attendance,
            stop_fix=stop_fix,
            cards=cards,
            machine_events=machine_events,
            construction_work=construction_work,
            other_activities=other_activities,
            created_at=_iso(row["created_at"]) or "",
            updated_at=_iso(row["updated_at"]) or "",
            crew_ids=tuple(item["crew_id"] for item in crew_rows) or ((row["crew_id"],) if row.get("crew_id") else ()),
            brothers_keeper=row.get("brothers_keeper"),
            safety_reviewed_empty=bool(row.get("safety_reviewed_empty", False)),
            machine_activity_reviewed_empty=bool(row.get("machine_activity_reviewed_empty", False)),
            other_activities_reviewed_empty=bool(row.get("other_activities_reviewed_empty", False)),
            construction_work_reviewed_empty=bool(row.get("construction_work_reviewed_empty", False)),
            construction_outstanding_reviewed_empty=bool(row.get("construction_outstanding_reviewed_empty", False)),
            submitted_at=_iso(row["submitted_at"]),
        )

    # -- machine state ----------------------------------------------------

    def add_machine_state(self, declaration: MachineStateDeclaration) -> MachineStateDeclaration:
        try:
            with self._db() as db:
                self._require_draft(db, declaration.report_id)
                row = db.execute(
                    """INSERT INTO morning_machine_state_declarations
                       (id, machine_id, report_id, declared_at, state, state_note, provenance,
                        source_state_id, follow_up)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       RETURNING *""",
                    (
                        declaration.id,
                        declaration.machine_id,
                        declaration.report_id,
                        declaration.declared_at,
                        declaration.state,
                        declaration.state_note,
                        declaration.provenance,
                        declaration.source_state_id,
                        declaration.follow_up,
                    ),
                ).fetchone()
        except ForeignKeyViolation as exc:
            raise MorningError("machine-state declaration references an unknown source record") from exc
        except psycopg.errors.CheckViolation as exc:
            raise MorningError("invalid machine-state declaration") from exc
        return self._machine_state_from_row(row)

    def list_machine_states(
        self,
        *,
        machine_id: str | None = None,
        report_id: str | None = None,
    ) -> tuple[MachineStateDeclaration, ...]:
        clauses: list[str] = []
        args: list[Any] = []
        if machine_id is not None:
            clauses.append("machine_id=%s")
            args.append(machine_id)
        if report_id is not None:
            clauses.append("report_id=%s")
            args.append(report_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._db() as db:
            rows = db.execute(
                f"""SELECT * FROM morning_machine_state_declarations{where}
                    ORDER BY declared_at, created_at, id""",
                args,
            ).fetchall()
        return tuple(self._machine_state_from_row(row) for row in rows)

    def latest_machine_state(self, machine_id: str) -> MachineStateDeclaration | None:
        with self._db() as db:
            row = db.execute(
                """SELECT * FROM morning_machine_state_declarations
                   WHERE machine_id=%s ORDER BY declared_at DESC, created_at DESC, id DESC LIMIT 1""",
                (machine_id,),
            ).fetchone()
        return None if row is None else self._machine_state_from_row(row)

    @staticmethod
    def _machine_state_from_row(row: dict[str, Any]) -> MachineStateDeclaration:
        return MachineStateDeclaration(
            id=row["id"],
            machine_id=row["machine_id"],
            report_id=row["report_id"],
            declared_at=_iso(row["declared_at"]) or "",
            state=row["state"],
            provenance=row["provenance"],
            state_note=row["state_note"],
            source_state_id=row["source_state_id"],
            follow_up=row["follow_up"],
            created_at=_iso(row["created_at"]),
        )

    # -- control-room observations ---------------------------------------

    def add_observation(self, observation: ControlRoomObservation) -> ControlRoomObservation:
        try:
            with self._db() as db:
                row = db.execute(
                    """INSERT INTO morning_control_room_observations
                       (id, reporting_date, machine_id, raw_machine_label, start_time, end_time, description,
                        source_message_id, source_artifact_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       RETURNING *""",
                    (
                        observation.id,
                        observation.reporting_date,
                        observation.machine_id,
                        observation.raw_machine_label,
                        observation.start_time,
                        observation.end_time,
                        observation.description,
                        observation.source_message_id,
                        observation.source_artifact_id,
                    ),
                ).fetchone()
        except ForeignKeyViolation as exc:
            raise UnknownRecordError(f"unknown machine: {observation.machine_id}") from exc
        return self._observation_from_row(row)

    def list_observations(self, *, reporting_date: str) -> tuple[ControlRoomObservation, ...]:
        with self._db() as db:
            rows = db.execute(
                """SELECT * FROM morning_control_room_observations
                   WHERE reporting_date=%s ORDER BY extracted_at, id""",
                (reporting_date,),
            ).fetchall()
        return tuple(self._observation_from_row(row) for row in rows)

    @staticmethod
    def _observation_from_row(row: dict[str, Any]) -> ControlRoomObservation:
        return ControlRoomObservation(
            id=row["id"],
            reporting_date=_iso(row["reporting_date"]) or "",
            machine_id=row["machine_id"],
            raw_machine_label=row["raw_machine_label"],
            start_time=_iso(row["start_time"]),
            end_time=_iso(row["end_time"]),
            description=row["description"],
            source_message_id=row["source_message_id"],
            source_artifact_id=row["source_artifact_id"],
            extracted_at=_iso(row["extracted_at"]) or "",
        )
