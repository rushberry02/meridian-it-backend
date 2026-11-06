from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.models import User
from sqlalchemy import select
from app.database import get_db
from app.security import Operator, require_admin, issue_employee_key, get_operator
from app.schemas.employee import EmployeeCreate, EmployeeRead, EmployeeUpdate
from app.services import employee as service

router = APIRouter(prefix="/employees", tags=["Employees"])
Admin = Annotated[Operator, Depends(require_admin)]
Current = Annotated[Operator, Depends(get_operator)]
Database = Annotated[Session, Depends(get_db)]
EmployeeId = Annotated[int, Path(gt=0)]


def _get_or_404(db: Session, employee_id: int):
    employee = service.get_employee(db, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    return employee


@router.post("", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
def create_employee(data: EmployeeCreate, db: Database, operator: Admin):
    try:
        return service.create_employee(db, data)
    except service.DuplicateEmailError:
        raise HTTPException(status_code=409, detail="Email is already assigned to an employee") from None


@router.get("", response_model=list[EmployeeRead])
def list_employees(
    db: Database,
    operator: Current,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    if operator.role == "employee":
        return [_get_or_404(db, operator.employee_id)] if offset == 0 else []
    return service.list_employees(db, offset, limit)


@router.get("/{employee_id}", response_model=EmployeeRead)
def get_employee(employee_id: EmployeeId, db: Database, operator: Current):
    if operator.role == "employee" and employee_id != operator.employee_id:
        raise HTTPException(status_code=404, detail="Employee not found")
    return _get_or_404(db, employee_id)


@router.patch("/{employee_id}", response_model=EmployeeRead)
def update_employee(employee_id: EmployeeId, data: EmployeeUpdate, db: Database, operator: Admin):
    employee = _get_or_404(db, employee_id)
    try:
        return service.update_employee(db, employee, data)
    except service.DuplicateEmailError:
        raise HTTPException(status_code=409, detail="Email is already assigned to an employee") from None


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee(employee_id: EmployeeId, db: Database, operator: Admin):
    try:
        service.delete_employee(db, _get_or_404(db, employee_id))
    except service.EmployeeHasTicketsError:
        raise HTTPException(status_code=409, detail="Employee is referenced by support tickets") from None
    except service.EmployeeHasDevicesError:
        raise HTTPException(status_code=409, detail="Unassign devices before deleting this employee") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{employee_id}/access-key")
def employee_access_key(employee_id: EmployeeId, db: Database, operator: Annotated[Operator, Depends(require_admin)]):
    employee = _get_or_404(db, employee_id)
    if not employee.is_active:
        raise HTTPException(status_code=409, detail="Employee is inactive")
    if db.scalar(select(User.id).where(User.employee_id == employee_id)) is not None:
        raise HTTPException(status_code=409, detail="This employee uses email/password login")
    return issue_employee_key(employee_id)
