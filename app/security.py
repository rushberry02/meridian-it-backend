import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from secrets import compare_digest
from typing import Annotated
from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader
from app.config import get_settings
from app.database import get_db
from app.models import Employee
from sqlalchemy.orm import Session

api_key = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass(frozen=True)
class Operator:
    role: str
    employee_id: int | None = None


def get_operator(key: Annotated[str | None, Depends(api_key)], db: Annotated[Session, Depends(get_db)]) -> Operator:
    settings = get_settings()
    if key:
        for role, expected in (("admin", settings.admin_api_key), ("support", settings.support_api_key)):
            secret = expected.get_secret_value()
            if secret and compare_digest(key.encode(), secret.encode()):
                return Operator(role)
        if key.startswith("meridian_employee."):
            try:
                prefix, payload, signature = key.split(".")
                secret = settings.admin_api_key.get_secret_value()
                if not secret:
                    raise ValueError("Missing signing key")
                expected = hmac.new(secret.encode(), f"{prefix}.{payload}".encode(), hashlib.sha256).hexdigest()
                if not compare_digest(expected, signature):
                    raise ValueError("Invalid signature")
                claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
                employee_id = claims["employee_id"]
                if type(employee_id) is not int or not 0 < employee_id <= 2147483647 or claims["exp"] <= time.time():
                    raise ValueError("Invalid or expired credential")
                employee = db.get(Employee, employee_id)
                if employee is not None and employee.is_active:
                    return Operator("employee", employee_id)
            except (ValueError, TypeError, KeyError):
                pass
    raise HTTPException(status_code=401, detail="Valid X-API-Key required")


def require_admin(operator: Annotated[Operator, Depends(get_operator)]) -> Operator:
    if operator.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return operator


def issue_employee_key(employee_id: int):
    secret = get_settings().admin_api_key.get_secret_value()
    if not secret:
        raise HTTPException(status_code=503, detail="Employee credential signing is not configured")
    expires = int(time.time()) + 7 * 24 * 60 * 60
    claims = {"employee_id": employee_id, "exp": expires, "nonce": secrets.token_urlsafe(16)}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    message = f"meridian_employee.{payload}"
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {"employee_id": employee_id, "api_key": f"{message}.{signature}", "expires_at": expires}
