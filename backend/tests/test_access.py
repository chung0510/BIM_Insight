from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pymongo import MongoClient
import pytest

from app.main import create_app
from test_api import AUTH, TOKEN

PASSWORD = "Only-for-isolated-tests-123!"


@pytest.fixture
def access_workspace(tmp_path):
    uri = "mongodb://127.0.0.1:27017"
    mongo = MongoClient(uri, serverSelectionTimeoutMS=1500)
    mongo.admin.command("ping")
    name = "bim_access_test_" + uuid4().hex
    app = create_app(api_token=TOKEN, mongo_uri=uri, database_name=name, data_dir=tmp_path)
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            yield client, mongo[name], tmp_path
    finally:
        assert name.startswith("bim_access_test_")
        mongo.drop_database(name)
        mongo.close()


def headers(account):
    return {**AUTH, "X-BIM-Session": account["session_token"]}


def account(client, username, *, bootstrap=False):
    result = client.post("/api/auth/bootstrap" if bootstrap else "/api/auth/register", headers=AUTH, json={"username": username, "display_name": username.title(), "password": PASSWORD})
    assert result.status_code == 201, result.text
    return result.json()


def actors(client):
    admin = account(client, "administrator", bootstrap=True)
    user = account(client, "ordinary")
    teacher = account(client, "reviewer")
    student = account(client, "student")
    for item, role in [(teacher, "teacher"), (student, "student")]:
        response = client.post(f"/api/admin/users/{item['user']['id']}/role", headers=headers(admin), json={"role": role, "expected_revision": item["user"]["revision"]})
        assert response.status_code == 200, response.text
        item["user"] = response.json()
    return admin, user, teacher, student


def project(client, owner, name="Private project"):
    response = client.post("/api/projects", headers=headers(owner), json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def seed_artifacts(database, directory, owner, project_id=None):
    ids = {kind: uuid4().hex for kind in ["report", "clash", "link"]}
    for kind, folder in [("report", "reports"), ("clash", "clashes"), ("link", "links")]:
        path = directory / folder / f"{ids[kind]}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"id": ids[kind], "project_id": project_id, "scope": "private-evidence"}), encoding="utf-8")
        database.auth_artifacts.insert_one({"_id": f"{kind}:{ids[kind]}", "kind": kind, "owner_id": owner["user"]["id"], "project_id": project_id})
    asset = directory / "assets" / ids["report"] / "model.glb"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"private-model")
    return ids, [f"/api/inspections/{ids['report']}/report", f"/api/inspections/{ids['report']}/assets/model.glb", f"/api/inspections/clashes/{ids['clash']}", f"/api/inspections/alignments/{ids['link']}"]


