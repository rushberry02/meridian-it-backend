from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Identity, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'in_progress', 'resolved', 'closed')", name="ck_tickets_status"),
        CheckConstraint("priority IN ('low', 'medium', 'high', 'urgent')", name="ck_tickets_priority"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", name="fk_tickets_employee", ondelete="RESTRICT"), index=True,
    )
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", name="fk_tickets_device", ondelete="RESTRICT"), nullable=True, index=True,
    )
    status: Mapped[str] = mapped_column(String(20), server_default=text("'open'"))
    priority: Mapped[str] = mapped_column(String(20), server_default=text("'medium'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
