"""Transactional tests for the trusted container admin bootstrap command."""
from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
import test_auth
from app.models import Employee, User

spec = importlib.util.spec_from_file_location("admin_bootstrap", Path(__file__).resolve().parents[1] / "scripts/create_admin_setup.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class ContainerAdminSetupTests(unittest.TestCase):
    setUp = test_auth.AuthenticationTests.setUp
    tearDown = test_auth.AuthenticationTests.tearDown
    account = test_auth.AuthenticationTests.account
    login = test_auth.AuthenticationTests.login

    def invoke(self, email):
        def session():
            return Session(bind=self.connection, join_transaction_mode="create_savepoint")
        output = io.StringIO()
        with patch.object(bootstrap, "SessionLocal", side_effect=session), patch("sys.argv", ["create_admin_setup.py", "--email", email, "--full-name", "Bootstrap Fixture"]), redirect_stdout(output):
            bootstrap.main()
        return output.getvalue().strip().splitlines()[-1]

    def test_first_admin_uses_browser_setup(self):
        email = f"docker-bootstrap-{uuid4().hex}@example.com"
        url = self.invoke(email)
        token = parse_qs(urlsplit(url).query)["setup"][0]
        employee_id = self.connection.scalar(select(Employee.id).where(Employee.email == email))
        self.assertIsNotNone(employee_id)
        self.assertIsNone(self.connection.scalar(select(User.id).where(User.employee_id == employee_id)))
        response = self.client.post("/auth/setup-password", json={"token": token, "password": test_auth.PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "admin")
        self.assertEqual(self.login({"email": email})["user"]["role"], "admin")

    def test_existing_employee_login_cannot_be_promoted_or_reset(self):
        with self.assertRaises(SystemExit):
            self.invoke(self.owner["email"])
        self.assertEqual(self.login()["user"]["role"], "employee")
