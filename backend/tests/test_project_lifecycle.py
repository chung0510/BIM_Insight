import hashlib
import json
from pathlib import Path
from threading import Event
from uuid import uuid4

from botocore.exceptions import ClientError
import pytest
from fastapi import HTTPException
from pymongo.errors import PyMongoError

from app.projects import utc_now
from app.storage import StorageService
from test_api import AUTH
from test_projects import workspace, project
from test_storage import MemoryS3, configuration


def seed(database, directory, project_id, content=b'original IFC'):
    identifier, run, link = (uuid4().hex for _ in range(3))
    digest = hashlib.sha256(content).hexdigest()
    database.project_inspections.insert_one({'_id': identifier, 'project_id': project_id, 'logical_source': 'ARCH', 'revision': 'R01', 'sha256': digest, 'published_version': True, 'status': 'completed', 'created_at': utc_now()})
    database.project_runs.insert_one({'_id': run, 'project_id': project_id, 'ready': True})
    database.project_links.insert_one({'_id': link, 'project_id': project_id})
    for collection in ['project_issues', 'project_cases', 'project_advice', 'project_conclusions']:
        database[collection].insert_one({'_id': uuid4().hex, 'project_id': project_id, 'run_id': run})
    database.auth_audit.insert_one({'target': project_id, 'action': 'project_shared', 'actor_id': 'bootstrap'})
    paths = [f'reports/{identifier}.json', f'assets/{identifier}/model.glb', f'assets/{identifier}/model.json', f'assets/{identifier}/inspection.json', f'clashes/{run}.json', f'links/{link}.json', f'cache/models/{digest}.ifc']
    for relative in paths:
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    for kind, key in [('report', identifier), ('clash', run), ('link', link)]:
        database.auth_artifacts.insert_one({'_id': f'{kind}:{key}', 'project_id': project_id, 'kind': kind})
    return paths, digest


class DeleteCloud(MemoryS3):
    fail_delete = False

    def delete_object(self, **params):
        if self.fail_delete:
            raise ClientError({'Error': {'Code': 'ServiceUnavailable'}}, 'DeleteObject')
        self.calls.append('delete')
        self.objects.pop(params['Key'], None)
        return {}


def test_upload_without_revision_updates_current_source_and_keeps_history(workspace):
    from app.demo import demo_files
    factory, database, _ = workspace
    with factory() as client:
        pid = project(client)
        item = demo_files()[0]
        def upload(content):
            response = client.post('/api/inspections', files={'file': (item['name'], content.encode())}, data={'project_id': pid, 'logical_source': 'ARCH'}, headers=AUTH)
            assert response.status_code == 200, response.text
            return response.json()
        first = upload(item['content'])
        assert upload(item['content'])['id'] == first['id']
        changed = upload(item['content'].replace('SYNTHETIC GEOMETRY LAB', 'Updated export'))
        assert changed['id'] != first['id'] and changed['sha256'] != first['sha256']
        current = client.get(f'/api/projects/{pid}/inspections', headers=AUTH).json()
        assert current['total'] == 1 and current['items'][0]['id'] == changed['id']
        assert database.project_inspections.count_documents({'project_id': pid}) == 2
        assert client.get(first['report_url'], headers=AUTH).json()['sha256'] == first['sha256']


def test_automatically_managed_sources_can_align_and_clash_without_revision(workspace):
    from app.demo import demo_files
    factory, _, _ = workspace
    with factory() as client:
        pid = project(client)
        reports = []
        for item in demo_files():
            response = client.post('/api/inspections', files={'file': (item['name'], item['content'].encode())}, data={'project_id': pid, 'logical_source': item['name']}, headers=AUTH)
            assert response.status_code == 200, response.text
            reports.append(response.json())
        link = client.post('/api/inspections/alignments', headers=AUTH, json={'drawing_id': reports[3]['id'], 'model_id': reports[0]['id'], 'storey_guid': reports[0]['result']['storeys'][0]['guid'], 'project_name': 'Research project', 'confirmed': True, 'same_revision_confirmed': True})
        assert link.status_code == 200, link.text
        clash = client.post('/api/inspections/clashes', headers=AUTH, json={'model_ids': [r['id'] for r in reports[:3]], 'coordinates_confirmed': True, 'link_id': link.json()['id']})
        assert clash.status_code == 200, clash.text
        assert len(clash.json()['issues']) == 2


