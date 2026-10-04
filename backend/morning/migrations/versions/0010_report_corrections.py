from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010_report_corrections"
down_revision = "0009_tmm_multicrew_demo"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("morning_reports", sa.Column("revision", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("morning_reports", sa.Column("correction_pending", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_table(
        "morning_report_versions",
        sa.Column("report_id", sa.Text(), sa.ForeignKey("morning_reports.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Text(), sa.ForeignKey("morning_principals.id"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("snapshot", JSONB(), nullable=False),
    )


def downgrade():
    op.drop_table("morning_report_versions")
    op.drop_column("morning_reports", "correction_pending")
    op.drop_column("morning_reports", "revision")
