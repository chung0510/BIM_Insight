from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.main import create_app
from test_api import TOKEN, TEST_PASSWORD


ORIGIN = "https://bim-insight.example.org"


@pytest.fixture
def web_client(tmp_path):
    from app.web import create_web_app

    mongo = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=1500)
    mongo.admin.command("ping")
    name = "bim_web_test_" + uuid4().hex
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html>BIM web test</html>", encoding="utf-8")
    (frontend / "asset.js").write_text("window.bim = true;", encoding="utf-8")
    monkeypatch = pytest.MonkeyPatch()
    for key, value in {
        "BIM_WEB_ORIGIN": ORIGIN,
        "BIM_MONGODB_URI": "mongodb://127.0.0.1:27017",
        "BIM_DATABASE": name,
        "BIM_DATA_DIR": str(tmp_path / "data"),
        "BIM_FRONTEND_DIR": str(frontend),
        "BIM_SETTINGS_KEY": "test-only-settings-key-" + "x" * 32,
        "BIM_ADMIN_USERNAME": "webadmin",
        "BIM_ADMIN_PASSWORD": TEST_PASSWORD,
    }.items():
        monkeypatch.setenv(key, value)
    try:
        with TestClient(create_web_app(), base_url=ORIGIN) as client:
            yield client, mongo[name]
    finally:
        monkeypatch.undo()
        assert name.startswith("bim_web_test_")
        mongo.drop_database(name)
        mongo.close()


