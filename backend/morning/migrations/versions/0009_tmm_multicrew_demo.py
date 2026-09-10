from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0009_tmm_multicrew_demo"
down_revision: str | None = "0008_three_shift_system"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "morning_principals",
        sa.Column("demo_mode", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_table(
        "morning_report_crews",
        sa.Column("report_id", sa.Text(), sa.ForeignKey("morning_reports.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("crew_id", sa.Text(), sa.ForeignKey("morning_crews.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("position >= 0", name="ck_morning_report_crews_position"),
    )
    op.create_index("ix_morning_report_crews_crew", "morning_report_crews", ["crew_id"])
    op.execute("""
        INSERT INTO morning_report_crews (report_id, crew_id, position)
        SELECT id, crew_id, 0 FROM morning_reports WHERE crew_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.drop_index("ix_morning_report_crews_crew", table_name="morning_report_crews")
    op.drop_table("morning_report_crews")
    op.drop_column("morning_principals", "demo_mode")
