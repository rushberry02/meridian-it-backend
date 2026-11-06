from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import uuid4
import jwt
from fastapi import HTTPException
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import Employee, RefreshSession, RefreshToken, User

password_hasher = PasswordHash.recommended()
DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(32))
ISSUER = "meridian-it"
AUDIENCE = "meridian-copilot"


def now():
    return datetime.now(timezone.utc)


def unauthorized():
    return HTTPException(status_code=401, detail="Invalid or expired authentication", headers={"WWW-Authenticate": "Bearer"})


def user_read(user: User, employee: Employee):
    return {"id": user.id, "employee_id": employee.id, "role": user.role, "full_name": employee.full_name, "email": employee.email}


def signing_secret():
    secret = get_settings().auth_jwt_secret.get_secret_value()
    if not secret:
        raise HTTPException(status_code=503, detail="Login is not configured")
    return secret


def token_hash(token: str):
    return hashlib.sha256(token.encode()).hexdigest()


def issue_tokens(db: Session, user: User, employee: Employee, session: RefreshSession):
    current = now()
    expires = current + timedelta(minutes=get_settings().access_token_minutes)
    access = jwt.encode({"sub": str(user.id), "sid": session.id, "role": user.role, "employee_id": employee.id, "iat": current, "exp": expires, "iss": ISSUER, "aud": AUDIENCE, "token_use": "access", "jti": uuid4().hex}, signing_secret(), algorithm="HS256")
    refresh = secrets.token_urlsafe(48)
    db.add(RefreshToken(session_id=session.id, token_hash=token_hash(refresh)))
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer", "expires_at": expires, "session_expires_at": session.expires_at, "user": user_read(user, employee)}


def provision_user(db: Session, employee_id: int, password: str, role: str | None = None, create_only=False, commit=True):
    if not 12 <= len(password) <= 128 or not password.strip():
        raise HTTPException(status_code=422, detail="Password must be 12 to 128 characters")
    if role is not None and role not in {"employee", "admin"}:
        raise HTTPException(status_code=422, detail="Invalid role")
    employee = db.scalar(select(Employee).where(Employee.id == employee_id).with_for_update())
    if employee is None or not employee.is_active:
        raise HTTPException(status_code=404, detail="Active employee not found")
    user = db.scalar(select(User).where(User.employee_id == employee_id))
    if user is not None and create_only:
        raise HTTPException(status_code=409, detail="Login account already exists")
    if user is None:
        user = User(employee_id=employee_id, password_hash=password_hasher.hash(password), role=role or "employee")
        db.add(user)
        db.flush()
    else:
        user.password_hash = password_hasher.hash(password)
        user.failed_login_attempts = 0
        user.locked_until = None
        if role is not None:
            user.role = role
        db.execute(update(RefreshSession).where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None)).values(revoked_at=now()))
    db.flush()
    if commit:
        db.commit()
        db.refresh(user)
    return user_read(user, employee)


def login(db: Session, email: str, password: str, requested_role: str | None = None):
    user = db.scalar(select(User).join(Employee, Employee.id == User.employee_id).where(func.lower(Employee.email) == email.strip().lower()).with_for_update(of=User))
    employee = db.get(Employee, user.employee_id) if user else None
    active = user is not None and user.is_active and employee.is_active
    locked = bool(user and user.locked_until and user.locked_until > now())
    try:
        valid, updated = password_hasher.verify_and_update(password, user.password_hash if active and not locked else DUMMY_HASH)
    except (ValueError, UnknownHashError):
        valid, updated = False, None
    if not active or locked or not valid:
        if active and not locked:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = now() + timedelta(minutes=15)
            db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if requested_role is not None and user.role != requested_role:
        raise HTTPException(status_code=403, detail="This account cannot use the selected login role")
    user.failed_login_attempts = 0
    user.locked_until = None
    if updated:
        user.password_hash = updated
    session = RefreshSession(id=uuid4().hex, user_id=user.id, expires_at=now() + timedelta(days=get_settings().refresh_session_days))
    db.add(session)
    db.flush()
    result = issue_tokens(db, user, employee, session)
    db.commit()
    return result