def test_bootstrap_is_atomic_and_adopts_legacy_project_without_changing_files(access_workspace):
    client, database, directory = access_workspace
    pid = str(uuid4())
    database.projects.insert_one({"_id": pid, "name": "Existing Nha02", "description": "", "created_at": "2026-11-01T00:00:00+00:00"})
    legacy = directory / "reports" / ("a" * 32 + ".json")
    legacy.parent.mkdir()
    original = json.dumps({"id": "a" * 32, "project_id": pid}).encode()
    legacy.write_bytes(original)
    response = client.get("/api/auth/state", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["setup_required"] is True
    admin = account(client, "administrator", bootstrap=True)
    assert admin["user"]["role"] == "admin"
    assert client.post("/api/auth/bootstrap", headers=AUTH, json={"username": "intruder", "display_name": "Intruder", "password": PASSWORD}).status_code == 409
    assert database.auth_users.count_documents({}) == 1
    assert database.projects.find_one({"_id": pid})["owner_id"] == admin["user"]["id"]
    assert legacy.read_bytes() == original
    assert client.get(f"/api/projects/{pid}", headers=headers(admin)).status_code == 200
    assert client.get(f"/api/inspections/{'a'*32}/report", headers=headers(admin)).content == original


def test_profile_is_private_persists_and_preserves_sessions_roles_and_credentials(access_workspace):
    client, database, _ = access_workspace
    admin, owner, teacher, _ = actors(client)
    assert client.get('/api/auth/profile', headers=AUTH).status_code == 401
    before = client.get('/api/auth/profile', headers=headers(teacher))
    assert before.status_code == 200
    assert before.json()['email'] == ''
    record = database.auth_users.find_one({'_id': teacher['user']['id']})
    payload = {'display_name': 'Reviewer New Name', 'email': 'reviewer@example.org', 'phone': '+84 912 345 678', 'organization': 'BIM Studio', 'job_title': 'Lecturer', 'bio': 'BIM coordination\nReview with evidence.', 'expected_revision': before.json()['user']['revision']}
    response = client.post('/api/auth/profile', headers=headers(teacher), json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['user']['role'] == 'teacher'
    assert response.json()['user']['display_name'] == payload['display_name']
    assert client.get('/api/auth/me', headers=headers(teacher)).json()['display_name'] == payload['display_name']
    assert client.get('/api/auth/profile', headers=headers(teacher)).json()['email'] == payload['email']
    assert client.get('/api/auth/profile', headers=headers(owner)).json()['email'] == ''
    after = database.auth_users.find_one({'_id': teacher['user']['id']})
    assert after['password_hash'] == record['password_hash'] and after['auth_version'] == record['auth_version']
    assert after['profile']['phone'] == payload['phone']
    directory = client.get('/api/admin/users', headers=headers(admin)).text
    assert payload['email'] not in directory and payload['phone'] not in directory
    audit = database.auth_audit.find_one({'action': 'profile_updated', 'actor_id': teacher['user']['id']})
    assert audit and payload['email'] not in json.dumps(audit, default=str)


def test_profile_rejects_stale_writes_and_role_or_identity_injection(access_workspace):
    client, database, _ = access_workspace
    admin = account(client, 'administrator', bootstrap=True)
    user = account(client, 'ordinary')
    payload = {'display_name': 'Own Profile', 'expected_revision': user['user']['revision']}
    assert client.post('/api/auth/profile', headers=headers(user), json=payload).status_code == 200
    assert client.post('/api/auth/profile', headers=headers(user), json={**payload, 'display_name': 'Stale'}).status_code == 409
    revision = client.get('/api/auth/profile', headers=headers(user)).json()['user']['revision']
    for extra in [{'role': 'admin'}, {'username': 'administrator'}, {'user_id': admin['user']['id']}, {'password': '1'}]:
        assert client.post('/api/auth/profile', headers=headers(user), json={**payload, 'expected_revision': revision, **extra}).status_code == 422
    assert client.get('/api/auth/me', headers=headers(user)).json()['role'] == 'user'
    assert database.auth_users.find_one({'_id': admin['user']['id']})['display_name'] == 'Administrator'


def test_profile_validation_prevents_bad_or_oversized_contact_data(access_workspace):
    client, database, _ = access_workspace
    user = account(client, 'administrator', bootstrap=True)
    for invalid in [{'display_name': ' '}, {'email': 'not-an-email'}, {'phone': '++++++'}, {'bio': 'x'*501}, {'job_title': 'Bad\x00Value'}, {'organization': 'x'*121}]:
        payload = {'display_name': 'Valid Name', 'expected_revision': user['user']['revision'], **invalid}
        assert client.post('/api/auth/profile', headers=headers(user), json=payload).status_code == 422
    assert database.auth_users.find_one({'_id': user['user']['id']})['revision'] == user['user']['revision']


def test_transport_token_alone_cannot_read_projects_or_private_artifacts(access_workspace):
    client, _, _ = access_workspace
    assert client.get("/api/projects", headers=AUTH).status_code == 401
    assert client.get(f"/api/inspections/{'a'*32}/report", headers=AUTH).status_code == 401
    assert client.get("/api/auth/state").status_code == 401


def test_interrupted_legacy_adoption_resumes_on_authenticated_login(access_workspace, monkeypatch):
    from app.access import AccessStore
    from pymongo.errors import PyMongoError
    client, database, _ = access_workspace
    pid = str(uuid4())
    database.projects.insert_one({"_id": pid, "name": "Legacy", "description": "", "created_at": "2026-11-01"})
    original = AccessStore.adopt_legacy
    def interrupted(self, user):
        raise PyMongoError("Simulated migration interruption")
    monkeypatch.setattr(AccessStore, "adopt_legacy", interrupted)
    response = client.post("/api/auth/bootstrap", headers=AUTH, json={"username": "administrator", "display_name": "Admin", "password": PASSWORD})
    assert response.status_code == 503
    monkeypatch.setattr(AccessStore, "adopt_legacy", original)
    login = client.post("/api/auth/login", headers=AUTH, json={"username": "administrator", "password": PASSWORD})
    assert login.status_code == 200
    assert client.get(f"/api/projects/{pid}", headers=headers(login.json())).status_code == 200
    assert database.auth_users.find_one({"_id": "bootstrap"})["legacy_adopted"] is True


def test_registration_cannot_choose_role_and_passwords_sessions_are_hashed(access_workspace):
    client, database, _ = access_workspace
    admin = account(client, "administrator", bootstrap=True)
    injected = client.post("/api/auth/register", headers=AUTH, json={"username": "intruder", "display_name": "Intruder", "password": PASSWORD, "role": "admin"})
    assert injected.status_code == 422 and PASSWORD not in injected.text
    user = account(client, "ordinary")
    assert user["user"]["role"] == "user"
    record = database.auth_users.find_one({"_id": user["user"]["id"]})
    assert PASSWORD not in str(record)
    assert database.auth_sessions.find_one({"_id": user["session_token"]}) is None
    assert user["session_token"] not in str(list(database.auth_sessions.find({})))
    assert client.get("/api/admin/users", headers=headers(user)).status_code == 403
    assert client.get("/api/admin/users", headers=headers(admin)).json()["total"] == 2


def test_four_roles_are_real_and_project_lists_are_scoped_even_for_admin(access_workspace):
    client, _, _ = access_workspace
    admin, user, teacher, student = actors(client)
    created = [project(client, owner, owner["user"]["username"]) for owner in [admin, user, teacher, student]]
    for owner, item in zip([admin, user, teacher, student], created):
        data = client.get("/api/projects", headers=headers(owner)).json()
        assert data["total"] == 1 and data["items"][0]["id"] == item["id"]
        assert item["owner_id"] == owner["user"]["id"]
    assert client.get(f"/api/projects/{created[1]['id']}", headers=headers(admin)).status_code == 404


def test_all_artifact_urls_require_owner_or_explicit_project_membership(access_workspace):
    client, database, directory = access_workspace
    admin, user, teacher, student = actors(client)
    item = project(client, user)
    _, urls = seed_artifacts(database, directory, user, item["id"])
    for url in urls:
        assert client.get(url, headers=headers(user)).status_code == 200
        for outsider in [admin, teacher, student]:
            assert client.get(url, headers=headers(outsider)).status_code == 404
    response = client.post(f"/api/projects/{item['id']}/members", headers=headers(user), json={"username": teacher["user"]["username"], "access": "review"})
    assert response.status_code == 200, response.text
    for url in urls:
        assert client.get(url, headers=headers(teacher)).status_code == 200
    shared = client.get(f"/api/projects/{item['id']}", headers=headers(teacher)).json()
    assert shared["permissions"] == {"view": True, "edit": False, "review": True, "share": False, "delete": False}
    assert client.get(f"/api/projects/{item['id']}/members", headers=headers(teacher)).status_code == 403
    assert client.post(f"/api/projects/{item['id']}/storage/sync", headers=headers(teacher)).status_code == 403
    denied = client.post("/api/inspections", headers=headers(teacher), files={"file": ("x.dxf", b"0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n")}, data={"project_id": item["id"], "logical_source": "x", "revision": "R01"})
    assert denied.status_code == 403
    assert not list((directory/"tmp").rglob("source.*"))


def test_ai_references_authorize_before_reading_or_downloading_private_report(access_workspace):
    from app.access import AccessStore, actor_context
    from app.projects import ProjectStore
    from app.retrieval import retrieve
    client, database, directory = access_workspace
    _, owner, reviewer, _ = actors(client)
    private = project(client, owner)
    ids, _ = seed_artifacts(database, directory, owner, private["id"])
    class Storage:
        def ensure_local(self, relative):
            pytest.fail("An unauthorized report must not touch disk or R2")
    access = AccessStore(database, directory)
    projects = ProjectStore(database, directory, storage=Storage(), access=access)
    context = actor_context.set(reviewer["user"])
    try:
        with pytest.raises(HTTPException) as caught:
            retrieve(projects, str(uuid4()), "R01", {"kind": "intersection", "a": {"ifc_type": "IfcBeam"}, "b": {"ifc_type": "IfcPipeSegment"}}, [ids["report"]])
        assert caught.value.status_code == 404
    finally:
        actor_context.reset(context)


def test_temporary_artifacts_are_private_and_members_cannot_delegate(access_workspace):
    client, database, directory = access_workspace
    admin, user, teacher, student = actors(client)
    _, urls = seed_artifacts(database, directory, user)
    for url in urls:
        assert client.get(url, headers=headers(user)).status_code == 200
        assert client.get(url, headers=headers(admin)).status_code == 404
    item = project(client, user)
    base = f"/api/projects/{item['id']}/members"
    assert client.post(base, headers=headers(user), json={"username": "student", "access": "view"}).status_code == 200
    viewed = client.get(f"/api/projects/{item['id']}", headers=headers(student)).json()
    assert viewed["permissions"]["review"] is False
    assert client.post(base, headers=headers(student), json={"username": "reviewer", "access": "review"}).status_code == 403
    assert client.post(base, headers=headers(user), json={"username": "student", "access": "review"}).status_code == 422
    assert client.post(base+f"/{student['user']['id']}/remove", headers=headers(user)).status_code == 200
    assert client.get(f"/api/projects/{item['id']}", headers=headers(student)).status_code == 404


def test_review_identity_is_bound_to_account_and_demotion_revokes_review_access(access_workspace):
    client, database, directory = access_workspace
    admin, user, teacher, _ = actors(client)
    item = project(client, user)
    rid, iid = uuid4().hex, uuid4().hex[:24]
    database.project_runs.insert_one({"_id": rid, "project_id": item["id"], "ready": True})
    database.project_issues.insert_one({"project_id": item["id"], "run_id": rid, "issue_id": iid, "review": {"revision": 0, "state": "unreviewed"}})
    client.post(f"/api/projects/{item['id']}/members", headers=headers(user), json={"username": "reviewer", "access": "review"})
    url=f"/api/projects/{item['id']}/runs/{rid}/issues/{iid}/review"
    payload={"state":"needs_fix","reviewer":"Pretend Administrator","note":"Please recheck","expected_revision":0}
    response=client.post(url, headers=headers(teacher),json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["review"]["reviewer"] == teacher["user"]["display_name"]
    assert response.json()["review"]["reviewer_id"] == teacher["user"]["id"]
    assert client.post(f"/api/admin/users/{teacher['user']['id']}/role",headers=headers(admin),json={"role":"user","expected_revision":teacher['user']['revision']}).status_code == 200
    assert client.post(url,headers=headers(teacher),json={**payload,"expected_revision":1}).status_code == 403


def test_logout_expiry_and_disabled_accounts_revoke_existing_sessions(access_workspace):
    client, database, _ = access_workspace
    admin, user, _, _ = actors(client)
    assert client.post("/api/auth/logout",headers=headers(user)).status_code == 200
    assert client.get("/api/auth/me",headers=headers(user)).status_code == 401
    login=client.post("/api/auth/login",headers=AUTH,json={"username":"ordinary","password":PASSWORD}).json()
    assert client.get("/api/auth/me",headers=headers(login)).status_code == 200
    response=client.post(f"/api/admin/users/{user['user']['id']}/status",headers=headers(admin),json={"disabled":True,"expected_revision":user['user']['revision']})
    assert response.status_code == 200
    assert client.get("/api/auth/me",headers=headers(login)).status_code == 401
    assert client.post("/api/auth/login",headers=AUTH,json={"username":"ordinary","password":PASSWORD}).status_code == 401
    database.auth_sessions.update_many({"user_id": admin['user']['id']},{"$set":{"expires_at":datetime.now(timezone.utc)-timedelta(seconds=1)}})
    assert client.get("/api/auth/me",headers=headers(admin)).status_code == 401


def test_changing_password_requires_current_password_and_revokes_other_sessions(access_workspace):
    client, _, _ = access_workspace
    account(client,"administrator",bootstrap=True)
    user=account(client,"ordinary")
    another=client.post("/api/auth/login",headers=AUTH,json={"username":"ordinary","password":PASSWORD}).json()
    bad=client.post("/api/auth/password",headers=headers(user),json={"current_password":"wrong","new_password":"New-only-test-password-456!"})
    assert bad.status_code == 401
    response=client.post("/api/auth/password",headers=headers(user),json={"current_password":PASSWORD,"new_password":"New-only-test-password-456!"})
    assert response.status_code == 200
    assert client.get("/api/auth/me",headers=headers(another)).status_code == 401
    assert client.get("/api/auth/me",headers=headers(response.json())).status_code == 200


def test_concurrent_demotions_cannot_remove_last_administrator(access_workspace):
    client, database, _ = access_workspace
    first=account(client,"administrator",bootstrap=True)
    second=account(client,"anotheradmin")
    promoted=client.post(f"/api/admin/users/{second['user']['id']}/role",headers=headers(first),json={"role":"admin","expected_revision":second['user']['revision']})
    assert promoted.status_code == 200
    second['user']=promoted.json()
    def demote(pair):
        actor,target=pair
        return client.post(f"/api/admin/users/{target['user']['id']}/role",headers=headers(actor),json={"role":"user","expected_revision":target['user']['revision']}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes=list(pool.map(demote,[(first,second),(second,first)]))
    assert codes.count(200) == 1
    assert database.auth_users.find_one({"_id":"bootstrap"})['admin_ids']


def test_mid_promotion_cannot_be_demoted_into_an_unprotected_admin(access_workspace, monkeypatch):
    from threading import Event
    from pymongo.collection import Collection
    client, database, _ = access_workspace
    admin = account(client, "administrator", bootstrap=True)
    target = account(client, "futureadmin")
    uid = target["user"]["id"]
    paused, resume = Event(), Event()
    original = Collection.update_one
    def delayed(collection, query, update, *args, **kwargs):
        if collection.full_name == database.auth_users.full_name and update.get("$addToSet", {}).get("admin_ids") == uid:
            paused.set()
            assert resume.wait(10)
        return original(collection, query, update, *args, **kwargs)
    monkeypatch.setattr(Collection, "update_one", delayed)
    url = f"/api/admin/users/{uid}"
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, url + "/role", headers=headers(admin), json={"role": "admin", "expected_revision": 1})
        try:
            assert paused.wait(10)
            result = client.post(url + "/role", headers=headers(admin), json={"role": "user", "expected_revision": 2})
        finally:
            resume.set()
        assert pending.result().status_code == 200
    assert result.status_code == 409
    current = database.auth_users.find_one({"_id": uid})
    assert current["admin_protected"] is True
    assert client.post(url + "/status", headers=headers(admin), json={"disabled": True, "expected_revision": current["revision"]}).status_code == 409


def test_login_has_generic_errors_and_rate_limits_without_leaking_password(access_workspace, monkeypatch):
    from types import SimpleNamespace
    from app import access
    instant = access.time.time()
    monkeypatch.setattr(access, "time", SimpleNamespace(time=lambda: instant))
    client, _, _ = access_workspace
    account(client,"administrator",bootstrap=True)
    for username in ['missinguser','administrator']:
        response=client.post('/api/auth/login',headers=AUTH,json={'username':username,'password':'Wrong-test-password'})
        assert response.status_code == 401 and response.json()['detail'] == 'invalid_credentials'
    codes=[client.post('/api/auth/login',headers=AUTH,json={'username':'missinguser','password':'Wrong-test-password'}).status_code for _ in range(12)]
    assert 429 in codes
    secret='do-not-echo-this-password'
    response=client.post('/api/auth/register',headers=AUTH,json={'username':'x','display_name':'Name','password':secret,'role':'admin'})
    assert response.status_code == 422 and secret not in response.text
