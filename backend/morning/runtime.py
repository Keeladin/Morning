from __future__ import annotations

from dataclasses import replace
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .accounts import MorningAccounts
from .aggregate import ReportBundle, build_report_bundle
from .models import (
    CONSTRUCTION_WORK_KINDS,
    CONSTRUCTION_WORK_STATUSES,
    MACHINE_STATES,
    REPORTING_MODELS,
    SHIFT_KINDS,
    AttendanceEntry,
    CardObservation,
    ConstructionWorkItem,
    MachineEvent,
    MachineStateDeclaration,
    OtherActivity,
    Person,
    ShiftIdentity,
    ShiftPolicy,
    ShiftReport,
    StopFixRecord,
)
from .renderers import render_compact_report, render_detailed_report, render_whatsapp_report
from .shift import anchor_time_to_shift, normalize_shift_override, require_zone, resolve_shift
from .store import MorningError, MorningStore, UnknownRecordError, new_id

DEFAULT_POLICY = ShiftPolicy(
    timezone="Africa/Johannesburg",
    morning_shift_start="06:00",
    afternoon_shift_start="14:00",
    night_shift_start="22:00",
    updated_at="",
)

Clock = Callable[[], datetime]


class MorningRuntime:
    """Standalone Morning business logic for shift capture and reporting."""

    def __init__(self, store: MorningStore, accounts: MorningAccounts, *, clock: Clock | None = None) -> None:
        self.store = store
        self.accounts = accounts
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def shift_policy(self) -> ShiftPolicy:
        return self.store.get_shift_policy() or DEFAULT_POLICY

    def current_shift(self, *, now: datetime | None = None) -> ShiftIdentity:
        return resolve_shift(self.shift_policy(), at=now or self._clock())

    def default_reporting_date(self, *, now: datetime | None = None) -> str:
        zone = require_zone(self.shift_policy().timezone)
        moment = now or self._clock()
        local = moment.astimezone(zone) if moment.tzinfo is not None else moment.replace(tzinfo=zone)
        return (local.date() - timedelta(days=1)).isoformat()

    def supervisor_crew_id(self, supervisor_principal_id: str) -> str | None:
        account = self.store.account_by_principal(supervisor_principal_id)
        if account is None or account.get("person_id") is None:
            return None
        try:
            person = self.store.get_person(account["person_id"])
        except UnknownRecordError:
            return None
        return person.crew_id

    def expected_attendance(self, crew_id: str | None) -> tuple[Person, ...]:
        if crew_id is None:
            return ()
        return self.store.roster_for_crew(crew_id)

    def expected_attendance_for_report(self, report: ShiftReport) -> tuple[Person, ...]:
        return self.store.roster_for_report(report)

    def tmm_personnel(self) -> tuple[Person, ...]:
        return self.store.list_tmm_persons(active_only=True)

    def current_draft(self, supervisor_principal_id: str, *, reporting_model: str | None = None) -> ShiftReport | None:
        return self.store.current_draft(supervisor_principal_id, reporting_model=reporting_model)

    def start_draft(
        self, supervisor_principal_id: str, *, shift_date: str, shift_kind: str, reporting_model: str = "tmm",
        crew_ids: tuple[str, ...] = (),
    ) -> ShiftReport:
        if shift_kind not in SHIFT_KINDS:
            raise MorningError(f"unsupported shift kind: {shift_kind}")
        if reporting_model not in REPORTING_MODELS:
            raise MorningError(f"unsupported reporting model: {reporting_model}")
        requested = normalize_shift_override(
            self.current_shift(),
            ShiftIdentity(shift_date=shift_date, shift_kind=shift_kind),
        )
        shift_date = requested.shift_date
        shift_kind = requested.shift_kind
        selected_crews: tuple[str, ...] = ()
        if reporting_model == "tmm":
            selected_crews = tuple(dict.fromkeys(str(item).strip() for item in crew_ids if str(item).strip()))
            if not selected_crews:
                raise MorningError("select at least one crew for this TMM shift")
            allowed = {crew.id for crew in self.store.list_tmm_crews()}
            invalid = [crew_id for crew_id in selected_crews if crew_id not in allowed]
            if invalid:
                raise MorningError("one or more selected crews are not available to TMM")
            crew_id = selected_crews[0]
        else:
            crew_id = self.supervisor_crew_id(supervisor_principal_id)
            if not self.store.is_active_construction_crew(crew_id):
                raise MorningError("supervisor is not linked to an active Construction crew")
            selected_crews = (crew_id,) if crew_id else ()
        return self.store.get_or_create_draft(
            supervisor_principal_id=supervisor_principal_id, shift_date=shift_date, shift_kind=shift_kind,
            crew_id=crew_id, reporting_model=reporting_model, crew_ids=selected_crews,
        )

    @staticmethod
    def _snapshot_hhmm(value: object) -> str:
        text = str(value or "").strip()
        if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", text):
            return text
        try:
            return datetime.fromisoformat(text).strftime("%H:%M")
        except (TypeError, ValueError) as exc:
            raise MorningError("offline machine-event time must be HH:MM or ISO timestamp") from exc

    def sync_offline_snapshot(
        self, supervisor_principal_id: str, snapshot: dict[str, Any], *, submit: bool = False
    ) -> ShiftReport:
        shift_date = str(snapshot.get("shift_date") or "")
        shift_kind = str(snapshot.get("shift_kind") or "")
        reporting_model = str(snapshot.get("reporting_model") or "tmm")
        crew_ids = tuple(str(item) for item in (snapshot.get("crew_ids") or []) if str(item))
        report = self.start_draft(
            supervisor_principal_id, shift_date=shift_date, shift_kind=shift_kind, reporting_model=reporting_model,
            crew_ids=crew_ids,
        )
        # Background Sync may have completed while the app was closed. In that case
        # the submitted server copy is already authoritative and is safe to return.
        if report.status == "submitted":
            return report

        expected_ids = {person.id for person in self.expected_attendance_for_report(report)}
        attendance_map: dict[str, bool] = {}
        for item in snapshot.get("attendance") or []:
            person_id = str((item or {}).get("person_id") or "")
            if person_id not in expected_ids:
                raise MorningError(f"person is not on this report crew: {person_id}")
            attendance_map[person_id] = bool((item or {}).get("present"))
        attendance = tuple(AttendanceEntry(person_id=key, present=value) for key, value in attendance_map.items())

        zone = require_zone(self.shift_policy().timezone)
        now_local = self._clock().astimezone(zone).isoformat()
        stop_fix: list[StopFixRecord] = []
        for raw in snapshot.get("stop_fix") or []:
            raw = raw or {}
            status = str(raw.get("status") or "open")
            if status not in {"open", "rectified"}:
                raise MorningError(f"unsupported Stop & Fix status: {status}")
            stop_fix.append(StopFixRecord(
                id=str(raw.get("id") or new_id("stopfix")), number=str(raw.get("number") or ""),
                issued_at=str(raw.get("issued_at") or now_local), area_of_concern=str(raw.get("area_of_concern") or ""),
                location=str(raw.get("location") or ""), reason=str(raw.get("reason") or ""),
                instruction=str(raw.get("instruction") or ""), status=status,
                rectified_at=(str(raw.get("rectified_at")) if raw.get("rectified_at") else None),
            ))

        cards: list[CardObservation] = []
        for raw in snapshot.get("cards") or []:
            raw = raw or {}
            card_type = str(raw.get("card_type") or "")
            if card_type not in {"red", "green"}:
                raise MorningError(f"unsupported card type: {card_type}")
            cards.append(CardObservation(
                id=str(raw.get("id") or new_id("card")), card_type=card_type, reason=str(raw.get("reason") or "")
            ))

        machine_events: list[MachineEvent] = []
        for raw in snapshot.get("machine_events") or []:
            raw = raw or {}
            person_id = str(raw.get("person_id") or "") or None
            self._validate_assignee(report, person_id)
            start_hhmm = self._snapshot_hhmm(raw.get("start_time") or raw.get("start_hhmm"))
            end_hhmm = self._snapshot_hhmm(raw.get("end_time") or raw.get("end_hhmm"))
            start_time, end_time = self._anchor_event_times(report, start_hhmm, end_hhmm)
            machine_events.append(MachineEvent(
                id=str(raw.get("id") or new_id("event")), machine_id=str(raw.get("machine_id") or ""),
                start_time=start_time, end_time=end_time, issue=str(raw.get("issue") or ""), person_id=person_id,
            ))

        construction_work: list[ConstructionWorkItem] = []
        for raw in snapshot.get("construction_work") or []:
            raw = raw or {}
            kind = str(raw.get("kind") or "core")
            level = "".join(str(raw.get("level") or "").split()).upper()
            status = str(raw.get("status") or "in_progress")
            progress_raw = raw.get("progress_percent")
            progress = None if progress_raw in (None, "") else int(progress_raw)
            self._validate_construction_work(
                kind, level, str(raw.get("location") or ""), str(raw.get("task") or ""), status, progress
            )
            construction_work.append(ConstructionWorkItem(
                id=str(raw.get("id") or new_id("construction")), kind=kind, level=level,
                location=str(raw.get("location") or "").strip(), task=str(raw.get("task") or "").strip(), status=status,
                progress_percent=progress, update_text=str(raw.get("update_text") or "").strip(),
                constraint_text=(str(raw.get("constraint_text") or "").strip() or None),
                next_action=(str(raw.get("next_action") or "").strip() or None),
            ))

        other_activities = tuple(OtherActivity(
            id=str((raw or {}).get("id") or new_id("activity")),
            category=((raw or {}).get("category") or None),
            description=str((raw or {}).get("description") or ""),
        ) for raw in (snapshot.get("other_activities") or []))

        report = self.store.replace_report_snapshot(
            report.id, attendance=attendance, stop_fix=tuple(stop_fix), cards=tuple(cards),
            machine_events=tuple(machine_events), construction_work=tuple(construction_work), other_activities=other_activities,
            brothers_keeper=(str(snapshot.get("brothers_keeper") or "").strip() or None),
            safety_reviewed_empty=bool(snapshot.get("safety_reviewed_empty")) and not (stop_fix or cards),
            machine_activity_reviewed_empty=bool(snapshot.get("machine_activity_reviewed_empty")) and not machine_events,
            other_activities_reviewed_empty=bool(snapshot.get("other_activities_reviewed_empty")) and not other_activities,
            construction_work_reviewed_empty=bool(snapshot.get("construction_work_reviewed_empty"))
                and not any(item.kind == "core" for item in construction_work),
            construction_outstanding_reviewed_empty=bool(snapshot.get("construction_outstanding_reviewed_empty"))
                and not any(item.kind == "outstanding" for item in construction_work),
        )

        existing_state_ids = {item.id for item in self.store.list_machine_states(report_id=report.id)}
        for raw in snapshot.get("machine_states") or []:
            raw = raw or {}
            declaration_id = str(raw.get("id") or new_id("state"))
            if declaration_id in existing_state_ids:
                continue
            state = str(raw.get("state") or "")
            if state not in MACHINE_STATES:
                raise MorningError(f"unsupported machine state: {state}")
            state_note = str(raw.get("state_note") or "").strip() or None
            if state == "other" and not state_note:
                raise MorningError("other machine state requires an explanatory note")
            declared_hhmm = self._snapshot_hhmm(raw.get("declared_at") or raw.get("declared_hhmm"))
            declared_at = anchor_time_to_shift(
                self.shift_policy(),
                ShiftIdentity(shift_date=report.shift_date, shift_kind=report.shift_kind),
                declared_hhmm,
            ).isoformat()
            self.store.add_machine_state(MachineStateDeclaration(
                id=declaration_id, machine_id=str(raw.get("machine_id") or ""), report_id=report.id,
                declared_at=declared_at, state=state, provenance="declared", state_note=state_note,
                follow_up=(str(raw.get("follow_up") or "").strip() or None),
            ))
            existing_state_ids.add(declaration_id)

        return self.store.submit_report(report.id) if submit else report

    def abandon_draft(self, report_id: str) -> ShiftReport:
        return self.store.abandon_report(report_id)

    def get_report(self, report_id: str) -> ShiftReport:
        return self.store.get_report(report_id)

    def report_participants(self, report_id: str) -> tuple[Person, ...]:
        report = self.store.get_report(report_id)
        person_ids = tuple(dict.fromkeys(
            [entry.person_id for entry in report.attendance]
            + [event.person_id for event in report.machine_events if event.person_id]
        ))
        return self.store.persons_by_ids(person_ids)

    def my_reports(self, supervisor_principal_id: str) -> tuple[ShiftReport, ...]:
        return self.store.list_reports(supervisor_principal_id=supervisor_principal_id)

    # Stage 1: attendance
    def set_attendance(self, report_id: str, entries: tuple[AttendanceEntry, ...]) -> ShiftReport:
        return self.store.replace_attendance(report_id, entries)

    # Stage 2: Brothers Keeper (TMM)
    def set_brothers_keeper(self, report_id: str, contribution: str) -> ShiftReport:
        report = self.store.get_report(report_id)
        if report.reporting_model != "tmm":
            raise MorningError("Brothers Keeper is part of the TMM reporting workflow")
        return self.store.set_brothers_keeper(report_id, contribution)

    # Stage 3: safety
    def add_stop_fix(
        self,
        report_id: str,
        *,
        number: str,
        issued_at: str,
        area_of_concern: str,
        location: str,
        reason: str,
        instruction: str,
    ) -> ShiftReport:
        record = StopFixRecord(
            id=new_id("stopfix"),
            number=number,
            issued_at=issued_at,
            area_of_concern=area_of_concern,
            location=location,
            reason=reason,
            instruction=instruction,
            status="open",
        )
        return self.store.add_stop_fix(report_id, record)

    def update_stop_fix(self, report_id: str, stop_fix_id: str, **fields) -> ShiftReport:
        current = self._find(self.store.get_report(report_id).stop_fix, stop_fix_id, "stop & fix record")
        return self.store.update_stop_fix(report_id, replace(current, **fields))

    def delete_stop_fix(self, report_id: str, stop_fix_id: str) -> ShiftReport:
        return self.store.delete_stop_fix(report_id, stop_fix_id)

    def add_card(self, report_id: str, *, card_type: str, reason: str) -> ShiftReport:
        if card_type not in {"red", "green"}:
            raise MorningError(f"unsupported card type: {card_type}")
        return self.store.add_card(report_id, CardObservation(id=new_id("card"), card_type=card_type, reason=reason))

    def delete_card(self, report_id: str, card_id: str) -> ShiftReport:
        return self.store.delete_card(report_id, card_id)

    # Stage 4: machine activity
    def add_machine_event(
        self,
        report_id: str,
        *,
        machine_id: str,
        start_hhmm: str,
        end_hhmm: str,
        issue: str,
        person_id: str | None = None,
    ) -> ShiftReport:
        report = self.store.get_report(report_id)
        self._validate_assignee(report, person_id)
        start_time, end_time = self._anchor_event_times(report, start_hhmm, end_hhmm)
        return self.store.add_machine_event(
            report_id,
            MachineEvent(
                id=new_id("event"),
                machine_id=machine_id,
                start_time=start_time,
                end_time=end_time,
                issue=issue,
                person_id=person_id,
            ),
        )

    def update_machine_event(
        self,
        report_id: str,
        event_id: str,
        *,
        machine_id: str | None = None,
        start_hhmm: str | None = None,
        end_hhmm: str | None = None,
        issue: str | None = None,
        person_id: str | None = None,
    ) -> ShiftReport:
        report = self.store.get_report(report_id)
        current = self._find(report.machine_events, event_id, "machine event")
        next_person_id = person_id if person_id is not None else current.person_id
        self._validate_assignee(report, next_person_id)
        if start_hhmm is not None or end_hhmm is not None:
            policy = self.shift_policy()
            start_time, end_time = self._anchor_event_times(
                report,
                start_hhmm or self._as_hhmm(current.start_time, policy.timezone),
                end_hhmm or self._as_hhmm(current.end_time, policy.timezone),
            )
        else:
            start_time, end_time = current.start_time, current.end_time
        updated = replace(
            current,
            machine_id=machine_id or current.machine_id,
            start_time=start_time,
            end_time=end_time,
            issue=issue if issue is not None else current.issue,
            person_id=next_person_id,
        )
        return self.store.update_machine_event(report_id, updated)

    def delete_machine_event(self, report_id: str, event_id: str) -> ShiftReport:
        return self.store.delete_machine_event(report_id, event_id)

    def declare_machine_state(
        self,
        report_id: str,
        *,
        machine_id: str,
        declared_hhmm: str,
        state: str,
        state_note: str | None = None,
        follow_up: str | None = None,
    ) -> MachineStateDeclaration:
        if state not in MACHINE_STATES:
            raise MorningError(f"unsupported machine state: {state}")
        if state == "other" and not (state_note or "").strip():
            raise MorningError("other machine state requires an explanatory note")
        report = self.store.get_report(report_id)
        declared_at = anchor_time_to_shift(
            self.shift_policy(),
            ShiftIdentity(shift_date=report.shift_date, shift_kind=report.shift_kind),
            declared_hhmm,
        ).isoformat()
        return self.store.add_machine_state(
            MachineStateDeclaration(
                id=new_id("state"),
                machine_id=machine_id,
                report_id=report_id,
                declared_at=declared_at,
                state=state,
                provenance="declared",
                state_note=state_note,
                follow_up=follow_up,
            )
        )

    def carry_machine_state(
        self,
        report_id: str,
        *,
        machine_id: str,
        declared_hhmm: str,
    ) -> MachineStateDeclaration:
        source = self.store.latest_machine_state(machine_id)
        if source is None:
            raise MorningError(f"no prior machine state exists for: {machine_id}")
        report = self.store.get_report(report_id)
        declared_at = anchor_time_to_shift(
            self.shift_policy(),
            ShiftIdentity(shift_date=report.shift_date, shift_kind=report.shift_kind),
            declared_hhmm,
        ).isoformat()
        return self.store.add_machine_state(
            MachineStateDeclaration(
                id=new_id("state"),
                machine_id=machine_id,
                report_id=report_id,
                declared_at=declared_at,
                state=source.state,
                provenance="carried",
                state_note=source.state_note,
                source_state_id=source.id,
                follow_up=source.follow_up,
            )
        )

    def machine_states_for_report(self, report_id: str) -> tuple[MachineStateDeclaration, ...]:
        return self.store.list_machine_states(report_id=report_id)

    def _anchor_event_times(self, report: ShiftReport, start_hhmm: str, end_hhmm: str) -> tuple[str, str]:
        policy = self.shift_policy()
        identity = ShiftIdentity(shift_date=report.shift_date, shift_kind=report.shift_kind)
        start = anchor_time_to_shift(policy, identity, start_hhmm)
        end = anchor_time_to_shift(policy, identity, end_hhmm)
        if end <= start:
            raise MorningError("machine event end time must be after its start time")
        return start.isoformat(), end.isoformat()

    @staticmethod
    def _as_hhmm(iso_value: str, timezone_name: str) -> str:
        moment = datetime.fromisoformat(iso_value)
        if moment.tzinfo is not None:
            moment = moment.astimezone(require_zone(timezone_name))
        return moment.strftime("%H:%M")

    # Construction operational core
    def add_construction_work(
        self, report_id: str, *, kind: str, level: str, location: str, task: str, status: str,
        progress_percent: int | None, update_text: str, constraint_text: str | None, next_action: str | None,
    ) -> ShiftReport:
        report = self.store.get_report(report_id)
        if report.reporting_model != "construction":
            raise MorningError("construction work can only be added to a construction report")
        normalized_level = "".join(str(level).split()).upper()
        self._validate_construction_work(kind, normalized_level, location, task, status, progress_percent)
        return self.store.add_construction_work(
            report_id,
            ConstructionWorkItem(
                id=new_id("construction"), kind=kind, level=normalized_level, location=location.strip(), task=task.strip(),
                status=status, progress_percent=progress_percent, update_text=update_text.strip(),
                constraint_text=(constraint_text or "").strip() or None, next_action=(next_action or "").strip() or None,
            ),
        )

    def update_construction_work(self, report_id: str, item_id: str, **fields) -> ShiftReport:
        report = self.store.get_report(report_id)
        current = self._find(report.construction_work, item_id, "construction work item")
        if "level" in fields and fields["level"] is not None:
            fields["level"] = "".join(str(fields["level"]).split()).upper()
        updated = replace(current, **fields)
        self._validate_construction_work(
            updated.kind, updated.level, updated.location, updated.task, updated.status, updated.progress_percent
        )
        return self.store.update_construction_work(report_id, updated)

    def delete_construction_work(self, report_id: str, item_id: str) -> ShiftReport:
        return self.store.delete_construction_work(report_id, item_id)

    @staticmethod
    def _validate_construction_work(kind: str, level: str, location: str, task: str, status: str, progress_percent: int | None) -> None:
        if kind not in CONSTRUCTION_WORK_KINDS:
            raise MorningError(f"unsupported construction work kind: {kind}")
        if status not in CONSTRUCTION_WORK_STATUSES:
            raise MorningError(f"unsupported construction work status: {status}")
        if re.fullmatch(r"\d+(?:[NS])?", level.upper()) is None:
            raise MorningError("construction level must be numeric with optional N or S, for example 813, 813N or 813S")
        if not location.strip():
            raise MorningError("construction location is required")
        if not task.strip():
            raise MorningError("construction task is required")
        if progress_percent is not None and not 0 <= progress_percent <= 100:
            raise MorningError("construction progress must be between 0 and 100")

    # Stage 5: other activities
    def add_other_activity(self, report_id: str, *, category: str | None, description: str) -> ShiftReport:
        return self.store.add_other_activity(
            report_id,
            OtherActivity(id=new_id("activity"), category=category, description=description),
        )

    def set_empty_section_reviewed(self, report_id: str, *, section: str, reviewed: bool) -> ShiftReport:
        report = self.store.get_report(report_id)
        has_records = {
            "safety": bool(report.stop_fix or report.cards),
            "machine_activity": bool(report.machine_events),
            "other_activities": bool(report.other_activities),
            "construction_work": any(item.kind == "core" for item in report.construction_work),
            "construction_outstanding": any(item.kind == "outstanding" for item in report.construction_work),
        }.get(section)
        if has_records is None:
            raise MorningError(f"unsupported report section: {section}")
        if reviewed and has_records:
            raise MorningError("nothing-to-report can only be selected when the section has no records")
        return self.store.set_empty_section_reviewed(report_id, section, reviewed)

    def delete_other_activity(self, report_id: str, activity_id: str) -> ShiftReport:
        return self.store.delete_other_activity(report_id, activity_id)

    def submit_report(self, report_id: str) -> ShiftReport:
        return self.store.submit_report(report_id)

    def _validate_assignee(self, report: ShiftReport, person_id: str | None) -> None:
        if not person_id:
            raise MorningError("person assigned is required")
        if report.reporting_model != "tmm":
            raise MorningError("machine assignments are only available in TMM reports")
        try:
            person = self.store.get_person(person_id)
        except UnknownRecordError as exc:
            raise MorningError("assigned person is not registered under TMM") from exc
        eligible_ids = {item.id for item in self.store.list_tmm_persons(active_only=True)}
        if not person.active or person.id not in eligible_ids:
            raise MorningError("assigned person must be an active person registered under TMM")

    def whatsapp_text(self, report_id: str) -> str:
        report = self.store.get_report(report_id)
        supervisor = self.store.principal_by_id(report.supervisor_principal_id)
        supervisor_name = supervisor["display_name"] if supervisor is not None else report.supervisor_principal_id
        persons_by_id = {person.id: person for person in self.store.list_persons()}
        machines_by_id = {machine.id: machine for machine in self.store.list_machines()}
        construction_crew = None
        if report.reporting_model == "construction" and report.crew_id:
            try:
                construction_crew = self.store.get_construction_crew(report.crew_id)
            except UnknownRecordError:
                construction_crew = None
        return render_whatsapp_report(
            report,
            supervisor_name=supervisor_name,
            persons_by_id=persons_by_id,
            machines_by_id=machines_by_id,
            timezone=self.shift_policy().timezone,
            machine_states=self.store.list_machine_states(report_id=report_id),
            construction_crew=construction_crew,
        )

    def daily_bundle(self, reporting_date: str, *, require_control_room: bool = True) -> ReportBundle:
        reports = tuple(
            report for report in self.store.list_reports(shift_date=reporting_date)
            if report.status == "submitted" and report.reporting_model == "tmm"
        )
        observations = self.store.list_observations(reporting_date=reporting_date)
        machine_states = tuple(
            state for report in reports for state in self.store.list_machine_states(report_id=report.id)
        )
        machines_by_id = {machine.id: machine for machine in self.store.list_machines()}
        persons_by_id = {person.id: person for person in self.store.list_persons()}
        return build_report_bundle(
            reporting_date=reporting_date,
            timezone=self.shift_policy().timezone,
            shift_reports=reports,
            observations=observations,
            machine_states=machine_states,
            machines_by_id=machines_by_id,
            persons_by_id=persons_by_id,
            require_control_room=require_control_room,
        )

    def detailed_text(self, reporting_date: str, *, require_control_room: bool = True) -> str:
        return render_detailed_report(self.daily_bundle(reporting_date, require_control_room=require_control_room))

    def compact_text(self, reporting_date: str, *, require_control_room: bool = True) -> str:
        return render_compact_report(self.daily_bundle(reporting_date, require_control_room=require_control_room))

    @staticmethod
    def _find(items, item_id: str, label: str):
        found = next((item for item in items if item.id == item_id), None)
        if found is None:
            raise UnknownRecordError(f"unknown {label}: {item_id}")
        return found
