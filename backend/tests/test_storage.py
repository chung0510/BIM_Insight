import hashlib
from io import BytesIO
from pathlib import Path
from threading import Event

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException

from test_projects import workspace


def configuration():
    from app.storage import R2Config
    return R2Config(endpoint="https://" + "a" * 32 + ".r2.cloudflarestorage.com", bucket="bim-insight-test", access_key_id="k" * 32, secret_access_key="s" * 64)


class MemoryS3:
    def __init__(self):
        self.objects = {}
        self.calls = []
        self.fail_put = False
        self.corrupt_get = False

    def list_objects_v2(self, **params):
        self.calls.append("list")
        return {"Contents": [{"Key": key, "Size": len(value[0])} for key, value in self.objects.items()], "IsTruncated": False}

    def head_object(self, **params):
        self.calls.append("head")
        if params["Key"] not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "HeadObject")
        data, metadata = self.objects[params["Key"]]
        return {"ContentLength": len(data), "Metadata": metadata}

    def put_object(self, **params):
        self.calls.append("put")
        if self.fail_put:
            raise ClientError({"Error": {"Code": "ServiceUnavailable"}}, "PutObject")
        self.objects[params["Key"]] = (params["Body"].read(), params["Metadata"])
        return {"ETag": '"not-a-sha256"'}

    def get_object(self, **params):
        self.calls.append("get")
        data, metadata = self.objects[params["Key"]]
        return {"Body": BytesIO(b"corrupt" if self.corrupt_get else data), "ContentLength": len(data), "Metadata": metadata}


@pytest.mark.parametrize("endpoint", ["http://" + "a" * 32 + ".r2.cloudflarestorage.com", "https://evil.example", "https://" + "a" * 32 + ".r2.cloudflarestorage.com.evil.example", "https://" + "a" * 32 + ".r2.cloudflarestorage.com/?secret=oops"])
def test_r2_config_rejects_other_endpoints_and_unsafe_transport(endpoint):
    from app.storage import R2Config
    with pytest.raises(ValueError):
        R2Config(endpoint=endpoint, bucket="bim-insight", access_key_id="k" * 32, secret_access_key="s" * 64)


def test_r2_config_does_not_expose_keys():
    config = configuration()
    assert "k" * 32 not in repr(config) and "s" * 64 not in repr(config)


def test_storage_round_trip_and_cache_hit_does_not_get_again(workspace, tmp_path):
    from app.storage import StorageService
    _, database, _ = workspace
    relative = "reports/" + "1" * 32 + ".json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"id":"' + b"1" * 32 + b'"}')
    original = path.read_bytes()
    cloud = MemoryS3()
    storage = StorageService(database, tmp_path, configuration(), client=cloud)
    record = storage.backup_file("project-test", relative, Event())
    assert record["status"] == "verified"
    assert record["sha256"] == hashlib.sha256(original).hexdigest()
    gets = cloud.calls.count("get")
    assert storage.ensure_local(relative).read_bytes() == original
    assert cloud.calls.count("get") == gets
    path.unlink()
    assert storage.ensure_local(relative).read_bytes() == original
    assert cloud.calls.count("get") == gets + 1
    storage.backup_file("project-test", relative, Event())
    assert cloud.calls.count("put") == 1


def test_storage_download_hash_mismatch_keeps_existing_cache(workspace, tmp_path):
    from app.storage import StorageService
    _, database, _ = workspace
    relative = "reports/" + "2" * 32 + ".json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"verified source")
    cloud = MemoryS3()
    storage = StorageService(database, tmp_path, configuration(), client=cloud)
    storage.backup_file("project-test", relative, Event())
    path.write_bytes(b"old corrupt cache")
    cloud.corrupt_get = True
    with pytest.raises(HTTPException) as error:
        storage.ensure_local(relative)
    assert error.value.detail == "storage_hash_mismatch"
    assert path.read_bytes() == b"old corrupt cache"


@pytest.mark.parametrize("relative", ["../database.dpapi", "database.dpapi", "assets/../../secret", "reports/../database.dpapi", "/etc/passwd", "cache/models/evil.ifc"])
def test_storage_rejects_unmanaged_paths(relative, workspace, tmp_path):
    from app.storage import StorageService
    _, database, _ = workspace
    storage = StorageService(database, tmp_path, configuration(), client=MemoryS3())
    with pytest.raises(HTTPException):
        storage.backup_file("project-test", relative, Event())


