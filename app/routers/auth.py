from typing import Annotated
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Employee, User
from app.schemas.auth import LoginRequest, PasswordSet, RefreshRequest, TokenResponse, UserCreate, UserRead
from app.security import Operator, get_operator, require_admin
from app.services import auth as service

router = APIRouter(prefix="/auth", tags=["Authentication"])
Database = Annotated[Session, Depends(get_db)]
Admin = Annotated[Operator, Depends(require_admin)]
Current = Annotated[Operator, Depends(get_operator)]


def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, response: Response, db: Database):
    no_store(response)
    return service.login(db, str(data.email), data.password.get_secret_value(), data.role)


@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshRequest, response: Response, db: Database):
    no_store(response)
    return service.refresh(db, data.refresh_token.get_secret_value())


@router.post("/logout", status_code=204)
def logout(data: RefreshRequest, db: Database):
    service.logout(db, data.refresh_token.get_secret_value())
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/me", response_model=UserRead)
def me(operator: Current, response: Response, db: Database):
    from fastapi import HTTPException
    if operator.user_id is None:
        raise HTTPException(status_code=401, detail="Password login required")
    no_store(response)
    return service.user_read(db.get(User, operator.user_id), db.get(Employee, operator.employee_id))


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(data: UserCreate, db: Database, admin: Admin):
    return service.provision_user(db, data.employee_id, data.password.get_secret_value(), data.role, create_only=True)


@router.put("/users/{employee_id}/password", response_model=UserRead)
def reset_password(employee_id: int, data: PasswordSet, db: Database, admin: Admin):
    return service.provision_user(db, employee_id, data.password.get_secret_value())


from app.schemas.auth import InvitationCreate, PasswordSetup


@router.post("/setup-invitations", status_code=201)
def setup_invitation(data: InvitationCreate, response: Response, db: Database, admin: Admin):
    no_store(response)
    return service.issue_password_invitation(db, data.employee_id, data.role)


@router.post("/setup-password", response_model=UserRead)
def setup_password(data: PasswordSetup, response: Response, db: Database):
    no_store(response)
    return service.complete_password_setup(db, data.token.get_secret_value(), data.password.get_secret_value())
