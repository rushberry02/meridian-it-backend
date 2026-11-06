"""PostgreSQL ticket API tests; all test records are rolled back."""
import unittest
from datetime import datetime, timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import engine, get_db
from app.main import app
from app.models import Ticket
from app.config import get_settings


class TicketApiTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        def override():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session
        app.dependency_overrides[get_db] = override
        self.client = TestClient(app, headers={"X-API-Key": get_settings().admin_api_key.get_secret_value()})
        self.employee_id = self.employee()

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_db, None)
        self.transaction.rollback()
        self.connection.close()

    def employee(self):
        response = self.client.post("/employees", json={"full_name": "Ticket Test", "email": f"ticket-{uuid4().hex}@example.com"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def device(self):
        response = self.client.post("/devices", json={"asset_tag": f"ticket-{uuid4().hex}", "device_type": "laptop"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def ticket(self, **changes):
        payload = {"title": "Cannot connect", "description": "Network unavailable", "employee_id": self.employee_id}
        desired_status = changes.pop("status", "open")
        payload.update(changes)
        response = self.client.post("/tickets", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        if desired_status != "open":
            response = self.client.patch(f'/tickets/{response.json()["id"]}/admin', json={"status": desired_status, "reason": "Test fixture status"})
            self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_crud_defaults_and_timestamps(self):
        ticket = self.ticket(title="  Network problem  ")
        endpoint = f'/tickets/{ticket["id"]}'
        self.assertEqual(ticket["title"], "Network problem")
        self.assertEqual(ticket["status"], "open")
        self.assertEqual(ticket["priority"], "medium")
        self.assertIsNone(ticket["device_id"])
        self.assertIsNotNone(datetime.fromisoformat(ticket["created_at"]).tzinfo)
        self.assertEqual(self.client.get(endpoint).json(), ticket)
        self.assertEqual(self.client.patch(endpoint, json={}).json(), ticket)
        # Make timestamp change observable even within one PostgreSQL transaction.
        self.connection.execute(Ticket.__table__.update().where(Ticket.id == ticket["id"]).values(updated_at=datetime(2000, 1, 1, tzinfo=timezone.utc)))
        response = self.client.patch(endpoint, json={"description": "Updated details", "priority": "urgent"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["title"], ticket["title"])
        self.assertEqual(response.json()["description"], "Updated details")
        self.assertEqual(response.json()["priority"], "urgent")
        self.assertGreater(datetime.fromisoformat(response.json()["updated_at"]).year, 2000)
        self.assertEqual(response.json()["created_at"], ticket["created_at"])
        response = self.client.delete(endpoint)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        for response in (self.client.get(endpoint), self.client.patch(endpoint, json={"status": "closed"}), self.client.delete(endpoint)):
            self.assertEqual(response.status_code, 404)

    def test_status_and_priority_changes(self):
        ticket = self.ticket()
        endpoint = f'/tickets/{ticket["id"]}'
        for status, priority in zip(("in_progress", "resolved", "closed", "open"), ("high", "low", "urgent", "medium")):
            response = self.client.patch(endpoint, json={"status": status, "priority": priority, "reason": "Test workflow override"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], status)
            self.assertEqual(response.json()["priority"], priority)

    def test_link_and_unlink_device_and_change_employee(self):
        first, second = self.device(), self.device()
        ticket = self.ticket(device_id=first)
        endpoint = f'/tickets/{ticket["id"]}'
        self.assertEqual(ticket["device_id"], first)
        response = self.client.patch(endpoint, json={"device_id": second})
        self.assertEqual(response.json()["device_id"], second)
        employee_id = self.employee()
        response = self.client.patch(endpoint, json={"device_id": None, "employee_id": employee_id})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["device_id"])
        self.assertEqual(response.json()["employee_id"], employee_id)

    def test_missing_links_and_update_atomicity(self):
        employee_id, device_id = self.employee(), self.device()
        self.assertEqual(self.client.delete(f"/employees/{employee_id}").status_code, 204)
        self.assertEqual(self.client.delete(f"/devices/{device_id}").status_code, 204)
        base = {"title": "Missing link", "description": "Test", "employee_id": self.employee_id}
        for change, detail in (({"employee_id": employee_id}, "Employee not found"), ({"device_id": device_id}, "Device not found")):
            response = self.client.post("/tickets", json={**base, **change})
            self.assertEqual(response.status_code, 404, response.text)
            self.assertEqual(response.json()["detail"], detail)
        ticket = self.ticket()
        endpoint = f'/tickets/{ticket["id"]}'
        for change in ({"employee_id": employee_id}, {"device_id": device_id}):
            response = self.client.patch(endpoint, json={"title": "Must not save", **change})
            self.assertEqual(response.status_code, 404, response.text)
            self.assertEqual(self.client.get(endpoint).json()["title"], ticket["title"])

    def test_linked_record_deletion_protection(self):
        device_id = self.device()
        ticket = self.ticket(device_id=device_id)
        self.assertEqual(self.client.delete(f"/employees/{self.employee_id}").status_code, 409)
        self.assertEqual(self.client.delete(f"/devices/{device_id}").status_code, 409)
        self.assertEqual(self.client.get(f'/tickets/{ticket["id"]}').status_code, 200)
        self.assertEqual(self.client.patch(f'/tickets/{ticket["id"]}', json={"device_id": None}).status_code, 200)
        self.assertEqual(self.client.delete(f"/devices/{device_id}").status_code, 204)
        self.assertEqual(self.client.delete(f'/tickets/{ticket["id"]}').status_code, 204)
        self.assertEqual(self.client.delete(f"/employees/{self.employee_id}").status_code, 204)

    def test_validation(self):
        valid = {"title": "Test", "description": "Details", "employee_id": self.employee_id}
        for payload in ({}, {**valid, "title": " "}, {**valid, "title": "x" * 201}, {**valid, "description": "x" * 10001}, {**valid, "description": " "}, {**valid, "status": "invalid"}, {**valid, "priority": "invalid"}, {**valid, "employee_id": 0}, {**valid, "device_id": -1}, {**valid, "id": 4}):
            self.assertEqual(self.client.post("/tickets", json=payload).status_code, 422)
        ticket = self.ticket()
        endpoint = f'/tickets/{ticket["id"]}'
        for field in ("title", "description", "employee_id", "status", "priority"):
            self.assertEqual(self.client.patch(endpoint, json={field: None}).status_code, 422)
        for value in ("0", "-1", "abc", "2147483648"):
            self.assertEqual(self.client.get(f"/tickets/{value}").status_code, 422)
        for params in ({"offset": -1}, {"limit": 101}, {"limit": 0}, {"employee_id": 0}, {"device_id": -1}, {"status": "bad"}, {"priority": "bad"}):
            self.assertEqual(self.client.get("/tickets", params=params).status_code, 422)

    def test_filters_pagination_and_openapi(self):
        device_id = self.device()
        first = self.ticket(device_id=device_id, priority="high")
        second = self.ticket(status="resolved")
        third = self.ticket(device_id=device_id, status="closed", priority="low")
        for filters, expected in (
            ({"employee_id": self.employee_id}, [first["id"], second["id"], third["id"]]),
            ({"employee_id": self.employee_id, "device_id": device_id}, [first["id"], third["id"]]),
            ({"employee_id": self.employee_id, "status": "open", "priority": "high"}, [first["id"]]),
            ({"employee_id": self.employee_id, "status": "closed", "priority": "high"}, []),
            ({"employee_id": self.employee_id, "offset": 1, "limit": 1}, [second["id"]]),
        ):
            response = self.client.get("/tickets", params=filters)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual([row["id"] for row in response.json()], expected)
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertEqual(set(paths["/tickets"]), {"get", "post"})
        self.assertEqual(set(paths["/tickets/{ticket_id}"]), {"get", "patch", "delete"})

    def test_database_constraints_and_defaults(self):
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            ticket = Ticket(title="Database default", description="Details", employee_id=self.employee_id)
            session.add(ticket)
            session.flush()
            session.refresh(ticket)
            self.assertEqual(ticket.status, "open")
            self.assertEqual(ticket.priority, "medium")
            for change in ({"status": "invalid"}, {"priority": "invalid"}, {"employee_id": None}):
                with self.assertRaises(IntegrityError):
                    with session.begin_nested():
                        session.add(Ticket(title="Constraint", description="Details", **{"employee_id": self.employee_id, **change}))
                        session.flush()
            missing = self.employee()
            self.assertEqual(self.client.delete(f"/employees/{missing}").status_code, 204)
            with self.assertRaises(IntegrityError):
                with session.begin_nested():
                    session.add(Ticket(title="Foreign key", description="Details", employee_id=missing))
                    session.flush()


def tearDownModule():
    engine.dispose()
