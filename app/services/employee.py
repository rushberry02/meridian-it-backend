from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Employee
from app.schemas.employee import EmployeeCreate, EmployeeUpdate


class EmployeeHasTicketsError(Exception):
    pass


class EmployeeHasDevicesError(Exception):
    pass


class DuplicateEmailError(Exception):
    pass


def _save(db: Session, employee: Employee) -> Employee:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        original = exc.orig
        if (
            getattr(original, "sqlstate", None) == "23505"
            and getattr(getattr(original, "diag", None), "constraint_name", None)
            == "ix_employees_email"
        ):
            raise DuplicateEmailError from None
        raise
    db.refresh(employee)
    return employee


def create_employee(db: Session, data: EmployeeCreate) -> Employee:
    employee = Employee(**data.model_dump())
    db.add(employee)
    return _save(db, employee)


def list_employees(db: Session, offset: int, limit: int):
    return db.scalars(select(Employee).order_by(Employee.id).offset(offset).limit(limit)).all()


def get_employee(db: Session, employee_id: int) -> Employee | None:
    return db.get(Employee, employee_id)


def update_employee(db: Session, employee: Employee, data: EmployeeUpdate) -> Employee:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(employee, field, value)
    return _save(db, employee)


def delete_employee(db: Session, employee: Employee) -> None:
    db.delete(employee)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if (
            getattr(exc.orig, "sqlstate", None) in {"23503", "23001"}
            and getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            == "fk_devices_assigned_employee"
        ):
            raise EmployeeHasDevicesError from None
        if (
            getattr(exc.orig, "sqlstate", None) in {"23503", "23001"}
            and getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == "fk_tickets_employee"
        ):
            raise EmployeeHasTicketsError from None
        raise
