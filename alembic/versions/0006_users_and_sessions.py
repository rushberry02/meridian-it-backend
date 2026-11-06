"""Link login users to employees and store revocable refresh sessions."""
from alembic import op
import sqlalchemy as sa
revision = "0006_users_and_sessions"
down_revision = "0005_employee_closure"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(20), server_default=sa.text("'employee'"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("failed_login_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE", name="fk_users_employee"),
        sa.CheckConstraint("role IN ('employee', 'admin')", name="ck_users_role"))
    op.create_index("ix_users_employee_id", "users", ["employee_id"], unique=True)
    op.create_table("refresh_sessions",
        sa.Column("id", sa.String(32), nullable=False), sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_refresh_sessions_user"))
    op.create_index("ix_refresh_sessions_user_id", "refresh_sessions", ["user_id"])
    op.create_table("refresh_tokens",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False), sa.Column("session_id", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False), sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["session_id"], ["refresh_sessions.id"], ondelete="CASCADE", name="fk_refresh_tokens_session"))
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)


def downgrade():
    op.drop_table("refresh_tokens")
    op.drop_table("refresh_sessions")
    op.drop_table("users")
