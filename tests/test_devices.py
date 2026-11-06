from app.config import get_settings
"""Device API integration tests with PostgreSQL and transaction rollback."""
import unittest
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import engine, get_db
from app.main import app
from app.models import Device


class DeviceApiTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        def override():
            with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
                yield session
        app.dependency_overrides[get_db] = override
        self.client = TestClient(app, headers={"X-API-Key": get_settings().admin_api_key.get_secret_value()})

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_db, None)
        self.transaction.rollback()
        self.connection.close()

    def device(self, **changes):
        payload = {"asset_tag": f"asset-{uuid4().hex}", "device_type": "laptop"}
        payload.update(changes)
        response = self.client.post("/devices", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def employee(self):
        response = self.client.post("/employees", json={"full_name": "Device Test", "email": f"device-{uuid4().hex}@example.com"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_crud(self):
        device = self.device(manufacturer="  Dell  ")
        endpoint = f'/devices/{device["id"]}'
        self.assertEqual(device["asset_tag"], device["asset_tag"].upper())
        self.assertEqual(device["manufacturer"], "Dell")
        self.assertIsNone(device["assigned_employee_id"])
        self.assertEqual(self.client.get(endpoint).json(), device)
        self.assertEqual(self.client.patch(endpoint, json={}).json(), device)
        response = self.client.patch(endpoint, json={"model": "Latitude", "manufacturer": None})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["model"], "Latitude")
        self.assertIsNone(response.json()["manufacturer"])
        self.assertEqual(response.json()["asset_tag"], device["asset_tag"])
        response = self.client.delete(endpoint)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        for response in (self.client.get(endpoint), self.client.patch(endpoint, json={"model": "X"}), self.client.delete(endpoint)):
            self.assertEqual(response.status_code, 404)

    def test_assign_reassign_unassign_and_employee_deletion(self):
        first, second = self.employee(), self.employee()
        device = self.device(assigned_employee_id=first)
        other = self.device(assigned_employee_id=first)
        endpoint = f'/devices/{device["id"]}'
        self.assertEqual(self.client.delete(f"/employees/{first}").status_code, 409)
        self.assertEqual(self.client.get(endpoint).json()["assigned_employee_id"], first)
        response = self.client.get("/devices", params={"assigned_employee_id": first})
        self.assertEqual({row["id"] for row in response.json()}, {device["id"], other["id"]})
        response = self.client.patch(endpoint, json={"assigned_employee_id": second})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["assigned_employee_id"], second)
        response = self.client.patch(endpoint, json={"assigned_employee_id": None})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["assigned_employee_id"])
        self.assertEqual(self.client.delete(f"/employees/{second}").status_code, 204)
        self.assertEqual(self.client.delete(f'/devices/{other["id"]}').status_code, 204)
        self.assertEqual(self.client.delete(f"/employees/{first}").status_code, 204)

    def test_missing_employee_and_database_foreign_key(self):
        missing = self.employee()
        self.assertEqual(self.client.delete(f"/employees/{missing}").status_code, 204)
        response = self.client.post("/devices", json={"asset_tag": f"x-{uuid4().hex}", "device_type": "desktop", "assigned_employee_id": missing})
        self.assertEqual(response.status_code, 404, response.text)
        device = self.device()
        response = self.client.patch(f'/devices/{device["id"]}', json={"assigned_employee_id": missing, "model": "Must not save"})
        self.assertEqual(response.status_code, 404)
        self.assertIsNone(self.client.get(f'/devices/{device["id"]}').json()["model"])
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            with self.assertRaises(IntegrityError):
                with session.begin_nested():
                    session.add(Device(asset_tag=f"FK-{uuid4().hex}", device_type="laptop", assigned_employee_id=missing))
                    session.flush()

    def test_duplicates_and_rollback(self):
        first, second = self.device(), self.device()
        response = self.client.post("/devices", json={"asset_tag": first["asset_tag"].lower(), "device_type": "phone"})
        self.assertEqual(response.status_code, 409, response.text)
        endpoint = f'/devices/{second["id"]}'
        response = self.client.patch(endpoint, json={"asset_tag": first["asset_tag"].lower(), "model": "Not saved"})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIsNone(self.client.get(endpoint).json()["model"])
        self.assertEqual(self.client.patch(endpoint, json={"model": "Saved"}).status_code, 200)

    def test_validation_pagination_and_docs(self):
        for payload in ({}, {"asset_tag": " ", "device_type": "laptop"}, {"asset_tag": "x", "device_type": "invalid"}, {"asset_tag": "x" * 101, "device_type": "laptop"}, {"asset_tag": "x", "device_type": "laptop", "assigned_employee_id": 0}, {"asset_tag": "x", "device_type": "laptop", "id": 5}):
            self.assertEqual(self.client.post("/devices", json=payload).status_code, 422)
        device = self.device()
        for payload in ({"asset_tag": None}, {"device_type": None}, {"assigned_employee_id": -1}, {"manufacturer": " "}):
            self.assertEqual(self.client.patch(f'/devices/{device["id"]}', json=payload).status_code, 422)
        expected = self.connection.scalars(select(Device.id).order_by(Device.id).limit(1)).all()
        response = self.client.get("/devices", params={"limit": 1})
        self.assertEqual([row["id"] for row in response.json()], expected)
        for params in ({"offset": -1}, {"limit": 101}, {"limit": 0}, {"assigned_employee_id": 0}):
            self.assertEqual(self.client.get("/devices", params=params).status_code, 422)
        schema = self.client.get("/openapi.json").json()
        self.assertEqual(set(schema["paths"]["/devices"]), {"get", "post"})
        self.assertEqual(set(schema["paths"]["/devices/{device_id}"]), {"get", "patch", "delete"})
        for value in ("0", "-1", "abc", "2147483648"):
            self.assertEqual(self.client.get(f"/devices/{value}").status_code, 422)


def tearDownModule():
    engine.dispose()
