from app.config import get_settings
"""PostgreSQL integration tests; each test rolls back all employee changes."""
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.main import app
from app.models import Employee


class EmployeeApiTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.transaction = self.connection.begin()

        def database_override():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_db] = database_override
        self.client = TestClient(app, headers={"X-API-Key": get_settings().admin_api_key.get_secret_value()})

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_db, None)
        self.transaction.rollback()
        self.connection.close()

    def create(self, **changes):
        data = {"full_name": "Test Employee", "email": f"test-{uuid4().hex}@example.com"}
        data.update(changes)
        response = self.client.post("/employees", json=data)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_create_get_update_delete(self):
        employee = self.create(full_name="  Test Employee  ", department="IT")
        employee_id = employee["id"]
        self.assertEqual(employee["full_name"], "Test Employee")
        self.assertTrue(employee["is_active"])
        self.assertIsNone(employee["job_title"])
        self.assertIn("created_at", employee)
        self.assertEqual(self.client.get(f"/employees/{employee_id}").json(), employee)
        response = self.client.patch(f"/employees/{employee_id}", json={"department": None, "job_title": "Engineer", "is_active": False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["department"])
        self.assertFalse(response.json()["is_active"])
        self.assertEqual(response.json()["email"], employee["email"])
        self.assertEqual(response.json()["job_title"], "Engineer")
        response = self.client.delete(f"/employees/{employee_id}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        for response in (
            self.client.get(f"/employees/{employee_id}"),
            self.client.patch(f"/employees/{employee_id}", json={"full_name": "Missing"}),
            self.client.delete(f"/employees/{employee_id}"),
        ):
            self.assertEqual(response.status_code, 404)

    def test_duplicate_email_and_session_recovery(self):
        employee = self.create(email=f"Mixed-{uuid4().hex}@EXAMPLE.COM")
        self.assertEqual(employee["email"], employee["email"].lower())
        response = self.client.post("/employees", json={"full_name": "Duplicate", "email": employee["email"].upper()})
        self.assertEqual(response.status_code, 409, response.text)
        other = self.create()
        response = self.client.patch(f'/employees/{other["id"]}', json={"email": employee["email"].upper(), "full_name": "Should roll back"})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.client.get(f'/employees/{other["id"]}').json()["full_name"], other["full_name"])

    def test_create_validation(self):
        valid = {"full_name": "Employee", "email": "employee@example.com"}
        for values in (
            {}, {**valid, "email": "invalid"}, {**valid, "full_name": "   "},
            {**valid, "full_name": "x" * 201}, {**valid, "department": "x" * 101},
            {**valid, "id": 999}, {**valid, "is_active": None},
        ):
            with self.subTest(values=values):
                self.assertEqual(self.client.post("/employees", json=values).status_code, 422)

    def test_patch_validation_and_empty_patch(self):
        employee = self.create()
        endpoint = f'/employees/{employee["id"]}'
        for values in ({"full_name": None}, {"email": None}, {"is_active": None}, {"email": "invalid"}, {"full_name": " "}, {"created_at": "2000-01-01"}):
            with self.subTest(values=values):
                self.assertEqual(self.client.patch(endpoint, json=values).status_code, 422)
        response = self.client.patch(endpoint, json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), employee)

    def test_pagination(self):
        self.create()
        self.create()
        expected = self.connection.scalars(select(Employee.id).order_by(Employee.id).offset(1).limit(2)).all()
        response = self.client.get("/employees", params={"offset": 1, "limit": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()], expected)
        for params in ({"offset": -1}, {"limit": 0}, {"limit": 101}):
            self.assertEqual(self.client.get("/employees", params=params).status_code, 422)

    def test_health_openapi_and_id_validation(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "healthy"})
        self.assertEqual(self.client.get("/health/database").json(), {"status": "healthy", "database": "connected"})
        schema = self.client.get("/openapi.json").json()
        self.assertEqual(set(schema["paths"]["/employees"]), {"get", "post"})
        self.assertEqual(set(schema["paths"]["/employees/{employee_id}"]), {"get", "patch", "delete"})
        for value in ("0", "-1", "not-an-id"):
            self.assertEqual(self.client.get(f"/employees/{value}").status_code, 422)


def tearDownModule():
    engine.dispose()


if __name__ == "__main__":
    unittest.main()