def test_delete_cascades_metadata_files_and_unshared_cache_but_keeps_accounts_and_sources(workspace):
    factory, database, directory = workspace
    with factory() as client:
        pid, other = project(client, 'Delete me'), project(client, 'Keep me')
        owned, digest = seed(database, directory, pid)
        kept, _ = seed(database, directory, other, b'other IFC')
        geometry = directory / 'cache/clash-geometry' / ('a' * 64)
        geometry.mkdir(parents=True)
        (geometry / 'manifest.json').write_text(json.dumps({'definition': {'source_sha256': digest}}))
        (geometry / 'geometry.h5').write_bytes(b'geometry')
        protected = [directory / 'database.dpapi', directory / 'inputs/original.ifc', directory / 'models/weights.safetensors']
        for path in protected:
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'keep')
        users = list(database.auth_users.find({}))
        response = client.delete(f'/api/projects/{pid}', headers=AUTH)
        assert response.status_code == 200, response.text
        assert database.projects.find_one({'_id': pid}) is None
        assert database.auth_audit.count_documents({'target': pid}) == 0
        assert database.auth_audit.count_documents({'target': other}) == 1
        for collection in ['project_inspections', 'project_runs', 'project_links', 'project_issues', 'project_cases', 'project_advice', 'project_conclusions', 'auth_artifacts']:
            assert database[collection].count_documents({'project_id': pid}) == 0, collection
        assert all(not (directory / relative).exists() for relative in owned)
        assert not geometry.exists()
        assert all((directory / relative).is_file() for relative in kept)
        assert all(path.read_bytes() == b'keep' for path in protected)
        assert list(database.auth_users.find({})) == users
        assert client.get(f'/api/projects/{other}', headers=AUTH).status_code == 200
        assert client.delete(f'/api/projects/{pid}', headers=AUTH).status_code == 404


def test_shared_source_survives_until_last_project_is_deleted(workspace):
    factory, database, directory = workspace
    with factory() as client:
        first, second = project(client), project(client, 'Second')
        paths, _ = seed(database, directory, first)
        seed(database, directory, second)
        source = directory / paths[-1]
        assert client.delete(f'/api/projects/{first}', headers=AUTH).status_code == 200
        assert source.is_file()
        assert client.delete(f'/api/projects/{second}', headers=AUTH).status_code == 200
        assert not source.exists()


def test_delete_r2_is_retryable_and_releases_only_unshared_objects_and_quota(workspace, monkeypatch):
    factory, database, directory = workspace
    cloud = DeleteCloud()
    storage = StorageService(database, directory, configuration(), client=cloud)
    monkeypatch.setattr('app.main.configured_storage', lambda *args: storage)
    with factory() as client:
        first, second = project(client), project(client, 'Second')
        paths, _ = seed(database, directory, first)
        other_paths, _ = seed(database, directory, second)
        for relative in paths:
            storage.backup_file(first, relative, Event())
        storage.backup_file(second, other_paths[-1], Event())
        before = storage.status()['allocated_bytes']
        cloud.fail_delete = True
        response = client.delete(f'/api/projects/{first}', headers=AUTH)
        assert response.status_code == 503, response.text
        assert database.projects.find_one({'_id': first}) is not None
        assert all((directory / relative).exists() for relative in paths)
        assert storage.status()['allocated_bytes'] == before
        assert client.get(f'/api/projects/{first}', headers=AUTH).json()['deleting'] is True
        assert client.post(f'/api/projects/{first}/storage/sync', headers=AUTH).status_code == 409
        cloud.fail_delete = False
        response = client.delete(f'/api/projects/{first}', headers=AUTH)
        assert response.status_code == 200, response.text
        assert len(cloud.objects) == 1 and database.storage_files.count_documents({}) == 1
        assert database.storage_refs.count_documents({'project_id': first}) == 0
        assert storage.status()['allocated_bytes'] == len((directory / other_paths[-1]).read_bytes())
        assert client.delete(f'/api/projects/{second}', headers=AUTH).status_code == 200
        assert not cloud.objects and storage.status()['allocated_bytes'] == 0


