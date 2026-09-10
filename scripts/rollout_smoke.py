#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import uuid

import httpx


BASE_URL = os.environ.get("MORNING_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
ADMIN_USERNAME = os.environ.get("MORNING_SMOKE_ADMIN_USERNAME", "smoke-admin")
ADMIN_PASSWORD = os.environ.get("MORNING_SMOKE_ADMIN_PASSWORD", "")
SUPERVISOR_PASSWORD = os.environ.get("MORNING_SMOKE_SUPERVISOR_PASSWORD", "Morning-Smoke-123!")


def fail(message: str) -> None:
    raise RuntimeError(message)


def wait_ready() -> None:
    deadline = time.monotonic() + 90
    last = ""
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{BASE_URL}/healthz", timeout=3)
            if response.status_code == 200:
                payload = response.json()
                if payload.get("status") == "ok" and payload.get("application_ready") is True:
                    return
                last = repr(payload)
            else:
                last = f"HTTP {response.status_code}: {response.text}"
        except Exception as exc:  # noqa: BLE001 - surface the final readiness reason
            last = str(exc)
        time.sleep(2)
    fail(f"Morning did not become ready: {last}")


def api(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    csrf: str | None = None,
    payload: dict | None = None,
    expected: tuple[int, ...] = (200,),
):
    headers = {"X-CSRF-Token": csrf} if csrf else {}
    response = client.request(method, f"{BASE_URL}{path}", json=payload, headers=headers, timeout=15)
    if response.status_code not in expected:
        fail(f"{method} {path} -> {response.status_code}: {response.text}")
    if not response.content:
        return None
    return response.json()


def login(client: httpx.Client, username: str, password: str) -> tuple[dict, str]:
    result = api(
        client,
        "POST",
        "/api/morning/auth/login",
        payload={"username": username, "password": password},
    )
    csrf = result.get("csrf_token")
    if not csrf:
        fail(f"login for {username} returned no CSRF token")
    return result, csrf


def submit_shift(
    client: httpx.Client,
    *,
    csrf: str,
    shift_date: str,
    shift_kind: str,
    person_id: str,
    machine_id: str,
    with_detail: bool,
) -> str:
    report = api(
        client,
        "POST",
        "/api/morning/draft",
        csrf=csrf,
        payload={"shift_date": shift_date, "shift_kind": shift_kind},
        expected=(200, 201),
    )
    report_id = report["id"]

    api(
        client,
        "POST",
        f"/api/morning/reports/{report_id}/attendance",
        csrf=csrf,
        payload={"entries": [{"person_id": person_id, "present": True}]},
    )

    if with_detail:
        api(
            client,
            "POST",
            f"/api/morning/reports/{report_id}/stop-fix",
            csrf=csrf,
            payload={
                "number": "SMOKE-001",
                "area_of_concern": "Transport and Tramming",
                "location": "Smoke test area",
                "reason": "Rollout verification",
                "instruction": "Verify deterministic capture",
            },
            expected=(201,),
        )
        api(
            client,
            "POST",
            f"/api/morning/reports/{report_id}/cards",
            csrf=csrf,
            payload={"card_type": "green", "reason": "Smoke test safe behaviour"},
            expected=(201,),
        )

    start_hhmm, end_hhmm, state_hhmm = {
        "morning": ("07:00", "08:00", "13:30"),
        "afternoon": ("15:00", "16:00", "21:30"),
        "night": ("23:00", "23:30", "05:30"),
    }[shift_kind]
    api(
        client,
        "POST",
        f"/api/morning/reports/{report_id}/machine-events",
        csrf=csrf,
        payload={
            "machine_id": machine_id,
            "start_hhmm": start_hhmm,
            "end_hhmm": end_hhmm,
            "issue": "Smoke test engineering activity",
            "person_id": person_id,
        },
        expected=(201,),
    )
    api(
        client,
        "POST",
        f"/api/morning/reports/{report_id}/machine-states",
        csrf=csrf,
        payload={
            "machine_id": machine_id,
            "declared_hhmm": state_hhmm,
            "state": "running",
            "state_note": None,
            "follow_up": None,
        },
        expected=(201,),
    )
    if with_detail:
        api(
            client,
            "POST",
            f"/api/morning/reports/{report_id}/other-activities",
            csrf=csrf,
            payload={"category": "Inspections", "description": "Rollout smoke inspection completed"},
            expected=(201,),
        )
    else:
        for section in ("safety", "other_activities"):
            api(
                client,
                "PATCH",
                f"/api/morning/reports/{report_id}/section-resolution",
                csrf=csrf,
                payload={"section": section, "reviewed": True},
            )

    submitted = api(
        client,
        "POST",
        f"/api/morning/reports/{report_id}/submit",
        csrf=csrf,
        payload={},
    )
    if submitted.get("status") != "submitted":
        fail(f"report {report_id} did not submit")
    whatsapp = api(client, "GET", f"/api/morning/reports/{report_id}/whatsapp")
    if "Machine Activity" not in whatsapp.get("text", ""):
        fail("WhatsApp projection did not contain machine activity")
    return report_id


def main() -> int:
    if os.environ.get("MORNING_SMOKE_ALLOW_MUTATION") != "1":
        print("Refusing to mutate Morning. Set MORNING_SMOKE_ALLOW_MUTATION=1 for a clean CI/staging database.", file=sys.stderr)
        return 2
    if not ADMIN_PASSWORD:
        print("MORNING_SMOKE_ADMIN_PASSWORD is required", file=sys.stderr)
        return 2

    wait_ready()
    suffix = uuid.uuid4().hex[:8]
    supervisor_username = f"smoke-supervisor-{suffix}"

    with httpx.Client(follow_redirects=True) as admin:
        admin_login, admin_csrf = login(admin, ADMIN_USERNAME, ADMIN_PASSWORD)
        if admin_login.get("principal", {}).get("role") != "admin":
            fail("smoke admin did not authenticate with admin role")

        crew = api(
            admin,
            "POST",
            "/api/morning/admin/crews",
            csrf=admin_csrf,
            payload={"name": f"Smoke Crew {suffix}"},
            expected=(201,),
        )
        machine = api(
            admin,
            "POST",
            "/api/morning/admin/machines",
            csrf=admin_csrf,
            payload={
                "machine_id": "STC14",
                "machine_type": "LHD",
                "section": "Smoke",
                "control_room_scope": True,
            },
            expected=(201,),
        )
        person = api(
            admin,
            "POST",
            "/api/morning/admin/persons",
            csrf=admin_csrf,
            payload={
                "name": f"Smoke Supervisor {suffix}",
                "employee_number": f"SMOKE-{suffix}",
                "role": "Shift Supervisor",
                "crew_id": crew["id"],
            },
            expected=(201,),
        )

        with httpx.Client(follow_redirects=True) as supervisor:
            registration = api(
                supervisor,
                "POST",
                "/api/morning/auth/register",
                payload={
                    "username": supervisor_username,
                    "password": SUPERVISOR_PASSWORD,
                    "display_name": f"Smoke Supervisor {suffix}",
                },
                expected=(201,),
            )
            principal_id = registration["principal"]["principal_id"]

            api(
                admin,
                "POST",
                f"/api/morning/admin/accounts/{principal_id}/approve",
                csrf=admin_csrf,
                payload={},
            )
            api(
                admin,
                "POST",
                f"/api/morning/admin/accounts/{principal_id}/link",
                csrf=admin_csrf,
                payload={"person_id": person["id"]},
            )

            supervisor_login, supervisor_csrf = login(supervisor, supervisor_username, SUPERVISOR_PASSWORD)
            if supervisor_login.get("principal", {}).get("role") != "supervisor":
                fail("registered account did not authenticate with supervisor role")

            suggestion = api(supervisor, "GET", "/api/morning/shift")
            shift_date = suggestion["shift_date"]
            morning_report = submit_shift(
                supervisor,
                csrf=supervisor_csrf,
                shift_date=shift_date,
                shift_kind="morning",
                person_id=person["id"],
                machine_id=machine["id"],
                with_detail=True,
            )
            afternoon_report = submit_shift(
                supervisor,
                csrf=supervisor_csrf,
                shift_date=shift_date,
                shift_kind="afternoon",
                person_id=person["id"],
                machine_id=machine["id"],
                with_detail=False,
            )
            night_report = submit_shift(
                supervisor,
                csrf=supervisor_csrf,
                shift_date=shift_date,
                shift_kind="night",
                person_id=person["id"],
                machine_id=machine["id"],
                with_detail=False,
            )

        control_room = api(
            admin,
            "POST",
            "/api/morning/admin/control-room/ingest",
            csrf=admin_csrf,
            payload={
                "reporting_date": shift_date,
                "source_message_id": f"smoke-control-room-{suffix}",
                "text": "07:38Brakes MechanicalMaintenance/Service/Pitstop 08:38 01:00 Brake testAxleSTC-14",
            },
            expected=(201,),
        )
        if len(control_room.get("observations", [])) != 1:
            fail("control-room smoke input did not produce exactly one observation")

        daily = api(admin, "GET", f"/api/morning/admin/reports/{shift_date}")
        if daily.get("status") != "complete":
            fail(f"24-hour report is not complete: {daily.get('expected_inputs')}")
        if "downtime" in daily.get("compact_text", "").casefold():
            fail("compact report regressed to calling engineering work downtime")

        teams = api(admin, "GET", f"/api/morning/admin/reports/{shift_date}/teams")
        if teams.get("status") != "complete":
            fail("Teams projection was not complete")
        cells = {item["cell"]: item["value"] for item in teams["teams_projection"]["machine_cells"]}
        if cells.get("L114") != f"{3600 / 86400:.6f}":
            fail(f"Teams duration did not come from the 1h control-room delay: {cells.get('L114')}")
        if "J114" not in cells:
            fail("Teams projection did not include STC14 remark cell")

    print(
        json.dumps(
            {
                "status": "ok",
                "base_url": BASE_URL,
                "shift_date": shift_date,
                "morning_report": morning_report,
                "afternoon_report": afternoon_report,
                "night_report": night_report,
                "teams_duration_cell": cells["L114"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
