"""One-time web password setup invitations."""
from alembic import op
import sqlalchemy as sa
revision = "0007_password_invitations"
down_revision = "0006_users_and_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("password_invitations",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('employee', 'admin')", name="ck_password_invitations_role"))
    op.create_index("ix_password_invitations_employee_id", "password_invitations", ["employee_id"])


def downgrade():
    op.drop_table("password_invitations")
