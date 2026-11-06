import unittest
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import engine, get_db
from app.main import app


class EmployeeClosureTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        def override():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session
        app.dependency_overrides[get_db] = override
        self.client = TestClient(app, headers={"X-API-Key": get_settings().admin_api_key.get_secret_value()})
        settings = get_settings()
        self.admin = {"X-API-Key": settings.admin_api_key.get_secret_value()}
        self.support = {"X-API-Key": settings.support_api_key.get_secret_value()}
        self.owner, self.owner_headers = self.employee()
        self.other, self.other_headers = self.employee()

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_db, None)
        self.transaction.rollback()
        self.connection.close()

    def employee(self):
        response = self.client.post("/employees", json={"full_name": "Closure Test", "email": f"closure-{uuid4().hex}@example.com"})
        employee_id = response.json()["id"]
        response = self.client.post(f"/employees/{employee_id}/access-key", headers=self.admin)
        self.assertEqual(response.status_code, 200, response.text)
        return employee_id, {"X-API-Key": response.json()["api_key"]}

    def ticket(self):
        response = self.client.post("/tickets", json={"title": "Closure test", "description": "Details", "employee_id": self.owner}, headers=self.owner_headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def resolve(self, ticket_id):
        for status in ("in_progress", "resolved"):
            response = self.client.patch(f"/tickets/{ticket_id}", json={"status": status}, headers=self.admin)
            self.assertEqual(response.status_code, 200, response.text)

    def test_owner_closes_from_every_active_status(self):
        for initial_status in ("open", "in_progress", "resolved"):
            with self.subTest(status=initial_status):
                ticket_id = self.ticket()
                endpoint = f"/tickets/{ticket_id}"
                if initial_status in ("in_progress", "resolved"):
                    self.assertEqual(self.client.patch(endpoint, json={"status": "in_progress"}, headers=self.admin).status_code, 200)
                if initial_status == "resolved":
                    self.assertEqual(self.client.patch(endpoint, json={"status": "resolved"}, headers=self.admin).status_code, 200)
                response = self.client.post(endpoint + "/close", headers=self.owner_headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["status"], "closed")
                history = self.client.get(endpoint + "/history").json()
                event = history[-1]
                self.assertEqual((event["old_status"], event["new_status"], event["actor_role"], event["actor_employee_id"]), (initial_status, "closed", "employee", self.owner))
                if initial_status == "open":
                    self.assertEqual(len(history), 2)
                    self.assertIn("without awaiting support", event["reason"])
                self.assertEqual(self.client.post(endpoint + "/close", headers=self.owner_headers).status_code, 200)
                self.assertEqual(self.client.get(endpoint + "/history").json(), history)

    def test_patch_can_close_open_own_ticket(self):
        ticket_id = self.ticket()
        response = self.client.patch(f"/tickets/{ticket_id}", json={"status": "closed"}, headers=self.owner_headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "closed")

    def test_other_employee_and_service_key_cannot_close(self):
        for initial_status in ("open", "in_progress", "resolved"):
            with self.subTest(status=initial_status):
                ticket_id = self.ticket()
                endpoint = f"/tickets/{ticket_id}"
                if initial_status in ("in_progress", "resolved"):
                    self.assertEqual(self.client.patch(endpoint, json={"status": "in_progress"}, headers=self.admin).status_code, 200)
                if initial_status == "resolved":
                    self.assertEqual(self.client.patch(endpoint, json={"status": "resolved"}, headers=self.admin).status_code, 200)
                history = self.client.get(endpoint + "/history").json()
                for headers in (self.other_headers, self.support):
                    self.assertEqual(self.client.post(endpoint + "/close", headers=headers).status_code, 404 if headers == self.other_headers else 403)
                    self.assertEqual(self.client.patch(endpoint, json={"status": "closed"}, headers=headers).status_code, 404 if headers == self.other_headers else 403)
                self.assertEqual(self.client.get(endpoint + "/history").json(), history)
                self.assertEqual(self.client.get(endpoint).json()["status"], initial_status)

    def test_employee_cannot_resolve_reopen_reassign_or_delete(self):
        ticket_id = self.ticket()
        endpoint = f"/tickets/{ticket_id}"
        for payload in ({"status": "resolved"}, {"status": "in_progress"}, {"status": "open"}, {"employee_id": self.other}, {"priority": "urgent"}, {"title": "Changed"}):
            self.assertEqual(self.client.patch(endpoint, json=payload, headers=self.owner_headers).status_code, 403)
        self.assertEqual(self.client.delete(endpoint, headers=self.owner_headers).status_code, 403)
        self.assertEqual(self.client.patch(endpoint + "/admin", json={"status": "resolved", "reason": "Claiming admin"}, headers=self.owner_headers).status_code, 403)
        self.resolve(ticket_id)
        self.assertEqual(self.client.patch(endpoint, json={"status": "closed"}, headers=self.owner_headers).status_code, 200)
        self.assertEqual(self.client.patch(endpoint, json={"status": "open"}, headers=self.owner_headers).status_code, 403)

    def test_identity_and_credential_integrity(self):
        self.assertEqual(self.client.get("/identity", headers=self.owner_headers).json(), {"role": "employee", "employee_id": self.owner})
        self.assertEqual(self.client.post(f"/employees/{self.other}/access-key", headers=self.owner_headers).status_code, 403)
        self.assertEqual(self.client.post("/tickets", json={"title": "Other", "description": "Spoof", "employee_id": self.other}, headers=self.owner_headers).status_code, 403)
        key = self.owner_headers["X-API-Key"]
        self.assertEqual(self.client.get("/identity", headers={"X-API-Key": key + "x"}).status_code, 401)
        self.assertEqual(self.client.patch(f"/employees/{self.owner}", json={"is_active": False}).status_code, 200)
        self.assertEqual(self.client.get("/identity", headers=self.owner_headers).status_code, 401)


def tearDownModule():
    engine.dispose()