def test_shared_viewer_cannot_delete_project(workspace):
    factory, database, directory = workspace
    with factory() as client:
        pid = project(client)
        paths, _ = seed(database, directory, pid)
        registered = client.post('/api/auth/register', headers=AUTH, json={'username': 'viewer-user', 'display_name': 'Viewer', 'password': 'Test-viewer-only-password-123!'})
        assert registered.status_code == 201, registered.text
        user = registered.json()
        database.projects.update_one({'_id': pid}, {'$push': {'members': {'user_id': user['user']['id'], 'access': 'view'}}})
        response = client.delete(f'/api/projects/{pid}', headers={**AUTH, 'X-BIM-Session': user['session_token']})
        assert response.status_code == 403, response.text
        assert all((directory / relative).exists() for relative in paths)
        assert client.delete(f'/api/projects/{pid}').status_code == 401


def test_delete_refuses_missing_r2_config_and_paths_outside_managed_root(workspace):
    factory, database, directory = workspace
    with factory() as client:
        pid = project(client)
        paths, _ = seed(database, directory, pid)
        database.storage_refs.insert_one({'_id': 'old-ref', 'project_id': pid, 'namespace': 'old-bucket', 'relative': paths[0], 'file_id': 'old-id'})
        response = client.delete(f'/api/projects/{pid}', headers=AUTH)
        assert response.status_code == 409, response.text
        assert response.json()['detail'] == 'storage_not_configured'
        assert all((directory / relative).exists() for relative in paths)
        database.storage_refs.delete_one({'_id': 'old-ref'})
        bad = uuid4().hex
        database.project_inspections.insert_one({'_id': '../escape', 'project_id': pid, 'sha256': bad, 'published_version': False})
        assert client.delete(f'/api/projects/{pid}', headers=AUTH).status_code == 409
        assert all((directory / relative).exists() for relative in paths)


@pytest.mark.parametrize('stage', ['quota', 'file_record'])
def test_r2_quota_release_survives_interrupted_metadata_cleanup(workspace, monkeypatch, stage):
    factory, database, directory = workspace
    cloud = DeleteCloud()
    storage = StorageService(database, directory, configuration(), client=cloud)
    monkeypatch.setattr('app.main.configured_storage', lambda *args: storage)
    with factory() as client:
        pid = project(client)
        paths, _ = seed(database, directory, pid)
        storage.backup_file(pid, paths[-1], Event())
        from pymongo.synchronous.collection import Collection
        method = 'update_one' if stage == 'quota' else 'find_one_and_delete'
        original = getattr(Collection, method)
        failed = []
        def interrupt(collection, *args, **kwargs):
            target = collection.name == ('storage_quota' if stage == 'quota' else 'storage_files')
            releases = stage == 'file_record' or args[1].get('$inc', {}).get('allocated_bytes', 0) < 0
            if target and collection.database.name == database.name and releases and not failed:
                failed.append(True)
                raise PyMongoError('Test-only interruption')
            return original(collection, *args, **kwargs)
        monkeypatch.setattr(Collection, method, interrupt)
        response = client.delete(f'/api/projects/{pid}', headers=AUTH)
        assert response.status_code == 503, response.text
        assert failed
        assert client.delete(f'/api/projects/{pid}', headers=AUTH).status_code == 200
        assert not cloud.objects
        assert storage.status()['allocated_bytes'] == 0
        assert database.storage_files.count_documents({}) == 0


def test_delete_checks_orphaned_storage_records_in_previous_namespace(workspace, monkeypatch):
    factory, database, directory = workspace
    cloud = DeleteCloud()
    original = StorageService(database, directory, configuration(), client=cloud)
    changed = StorageService(database, directory, configuration().model_copy(update={'bucket': 'new-test-bucket'}), client=cloud)
    monkeypatch.setattr('app.main.configured_storage', lambda *args: changed)
    with factory() as client:
        pid = project(client)
        paths, digest = seed(database, directory, pid)
        source = directory / paths[-1]
        record = original._reserve(paths[-1], digest, source.stat().st_size)
        cloud.objects[record['key']] = (source.read_bytes(), {'sha256': digest})
        response = client.delete(f'/api/projects/{pid}', headers=AUTH)
        assert response.status_code == 409, response.text
        assert response.json()['detail'] == 'storage_namespace_mismatch'
        assert source.is_file() and cloud.objects


