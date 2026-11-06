from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import Operator, get_operator, require_admin
from app.schemas.ticket import TicketCreate, TicketHistoryRead, TicketPriority, TicketRead, TicketStatus, TicketUpdate
from app.services import ticket as service

router = APIRouter(prefix="/tickets", tags=["Tickets"])
CurrentOperator = Annotated[Operator, Depends(get_operator)]
Admin = Annotated[Operator, Depends(require_admin)]
Database = Annotated[Session, Depends(get_db)]
TicketId = Annotated[int, Path(gt=0, le=2147483647)]
FilterId = Annotated[int | None, Query(gt=0, le=2147483647)]


def _get_or_404(db, ticket_id):
    ticket = service.get_ticket(db, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


def _save(operation, *args):
    try:
        return operation(*args)
    except service.EmployeeActionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except service.AdminRequiredError:
        raise HTTPException(status_code=403, detail="Administrator access required") from None
    except service.WorkflowConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except service.LinkedRecordNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.post("", response_model=TicketRead, status_code=201)
def create_ticket(data: TicketCreate, db: Database, operator: CurrentOperator):
    return _save(service.create_ticket, db, data, operator)


@router.get("", response_model=list[TicketRead])
def list_tickets(
    db: Database,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    employee_id: FilterId = None,
    device_id: FilterId = None,
    status: TicketStatus | None = None,
    priority: TicketPriority | None = None,
):
    return service.list_tickets(db, offset, limit, employee_id=employee_id, device_id=device_id, status=status, priority=priority)


@router.get("/{ticket_id}", response_model=TicketRead)
def get_ticket(ticket_id: TicketId, db: Database):
    return _get_or_404(db, ticket_id)


@router.patch("/{ticket_id}", response_model=TicketRead)
def update_ticket(ticket_id: TicketId, data: TicketUpdate, db: Database, operator: CurrentOperator):
    return _save(service.update_ticket, db, _get_or_404(db, ticket_id), data, operator)


@router.delete("/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: TicketId, db: Database, operator: Admin):
    service.delete_ticket(db, _get_or_404(db, ticket_id), operator)
    return Response(status_code=204)


@router.get("/{ticket_id}/history", response_model=list[TicketHistoryRead])
def ticket_history(ticket_id: TicketId, db: Database, offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=100)] = 20):
    _get_or_404(db, ticket_id)
    return service.get_status_history(db, ticket_id, offset, limit)


@router.patch("/{ticket_id}/admin", response_model=TicketRead)
def admin_update_ticket(ticket_id: TicketId, data: TicketUpdate, db: Database, operator: Admin):
    return _save(service.update_ticket, db, _get_or_404(db, ticket_id), data, operator, True)


@router.post("/{ticket_id}/close", response_model=TicketRead)
def close_own_ticket(ticket_id: TicketId, db: Database, operator: CurrentOperator):
    return _save(service.close_ticket, db, _get_or_404(db, ticket_id), operator)
