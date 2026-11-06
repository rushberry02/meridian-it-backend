from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import Operator, get_operator, require_admin
from app.schemas.device import DeviceCreate, DeviceRead, DeviceUpdate
from app.services import device as service

router = APIRouter(prefix="/devices", tags=["Devices"])
Admin = Annotated[Operator, Depends(require_admin)]
Current = Annotated[Operator, Depends(get_operator)]
Database = Annotated[Session, Depends(get_db)]
DeviceId = Annotated[int, Path(gt=0, le=2147483647)]


def _get_or_404(db, device_id):
    device = service.get_device(db, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


def _save(operation, *args):
    try:
        return operation(*args)
    except service.DuplicateAssetTagError:
        raise HTTPException(status_code=409, detail="Asset tag is already in use") from None
    except service.EmployeeNotFoundError:
        raise HTTPException(status_code=404, detail="Assigned employee not found") from None


@router.post("", response_model=DeviceRead, status_code=201)
def create_device(data: DeviceCreate, db: Database, operator: Admin):
    return _save(service.create_device, db, data)


@router.get("", response_model=list[DeviceRead])
def list_devices(
    db: Database,
    operator: Current,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    assigned_employee_id: Annotated[int | None, Query(gt=0, le=2147483647)] = None,
):
    if operator.role == "employee":
        if assigned_employee_id is not None and assigned_employee_id != operator.employee_id:
            raise HTTPException(status_code=403, detail="Cannot list another employee's devices")
        assigned_employee_id = operator.employee_id
    return service.list_devices(db, offset, limit, assigned_employee_id)


@router.get("/{device_id}", response_model=DeviceRead)
def get_device(device_id: DeviceId, db: Database, operator: Current):
    device = _get_or_404(db, device_id)
    if operator.role == "employee" and device.assigned_employee_id != operator.employee_id:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.patch("/{device_id}", response_model=DeviceRead)
def update_device(device_id: DeviceId, data: DeviceUpdate, db: Database, operator: Admin):
    return _save(service.update_device, db, _get_or_404(db, device_id), data)


@router.delete("/{device_id}", status_code=204)
def delete_device(device_id: DeviceId, db: Database, operator: Admin):
    try:
        service.delete_device(db, _get_or_404(db, device_id))
    except service.DeviceHasTicketsError:
        raise HTTPException(status_code=409, detail="Device is referenced by support tickets") from None
    return Response(status_code=204)
