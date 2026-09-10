from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from starlette.testclient import TestClient

from morning.app import create_app
from morning.config import Settings
from morning.db import create_database_engine


def _config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["MORNING_DATABASE_URL"])
    return config


@pytest.fixture(scope="module", autouse=True)
def schema() -> None:
    if "MORNING_DATABASE_URL" not in os.environ:
        pytest.skip("MORNING_DATABASE_URL is required for API tests")
    command.upgrade(_config(), "head")


@pytest.fixture()
def client() -> TestClient:
    database_url = os.environ["MORNING_DATABASE_URL"]
    engine = create_database_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE morning_construction_levels, morning_construction_workstreams, morning_principals, morning_crews, morning_machines CASCADE"))
        connection.execute(text("DELETE FROM morning_shift_policy"))
    engine.dispose()
    app = create_app(
        Settings(
            environment="test",
            database_url=database_url,
            session_secret="test-morning-session-secret-with-enough-entropy",
        )
    )
    app.state.morning_store.set_shift_policy(
        timezone="Africa/Johannesburg",
        morning_shift_start="06:00",
        afternoon_shift_start="14:00",
        night_shift_start="22:00",
    )
    return TestClient(app)


def _login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/api/morning/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def _admin(client: TestClient) -> dict:
    client.app.state.morning_accounts.create_admin(
        username="admin",
        password="correct-horse",
        display_name="Morning Admin",
    )
    return _login(client, "admin", "correct-horse")


def _construction_admin(client: TestClient) -> dict:
    client.app.state.morning_accounts.create_admin(
        username="construction-admin",
        password="correct-horse",
        display_name="Construction Admin",
        workspace="construction",
    )
    return _login(client, "construction-admin", "correct-horse")


def _supervisor(client: TestClient, admin_headers: dict[str, str]) -> dict:
    registered = client.post(
        "/api/morning/auth/register",
        json={"username": "jurie", "password": "correct-horse", "display_name": "Jurie Venter"},
    )
    assert registered.status_code == 201
    principal_id = registered.json()["principal"]["principal_id"]
    approved = client.post(
        f"/api/morning/admin/accounts/{principal_id}/approve",
        headers=admin_headers,
    )
    assert approved.status_code == 200, approved.text
    # Login on a separate browser session so creating a supervisor never
    # overwrites the admin cookie carried by the caller's TestClient.
    with TestClient(client.app) as supervisor_client:
        return _login(supervisor_client, "jurie", "correct-horse")


def test_registration_requires_admin_approval(client: TestClient) -> None:
    registered = client.post(
        "/api/morning/auth/register",
        json={"username": "jurie", "password": "correct-horse", "display_name": "Jurie Venter"},
    )
    assert registered.status_code == 201
    assert registered.json()["principal"]["role"] == "supervisor"
    pending = client.post("/api/morning/auth/login", json={"username": "jurie", "password": "correct-horse"})
    assert pending.status_code == 403
    assert pending.json()["pending_approval"] is True


def test_admin_authorization_matrix(client: TestClient) -> None:
    assert client.get("/api/morning/admin/machines").status_code == 401
    admin = _admin(client)
    admin_headers = {"X-CSRF-Token": admin["csrf_token"]}
    _supervisor(client, admin_headers)
    supervisor_client = TestClient(client.app)
    login = supervisor_client.post(
        "/api/morning/auth/login",
        json={"username": "jurie", "password": "correct-horse"},
    )
    assert login.status_code == 200
    assert supervisor_client.get("/api/morning/admin/machines").status_code == 403
    assert client.get("/api/morning/admin/machines").status_code == 200
    assert client.post("/api/morning/admin/machines", json={"machine_id": "RLH1"}).status_code == 403
    created = client.post(
        "/api/morning/admin/machines",
        json={"machine_id": "RLH1", "machine_type": "LHD"},
        headers=admin_headers,
    )
    assert created.status_code == 201


