from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from morning.accounts import AccountError, MorningAccounts, PendingApprovalError
from morning.db import create_database_engine
from morning.store import MorningStore


def _config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["MORNING_DATABASE_URL"])
    return config


@pytest.fixture(scope="module", autouse=True)
def schema() -> None:
    if "MORNING_DATABASE_URL" not in os.environ:
        pytest.skip("MORNING_DATABASE_URL is required for account tests")
    command.upgrade(_config(), "head")


@pytest.fixture()
def accounts() -> MorningAccounts:
    database_url = os.environ["MORNING_DATABASE_URL"]
    engine = create_database_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE morning_construction_levels, morning_construction_workstreams, morning_principals, morning_crews, morning_machines CASCADE"))
    engine.dispose()
    return MorningAccounts(MorningStore(database_url))


def test_register_creates_morning_owned_supervisor_principal(accounts: MorningAccounts) -> None:
    principal = accounts.register(username="lyle", password="correct-horse", display_name="Lyle")
    assert principal.display_name == "Lyle"
    assert principal.role == "supervisor"
    assert principal.status == "active"


def test_duplicate_username_is_rejected_case_insensitively(accounts: MorningAccounts) -> None:
    accounts.register(username="lyle", password="correct-horse", display_name="Lyle")
    with pytest.raises(AccountError):
        accounts.register(username="Lyle", password="another-password", display_name="Someone Else")


def test_duplicate_supervisor_name_is_rejected_even_with_a_different_username(accounts: MorningAccounts) -> None:
    accounts.register(username="jurie-first", password="correct-horse", display_name="Jurie Venter")
    with pytest.raises(AccountError, match="already registered for this full name"):
        accounts.register(
            username="jurie-second",
            password="another-password",
            display_name="  jurie venter  ",
        )


def test_short_password_is_rejected(accounts: MorningAccounts) -> None:
    with pytest.raises(AccountError):
        accounts.register(username="jurie", password="short", display_name="Jurie")


def test_registration_does_not_grant_login_until_admin_approves(accounts: MorningAccounts) -> None:
    accounts.register(username="jurie", password="correct-horse", display_name="Jurie Venter")
    with pytest.raises(PendingApprovalError):
        accounts.authenticate(username="jurie", password="correct-horse")


def test_approve_then_authenticate_case_insensitively(accounts: MorningAccounts) -> None:
    registered = accounts.register(username="jurie", password="correct-horse", display_name="Jurie Venter")
    assert len(accounts.list_pending()) == 1
    accounts.approve(registered.principal_id)
    authenticated = accounts.authenticate(username="JURIE", password="correct-horse")
    assert authenticated.principal_id == registered.principal_id
    assert accounts.list_pending() == ()


def test_wrong_password_is_rejected(accounts: MorningAccounts) -> None:
    registered = accounts.register(username="jurie", password="correct-horse", display_name="Jurie Venter")
    accounts.approve(registered.principal_id)
    with pytest.raises(AccountError):
        accounts.authenticate(username="jurie", password="wrong-password")


def test_suspended_principal_cannot_authenticate(accounts: MorningAccounts) -> None:
    registered = accounts.register(username="jurie", password="correct-horse", display_name="Jurie Venter")
    accounts.approve(registered.principal_id)
    accounts.identities.set_status(registered.principal_id, "suspended")
    with pytest.raises(AccountError):
        accounts.authenticate(username="jurie", password="correct-horse")
