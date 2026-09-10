from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from morning.db import create_database_engine

EXPECTED_TABLES = {
    "alembic_version",
    "morning_accounts",
    "morning_attendance",
    "morning_cards",
    "morning_control_room_observations",
    "morning_crews",
    "morning_machine_events",
    "morning_machine_state_declarations",
    "morning_messages",
    "morning_machines",
    "morning_other_activities",
    "morning_persons",
    "morning_principals",
    "morning_reports",
    "morning_shift_policy",
    "morning_stop_fix",
}


def _config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["MORNING_DATABASE_URL"])
    return config


@pytest.fixture(scope="module", autouse=True)
def migrated_database():
    database_url = os.environ.get("MORNING_DATABASE_URL")
    if not database_url:
        pytest.skip("MORNING_DATABASE_URL is required for migration tests")

    config = _config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield
    command.downgrade(config, "base")

    engine = create_database_engine(database_url)
    try:
        remaining = {name for name in inspect(engine).get_table_names() if name.startswith("morning_")}
        assert remaining == set()
    finally:
        engine.dispose()


def test_initial_schema_and_machine_state_migrations_create_expected_tables() -> None:
    engine = create_database_engine(os.environ["MORNING_DATABASE_URL"])
    try:
        assert EXPECTED_TABLES.issubset(set(inspect(engine).get_table_names()))
    finally:
        engine.dispose()


def test_username_uniqueness_is_database_enforced() -> None:
    engine = create_database_engine(os.environ["MORNING_DATABASE_URL"])
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO morning_principals (id, display_name, role) "
                    "VALUES ('principal-a', 'A', 'supervisor'), ('principal-b', 'B', 'supervisor')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO morning_accounts (principal_id, username, password_hash, password_salt) "
                    "VALUES ('principal-a', 'duplicate', 'hash', 'salt')"
                )
            )
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO morning_accounts (principal_id, username, password_hash, password_salt) "
                        "VALUES ('principal-b', 'duplicate', 'hash', 'salt')"
                    )
                )
    finally:
        engine.dispose()


def test_one_non_abandoned_report_per_supervisor_shift_is_database_enforced() -> None:
    engine = create_database_engine(os.environ["MORNING_DATABASE_URL"])
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO morning_principals (id, display_name, role) "
                    "VALUES ('principal-report', 'Reporter', 'supervisor')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO morning_reports (id, shift_date, shift_kind, supervisor_principal_id, status) "
                    "VALUES ('report-a', DATE '2026-08-28', 'morning', 'principal-report', 'draft')"
                )
            )
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO morning_reports (id, shift_date, shift_kind, supervisor_principal_id, status) "
                        "VALUES ('report-b', DATE '2026-08-28', 'morning', 'principal-report', 'draft')"
                    )
                )
    finally:
        engine.dispose()


def test_machine_event_foreign_keys_and_positive_interval_are_database_enforced() -> None:
    engine = create_database_engine(os.environ["MORNING_DATABASE_URL"])
    try:
        with engine.begin() as connection:
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO morning_machine_events "
                        "(id, report_id, machine_id, start_time, end_time, issue) VALUES "
                        "('bad-event', 'missing-report', 'missing-machine', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'bad')"
                    )
                )
    finally:
        engine.dispose()


def test_machine_state_requires_explicit_other_note_and_honest_carry_provenance() -> None:
    engine = create_database_engine(os.environ["MORNING_DATABASE_URL"])
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO morning_principals (id, display_name, role) VALUES ('state-p', 'S', 'supervisor')"))
            connection.execute(text("INSERT INTO morning_machines (id, machine_id) VALUES ('machine-a', 'RLH1')"))
            connection.execute(
                text(
                    "INSERT INTO morning_reports (id, shift_date, shift_kind, supervisor_principal_id) "
                    "VALUES ('state-report', DATE '2026-08-28', 'morning', 'state-p')"
                )
            )
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO morning_machine_state_declarations "
                        "(id, machine_id, report_id, declared_at, state, provenance) VALUES "
                        "('state-bad-other', 'machine-a', 'state-report', CURRENT_TIMESTAMP, 'other', 'declared')"
                    )
                )
    finally:
        engine.dispose()
