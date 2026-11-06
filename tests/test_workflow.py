import unittest
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import engine, get_db
from app.main import app
from app.models import TicketStatusHistory


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        def override():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session
        app.dependency_overrides[get_db] = override
        settings = get_settings()
        self.support = {"X-API-Key": settings.support_api_key.get_secret_value()}
        self.admin = {"X-API-Key": settings.admin_api_key.get_secret_value()}
        self.client = TestClient(app)
        response = self.client.post("/employees", json={"full_name": "Workflow Test", "email": f"workflow-{uuid4().hex}@example.com"})
        self.employee_id = response.json()["id"]
        self.payload = {"title": "Workflow test", "description": "Details", "employee_id": self.employee_id}

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_db, None)
        self.transaction.rollback()
        self.connection.close()

    def create(self):
        response = self.client.post("/tickets", json=self.payload, headers=self.support)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_keys_and_admin_boundary(self):
        for headers in ({}, {"X-API-Key": "wrong"}):
            self.assertEqual(self.client.post("/tickets", json=self.payload, headers=headers).status_code, 401)
        ticket_id = self.create()
        endpoint = f"/tickets/{ticket_id}"
        for payload in ({"priority": "urgent"}, {"employee_id": self.employee_id + 1}):
            self.assertEqual(self.client.patch(endpoint, json=payload, headers=self.support).status_code, 403)
        self.assertEqual(self.client.patch(endpoint + "/admin", json={"priority": "urgent"}, headers=self.support).status_code, 403)
        self.assertEqual(self.client.delete(endpoint, headers=self.support).status_code, 403)
        response = self.client.patch(endpoint + "/admin", json={"priority": "urgent"}, headers=self.admin)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["priority"], "urgent")

    def test_workflow_and_history(self):
        ticket_id = self.create()
        endpoint = f"/tickets/{ticket_id}"
        history = self.client.get(endpoint + "/history").json()
        self.assertEqual([(row["old_status"], row["new_status"], row["actor_role"]) for row in history], [(None, "open", "support")])
        for state in ("in_progress", "resolved", "in_progress", "resolved", "closed"):
            response = self.client.patch(endpoint, json={"status": state, "reason": "Admin requested"}, headers=self.admin)
            self.assertEqual(response.status_code, 200, response.text)
        history = self.client.get(endpoint + "/history").json()
        self.assertEqual([row["new_status"] for row in history], ["open", "in_progress", "resolved", "in_progress", "resolved", "closed"])
        self.assertTrue(all(row["reason"] == "Admin requested" for row in history[1:]))
        self.assertTrue(all(row["actor_role"] == "admin" for row in history[1:]))
        self.assertEqual(self.client.get(endpoint + "/history", params={"offset": 1, "limit": 1}).json(), history[1:2])
        # A repeated request to the current status is a no-op, not a second event.
        self.assertEqual(self.client.patch(endpoint, json={"status": "closed"}, headers=self.admin).status_code, 200)
        self.assertEqual(len(self.client.get(endpoint + "/history").json()), 6)

    def test_invalid_transitions_and_admin_override(self):
        ticket_id = self.create()
        endpoint = f"/tickets/{ticket_id}"
        for state in ("resolved", "closed"):
            response = self.client.patch(endpoint, json={"status": state, "title": "Must roll back"}, headers=self.admin)
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.client.get(endpoint).json()["title"], "Workflow test")
        self.assertEqual(len(self.client.get(endpoint + "/history").json()), 1)
        self.assertEqual(self.client.patch(endpoint + "/admin", json={"status": "closed"}, headers=self.admin).status_code, 409)
        response = self.client.patch(endpoint + "/admin", json={"status": "closed", "reason": "Closed by administrator"}, headers=self.admin)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.patch(endpoint, json={"status": "open"}, headers=self.support).status_code, 403)
        response = self.client.patch(endpoint + "/admin", json={"status": "open", "reason": "Issue recurred"}, headers=self.admin)
        self.assertEqual(response.status_code, 200, response.text)
        latest = self.client.get(endpoint + "/history").json()[-1]
        self.assertEqual((latest["old_status"], latest["new_status"], latest["actor_role"], latest["reason"]), ("closed", "open", "admin", "Issue recurred"))

    def test_support_cannot_submit_status_or_mutate_history(self):
        ticket_id = self.create()
        endpoint = f"/tickets/{ticket_id}"
        original = self.client.get(endpoint).json()
        history = self.client.get(endpoint + "/history").json()
        for status in ("open", "in_progress", "resolved", "closed"):
            for suffix in ("", "/admin"):
                response = self.client.patch(endpoint + suffix, json={"status": status, "title": "Must not change", "reason": "I claim to be admin"}, headers=self.support)
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(self.client.get(endpoint).json(), original)
                self.assertEqual(self.client.get(endpoint + "/history").json(), history)
        # Non-status employee edits remain possible, and admins can update normally.
        self.assertEqual(self.client.patch(endpoint, json={"description": "More details"}, headers=self.support).status_code, 200)
        self.assertEqual(self.client.patch(endpoint, json={"status": "in_progress"}, headers=self.admin).status_code, 200)
        event = self.client.get(endpoint + "/history").json()[-1]
        self.assertEqual(event["actor_role"], "admin")

    def test_creation_state_and_history_deletion(self):
        self.assertEqual(self.client.post("/tickets", json={**self.payload, "status": "closed"}, headers=self.support).status_code, 422)
        ticket_id = self.create()
        self.assertEqual(self.client.delete(f"/tickets/{ticket_id}", headers=self.admin).status_code, 204)
        self.assertEqual(self.client.get(f"/tickets/{ticket_id}/history").status_code, 404)
        count = self.connection.scalar(select(func.count()).select_from(TicketStatusHistory).where(TicketStatusHistory.ticket_id == ticket_id))
        self.assertEqual(count, 0)

    def test_failed_link_update_has_no_history(self):
        ticket_id = self.create()
        employee = self.client.post("/employees", json={"full_name": "Missing Test", "email": f"missing-{uuid4().hex}@example.com"}).json()["id"]
        self.assertEqual(self.client.delete(f"/employees/{employee}").status_code, 204)
        response = self.client.patch(f"/tickets/{ticket_id}", json={"employee_id": employee, "status": "in_progress"}, headers=self.admin)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(f"/tickets/{ticket_id}").json()["status"], "open")
        self.assertEqual(len(self.client.get(f"/tickets/{ticket_id}/history").json()), 1)


def tearDownModule():
    engine.dispose()
