from datetime import timedelta
import unittest
from uuid import uuid4
import jwt
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import engine, get_db
from app.main import app
from app.models import Employee, RefreshSession, RefreshToken, User
from app.services.auth import now

PASSWORD = "Fixture password 2026!"


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        def override():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session
        app.dependency_overrides[get_db] = override
        self.client = TestClient(app)
        self.admin = {"X-API-Key": get_settings().admin_api_key.get_secret_value()}
        self.owner = self.account()
        self.other = self.account()
        self.admin_user = self.account(role="admin")

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_db, None)
        self.transaction.rollback()
        self.connection.close()

    def account(self, role="employee"):
        email = f"login-{uuid4().hex}@example.com"
        response = self.client.post("/employees", json={"full_name": "Login Fixture", "email": email}, headers=self.admin)
        self.assertEqual(response.status_code, 201, response.text)
        employee_id = response.json()["id"]
        response = self.client.post("/auth/users", json={"employee_id": employee_id, "password": PASSWORD, "role": role}, headers=self.admin)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotIn(PASSWORD, response.text)
        return {"email": email, "employee_id": employee_id, "user_id": response.json()["id"]}

    def login(self, account=None, password=PASSWORD):
        account = account or self.owner
        response = self.client.post("/auth/login", json={"email": account["email"], "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def headers(self, tokens):
        return {"Authorization": "Bearer " + tokens["access_token"]}

    def ticket(self, account, tokens):
        response = self.client.post("/tickets", json={"title": "Login test", "description": "Details", "employee_id": account["employee_id"]}, headers=self.headers(tokens))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_login_password_hash_identity_and_duplicate_account(self):
        response = self.client.post("/auth/login", json={"email": self.owner["email"].upper(), "password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        tokens = response.json()
        self.assertEqual(tokens["user"]["employee_id"], self.owner["employee_id"])
        self.assertNotIn(PASSWORD, response.text)
        self.assertEqual(self.client.get("/auth/me", headers=self.headers(tokens)).json(), tokens["user"])
        stored = self.connection.execute(select(User.password_hash).where(User.id == self.owner["user_id"])).scalar_one()
        self.assertTrue(stored.startswith("$argon2id$"))
        self.assertNotEqual(stored, PASSWORD)
        hashes = self.connection.scalars(select(RefreshToken.token_hash)).all()
        self.assertNotIn(tokens["refresh_token"], hashes)
        response = self.client.post("/auth/users", json={"employee_id": self.owner["employee_id"], "password": PASSWORD}, headers=self.admin)
        self.assertEqual(response.status_code, 409)

    def test_password_account_retires_old_employee_keys(self):
        response = self.client.post("/employees", json={"full_name": "Legacy Fixture", "email": f"legacy-{uuid4().hex}@example.com"}, headers=self.admin)
        employee_id = response.json()["id"]
        key = self.client.post(f"/employees/{employee_id}/access-key", headers=self.admin).json()["api_key"]
        self.assertEqual(self.client.get("/identity", headers={"X-API-Key": key}).status_code, 200)
        self.assertEqual(self.client.post("/auth/users", json={"employee_id": employee_id, "password": PASSWORD}, headers=self.admin).status_code, 201)
        self.assertEqual(self.client.get("/identity", headers={"X-API-Key": key}).status_code, 401)
        self.assertEqual(self.client.post(f"/employees/{employee_id}/access-key", headers=self.admin).status_code, 409)

    def test_login_role_selection_cannot_grant_permissions(self):
        for account, wrong_role, correct_role in ((self.owner, "admin", "employee"), (self.admin_user, "employee", "admin")):
            before = self.connection.scalars(select(RefreshSession.id).where(RefreshSession.user_id == account["user_id"])).all()
            response = self.client.post("/auth/login", json={"email": account["email"], "password": PASSWORD, "role": wrong_role})
            self.assertEqual(response.status_code, 403, response.text)
            after = self.connection.scalars(select(RefreshSession.id).where(RefreshSession.user_id == account["user_id"])).all()
            self.assertEqual(before, after)
            response = self.client.post("/auth/login", json={"email": account["email"], "password": PASSWORD, "role": correct_role})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["user"]["role"], correct_role)
        self.assertEqual(self.client.post("/auth/login", json={"email": self.owner["email"], "password": PASSWORD, "role": "superadmin"}).status_code, 422)

    def test_missing_tampered_expired_and_wrong_use_access(self):
        for endpoint in ("/auth/me", "/tickets", "/employees", "/devices"):
            self.assertEqual(self.client.get(endpoint).status_code, 401)
        tokens = self.login()
        secret = get_settings().auth_jwt_secret.get_secret_value()
        claims = jwt.decode(tokens["access_token"], secret, algorithms=["HS256"], audience="meridian-copilot", issuer="meridian-it")
        variants = [tokens["access_token"] + "x", jwt.encode({**claims, "exp": now() - timedelta(seconds=1)}, secret, algorithm="HS256"), jwt.encode({**claims, "token_use": "refresh"}, secret, algorithm="HS256"), jwt.encode(claims, secret, algorithm="HS512")]
        for token in variants:
            self.assertEqual(self.client.get("/auth/me", headers={"Authorization": "Bearer " + token}).status_code, 401)

    def test_refresh_rotation_and_replay_revokes_family(self):
        initial = self.login()
        response = self.client.post("/auth/refresh", json={"refresh_token": initial["refresh_token"]})
        self.assertEqual(response.status_code, 200, response.text)
        rotated = response.json()
        self.assertNotEqual(initial["refresh_token"], rotated["refresh_token"])
        self.assertEqual(self.client.get("/auth/me", headers=self.headers(rotated)).status_code, 200)
        self.assertEqual(self.client.post("/auth/refresh", json={"refresh_token": initial["refresh_token"]}).status_code, 401)
        self.assertEqual(self.client.get("/auth/me", headers=self.headers(rotated)).status_code, 401)
        self.assertEqual(self.client.post("/auth/refresh", json={"refresh_token": rotated["refresh_token"]}).status_code, 401)

    def test_logout_revokes_access_and_refresh(self):
        tokens = self.login()
        for _ in range(2):
            self.assertEqual(self.client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]}).status_code, 204)
        self.assertEqual(self.client.get("/auth/me", headers=self.headers(tokens)).status_code, 401)
        self.assertEqual(self.client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code, 401)

    def test_reset_password_revokes_sessions_and_employee_cannot_reset(self):
        tokens = self.login()
        url = f"/auth/users/{self.owner['employee_id']}/password"
        new = "New fixture password 2026!"
        self.assertEqual(self.client.put(url, json={"password": new}, headers=self.headers(tokens)).status_code, 403)
        response = self.client.put(url, json={"password": new}, headers=self.headers(self.login(self.admin_user)))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get("/auth/me", headers=self.headers(tokens)).status_code, 401)
        self.assertEqual(self.client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code, 401)
        self.assertEqual(self.client.post("/auth/login", json={"email": self.owner["email"], "password": PASSWORD}).status_code, 401)
        self.login(password=new)

    def test_ticket_ownership_and_admin_status_permissions(self):
        owner, other, admin = self.login(), self.login(self.other), self.login(self.admin_user)
        ticket_id = self.ticket(self.owner, owner)
        other_id = self.ticket(self.other, other)
        rows = self.client.get("/tickets", headers=self.headers(owner)).json()
        self.assertEqual([row["id"] for row in rows], [ticket_id])
        for endpoint in (f"/tickets/{other_id}", f"/tickets/{other_id}/history"):
            self.assertEqual(self.client.get(endpoint, headers=self.headers(owner)).status_code, 404)
        self.assertEqual(self.client.get("/tickets", params={"employee_id": self.other["employee_id"]}, headers=self.headers(owner)).status_code, 403)
        self.assertEqual(self.client.post(f"/tickets/{other_id}/close", headers=self.headers(owner)).status_code, 404)
        self.assertEqual(self.client.patch(f"/tickets/{ticket_id}", json={"status": "resolved"}, headers=self.headers(owner)).status_code, 403)
        for status in ("in_progress", "resolved"):
            self.assertEqual(self.client.patch(f"/tickets/{ticket_id}", json={"status": status}, headers=self.headers(admin)).status_code, 200)
        self.assertEqual(self.client.post(f"/tickets/{ticket_id}/close", headers=self.headers(owner)).status_code, 200)
        self.assertEqual(self.client.get(f"/tickets/{ticket_id}/history", headers=self.headers(owner)).json()[-1]["actor_employee_id"], self.owner["employee_id"])

    def test_employee_directory_and_device_permissions(self):
        tokens = self.login()
        headers = self.headers(tokens)
        self.assertEqual(self.client.get(f"/employees/{self.other['employee_id']}", headers=headers).status_code, 404)
        self.assertEqual([row["id"] for row in self.client.get("/employees", headers=headers).json()], [self.owner["employee_id"]])
        self.assertEqual(self.client.patch(f"/employees/{self.owner['employee_id']}", json={"is_active": True}, headers=headers).status_code, 403)
        self.assertEqual(self.client.post("/auth/users", json={"employee_id": self.other["employee_id"], "password": PASSWORD, "role": "admin"}, headers=headers).status_code, 403)
        device = self.client.post("/devices", json={"asset_tag": uuid4().hex, "device_type": "laptop", "assigned_employee_id": self.other["employee_id"]}, headers=self.admin).json()
        self.assertEqual(self.client.get(f"/devices/{device['id']}", headers=headers).status_code, 404)
        self.assertEqual(self.client.get("/devices", headers=headers).json(), [])
        self.assertEqual(self.client.post("/devices", json={"asset_tag": uuid4().hex, "device_type": "laptop"}, headers=headers).status_code, 403)

    def test_inactive_user_or_employee_invalidates_existing_jwt(self):
        tokens = self.login()
        self.connection.execute(update(User).where(User.id == self.owner["user_id"]).values(is_active=False))
        self.assertEqual(self.client.get("/auth/me", headers=self.headers(tokens)).status_code, 401)
        self.assertEqual(self.client.post("/auth/login", json={"email": self.owner["email"], "password": PASSWORD}).status_code, 401)
        self.connection.execute(update(User).where(User.id == self.owner["user_id"]).values(is_active=True))
        self.client.patch(f"/employees/{self.owner['employee_id']}", json={"is_active": False}, headers=self.admin)
        self.assertEqual(self.client.get("/auth/me", headers=self.headers(tokens)).status_code, 401)
        self.assertEqual(self.client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code, 401)

    def test_login_lockout_and_generic_errors(self):
        for _ in range(5):
            response = self.client.post("/auth/login", json={"email": self.owner["email"], "password": "Wrong fixture password"})
            self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.post("/auth/login", json={"email": self.owner["email"], "password": PASSWORD}).status_code, 401)
        unknown = self.client.post("/auth/login", json={"email": "unknown@example.com", "password": PASSWORD})
        self.assertEqual(unknown.json(), response.json())
        self.connection.execute(update(User).where(User.id == self.owner["user_id"]).values(locked_until=now() - timedelta(seconds=1)))
        self.login()

    def test_expired_session_and_validation_do_not_leak_password(self):
        tokens = self.login()
        self.connection.execute(update(RefreshSession).where(RefreshSession.user_id == self.owner["user_id"]).values(expires_at=now() - timedelta(seconds=1)))
        self.assertEqual(self.client.get("/auth/me", headers=self.headers(tokens)).status_code, 401)
        self.assertEqual(self.client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code, 401)
        raw = "private" * 30
        response = self.client.post("/auth/login", json={"email": self.owner["email"], "password": raw})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(raw, response.text)


def tearDownModule():
    engine.dispose()
