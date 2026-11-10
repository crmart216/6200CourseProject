"""Start a fresh, append-only event log (no historic backfill)."""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("group_name", sa.String(120), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_audit_events_group_id_id", "audit_events", ["group_id", "id"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])


def downgrade():
    op.drop_table("audit_events")
