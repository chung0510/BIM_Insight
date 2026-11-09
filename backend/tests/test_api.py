import os
from uuid import uuid4
import hashlib

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient


TOKEN = "test-only-token-" + "x" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}
TEST_DATABASES = set()
TEST_PASSWORD = "Local-tests-only-password-123!"


class AccountClient(TestClient):
    def __init__(self, *args, mongo_uri="mongodb://127.0.0.1:27017", database_name=None, **kwargs):
        self.mongo_uri, self.database_name = mongo_uri, database_name
        self.upload_project = None
        super().__init__(*args, **kwargs)

    def post(self, url, **kwargs):
        # Older upload fixtures now use a real persistent project in the isolated test database.
        if url == "/api/inspections" and kwargs.get("files") and not (kwargs.get("data") or {}).get("project_id") and kwargs.get("headers", {}).get("Authorization") == AUTH["Authorization"]:
            if not self.upload_project:
                created = super().post("/api/projects", json={"name": "Local test uploads"}, headers=AUTH)
                assert created.status_code == 201, created.text
                self.upload_project = created.json()["id"]
            kwargs["data"] = {**(kwargs.get("data") or {}), "project_id": self.upload_project,
                              "revision": "R01", "logical_source": uuid4().hex}
        return super().post(url, **kwargs)

    def __enter__(self):
        super().__enter__()
        state = self.get("/api/auth/state", headers=AUTH)
        if state.status_code == 200:
            payload = {"username": "localtester", "password": TEST_PASSWORD}
            if state.json()["setup_required"]:
                response = self.post("/api/auth/bootstrap", headers=AUTH, json={**payload, "display_name": "Local tester"})
            else:
                response = self.post("/api/auth/login", headers=AUTH, json=payload)
            assert response.status_code in {200, 201}, response.text
            self.headers["X-BIM-Session"] = response.json()["session_token"]
            if self.database_name:
                TEST_DATABASES.add((self.mongo_uri, self.database_name))
        return self


def database_name_for(directory):
    return "bim_insight_test_" + hashlib.sha256(str(directory).encode()).hexdigest()[:24]


def client_for(**kwargs):
    from app.main import create_app

    kwargs.setdefault("database_name", "bim_insight_test_" + uuid4().hex)
    return AccountClient(
        create_app(api_token=TOKEN, **kwargs), base_url="http://127.0.0.1", mongo_uri=kwargs.get("mongo_uri", "mongodb://127.0.0.1:27017"), database_name=kwargs["database_name"]
    )


def test_health_does_not_claim_database_or_ai_is_ready():
    with client_for(mongo_uri="mongodb://127.0.0.1:1") as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["capabilities"]["clash_detection"] == "cross_source_ifc_geometry"
    assert response.json()["capabilities"]["trained_ai"] == "not_verified"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": b"Bearer \xe9"}])
def test_project_write_requires_session_token(headers):
    with client_for() as client:
        response = client.post("/api/projects", json={"name": "Nhà A"}, headers=headers)
    assert response.status_code == 401


@pytest.mark.parametrize("uri", ["mongodb://remote.example:27017", "mongodb+srv://remote.example"])
def test_local_backend_rejects_remote_database_configuration(uri):
    from app.main import create_app

    with pytest.raises(ValueError, match="loopback"):
        create_app(api_token=TOKEN, mongo_uri=uri)


def test_untrusted_browser_origin_cannot_write_even_with_token():
    with client_for() as client:
        response = client.post(
            "/api/projects",
            json={"name": "Nhà A"},
            headers={**AUTH, "Origin": "https://untrusted.example"},
        )
    assert response.status_code == 403


@pytest.mark.parametrize("name", ["", "   ", "a" * 121])
def test_invalid_project_name_is_rejected_before_database_write(name):
    with client_for() as client:
        response = client.post("/api/projects", json={"name": name}, headers=AUTH)
    assert response.status_code == 422


def test_database_failure_is_not_reported_as_ready_or_exposed_as_credentials():
    with client_for(mongo_uri="mongodb://fake-user:secret-value@127.0.0.1:1") as client:
        response = client.get("/api/ready", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["detail"] == "database_unavailable"
    assert "secret-value" not in response.text


@pytest.mark.integration
def test_project_round_trip_persists_in_real_mongodb():
    uri = os.getenv("BIM_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set BIM_TEST_MONGODB_URI to explicitly test local MongoDB")
    name = "bim_insight_test_" + uuid4().hex
    database_client = MongoClient(uri, serverSelectionTimeoutMS=1500)
    try:
        with client_for(mongo_uri=uri, database_name=name) as client:
            assert client.get("/api/ready", headers=AUTH).status_code == 200
            response = client.post(
                "/api/projects",
                json={"name": "  Nhà phố thử nghiệm  ", "description": "IFC ba bộ môn"},
                headers=AUTH,
            )
            assert response.status_code == 201
            created = response.json()
            assert created["name"] == "Nhà phố thử nghiệm"
        with client_for(mongo_uri=uri, database_name=name) as reopened:
            loaded = reopened.get(f"/api/projects/{created['id']}", headers=AUTH)
            missing = reopened.get(f"/api/projects/{uuid4()}", headers=AUTH)
        assert loaded.status_code == 200
        assert loaded.json() == created
        assert missing.status_code == 404
        stored = database_client[name].projects.find_one({"_id": created["id"]})
        assert stored["name"] == "Nhà phố thử nghiệm"
    finally:
        database_client.drop_database(name)
        database_client.close()
