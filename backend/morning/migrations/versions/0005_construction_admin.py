from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_construction_admin"
down_revision: str | None = "0004_construction_reporting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "morning_construction_levels",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("level", name="uq_morning_construction_levels_level"),
    )
    op.create_table(
        "morning_construction_workstreams",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("name", name="uq_morning_construction_workstreams_name"),
    )
    op.create_table(
        "morning_construction_crews",
        sa.Column("crew_id", sa.Text(), sa.ForeignKey("morning_crews.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("workstream_id", sa.Text(), sa.ForeignKey("morning_construction_workstreams.id", ondelete="SET NULL")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_morning_construction_crews_workstream", "morning_construction_crews", ["workstream_id"])


def downgrade() -> None:
    op.drop_index("ix_morning_construction_crews_workstream", table_name="morning_construction_crews")
    op.drop_table("morning_construction_crews")
    op.drop_table("morning_construction_workstreams")
    op.drop_table("morning_construction_levels")
