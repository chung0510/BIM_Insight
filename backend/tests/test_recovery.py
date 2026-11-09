from test_access import access_workspace, account, headers, PASSWORD
from test_api import AUTH
from test_provisioning import batch, temporary_password
import json
import re
from datetime import timedelta


def fake_mail(directory, monkeypatch):
    from app.db import _dpapi
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "mail.dpapi").write_bytes(_dpapi(json.dumps({"email": "sender@gmail.com", "app_password": "abcdefghijklmnop"}).encode(), decrypt=False))
    messages = []
    class SMTP:
        def __init__(self, host, port, **kwargs):
            assert host == "smtp.gmail.com" and port == 465 and kwargs.get("context")
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def login(self, email, password): assert email == "sender@gmail.com" and password == "abcdefghijklmnop"
        def send_message(self, message): messages.append(message)
    monkeypatch.setattr("smtplib.SMTP_SSL", SMTP)
    return messages


def active_teacher(client):
    admin = account(client, "administrator", bootstrap=True)
    payload = batch()
    assert client.post("/api/admin/provision/batches", headers=headers(admin), json=payload).status_code == 201
    password = temporary_password(client, admin, payload["batch_id"])
    logged = client.post("/api/auth/login", headers=AUTH, json={"username": "001234", "password": password}).json()
    return admin, client.post("/api/auth/password", headers=headers(logged), json={"current_password": password, "new_password": PASSWORD}).json()


def otp(message):
    return re.search(r"\b([0-9]{6})\b", message.get_content()).group(1)


def test_recovery_requires_config_without_disclosing_account_existence(access_workspace):
    client, _, _ = access_workspace
    account(client, "administrator", bootstrap=True)
    from test_api import AUTH
    for identifier in ["administrator", "missing@example.org"]:
        result = client.post("/api/auth/recovery/request", headers=AUTH, json={"identifier": identifier})
        assert result.status_code == 503 and result.json()["detail"] == "mail_not_configured"


def test_recovery_is_private_one_time_and_revokes_old_sessions(access_workspace, monkeypatch):
    client, database, directory = access_workspace
    messages = fake_mail(directory, monkeypatch)
    _, user = active_teacher(client)
    known = client.post("/api/auth/recovery/request", headers=AUTH, json={"identifier": "teacher@example.org"})
    unknown = client.post("/api/auth/recovery/request", headers=AUTH, json={"identifier": "missing@example.org"})
    assert known.status_code == unknown.status_code == 200
    assert known.json()["message"] == unknown.json()["message"] and len(messages) == 1
    code = otp(messages[0]); challenge = known.json()["challenge_id"]
    assert code not in known.text and code not in json.dumps(list(database.auth_challenges.find({})), default=str)
    body = {"challenge_id": challenge, "code": code, "new_password": "Recovered-password-123!"}
    assert client.post("/api/auth/recovery/confirm", headers=AUTH, json=body).status_code == 200
    assert client.post("/api/auth/recovery/confirm", headers=AUTH, json=body).status_code == 400
    assert client.get("/api/auth/me", headers=headers(user)).status_code == 401
    assert client.post("/api/auth/login", headers=AUTH, json={"username": "teacher@example.org", "password": body["new_password"]}).status_code == 200


def test_recovery_expires_locks_failed_attempts_and_resend_cancels_old_code(access_workspace, monkeypatch):
    client, database, directory = access_workspace
    messages = fake_mail(directory, monkeypatch); active_teacher(client)
    first = client.post("/api/auth/recovery/request", headers=AUTH, json={"identifier": "001234"}).json()
    first_code = otp(messages[-1])
    second = client.post("/api/auth/recovery/request", headers=AUTH, json={"identifier": "001234"}).json()
    assert client.post("/api/auth/recovery/confirm", headers=AUTH, json={"challenge_id": first["challenge_id"], "code": first_code, "new_password": PASSWORD}).status_code == 400
    second_code = otp(messages[-1]); wrong = "000000" if second_code != "000000" else "999999"
    for _ in range(5):
        assert client.post("/api/auth/recovery/confirm", headers=AUTH, json={"challenge_id": second["challenge_id"], "code": wrong, "new_password": PASSWORD}).status_code == 400
    assert client.post("/api/auth/recovery/confirm", headers=AUTH, json={"challenge_id": second["challenge_id"], "code": second_code, "new_password": PASSWORD}).status_code == 400
    third = client.post("/api/auth/recovery/request", headers=AUTH, json={"identifier": "001234"}).json()
    from app.access import now
    database.auth_challenges.update_one({"challenge_id": third["challenge_id"]}, {"$set": {"expires_at": now() - timedelta(seconds=1)}})
    assert client.post("/api/auth/recovery/confirm", headers=AUTH, json={"challenge_id": third["challenge_id"], "code": otp(messages[-1]), "new_password": PASSWORD}).status_code == 400
    assert client.post("/api/auth/recovery/request", headers=AUTH, json={"identifier": "001234"}).status_code == 429


