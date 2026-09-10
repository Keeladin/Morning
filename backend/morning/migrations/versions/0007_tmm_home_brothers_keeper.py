from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0007_tmm_home_brothers_keeper"
down_revision: str | None = "0006_admin_workspace_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("morning_reports", sa.Column("brothers_keeper", sa.Text()))
    op.create_table(
        "morning_messages",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("sender_principal_id", sa.Text(), sa.ForeignKey("morning_principals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("recipient_principal_id", sa.Text(), sa.ForeignKey("morning_principals.id", ondelete="RESTRICT")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('direct','announcement')", name="ck_morning_messages_kind"),
        sa.CheckConstraint(
            "(kind='direct' AND recipient_principal_id IS NOT NULL) OR (kind='announcement' AND recipient_principal_id IS NULL)",
            name="ck_morning_messages_recipient",
        ),
        sa.CheckConstraint("length(trim(body)) > 0", name="ck_morning_messages_body"),
    )
    op.create_index("ix_morning_messages_recipient", "morning_messages", ["recipient_principal_id", "created_at"])
    op.create_index("ix_morning_messages_created", "morning_messages", ["kind", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_morning_messages_created", table_name="morning_messages")
    op.drop_index("ix_morning_messages_recipient", table_name="morning_messages")
    op.drop_table("morning_messages")
    op.drop_column("morning_reports", "brothers_keeper")
