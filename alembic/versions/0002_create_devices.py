"""Create devices and employee assignment foreign key."""
from alembic import op
import sqlalchemy as sa

revision = "0002_create_devices"
down_revision = "0001_create_employees"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("asset_tag", sa.String(100), nullable=False),
        sa.Column("device_type", sa.String(50), nullable=False),
        sa.Column("manufacturer", sa.String(100), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("serial_number", sa.String(100), nullable=True),
        sa.Column("assigned_employee_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["assigned_employee_id"], ["employees.id"], name="fk_devices_assigned_employee", ondelete="RESTRICT"),
    )
    op.create_index("ix_devices_asset_tag", "devices", ["asset_tag"], unique=True)
    op.create_index("ix_devices_assigned_employee_id", "devices", ["assigned_employee_id"])


def downgrade():
    op.drop_index("ix_devices_assigned_employee_id", table_name="devices")
    op.drop_index("ix_devices_asset_tag", table_name="devices")
    op.drop_table("devices")
