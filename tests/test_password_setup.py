from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, update
from test_auth import AuthenticationTests, PASSWORD
from app.models import PasswordInvitation, User
from app.services.auth import now, token_hash


class PasswordInvitationTests(AuthenticationTests):
    # Use the existing transactional authentication fixture without inheriting tests.
    def employee(self):
        email = f"setup-{uuid4().hex}@example.com"
        response = self.client.post("/employees", json={"full_name": "Setup Fixture", "email": email}, headers=self.admin)
        self.assertEqual(response.status_code, 201)
        return response.json()

    def issue(self, employee, role="employee"):
        response = self.client.post("/auth/setup-invitations", json={"employee_id": employee["id"], "role": role}, headers=self.admin)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response.json()["token"]

    def test_new_account_setup_and_replay(self):
        for role in ("employee", "admin"):
            employee = self.employee()
            token = self.issue(employee, role)
            stored = self.connection.execute(select(PasswordInvitation.token_hash).where(PasswordInvitation.employee_id == employee["id"])).scalar_one()
            self.assertEqual(stored, token_hash(token))
            self.assertNotEqual(stored, token)
            body = {"token": token, "password": PASSWORD}
            response = self.client.post("/auth/setup-password", json=body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["role"], role)
            self.assertNotIn(PASSWORD, response.text)
            self.assertEqual(self.client.post("/auth/setup-password", json=body).status_code, 400)
            self.assertEqual(self.login({"email": employee["email"]})["user"]["role"], role)

    def test_expired_replaced_invalid_and_tampered_links(self):
        employee = self.employee()
        old = self.issue(employee)
        new = self.issue(employee)
        def complete(token):
            return self.client.post("/auth/setup-password", json={"token": token, "password": PASSWORD})
        self.assertEqual(complete(old).status_code, 400)
        self.assertEqual(complete("x" * 64).status_code, 400)
        self.connection.execute(update(PasswordInvitation).where(PasswordInvitation.token_hash == token_hash(new)).values(expires_at=now()-timedelta(seconds=1)))
        self.assertEqual(complete(new).status_code, 400)
        self.assertIsNone(self.connection.scalar(select(User.id).where(User.employee_id == employee["id"])))

    def test_admin_only_issuance_and_no_role_injection(self):
        employee = self.employee()
        self.assertEqual(self.client.post("/auth/setup-invitations", json={"employee_id": employee["id"]}).status_code, 401)
        self.assertEqual(self.client.post("/auth/setup-invitations", json={"employee_id": employee["id"], "role": "admin"}, headers=self.headers(self.login())).status_code, 403)
        token = self.issue(employee)
        for extra in ({"role": "admin"}, {"password": "short"}):
            response = self.client.post("/auth/setup-password", json={"token": token, "password": PASSWORD, **extra})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(token, response.text)
        self.assertEqual(self.client.post("/auth/setup-password", json={"token": token, "password": PASSWORD}).json()["role"], "employee")

    def test_existing_account_and_inactive_employee_protected(self):
        self.assertEqual(self.client.post("/auth/setup-invitations", json={"employee_id": self.owner["employee_id"], "role": "admin"}, headers=self.admin).status_code, 409)
        employee = self.employee()
        token = self.issue(employee)
        self.client.patch(f"/employees/{employee['id']}", json={"is_active": False}, headers=self.admin)
        self.assertEqual(self.client.post("/auth/setup-password", json={"token": token, "password": PASSWORD}).status_code, 404)
