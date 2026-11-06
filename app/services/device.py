from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models import Device, Employee
from app.schemas.device import DeviceCreate, DeviceUpdate


class DeviceHasTicketsError(Exception):
    pass


class DuplicateAssetTagError(Exception):
    pass


class EmployeeNotFoundError(Exception):
    pass


def _check_employee(db: Session, employee_id: int | None):
    if employee_id is not None and db.get(Employee, employee_id) is None:
        raise EmployeeNotFoundError


def _save(db: Session, device: Device) -> Device:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        code = getattr(exc.orig, "sqlstate", None)
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if code == "23505" and constraint == "ix_devices_asset_tag":
            raise DuplicateAssetTagError from None
        if code == "23503" and constraint == "fk_devices_assigned_employee":
            raise EmployeeNotFoundError from None
        raise
    db.refresh(device)
    return device


def create_device(db: Session, data: DeviceCreate):
    _check_employee(db, data.assigned_employee_id)
    device = Device(**data.model_dump())
    db.add(device)
    return _save(db, device)


def list_devices(db: Session, offset: int, limit: int, employee_id: int | None):
    query = select(Device).order_by(Device.id)
    if employee_id is not None:
        query = query.where(Device.assigned_employee_id == employee_id)
    return db.scalars(query.offset(offset).limit(limit)).all()


def get_device(db: Session, device_id: int):
    return db.get(Device, device_id)


def update_device(db: Session, device: Device, data: DeviceUpdate):
    values = data.model_dump(exclude_unset=True)
    if "assigned_employee_id" in values:
        _check_employee(db, values["assigned_employee_id"])
    for key, value in values.items():
        setattr(device, key, value)
    return _save(db, device)


def delete_device(db: Session, device: Device):
    db.delete(device)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if (
            getattr(exc.orig, "sqlstate", None) in {"23503", "23001"}
            and getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == "fk_tickets_device"
        ):
            raise DeviceHasTicketsError from None
        raise