def test_contact_email_cannot_be_used_for_login_or_recovery_until_verified(access_workspace, monkeypatch):
    client, _, directory = access_workspace
    messages = fake_mail(directory, monkeypatch)
    admin = account(client, "administrator", bootstrap=True)
    profile = client.get("/api/auth/profile", headers=headers(admin)).json()
    assert client.post("/api/auth/profile", headers=headers(admin), json={"display_name": "Administrator", "email": "contact@example.org", "expected_revision": profile["user"]["revision"]}).status_code == 200
    assert client.post("/api/auth/login", headers=AUTH, json={"username": "contact@example.org", "password": PASSWORD}).status_code == 401
    assert client.post("/api/auth/recovery/request", headers=AUTH, json={"identifier": "contact@example.org"}).status_code == 200 and not messages
    request = client.post("/api/auth/email/request", headers=headers(admin), json={"email": "verified@example.org"})
    assert request.status_code == 200 and len(messages) == 1
    assert client.post("/api/auth/email/confirm", headers=headers(admin), json={"challenge_id": request.json()["challenge_id"], "code": otp(messages[0])}).status_code == 200
    assert client.post("/api/auth/login", headers=AUTH, json={"username": "VERIFIED@example.org", "password": PASSWORD}).status_code == 200


def test_mail_configuration_is_admin_only_encrypted_and_never_returns_password(access_workspace, monkeypatch):
    client, _, directory = access_workspace
    fake_mail(directory, monkeypatch)
    admin = account(client, "administrator", bootstrap=True); user = account(client, "ordinary")
    config = {"email": "sender@gmail.com", "app_password": "abcdefghijklmnop"}
    assert client.post("/api/admin/mail", headers=headers(user), json=config).status_code == 403
    saved = client.post("/api/admin/mail", headers=headers(admin), json=config)
    assert saved.status_code == 200 and config["app_password"] not in saved.text
    status = client.get("/api/admin/mail", headers=headers(admin))
    assert status.json()["configured"] and config["app_password"] not in status.text
    assert config["app_password"].encode() not in (directory / "mail.dpapi").read_bytes()


def test_recovery_cannot_keep_the_admin_issued_temporary_password(access_workspace, monkeypatch):
    client, database, directory = access_workspace
    messages = fake_mail(directory, monkeypatch)
    admin = account(client, "administrator", bootstrap=True); payload = batch()
    assert client.post("/api/admin/provision/batches", headers=headers(admin), json=payload).status_code == 201
    password = temporary_password(client, admin, payload["batch_id"])
    challenge = client.post("/api/auth/recovery/request", headers=AUTH, json={"identifier": "001234"}).json()["challenge_id"]
    body = {"challenge_id": challenge, "code": otp(messages[-1]), "new_password": password}
    result = client.post("/api/auth/recovery/confirm", headers=AUTH, json=body)
    assert result.status_code == 422 and result.json()["detail"] == "password_must_differ"
    assert database.auth_users.find_one({"username": "001234"})["must_change_password"] is True
    body["new_password"] = PASSWORD
    assert client.post("/api/auth/recovery/confirm", headers=AUTH, json=body).status_code == 200


def test_recovery_code_has_one_atomic_consumer(access_workspace, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    client, _, directory = access_workspace
    messages = fake_mail(directory, monkeypatch); active_teacher(client)
    challenge = client.post("/api/auth/recovery/request", headers=AUTH, json={"identifier": "001234"}).json()["challenge_id"]
    body = {"challenge_id": challenge, "code": otp(messages[-1]), "new_password": "Recovered-concurrently-123!"}
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: client.post("/api/auth/recovery/confirm", headers=AUTH, json=body).status_code, range(2)))
    assert sorted(results) == [200, 400]

