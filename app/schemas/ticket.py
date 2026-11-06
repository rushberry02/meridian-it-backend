from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

TicketStatus = Literal["open", "in_progress", "resolved", "closed"]
TicketPriority = Literal["low", "medium", "high", "urgent"]
RecordId = Annotated[int, Field(gt=0, le=2147483647)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class TicketInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TicketCreate(TicketInput):
    title: Title
    description: Description
    employee_id: RecordId
    device_id: RecordId | None = None
    status: Literal["open"] = "open"
    priority: TicketPriority = "medium"


Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class TicketUpdate(TicketInput):
    reason: Reason | None = None
    title: Title | None = None
    description: Description | None = None
    employee_id: RecordId | None = None
    device_id: RecordId | None = None
    status: TicketStatus | None = None
    priority: TicketPriority | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        for field in ("title", "description", "employee_id", "status", "priority"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: str
    employee_id: int
    device_id: int | None
    status: TicketStatus
    priority: TicketPriority
    created_at: datetime
    updated_at: datetime


class TicketHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticket_id: int
    old_status: TicketStatus | None
    new_status: TicketStatus
    actor_employee_id: int | None
    actor_role: str
    reason: str | None
    changed_at: datetime
