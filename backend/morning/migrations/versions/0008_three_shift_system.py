from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0008_three_shift_system"
down_revision: str | None = "0007_tmm_home_brothers_keeper"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "morning_shift_policy", "day_shift_start",
        new_column_name="morning_shift_start",
        existing_type=sa.Time(), existing_nullable=False,
    )
    op.add_column(
        "morning_shift_policy",
        sa.Column("afternoon_shift_start", sa.Time(), nullable=False, server_default=sa.text("TIME '14:00'")),
    )
    op.execute("UPDATE morning_shift_policy SET night_shift_start = TIME '22:00'")
    op.execute(
        """INSERT INTO morning_shift_policy
               (id, timezone, morning_shift_start, afternoon_shift_start, night_shift_start, updated_at)
           VALUES ('default', 'Africa/Johannesburg', TIME '06:00', TIME '14:00', TIME '22:00', CURRENT_TIMESTAMP)
           ON CONFLICT (id) DO NOTHING"""
    )
    op.drop_constraint("ck_morning_reports_shift_kind", "morning_reports", type_="check")
    op.create_check_constraint(
        "ck_morning_reports_shift_kind", "morning_reports",
        "shift_kind IN ('morning','afternoon','night')",
    )


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM morning_reports) THEN
                RAISE EXCEPTION 'cannot downgrade three-shift schema while reports exist';
            END IF;
        END $$;
    """)
    op.drop_constraint("ck_morning_reports_shift_kind", "morning_reports", type_="check")
    op.create_check_constraint(
        "ck_morning_reports_shift_kind", "morning_reports",
        "shift_kind IN ('day','night')",
    )
    op.drop_column("morning_shift_policy", "afternoon_shift_start")
    op.alter_column(
        "morning_shift_policy", "morning_shift_start",
        new_column_name="day_shift_start",
        existing_type=sa.Time(), existing_nullable=False,
    )
