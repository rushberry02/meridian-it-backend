"""Create support tickets linked to employees and optional devices."""
from alembic import op
import sqlalchemy as sa

revision = "0003_create_tickets"
down_revision = "0002_create_devices"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'open'"), nullable=False),
        sa.Column("priority", sa.String(20), server_default=sa.text("'medium'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], name="fk_tickets_employee", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], name="fk_tickets_device", ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('open', 'in_progress', 'resolved', 'closed')", name="ck_tickets_status"),
        sa.CheckConstraint("priority IN ('low', 'medium', 'high', 'urgent')", name="ck_tickets_priority"),
    )
    op.create_index("ix_tickets_employee_id", "tickets", ["employee_id"])
    op.create_index("ix_tickets_device_id", "tickets", ["device_id"])


def downgrade():
    op.drop_index("ix_tickets_device_id", table_name="tickets")
    op.drop_index("ix_tickets_employee_id", table_name="tickets")
    op.drop_table("tickets")
