from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Identity, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    asset_tag: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    device_type: Mapped[str] = mapped_column(String(50))
    manufacturer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    assigned_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", name="fk_devices_assigned_employee", ondelete="RESTRICT"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
