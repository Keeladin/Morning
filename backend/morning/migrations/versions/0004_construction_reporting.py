from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_construction_reporting"
down_revision: str | None = "0003_supervisor_completion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "morning_reports",
        sa.Column("reporting_model", sa.Text(), nullable=False, server_default=sa.text("'tmm'")),
    )
    op.add_column("morning_reports", sa.Column("construction_work_reviewed_empty", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("morning_reports", sa.Column("construction_outstanding_reviewed_empty", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_check_constraint(
        "ck_morning_reports_reporting_model",
        "morning_reports",
        "reporting_model IN ('tmm','construction')",
    )
    op.drop_index("uq_morning_reports_open_slot", table_name="morning_reports")
    op.create_index(
        "uq_morning_reports_open_slot",
        "morning_reports",
        ["shift_date", "shift_kind", "supervisor_principal_id", "reporting_model"],
        unique=True,
        postgresql_where=sa.text("status <> 'abandoned'"),
    )
    op.create_table(
        "morning_construction_work",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("report_id", sa.Text(), sa.ForeignKey("morning_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'in_progress'")),
        sa.Column("progress_percent", sa.Integer()),
        sa.Column("update_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("constraint_text", sa.Text()),
        sa.Column("next_action", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("kind IN ('core','outstanding')", name="ck_morning_construction_work_kind"),
        sa.CheckConstraint("status IN ('not_started','in_progress','held','complete')", name="ck_morning_construction_work_status"),
        sa.CheckConstraint("progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)", name="ck_morning_construction_work_progress"),
    )
    op.create_index("ix_morning_construction_work_report", "morning_construction_work", ["report_id"])


def downgrade() -> None:
    op.drop_index("ix_morning_construction_work_report", table_name="morning_construction_work")
    op.drop_table("morning_construction_work")
    op.drop_index("uq_morning_reports_open_slot", table_name="morning_reports")
    op.create_index(
        "uq_morning_reports_open_slot",
        "morning_reports",
        ["shift_date", "shift_kind", "supervisor_principal_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'abandoned'"),
    )
    op.drop_constraint("ck_morning_reports_reporting_model", "morning_reports", type_="check")
    op.drop_column("morning_reports", "construction_outstanding_reviewed_empty")
    op.drop_column("morning_reports", "construction_work_reviewed_empty")
    op.drop_column("morning_reports", "reporting_model")
