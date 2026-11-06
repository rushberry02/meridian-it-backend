from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Identity, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class TicketStatusHistory(Base):
    __tablename__ = "ticket_status_history"
    __table_args__ = (
        CheckConstraint("old_status IS NULL OR old_status IN ('open', 'in_progress', 'resolved', 'closed')", name="ck_ticket_history_old_status"),
        CheckConstraint("new_status IN ('open', 'in_progress', 'resolved', 'closed')", name="ck_ticket_history_new_status"),
        CheckConstraint("actor_role IN ('support', 'admin', 'migration', 'employee')", name="ck_ticket_history_actor"),
    )
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE", name="fk_ticket_history_ticket"), index=True)
    old_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_status: Mapped[str] = mapped_column(String(20))
    actor_employee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_role: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