def login(client):
    response = client.post("/api/auth/login", json={"username": "webadmin", "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return {"X-BIM-Session": response.json()["session_token"]}


def test_web_serves_frontend_and_preserves_api_404(web_client):
    client, _ = web_client
    assert "BIM web test" in client.get("/").text
    assert client.get("/asset.js").status_code == 200
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/not-a-route").status_code == 404
    assert client.get("/%2e%2e/settings.dpapi").status_code == 404


def test_web_requires_account_and_rejects_public_bootstrap(web_client):
    client, _ = web_client
    assert client.get("/api/auth/state").json() == {"setup_required": False}
    assert client.post("/api/auth/bootstrap", json={}).status_code == 403
    assert client.get("/api/projects").status_code == 401
    assert client.post("/api/projects", json={"name": "Private web project"}).status_code == 401
    headers = login(client)
    response = client.post("/api/projects", headers=headers, json={"name": "Private web project"})
    assert response.status_code == 201, response.text
    assert client.get("/api/projects", headers=headers).json()["total"] == 1


def test_web_upload_and_project_isolation(web_client):
    from test_inspections import pdf_bytes

    client, _ = web_client
    owner = login(client)
    project = client.post("/api/projects", headers=owner, json={"name": "Web upload sample"}).json()
    response = client.post("/api/inspections", headers=owner,
                           files={"file": ("sample.pdf", pdf_bytes(), "application/pdf")},
                           data={"project_id": project["id"], "logical_source": "sample.pdf", "discipline": "ARCH"})
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["status"] == "completed"
    assert client.get(report["report_url"], headers=owner).status_code == 200
    assert client.get(report["report_url"]).status_code == 401
    other = client.post("/api/auth/register", json={"username": "otheruser", "password": TEST_PASSWORD, "display_name": "Other user"})
    assert other.status_code == 201, other.text
    other_headers = {"X-BIM-Session": other.json()["session_token"]}
    assert client.get("/api/projects", headers=other_headers).json()["total"] == 0
    assert client.get(f"/api/projects/{project['id']}", headers=other_headers).status_code == 404
    assert client.get(report["report_url"], headers=other_headers).status_code == 404


def test_web_rejects_other_origins_and_hosts(web_client):
    client, _ = web_client
    assert client.get("/api/health", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/health", headers={"Origin": "http://localhost:1420"}).status_code == 403
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
    response = client.options("/api/auth/login", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_static_frontend_origin_preserves_api_host_and_auth(web_client, monkeypatch):
    from app.web import create_web_app

    frontend_origin = "https://bim-insight-static.example.org"
    monkeypatch.setenv("BIM_FRONTEND_ORIGIN", frontend_origin)
    with TestClient(create_web_app(), base_url=ORIGIN) as client:
        preflight = client.options("/api/auth/login", headers={"Origin": frontend_origin,
                                   "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type,X-BIM-Session"})
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == frontend_origin
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/health", headers={"Host": "untrusted.example"}).status_code == 400
        assert client.get("/api/projects", headers={"Origin": frontend_origin}).status_code == 401
        signed_in = client.post("/api/auth/login", headers={"Origin": frontend_origin},
                                json={"username": "webadmin", "password": TEST_PASSWORD})
        assert signed_in.status_code == 200
        headers = {"Origin": frontend_origin, "X-BIM-Session": signed_in.json()["session_token"]}
        assert client.post("/api/projects", headers=headers, json={"name": "Static origin project"}).status_code == 201
        assert client.post("/api/auth/login", headers={"Origin": ORIGIN},
                           json={"username": "webadmin", "password": TEST_PASSWORD}).status_code == 200
        assert client.get("/api/health", headers={"Origin": "https://other-static.example.org"}).status_code == 403
        assert client.post("/api/auth/bootstrap", headers={"Origin": frontend_origin}, json={}).status_code == 403


@pytest.mark.parametrize("origin", ["*", "https://user:password@example.org", "https://example.org/path", "http://example.org", "https://example.org?query=1"])
def test_static_frontend_origin_is_validated_before_startup(origin, monkeypatch):
    from app.web import create_web_app

    monkeypatch.setenv("BIM_WEB_ORIGIN", ORIGIN)
    monkeypatch.setenv("BIM_FRONTEND_ORIGIN", origin)
    with pytest.raises(ValueError, match="origin"):
        create_web_app()


def test_existing_desktop_still_requires_local_token(tmp_path):
    with TestClient(create_app(api_token=TOKEN, data_dir=tmp_path), base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/auth/state").status_code == 401


def test_web_startup_does_not_reset_existing_admin(web_client, monkeypatch):
    from app.web import create_web_app

    client, database = web_client
    previous = database.auth_users.find_one({"_id": "bootstrap"})["password_hash"]
    monkeypatch.setenv("BIM_ADMIN_PASSWORD", "Changed-environment-password-123!")
    with TestClient(create_web_app(), base_url=ORIGIN) as restarted:
        login(restarted)
    assert database.auth_users.find_one({"_id": "bootstrap"})["password_hash"] == previous


@pytest.mark.parametrize("origin", ["*", "https://user:password@example.org", "https://example.org/path", "https://example.org?query=1", "http://example.org"])
def test_web_rejects_invalid_public_origin(origin, monkeypatch):
    from app.web import create_web_app

    monkeypatch.setenv("BIM_WEB_ORIGIN", origin)
    with pytest.raises(ValueError, match="origin"):
        create_web_app()


def test_private_settings_round_trip_and_tamper_detection(tmp_path, monkeypatch):
    from app.settings import save_settings, load_settings

    monkeypatch.setenv("BIM_SETTINGS_KEY", "test-settings-key-" + "x" * 32)
    secret = {"email": "test@example.org", "app_password": "never-store-plaintext"}
    save_settings(tmp_path, "mail", secret)
    path = tmp_path / "mail.dpapi"
    assert b"never-store-plaintext" not in path.read_bytes()
    assert path.read_bytes().startswith(b"BIM1:")
    assert load_settings(tmp_path, "mail") == secret
    monkeypatch.setenv("BIM_SETTINGS_KEY", "different-settings-key-" + "y" * 32)
    with pytest.raises(ValueError, match="private mail"):
        load_settings(tmp_path, "mail")
    monkeypatch.delenv("BIM_SETTINGS_KEY")
    with pytest.raises(ValueError, match="private mail"):
        load_settings(tmp_path, "mail")
    monkeypatch.setenv("BIM_SETTINGS_KEY", "test-settings-key-" + "x" * 32)
    data = path.read_bytes()
    path.write_bytes(data[:-10] + b"tampered!!")
    with pytest.raises(ValueError, match="private mail"):
        load_settings(tmp_path, "mail")


def test_portable_encryption_rejects_short_key(monkeypatch):
    from app.db import _dpapi

    monkeypatch.setenv("BIM_SETTINGS_KEY", "short")
    with pytest.raises(ValueError, match="BIM_SETTINGS_KEY"):
        _dpapi(b"secret", decrypt=False)
