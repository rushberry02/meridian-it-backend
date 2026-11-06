import unittest
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import engine, get_db
from app.main import app

PASSWORD = "Dashboard fixture password!"


class AdminDashboardTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        def override():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session
        app.dependency_overrides[get_db] = override
        self.client = TestClient(app)
        self.bootstrap = {"X-API-Key": get_settings().admin_api_key.get_secret_value()}
        self.admin_id, self.admin = self.login_account("admin")
        self.employee_id, self.employee = self.login_account("employee")

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_db, None)
        self.transaction.rollback()
        self.connection.close()

    def login_account(self, role):
        email = f"dashboard-{uuid4().hex}@example.com"
        employee = self.client.post("/employees", json={"full_name": "Dashboard Fixture", "email": email}, headers=self.bootstrap).json()
        created = self.client.post("/auth/users", json={"employee_id": employee["id"], "password": PASSWORD, "role": role}, headers=self.bootstrap)
        self.assertEqual(created.status_code, 201, created.text)
        response = self.client.post("/auth/login", json={"email": email, "password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        return employee["id"], {"Authorization": "Bearer " + response.json()["access_token"]}

    def test_employee_and_anonymous_cannot_access_dashboard(self):
        for endpoint in ("/admin/summary", "/admin/tickets", "/admin/employees", "/admin/devices"):
            self.assertEqual(self.client.get(endpoint).status_code, 401)
            self.assertEqual(self.client.get(endpoint, headers=self.employee).status_code, 403)
            self.assertEqual(self.client.get(endpoint, headers=self.admin).status_code, 200)

    def test_summary_tracks_real_operational_changes(self):
        before = self.client.get("/admin/summary", headers=self.admin).json()
        created = self.client.post("/employees", json={"full_name": "Inactive Fixture", "email": f"inactive-{uuid4().hex}@example.com", "is_active": False}, headers=self.admin)
        self.assertEqual(created.status_code, 201)
        for assignment in (self.employee_id, None):
            self.assertEqual(self.client.post("/devices", json={"asset_tag": uuid4().hex, "device_type": "laptop", "assigned_employee_id": assignment}, headers=self.admin).status_code, 201)
        ids = []
        for priority in ("high", "low"):
            response = self.client.post("/tickets", json={"title": "Summary fixture", "description": "Details", "employee_id": self.employee_id, "priority": priority}, headers=self.admin)
            self.assertEqual(response.status_code, 201)
            ids.append(response.json()["id"])
        for status in ("in_progress", "resolved"):
            self.assertEqual(self.client.patch(f"/tickets/{ids[0]}", json={"status": status}, headers=self.admin).status_code, 200)
        history = self.client.get(f"/tickets/{ids[0]}/history", headers=self.admin).json()
        self.assertEqual(history[-1]["actor_employee_id"], self.admin_id)
        response = self.client.get("/admin/summary", headers=self.admin)
        self.assertEqual(response.headers["cache-control"], "no-store")
        after = response.json()
        self.assertEqual(after["employees"]["total"], before["employees"]["total"] + 1)
        self.assertEqual(after["employees"]["active"], before["employees"]["active"])
        self.assertEqual(after["devices"]["total"], before["devices"]["total"] + 2)
        self.assertEqual(after["devices"]["unassigned"], before["devices"]["unassigned"] + 1)
        self.assertEqual(after["tickets"]["open"], before["tickets"]["open"] + 1)
        self.assertEqual(after["tickets"]["resolved"], before["tickets"]["resolved"] + 1)
        self.assertEqual(after["tickets"]["high_priority_active"], before["tickets"]["high_priority_active"])

    def test_ticket_queue_search_filters_total_and_pagination(self):
        token = uuid4().hex
        ids = []
        for priority in ("low", "medium", "high"):
            response = self.client.post("/tickets", json={"title": f"Queue {token} {priority}", "description": "Details", "employee_id": self.employee_id, "priority": priority}, headers=self.admin)
            ids.append(response.json()["id"])
        response = self.client.get("/admin/tickets", params={"search": token, "limit": 2}, headers=self.admin)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total"], 3)
        self.assertEqual([row["id"] for row in response.json()["items"]], list(reversed(ids))[0:2])
        page = self.client.get("/admin/tickets", params={"search": token, "offset": 2, "limit": 2}, headers=self.admin).json()
        self.assertEqual([row["id"] for row in page["items"]], ids[0:1])
        filtered = self.client.get("/admin/tickets", params={"search": token, "priority": "high", "status": "open", "employee_id": self.employee_id}, headers=self.admin).json()
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["id"], ids[-1])

    def test_employee_device_search_and_validation(self):
        token = uuid4().hex
        response = self.client.post("/devices", json={"asset_tag": f"ASSET-{token}", "serial_number": f"100%{token}", "device_type": "laptop", "assigned_employee_id": self.employee_id}, headers=self.admin)
        self.assertEqual(response.status_code, 201)
        rows = self.client.get("/admin/devices", params={"search": f"100%{token}", "assigned_employee_id": self.employee_id}, headers=self.admin).json()
        self.assertEqual(rows["total"], 1)
        self.assertEqual(rows["items"][0]["id"], response.json()["id"])
        employee = self.client.get(f"/employees/{self.employee_id}", headers=self.admin).json()
        rows = self.client.get("/admin/employees", params={"search": employee["email"], "is_active": True}, headers=self.admin).json()
        self.assertEqual(rows["total"], 1)
        self.assertEqual(rows["items"][0]["id"], self.employee_id)
        for endpoint, params in (("tickets", {"limit": 101}), ("employees", {"offset": -1}), ("devices", {"assigned_employee_id": 0}), ("tickets", {"status": "invalid"})):
            self.assertEqual(self.client.get("/admin/" + endpoint, params=params, headers=self.admin).status_code, 422)


def tearDownModule():
    engine.dispose()
