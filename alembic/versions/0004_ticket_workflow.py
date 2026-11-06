"""Add status history and a truthful baseline for existing tickets."""
from alembic import op
import sqlalchemy as sa
revision = "0004_ticket_workflow"
down_revision = "0003_create_tickets"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ticket_status_history",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("old_status", sa.String(20), nullable=True),
        sa.Column("new_status", sa.String(20), nullable=False),
        sa.Column("actor_role", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name="fk_ticket_history_ticket", ondelete="CASCADE"),
        sa.CheckConstraint("old_status IS NULL OR old_status IN ('open', 'in_progress', 'resolved', 'closed')", name="ck_ticket_history_old_status"),
        sa.CheckConstraint("new_status IN ('open', 'in_progress', 'resolved', 'closed')", name="ck_ticket_history_new_status"),
        sa.CheckConstraint("actor_role IN ('support', 'admin', 'migration')", name="ck_ticket_history_actor"),
    )
    op.create_index("ix_ticket_status_history_ticket_id", "ticket_status_history", ["ticket_id"])
    op.execute("INSERT INTO ticket_status_history (ticket_id, old_status, new_status, actor_role, reason) SELECT id, NULL, status, 'migration', 'Baseline at workflow migration; earlier transitions unavailable' FROM tickets")


def downgrade():
    op.drop_index("ix_ticket_status_history_ticket_id", table_name="ticket_status_history")
    op.drop_table("ticket_status_history")