def test_supervisor_full_capture_and_explicit_machine_state(client: TestClient) -> None:
    admin = _admin(client)
    admin_headers = {"X-CSRF-Token": admin["csrf_token"]}
    crew = client.post("/api/morning/admin/crews", json={"name": "Crew A"}, headers=admin_headers).json()
    person = client.post(
        "/api/morning/admin/persons",
        json={"name": "Jurie Venter", "role": "Supervisor", "crew_id": crew["id"]},
        headers=admin_headers,
    ).json()
    machine = client.post(
        "/api/morning/admin/machines",
        json={"machine_id": "RLH1", "machine_type": "LHD"},
        headers=admin_headers,
    ).json()
    supervisor = _supervisor(client, admin_headers)
    principal_id = supervisor["principal"]["principal_id"]
    linked = client.post(
        f"/api/morning/admin/accounts/{principal_id}/link",
        json={"person_id": person["id"]},
        headers=admin_headers,
    )
    assert linked.status_code == 200

    supervisor_client = TestClient(client.app)
    login = supervisor_client.post(
        "/api/morning/auth/login",
        json={"username": "jurie", "password": "correct-horse"},
    ).json()
    headers = {"X-CSRF-Token": login["csrf_token"]}
    report = supervisor_client.post(
        "/api/morning/draft",
        json={"shift_date": "2026-08-28", "shift_kind": "morning", "crew_ids": [crew["id"]]},
        headers=headers,
    )
    assert report.status_code == 201, report.text
    report_id = report.json()["id"]

    attendance = supervisor_client.post(
        f"/api/morning/reports/{report_id}/attendance",
        json={"entries": [{"person_id": person["id"], "present": True}]},
        headers=headers,
    )
    assert attendance.status_code == 200

    brothers = supervisor_client.put(
        f"/api/morning/reports/{report_id}/brothers-keeper",
        json={"contribution": "Improve lighting at the workshop entrance."},
        headers=headers,
    )
    assert brothers.status_code == 200

    safety = supervisor_client.post(
        f"/api/morning/reports/{report_id}/stop-fix",
        json={
            "number": "SF-001",
            "issued_at": "1999-01-01T00:00",
            "area_of_concern": "Support",
            "location": "17L",
            "reason": "Loose rock",
            "instruction": "Make safe",
        },
        headers=headers,
    )
    assert safety.status_code == 201
    assert not safety.json()["stop_fix"][0]["issued_at"].startswith("1999-")

    event = supervisor_client.post(
        f"/api/morning/reports/{report_id}/machine-events",
        json={
            "machine_id": machine["id"],
            "start_hhmm": "10:00",
            "end_hhmm": "10:40",
            "issue": "hydraulic hose",
            "person_id": person["id"],
        },
        headers=headers,
    )
    assert event.status_code == 201, event.text

    other_resolution = supervisor_client.patch(
        f"/api/morning/reports/{report_id}/section-resolution",
        json={"section": "other_activities", "reviewed": True},
        headers=headers,
    )
    assert other_resolution.status_code == 200

    state = supervisor_client.post(
        f"/api/morning/reports/{report_id}/machine-states",
        json={"machine_id": machine["id"], "declared_hhmm": "10:40", "state": "not_tested"},
        headers=headers,
    )
    assert state.status_code == 201, state.text
    assert state.json()["state"] == "not_tested"

    submitted = supervisor_client.post(f"/api/morning/reports/{report_id}/submit", headers=headers)
    assert submitted.status_code == 200
    whatsapp = supervisor_client.get(f"/api/morning/reports/{report_id}/whatsapp")
    assert "Not tested" in whatsapp.json()["text"]
    assert "Total downtime: 40m" in whatsapp.json()["text"]


def test_submission_returns_structured_missing_sections(client: TestClient) -> None:
    admin = _admin(client)
    admin_headers = {"X-CSRF-Token": admin["csrf_token"]}
    crew = client.post("/api/morning/admin/crews", json={"name": "Crew A"}, headers=admin_headers).json()
    person = client.post("/api/morning/admin/persons", json={"name": "Jurie", "crew_id": crew["id"]}, headers=admin_headers).json()
    supervisor = _supervisor(client, admin_headers)
    principal_id = supervisor["principal"]["principal_id"]
    client.post(f"/api/morning/admin/accounts/{principal_id}/link", json={"person_id": person["id"]}, headers=admin_headers)
    browser = TestClient(client.app)
    login = browser.post(
        "/api/morning/auth/login", json={"username": "jurie", "password": "correct-horse"}
    ).json()
    headers = {"X-CSRF-Token": login["csrf_token"]}
    report = browser.post("/api/morning/draft", json={"shift_date": "2026-09-01", "shift_kind": "morning", "crew_ids": [crew["id"]]}, headers=headers).json()
    response = browser.post(f"/api/morning/reports/{report['id']}/submit", headers=headers)
    assert response.status_code == 409
    assert response.json()["missing_sections"] == ["attendance", "safety", "brothers_keeper", "machine_activity", "other_activities"]


