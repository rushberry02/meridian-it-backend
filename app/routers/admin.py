"""Admin-only overview and searchable, paginated operational queues."""
from typing import Annotated
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Device, Employee, Ticket
from app.schemas.device import DeviceRead
from app.schemas.employee import EmployeeRead
from app.schemas.ticket import TicketPriority, TicketRead, TicketStatus
from app.security import require_admin

router = APIRouter(prefix="/admin", tags=["Admin dashboard"], dependencies=[Depends(require_admin)])
Database = Annotated[Session, Depends(get_db)]
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]
Search = Annotated[str, Query(max_length=200)]


def page(db, model, schema, filters, offset, limit):
    total = db.scalar(select(func.count()).select_from(model).where(*filters))
    rows = db.scalars(select(model).where(*filters).order_by(model.id.desc()).offset(offset).limit(limit)).all()
    return {"items": [schema.model_validate(row).model_dump(mode="json") for row in rows], "total": total, "offset": offset, "limit": limit}


@router.get("/summary")
def summary(response: Response, db: Database):
    response.headers["Cache-Control"] = "no-store"
    statuses = dict(db.execute(select(Ticket.status, func.count()).group_by(Ticket.status)).all())
    employees = db.scalar(select(func.count()).select_from(Employee))
    active = db.scalar(select(func.count()).select_from(Employee).where(Employee.is_active.is_(True)))
    devices = db.scalar(select(func.count()).select_from(Device))
    assigned = db.scalar(select(func.count()).select_from(Device).where(Device.assigned_employee_id.is_not(None)))
    urgent = db.scalar(select(func.count()).select_from(Ticket).where(Ticket.status.in_(["open", "in_progress"]), Ticket.priority.in_(["high", "urgent"])))
    return {"employees": {"total": employees, "active": active, "inactive": employees-active}, "devices": {"total": devices, "assigned": assigned, "unassigned": devices-assigned}, "tickets": {"total": sum(statuses.values()), **{key: statuses.get(key, 0) for key in ("open", "in_progress", "resolved", "closed")}, "high_priority_active": urgent}}


@router.get("/tickets")
def tickets(response: Response, db: Database, offset: Offset = 0, limit: Limit = 20, search: Search = "", status: TicketStatus | None = None, priority: TicketPriority | None = None, employee_id: Annotated[int | None, Query(gt=0)] = None):
    response.headers["Cache-Control"] = "no-store"
    filters = []
    if search.strip():
        filters.append(or_(func.lower(Ticket.title).contains(search.strip().lower(), autoescape=True), func.lower(Ticket.description).contains(search.strip().lower(), autoescape=True)))
    for field, value in ((Ticket.status, status), (Ticket.priority, priority), (Ticket.employee_id, employee_id)):
        if value is not None:
            filters.append(field == value)
    return page(db, Ticket, TicketRead, filters, offset, limit)


@router.get("/employees")
def employees(response: Response, db: Database, offset: Offset = 0, limit: Limit = 20, search: Search = "", is_active: bool | None = None):
    response.headers["Cache-Control"] = "no-store"
    filters = []
    if search.strip():
        filters.append(or_(func.lower(Employee.full_name).contains(search.strip().lower(), autoescape=True), func.lower(Employee.email).contains(search.strip().lower(), autoescape=True)))
    if is_active is not None:
        filters.append(Employee.is_active == is_active)
    return page(db, Employee, EmployeeRead, filters, offset, limit)


@router.get("/devices")
def devices(response: Response, db: Database, offset: Offset = 0, limit: Limit = 20, search: Search = "", assigned_employee_id: Annotated[int | None, Query(gt=0)] = None):
    response.headers["Cache-Control"] = "no-store"
    filters = []
    if search.strip():
        filters.append(or_(func.lower(Device.asset_tag).contains(search.strip().lower(), autoescape=True), func.lower(Device.serial_number).contains(search.strip().lower(), autoescape=True)))
    if assigned_employee_id is not None:
        filters.append(Device.assigned_employee_id == assigned_employee_id)
    return page(db, Device, DeviceRead, filters, offset, limit)