def test_failed_upload_keeps_reservation_and_retry_is_idempotent(workspace, tmp_path):
    from app.storage import StorageService
    _, database, _ = workspace
    relative = "reports/" + "3" * 32 + ".json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"payload")
    cloud = MemoryS3()
    storage = StorageService(database, tmp_path, configuration(), client=cloud)
    cloud.fail_put = True
    with pytest.raises(HTTPException):
        storage.backup_file("project-test", relative, Event())
    assert storage.status()["allocated_bytes"] == len(b"payload")
    cloud.fail_put = False
    storage.backup_file("project-test", relative, Event())
    assert storage.status()["allocated_bytes"] == len(b"payload")
    assert storage.status()["verified_bytes"] == len(b"payload")


def test_quota_reserves_atomically_under_concurrent_uploads(workspace, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import app.storage as module
    monkeypatch.setattr(module, "BYTE_LIMIT", 10)
    _, database, _ = workspace
    storage = module.StorageService(database, tmp_path, configuration(), client=MemoryS3())
    paths = [f"reports/{index:032x}.json" for index in range(12)]
    for relative in paths:
        path = tmp_path / relative
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"1234567")
    storage.reconcile(Event())
    def upload(relative):
        try:
            return storage.backup_file("project-test", relative, Event())["status"]
        except HTTPException as error:
            return error.detail
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(upload, paths))
    assert results.count("verified") == 1
    assert results.count("storage_byte_budget") == 11
    assert storage.status()["allocated_bytes"] == 7


def test_immutable_binding_and_cancel_do_not_write_to_cloud(workspace, tmp_path):
    from app.storage import StorageService
    _, database, _ = workspace
    relative = "reports/" + "4" * 32 + ".json"
    path = tmp_path / relative
    path.parent.mkdir()
    path.write_bytes(b"original")
    cloud = MemoryS3()
    storage = StorageService(database, tmp_path, configuration(), client=cloud)
    cancelled = Event()
    cancelled.set()
    with pytest.raises(HTTPException) as error:
        storage.backup_file("project-test", relative, cancelled)
    assert error.value.detail == "storage_cancelled" and cloud.calls == []
    storage.backup_file("project-test", relative, Event())
    path.write_bytes(b"changed")
    with pytest.raises(HTTPException) as error:
        storage.backup_file("project-test", relative, Event())
    assert error.value.detail == "storage_immutable_conflict"
    assert cloud.calls.count("put") == 1


def test_monthly_request_budget_stops_before_provider_call(workspace, tmp_path, monkeypatch):
    import app.storage as module
    monkeypatch.setattr(module, "REQUEST_LIMITS", {"a": 1, "b": 1})
    _, database, _ = workspace
    cloud = MemoryS3()
    storage = module.StorageService(database, tmp_path, configuration(), client=cloud)
    storage._call("a", "list_objects_v2")
    with pytest.raises(HTTPException) as error:
        storage._call("a", "list_objects_v2")
    assert error.value.detail == "storage_request_budget"
    assert cloud.calls == ["list"]


def test_project_sync_restores_in_a_fresh_cache_and_can_run_clash_again(workspace, tmp_path, monkeypatch):
    from test_api import AccountClient
    import app.main as main
    from app.storage import StorageService
    from app.demo import demo_files
    from test_projects import project, upload, run_clash
    from test_api import AUTH, TOKEN
    factory, database, _ = workspace
    cloud = MemoryS3()
    monkeypatch.setattr(main, "configured_storage", lambda db, root: StorageService(db, root, configuration(), client=cloud))
    with factory() as client:
        identifier = project(client)
        reports = [upload(client, identifier, item) for item in demo_files()]
        run = run_clash(client, reports)
        url = f"/api/projects/{identifier}/storage"
        assert client.post(url + "/sync").status_code == 401
        response = client.post(url + "/sync", headers=AUTH)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "verified"
        assert response.json()["verified_files"] >= 12
        assert cloud.calls.count("put") > 0
    fresh = tmp_path / "fresh-cache"
    with AccountClient(main.create_app(api_token=TOKEN, mongo_uri="mongodb://127.0.0.1:27017", database_name=database.name, data_dir=fresh), base_url="http://127.0.0.1", database_name=database.name) as client:
        restored = client.get(f"/api/projects/{identifier}/runs/{run['id']}", headers=AUTH)
        assert restored.status_code == 200, restored.text
        assert restored.json()["report"]["issues"] == run["issues"]
        asset = client.get(reports[0]["assets"]["model"], headers=AUTH)
        assert asset.status_code == 200
        assert list((fresh / "assets").glob("*/model.glb"))
        repeated = run_clash(client, reports)
        assert repeated["counts"] == run["counts"]
        assert list((fresh / "cache" / "models").glob("*.ifc"))