def verify_access(db: Session, token: str):
    try:
        claims = jwt.decode(token, signing_secret(), algorithms=["HS256"], issuer=ISSUER, audience=AUDIENCE, options={"require": ["sub", "sid", "iat", "exp", "iss", "aud", "token_use"]})
        if claims["token_use"] != "access":
            raise ValueError("Wrong token use")
        user_id = int(claims["sub"])
        session = db.get(RefreshSession, claims["sid"])
        if session is None or session.user_id != user_id or session.revoked_at is not None or session.expires_at <= now():
            raise ValueError("Inactive session")
        user = db.get(User, user_id)
        employee = db.get(Employee, user.employee_id) if user else None
        if user is None or not user.is_active or employee is None or not employee.is_active:
            raise ValueError("Inactive account")
        return user, employee, session
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise unauthorized() from None


def refresh(db: Session, raw_token: str):
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash(raw_token)).with_for_update())
    if token is None:
        raise unauthorized()
    session = db.scalar(select(RefreshSession).where(RefreshSession.id == token.session_id).with_for_update())
    if session is None or session.revoked_at is not None or session.expires_at <= now():
        raise unauthorized()
    if token.used_at is not None:
        session.revoked_at = now()  # Reuse invalidates the entire token family.
        db.commit()
        raise unauthorized()
    user = db.get(User, session.user_id)
    employee = db.get(Employee, user.employee_id) if user else None
    if user is None or not user.is_active or employee is None or not employee.is_active:
        session.revoked_at = now()
        db.commit()
        raise unauthorized()
    token.used_at = now()
    result = issue_tokens(db, user, employee, session)
    db.commit()
    return result


def logout(db: Session, raw_refresh: str):
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash(raw_refresh)))
    if token:
        db.execute(update(RefreshSession).where(RefreshSession.id == token.session_id).values(revoked_at=now()))
        db.commit()


def issue_password_invitation(db: Session, employee_id: int, role: str):
    from app.models import PasswordInvitation
    employee = db.scalar(select(Employee).where(Employee.id == employee_id).with_for_update())
    if employee is None or not employee.is_active:
        raise HTTPException(status_code=404, detail="Active employee not found")
    if db.scalar(select(User.id).where(User.employee_id == employee_id)) is not None:
        raise HTTPException(status_code=409, detail="Login already exists. Use the existing account.")
    current = now()
    db.execute(update(PasswordInvitation).where(PasswordInvitation.employee_id == employee_id, PasswordInvitation.used_at.is_(None)).values(used_at=current))
    raw = secrets.token_urlsafe(48)
    expires = current + timedelta(hours=24)
    db.add(PasswordInvitation(employee_id=employee_id, token_hash=token_hash(raw), role=role, expires_at=expires))
    db.commit()
    return {"token": raw, "expires_at": expires, "email": employee.email, "role": role}


def complete_password_setup(db: Session, raw: str, password: str):
    from app.models import PasswordInvitation
    # Lock employee first, matching issuance and account provisioning lock order.
    employee_id = db.scalar(select(PasswordInvitation.employee_id).where(PasswordInvitation.token_hash == token_hash(raw)))
    if employee_id is None:
        raise HTTPException(status_code=400, detail="Setup link is invalid or expired")
    db.scalar(select(Employee).where(Employee.id == employee_id).with_for_update())
    invitation = db.scalar(select(PasswordInvitation).where(PasswordInvitation.token_hash == token_hash(raw)).with_for_update())
    if invitation is None or invitation.used_at is not None or invitation.expires_at <= now():
        raise HTTPException(status_code=400, detail="Setup link is invalid or expired")
    result = provision_user(db, invitation.employee_id, password, invitation.role, create_only=True, commit=False)
    invitation.used_at = now()
    db.commit()
    return result
