"""Create the employees table.

Revision ID: 0001_create_employees
Revises: None
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_create_employees"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("department", sa.String(length=100), nullable=True),
        sa.Column("job_title", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_employees_email", "employees", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_employees_email", table_name="employees")
    op.drop_table("employees")
