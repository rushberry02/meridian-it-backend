from typing import Annotated
from app.security import Operator, get_operator
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.employees import router as employees_router
from app.routers.devices import router as devices_router
from app.routers.tickets import router as tickets_router
from app.routers.auth import router as auth_router
from app.routers.admin import router as admin_router

app = FastAPI(
    title="Meridian IT Management API",
    description="Employee, device and IT support ticket management",
    version="1.0.0",
)


@app.get("/")
def home():
    return {"message": "Meridian IT Management Backend is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/health/database")
def database_health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    return {"status": "healthy", "database": "connected"}

app.include_router(employees_router)

app.include_router(devices_router)

app.include_router(tickets_router)


@app.get("/identity")
def identity(operator: Annotated[Operator, Depends(get_operator)]):
    return {"role": operator.role, "employee_id": operator.employee_id}

app.include_router(auth_router)


from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse


@app.exception_handler(RequestValidationError)
async def safe_auth_validation(request, exc):
    if request.url.path.startswith("/auth/"):
        return JSONResponse(status_code=422, content={"detail": "Invalid authentication input. Password setup requires 12 to 128 characters."}, headers={"Cache-Control": "no-store"})
    return await request_validation_exception_handler(request, exc)

app.include_router(admin_router)