def test_supervisor_cannot_read_another_supervisors_report(client: TestClient) -> None:
    admin = _admin(client)
    admin_headers = {"X-CSRF-Token": admin["csrf_token"]}
    crew = client.post("/api/morning/admin/crews", json={"name": "Ownership Crew"}, headers=admin_headers).json()
    _supervisor(client, admin_headers)
    first_client = TestClient(client.app)
    first_login = first_client.post(
        "/api/morning/auth/login",
        json={"username": "jurie", "password": "correct-horse"},
    ).json()
    first_report = first_client.post(
        "/api/morning/draft",
        json={"shift_date": "2026-08-28", "shift_kind": "morning", "crew_ids": [crew["id"]]},
        headers={"X-CSRF-Token": first_login["csrf_token"]},
    ).json()

    registered = client.post(
        "/api/morning/auth/register",
        json={"username": "lyle", "password": "correct-horse", "display_name": "Lyle"},
    ).json()
    approved = client.post(
        f"/api/morning/admin/accounts/{registered['principal']['principal_id']}/approve",
        headers=admin_headers,
    )
    assert approved.status_code == 200
    other = TestClient(client.app)
    login = other.post("/api/morning/auth/login", json={"username": "lyle", "password": "correct-horse"})
    assert login.status_code == 200
    assert other.get(f"/api/morning/reports/{first_report['id']}").status_code == 404


