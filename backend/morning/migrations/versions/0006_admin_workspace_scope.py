from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0006_admin_workspace_scope"
down_revision: str | None = "0005_construction_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("morning_principals", sa.Column("admin_workspace", sa.Text()))
    op.execute("UPDATE morning_principals SET admin_workspace='morning' WHERE role='admin'")
    op.create_check_constraint(
        "ck_morning_principals_admin_workspace",
        "morning_principals",
        "(role='admin' AND admin_workspace IS NOT NULL) OR (role='supervisor' AND admin_workspace IS NULL)",
    )
    op.create_index(
        "ix_morning_principals_admin_workspace",
        "morning_principals",
        ["role", "admin_workspace"],
    )


def downgrade() -> None:
    op.drop_index("ix_morning_principals_admin_workspace", table_name="morning_principals")
    op.drop_constraint("ck_morning_principals_admin_workspace", "morning_principals", type_="check")
    op.drop_column("morning_principals", "admin_workspace")
