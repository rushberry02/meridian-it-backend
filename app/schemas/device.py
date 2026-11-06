from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
DeviceType = Literal["laptop", "desktop", "monitor", "printer", "phone", "tablet", "other"]
EmployeeId = Annotated[int, Field(gt=0, le=2147483647)]


class DeviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("asset_tag", check_fields=False)
    @classmethod
    def normalize_asset_tag(cls, value):
        if value is None:
            return None
        normalized = value.upper()
        if len(normalized) > 100:
            raise ValueError("Normalized asset tag must be at most 100 characters")
        return normalized


class DeviceCreate(DeviceInput):
    asset_tag: Label
    device_type: DeviceType
    manufacturer: Label | None = None
    model: Label | None = None
    serial_number: Label | None = None
    assigned_employee_id: EmployeeId | None = None


class DeviceUpdate(DeviceInput):
    asset_tag: Label | None = None
    device_type: DeviceType | None = None
    manufacturer: Label | None = None
    model: Label | None = None
    serial_number: Label | None = None
    assigned_employee_id: EmployeeId | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        for field in ("asset_tag", "device_type"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class DeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    asset_tag: str
    device_type: str
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    assigned_employee_id: int | None
    created_at: datetime
    updated_at: datetime
