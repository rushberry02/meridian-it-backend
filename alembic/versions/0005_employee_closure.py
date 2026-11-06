"""Audit authenticated employee self-service closure."""
from alembic import op
import sqlalchemy as sa
revision = "0005_employee_closure"
down_revision = "0004_ticket_workflow"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ticket_status_history", sa.Column("actor_employee_id", sa.Integer(), nullable=True))
    op.drop_constraint("ck_ticket_history_actor", "ticket_status_history", type_="check")
    op.create_check_constraint("ck_ticket_history_actor", "ticket_status_history", "actor_role IN ('support', 'admin', 'migration', 'employee')")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM ticket_status_history WHERE actor_role = 'employee'")):
        raise RuntimeError("Cannot downgrade while employee closure events exist; preserve their audit attribution")
    op.drop_constraint("ck_ticket_history_actor", "ticket_status_history", type_="check")
    op.create_check_constraint("ck_ticket_history_actor", "ticket_status_history", "actor_role IN ('support', 'admin', 'migration')")
    op.drop_column("ticket_status_history", "actor_employee_id")