def test_construction_admin_configuration_api(client: TestClient) -> None:
    admin = _construction_admin(client)
    headers = {"X-CSRF-Token": admin["csrf_token"]}
    level = client.post("/api/morning/admin/construction/levels", json={"level": "8 1 3"}, headers=headers)
    assert level.status_code == 201, level.text
    edited = client.patch(
        f"/api/morning/admin/construction/levels/{level.json()['id']}",
        json={"level": "8 3 9"},
        headers=headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["level"] == "839"
    stream = client.post("/api/morning/admin/construction/workstreams", json={"name": "Main Construction"}, headers=headers)
    assert stream.status_code == 201, stream.text
    crew = client.post(
        "/api/morning/admin/construction/crews",
        json={"name": "Construction Crew 1", "workstream_id": stream.json()["id"]},
        headers=headers,
    )
    assert crew.status_code == 201, crew.text
    person = client.post(
        "/api/morning/admin/construction/persons",
        json={"name": "Alex Builder", "role": "Boilermaker", "crew_id": crew.json()["crew_id"]},
        headers=headers,
    )
    assert person.status_code == 201, person.text
    config = client.get("/api/morning/admin/construction/config")
    assert config.status_code == 200
    body = config.json()
    assert [item["level"] for item in body["levels"]] == ["839"]
    assert body["crews"][0]["workstream_name"] == "Main Construction"
    assert body["persons"][0]["name"] == "Alex Builder"


def test_admin_workspaces_are_strictly_separated(client: TestClient) -> None:
    morning = _admin(client)
    morning_headers = {"X-CSRF-Token": morning["csrf_token"]}
    assert client.get("/api/morning/admin/machines").status_code == 200
    assert client.get("/api/morning/admin/construction/config").status_code == 403

    construction_client = TestClient(client.app)
    construction_client.app.state.morning_accounts.create_admin(
        username="construction-admin", password="correct-horse", display_name="Construction Admin", workspace="construction"
    )
    construction = _login(construction_client, "construction-admin", "correct-horse")
    construction_headers = {"X-CSRF-Token": construction["csrf_token"]}
    assert construction_client.get("/api/morning/admin/construction/config").status_code == 200
    assert construction_client.get("/api/morning/admin/machines").status_code == 403
    assert client.post("/api/morning/admin/construction/levels", json={"level":"813N"}, headers=morning_headers).status_code == 403
    assert construction_client.post("/api/morning/admin/machines", json={"machine_id":"RLH9"}, headers=construction_headers).status_code == 403


def test_morning_admin_can_only_bootstrap_first_construction_admin(client: TestClient) -> None:
    morning = _admin(client)
    headers = {"X-CSRF-Token": morning["csrf_token"]}
    status = client.get("/api/morning/admin/construction/bootstrap-status")
    assert status.status_code == 200 and status.json()["available"] is True
    created = client.post(
        "/api/morning/admin/construction/bootstrap",
        json={"username":"build-admin","password":"correct-horse","display_name":"Build Admin"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["admin_workspace"] == "construction"
    assert client.get("/api/morning/admin/construction/bootstrap-status").json()["available"] is False
    duplicate = client.post(
        "/api/morning/admin/construction/bootstrap",
        json={"username":"build-admin-2","password":"correct-horse","display_name":"Build Admin 2"},
        headers=headers,
    )
    assert duplicate.status_code == 409


def test_offline_snapshot_sync_is_idempotent(client: TestClient) -> None:
    admin = _admin(client)
    admin_headers = {"X-CSRF-Token": admin["csrf_token"]}
    crew = client.post("/api/morning/admin/crews", json={"name": "Offline Crew"}, headers=admin_headers).json()
    person = client.post(
        "/api/morning/admin/persons",
        json={"name": "Lyle", "role": "Supervisor", "crew_id": crew["id"]},
        headers=admin_headers,
    ).json()
    machine = client.post(
        "/api/morning/admin/machines", json={"machine_id": "RLH7", "machine_type": "LHD"}, headers=admin_headers
    ).json()
    supervisor = _supervisor(client, admin_headers)
    principal_id = supervisor["principal"]["principal_id"]
    client.post(
        f"/api/morning/admin/accounts/{principal_id}/link", json={"person_id": person["id"]}, headers=admin_headers
    )
    browser = TestClient(client.app)
    login = browser.post("/api/morning/auth/login", json={"username": "jurie", "password": "correct-horse"}).json()
    headers = {"X-CSRF-Token": login["csrf_token"]}
    snapshot = {
        "id": "offline_local_report",
        "shift_date": "2026-09-02", "shift_kind": "morning", "reporting_model": "tmm", "crew_ids": [crew["id"]],
        "attendance": [{"person_id": person["id"], "present": True}],
        "stop_fix": [{
            "id": "offline_sf_1", "number": "SF-77", "issued_at": "2026-09-02T08:10:00+02:00",
            "area_of_concern": "Support", "location": "813L", "reason": "Loose rock",
            "instruction": "Make safe", "status": "open", "rectified_at": None,
        }],
        "cards": [],
        "machine_events": [{
            "id": "offline_event_1", "machine_id": machine["id"], "start_time": "08:20", "end_time": "08:45",
            "issue": "Hydraulic hose", "person_id": person["id"],
        }],
        "construction_work": [], "other_activities": [],
        "brothers_keeper": "Improve access lighting.",
        "safety_reviewed_empty": False, "machine_activity_reviewed_empty": False,
        "other_activities_reviewed_empty": True,
        "construction_work_reviewed_empty": False, "construction_outstanding_reviewed_empty": False,
    }
    first = browser.post("/api/morning/offline-sync", json={"report": snapshot, "submit": True}, headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "submitted"
    assert len(body["stop_fix"]) == 1
    assert len(body["machine_events"]) == 1

    second = browser.post("/api/morning/offline-sync", json={"report": snapshot, "submit": True}, headers=headers)
    assert second.status_code == 200, second.text
    repeated = second.json()
    assert repeated["id"] == body["id"]
    assert len(repeated["stop_fix"]) == 1
    assert len(repeated["machine_events"]) == 1


def test_tmm_home_messages_notice_board_and_department_personnel_pool(client: TestClient) -> None:
    admin = _admin(client)
    admin_headers = {"X-CSRF-Token": admin["csrf_token"]}
    crew_a = client.post("/api/morning/admin/crews", json={"name": "Crew A"}, headers=admin_headers).json()
    crew_b = client.post("/api/morning/admin/crews", json={"name": "Crew B"}, headers=admin_headers).json()
    jurie_person = client.post("/api/morning/admin/persons", json={"name": "Jurie", "role": "Supervisor", "crew_id": crew_a["id"]}, headers=admin_headers).json()
    helper = client.post("/api/morning/admin/persons", json={"name": "Cross-crew Artisan", "role": "Fitter", "crew_id": crew_b["id"]}, headers=admin_headers).json()

    jurie = _supervisor(client, admin_headers)
    jurie_id = jurie["principal"]["principal_id"]
    client.post(f"/api/morning/admin/accounts/{jurie_id}/link", json={"person_id": jurie_person["id"]}, headers=admin_headers)

    registered = client.post("/api/morning/auth/register", json={"username": "lyle", "password": "correct-horse", "display_name": "Lyle Supervisor"}).json()
    lyle_id = registered["principal"]["principal_id"]
    client.post(f"/api/morning/admin/accounts/{lyle_id}/approve", headers=admin_headers)

    jurie_browser = TestClient(client.app)
    jurie_login = jurie_browser.post("/api/morning/auth/login", json={"username": "jurie", "password": "correct-horse"}).json()
    jurie_headers = {"X-CSRF-Token": jurie_login["csrf_token"]}
    pool = jurie_browser.get("/api/morning/personnel")
    assert pool.status_code == 200
    assert {item["id"] for item in pool.json()["people"]} >= {jurie_person["id"], helper["id"]}

    report = jurie_browser.post("/api/morning/draft", json={"shift_date": "2026-09-10", "shift_kind": "morning", "crew_ids": [crew_a["id"]]}, headers=jurie_headers).json()
    jurie_browser.post(f"/api/morning/reports/{report['id']}/attendance", json={"entries": [{"person_id": jurie_person["id"], "present": True}]}, headers=jurie_headers)
    jurie_browser.put(f"/api/morning/reports/{report['id']}/brothers-keeper", json={"contribution": "Improve pedestrian separation at the workshop."}, headers=jurie_headers)
    for section in ("safety", "machine_activity", "other_activities"):
        jurie_browser.patch(f"/api/morning/reports/{report['id']}/section-resolution", json={"section": section, "reviewed": True}, headers=jurie_headers)
    submitted = jurie_browser.post(f"/api/morning/reports/{report['id']}/submit", headers=jurie_headers)
    assert submitted.status_code == 200, submitted.text

    direct = jurie_browser.post("/api/morning/messages", json={"recipient_principal_id": lyle_id, "body": "Please check the handover."}, headers=jurie_headers)
    notice = jurie_browser.post("/api/morning/announcements", json={"body": "Workshop briefing at shift start."}, headers=jurie_headers)
    assert direct.status_code == 201 and notice.status_code == 201

    lyle_browser = TestClient(client.app)
    lyle_login = lyle_browser.post("/api/morning/auth/login", json={"username": "lyle", "password": "correct-horse"}).json()
    lyle_headers = {"X-CSRF-Token": lyle_login["csrf_token"]}
    home = lyle_browser.get("/api/morning/home")
    assert home.status_code == 200, home.text
    payload = home.json()
    assert payload["recent_reports"][0]["id"] == report["id"]
    assert "*Brothers Keeper*\nImprove pedestrian separation at the workshop." in payload["recent_reports"][0]["summary_text"]
    assert payload["announcements"][0]["body"] == "Workshop briefing at shift start."
    assert payload["messages"][0]["body"] == "Please check the handover."
    assert payload["unread_count"] == 1
    marked = lyle_browser.post(f"/api/morning/messages/{direct.json()['id']}/read", headers=lyle_headers)
    assert marked.status_code == 200
    assert lyle_browser.get("/api/morning/home").json()["unread_count"] == 0


def test_admin_can_edit_and_delete_unused_configuration(client: TestClient) -> None:
    admin = _admin(client)
    headers = {"X-CSRF-Token": admin["csrf_token"]}
    machine = client.post("/api/morning/admin/machines", json={"machine_id": "TEMP1"}, headers=headers).json()
    edited_machine = client.patch(f"/api/morning/admin/machines/{machine['id']}", json={"machine_id": "TEMP2", "machine_type": "LHD", "section": "North"}, headers=headers)
    assert edited_machine.status_code == 200
    assert edited_machine.json()["machine_id"] == "TEMP2"
    assert client.delete(f"/api/morning/admin/machines/{machine['id']}", headers=headers).status_code == 200

    person = client.post("/api/morning/admin/persons", json={"name": "Temporary Person"}, headers=headers).json()
    edited_person = client.patch(f"/api/morning/admin/persons/{person['id']}", json={"name": "Temporary Artisan", "role": "Auto Electrician", "employee_number": "T123"}, headers=headers)
    assert edited_person.status_code == 200
    assert edited_person.json()["role"] == "Auto Electrician"
    assert client.delete(f"/api/morning/admin/persons/{person['id']}", headers=headers).status_code == 200

    registered = client.post("/api/morning/auth/register", json={"username": "temp-supervisor", "password": "correct-horse", "display_name": "Temp Supervisor"}).json()
    principal_id = registered["principal"]["principal_id"]
    edited_supervisor = client.patch(f"/api/morning/admin/accounts/{principal_id}", json={"display_name": "Edited Supervisor", "username": "edited-supervisor"}, headers=headers)
    assert edited_supervisor.status_code == 200
    assert edited_supervisor.json()["display_name"] == "Edited Supervisor"
    assert edited_supervisor.json()["username"] == "edited-supervisor"
    assert client.post(f"/api/morning/admin/accounts/{principal_id}/deactivate", headers=headers).json()["status"] == "suspended"
    assert client.post(f"/api/morning/admin/accounts/{principal_id}/activate", headers=headers).json()["status"] == "active"
    assert client.delete(f"/api/morning/admin/accounts/{principal_id}", headers=headers).status_code == 200


def test_tmm_multicrew_selection_combines_roster(client: TestClient) -> None:
    admin = _admin(client)
    admin_headers = {"X-CSRF-Token": admin["csrf_token"]}
    crew_a = client.post("/api/morning/admin/crews", json={"name": "Crew A"}, headers=admin_headers).json()
    crew_b = client.post("/api/morning/admin/crews", json={"name": "Crew B"}, headers=admin_headers).json()
    person_a = client.post("/api/morning/admin/persons", json={"name": "Artisan A", "crew_id": crew_a["id"]}, headers=admin_headers).json()
    person_b = client.post("/api/morning/admin/persons", json={"name": "Artisan B", "crew_id": crew_b["id"]}, headers=admin_headers).json()
    _supervisor(client, admin_headers)
    browser = TestClient(client.app)
    login = browser.post("/api/morning/auth/login", json={"username": "jurie", "password": "correct-horse"}).json()
    headers = {"X-CSRF-Token": login["csrf_token"]}
    report = browser.post("/api/morning/draft", json={"shift_date": "2026-09-10", "shift_kind": "morning", "crew_ids": [crew_a["id"], crew_b["id"]]}, headers=headers)
    assert report.status_code == 201, report.text
    body = report.json()
    assert body["crew_ids"] == [crew_a["id"], crew_b["id"]]
    roster = browser.get(f"/api/morning/roster?report_id={body['id']}")
    assert roster.status_code == 200, roster.text
    assert {item["id"] for item in roster.json()["people"]} == {person_a["id"], person_b["id"]}


def test_crew_delete_blocks_referenced_and_removes_unused(client: TestClient) -> None:
    admin = _admin(client)
    headers = {"X-CSRF-Token": admin["csrf_token"]}
    used = client.post("/api/morning/admin/crews", json={"name": "Used Crew"}, headers=headers).json()
    client.post("/api/morning/admin/persons", json={"name": "Assigned Person", "crew_id": used["id"]}, headers=headers)
    blocked = client.delete(f"/api/morning/admin/crews/{used['id']}", headers=headers)
    assert blocked.status_code == 400
    assert "personnel assigned" in blocked.json()["error"]
    unused = client.post("/api/morning/admin/crews", json={"name": "Unused Crew"}, headers=headers).json()
    removed = client.delete(f"/api/morning/admin/crews/{unused['id']}", headers=headers)
    assert removed.status_code == 200, removed.text


def test_demo_supervisor_cannot_write_operational_report(client: TestClient) -> None:
    admin = _admin(client)
    admin_headers = {"X-CSRF-Token": admin["csrf_token"]}
    crew = client.post("/api/morning/admin/crews", json={"name": "Demo Crew"}, headers=admin_headers).json()
    registered = client.post("/api/morning/auth/register", json={"username": "demo", "password": "correct-horse", "display_name": "Demo Supervisor"}).json()
    principal_id = registered["principal"]["principal_id"]
    client.post(f"/api/morning/admin/accounts/{principal_id}/approve", headers=admin_headers)
    toggled = client.patch(f"/api/morning/admin/accounts/{principal_id}", json={"demo_mode": True}, headers=admin_headers)
    assert toggled.status_code == 200, toggled.text
    browser = TestClient(client.app)
    login = browser.post("/api/morning/auth/login", json={"username": "demo", "password": "correct-horse"})
    assert login.status_code == 200, login.text
    assert login.json()["principal"]["demo_mode"] is True
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}
    write = browser.post("/api/morning/draft", json={"shift_date": "2026-09-10", "shift_kind": "morning", "crew_ids": [crew["id"]]}, headers=headers)
    assert write.status_code == 403
    assert browser.get("/api/morning/home").json()["recent_reports"] == []
    engine = create_database_engine(os.environ["MORNING_DATABASE_URL"])
    try:
        with engine.begin() as connection:
            assert connection.execute(text("SELECT count(*) FROM morning_reports")).scalar_one() == 0
    finally:
        engine.dispose()