def test_r2_deletion_claim_respects_references_added_after_the_initial_plan(workspace):
    _, database, directory = workspace
    cloud = DeleteCloud()
    storage = StorageService(database, directory, configuration(), client=cloud)
    relative = f'cache/models/{"a" * 64}.ifc'
    path = directory / relative; path.parent.mkdir(parents=True); path.write_bytes(b'shared')
    storage.backup_file('first', relative, Event())
    storage.backup_file('second', relative, Event())
    storage.delete_project_files('first', [relative])
    assert len(cloud.objects) == 1
    assert storage.status()['allocated_bytes'] == path.stat().st_size
    assert database.storage_refs.count_documents({'project_id': 'second'}) == 1


def test_backup_cannot_publish_an_object_claimed_for_deletion(workspace):
    _, database, directory = workspace
    cloud = DeleteCloud()
    storage = StorageService(database, directory, configuration(), client=cloud)
    relative = f'cache/models/{"b" * 64}.ifc'
    path = directory / relative; path.parent.mkdir(parents=True); path.write_bytes(b'shared')
    storage.backup_file('first', relative, Event())
    database.storage_files.update_one({'_id': storage.file_id(relative)}, {'$set': {'status': 'deleting', 'delete_token': uuid4().hex}})
    with pytest.raises(HTTPException) as error:
        storage.backup_file('second', relative, Event())
    assert error.value.detail == 'storage_file_deleting'
    assert database.storage_refs.count_documents({'project_id': 'second'}) == 0


def test_cancelled_delete_keeps_the_slot_until_its_cleanup_thread_finishes(workspace, monkeypatch):
    import asyncio
    from app.access import actor_context
    from app.projects import ProjectStore
    factory, _, _ = workspace
    started, release = Event(), Event()
    original = ProjectStore.delete_project
    def slow(store, identifier):
        started.set()
        assert release.wait(5)
        return original(store, identifier)
    monkeypatch.setattr(ProjectStore, 'delete_project', slow)
    with factory() as client:
        first, second = project(client), project(client, 'Second')
        endpoint = next(route.endpoint for route in client.app.routes if getattr(route, 'path', '') == '/api/projects/{project_id}' and 'DELETE' in route.methods)
        async def check():
            token = actor_context.set({'id': 'bootstrap', 'role': 'admin'})
            tasks = []
            try:
                deletion = asyncio.create_task(endpoint(first)); tasks.append(deletion)
                assert await asyncio.to_thread(started.wait, 2)
                deletion.cancel()
                await asyncio.sleep(.05)
                other = asyncio.create_task(endpoint(second)); tasks.append(other)
                await asyncio.sleep(.1)
                assert other.done(), 'Cancellation released the slot while destructive cleanup was still running'
                assert isinstance(other.exception(), HTTPException) and other.exception().detail == 'project_busy'
            finally:
                release.set()
                await asyncio.gather(*tasks, return_exceptions=True)
                actor_context.reset(token)
        asyncio.run(check())


def test_deletion_is_serialized_across_app_instances_sharing_mongodb(workspace, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from pymongo.synchronous.collection import Collection
    from app.projects import ProjectStore
    factory, database, directory = workspace
    started, release = Event(), Event()
    with factory() as client:
        first, second = project(client), project(client, 'Second')
        paths, _ = seed(database, directory, first)
        seed(database, directory, second)
        original = Collection.find
        def pause(collection, query=None, *args, **kwargs):
            if collection.database.name == database.name and collection.name == 'project_inspections' and query == {'project_id': first} and not started.is_set():
                started.set(); assert release.wait(5)
            return original(collection, query, *args, **kwargs)
        monkeypatch.setattr(Collection, 'find', pause)
        store = ProjectStore(database, directory)
        with ThreadPoolExecutor(max_workers=1) as pool:
            task = pool.submit(store.delete_project, first)
            try:
                assert started.wait(2)
                with pytest.raises(HTTPException) as error:
                    ProjectStore(database, directory).delete_project(second)
                assert error.value.detail == 'project_busy'
            finally:
                release.set(); task.result(timeout=5)
        assert (directory / paths[-1]).is_file()
        store.delete_project(second)
        assert not (directory / paths[-1]).exists()


def test_device_clock_skew_cannot_steal_an_active_database_lock(workspace, monkeypatch):
    from datetime import datetime, timedelta
    import app.project_cleanup as cleanup
    _, database, _ = workspace
    class SkewedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=1)
    with cleanup.project_data_lock(database):
        monkeypatch.setattr(cleanup, 'datetime', SkewedClock, raising=False)
        with pytest.raises(HTTPException) as error:
            with cleanup.project_data_lock(database):
                pass
        assert error.value.detail == 'project_busy'
