"""Local account provisioning; --show-password makes terminal input visible."""
import argparse
import getpass
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import func, select
from app.database import SessionLocal
from app.models import Employee
from app.services.auth import provision_user


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", choices=["employee", "admin"], default=None)
    parser.add_argument("--show-password", action="store_true", help="Show password characters in this terminal while entering and confirming")
    args = parser.parse_args()
    read_password = input if args.show_password else getpass.getpass
    password = read_password("New password (12-128 characters): ")
    if password != read_password("Confirm password: "):
        raise SystemExit("Passwords do not match; nothing changed.")
    with SessionLocal() as db:
        employee = db.scalar(select(Employee).where(func.lower(Employee.email) == args.email.strip().lower()))
        if employee is None:
            raise SystemExit("Employee not found. Create the employee record first.")
        result = provision_user(db, employee.id, password, args.role)
        print(f"Login ready for {result['email']} ({result['role']}). Existing login sessions were revoked.")


if __name__ == "__main__":
    main()
