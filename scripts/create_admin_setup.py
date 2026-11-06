"""Trusted Meridian container bootstrap: choose the password in the browser."""
import argparse
import sys
from pathlib import Path
from urllib.parse import urlencode

# This script is copied into the separate Meridian repository.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Employee, User
from app.schemas.auth import LoginRequest
from app.services.auth import issue_password_invitation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--public-url", default="http://localhost:8501")
    args = parser.parse_args()
    # Reuse the same email validation and normalization as login.
    email = str(LoginRequest(email=args.email, password="validation-only").email)
    if not args.full_name.strip() or len(args.full_name.strip()) > 200:
        parser.error("Full name must be 1 to 200 characters")
    with SessionLocal() as db:
        employee = db.scalar(select(Employee).where(Employee.email == email))
        if employee is None:
            employee = Employee(full_name=args.full_name.strip(), email=email)
            db.add(employee)
            db.flush()
        if db.scalar(select(User.id).where(User.employee_id == employee.id)) is not None:
            raise SystemExit("A login already exists. Existing credentials were preserved.")
        invitation = issue_password_invitation(db, employee.id, "admin")
    print("Private admin activation link; expires in 24 hours and works once:")
    print(args.public_url.rstrip("/") + "/?" + urlencode({"setup": invitation["token"]}))


if __name__ == "__main__":
    main()
