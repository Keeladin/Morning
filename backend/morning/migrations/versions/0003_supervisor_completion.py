from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_supervisor_completion"
down_revision: str | None = "0002_machine_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("morning_reports", sa.Column("safety_reviewed_empty", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("morning_reports", sa.Column("machine_activity_reviewed_empty", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("morning_reports", sa.Column("other_activities_reviewed_empty", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("morning_machine_events", sa.Column("person_id", sa.Text(), sa.ForeignKey("morning_persons.id", ondelete="RESTRICT")))


def downgrade() -> None:
    op.drop_column("morning_machine_events", "person_id")
    op.drop_column("morning_reports", "other_activities_reviewed_empty")
    op.drop_column("morning_reports", "machine_activity_reviewed_empty")
    op.drop_column("morning_reports", "safety_reviewed_empty")
