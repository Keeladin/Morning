from __future__ import annotations

import argparse
import getpass
from os import environ
import sys

from .accounts import AccountError, MorningAccounts
from .config import ConfigError, Settings
from .store import MorningStore
from .weekly_export import WeeklyAtlasExporter, WeeklyExportError, run_export_scheduler


def _read_password(args: argparse.Namespace) -> str:
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise AccountError("admin password from stdin must not be empty")
        return password
    password = getpass.getpass("Admin password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise AccountError("password confirmation does not match")
    return password


def _bootstrap_admin(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    if settings.database_url is None:
        raise ConfigError("MORNING_DATABASE_URL is required to bootstrap an admin")
    accounts = MorningAccounts(MorningStore(settings.database_url))
    principal = accounts.create_admin(
        username=args.username,
        password=_read_password(args),
        display_name=args.display_name,
    )
    print(f"Created Morning admin {principal.display_name} ({principal.principal_id})")
    return 0


def _atlas_store() -> MorningStore:
    settings = Settings.from_env()
    if settings.database_url is None:
        raise ConfigError("MORNING_DATABASE_URL is required for Atlas export")
    return MorningStore(settings.database_url)


def _atlas_export(args: argparse.Namespace) -> int:
    output = args.output or environ.get("MORNING_ATLAS_EXPORT_DIR", "./atlas-export")
    exporter = WeeklyAtlasExporter(_atlas_store(), output)
    result = exporter.export_week(args.week_start)
    print(f"Published {result.week_id} to {result.output_dir} ({result.report_count} reports)")
    return 0


def _atlas_export_runner(args: argparse.Namespace) -> int:
    output = args.output or environ.get("MORNING_ATLAS_EXPORT_DIR", "./atlas-export")
    lookback = int(environ.get("MORNING_ATLAS_EXPORT_LOOKBACK_WEEKS", "4"))
    poll_seconds = int(environ.get("MORNING_ATLAS_EXPORT_POLL_SECONDS", "900"))
    run_export_scheduler(_atlas_store(), output, lookback_weeks=lookback, poll_seconds=poll_seconds)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="morning")
    commands = parser.add_subparsers(dest="command", required=True)

    bootstrap = commands.add_parser("bootstrap-admin", help="create an approved Morning admin account")
    bootstrap.add_argument("--username", required=True)
    bootstrap.add_argument("--display-name", required=True)
    bootstrap.add_argument(
        "--password-stdin",
        action="store_true",
        help="read one password line from stdin instead of prompting (for controlled automation)",
    )
    bootstrap.set_defaults(handler=_bootstrap_admin)

    atlas_export = commands.add_parser("atlas-export", help="publish one weekly Atlas evidence package")
    atlas_export.add_argument("--week-start", required=True, help="Monday in YYYY-MM-DD format")
    atlas_export.add_argument("--output", help="export root; defaults to MORNING_ATLAS_EXPORT_DIR")
    atlas_export.set_defaults(handler=_atlas_export)

    atlas_runner = commands.add_parser("atlas-export-runner", help="run the Morning weekly Atlas export trigger")
    atlas_runner.add_argument("--output", help="export root; defaults to MORNING_ATLAS_EXPORT_DIR")
    atlas_runner.set_defaults(handler=_atlas_export_runner)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except (AccountError, ConfigError, WeeklyExportError, ValueError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
