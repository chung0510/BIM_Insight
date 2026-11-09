import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from test_clash import demo_sources, options
from test_projects import workspace, project, upload
from test_api import AUTH


def test_precise_clash_reports_real_geometry_and_pair_progress(demo_sources, monkeypatch):
    import app.clash as engine

    events = []
    monkeypatch.setattr(engine, 'ifc_geometry_threads', lambda: 2)
    result = engine.check_clashes(demo_sources, options(), progress=events.append)

    assert result['status'] == 'completed'
    assert len(result['issues']) == 2
    assert result['geometry_settings']['linear_deflection_m'] == .0005
    assert result['geometry_settings']['threads'] == 2
    assert {event['phase'] for event in events} >= {'loading_model', 'building_geometry', 'checking_pairs'}
    geometry = [event for event in events if event['phase'] == 'building_geometry']
    assert {event['source_index'] for event in geometry} == {1, 2, 3}
    assert all(0 <= event['done'] <= event['total'] for event in geometry)
    assert any(event['done'] == event['total'] > 0 for event in geometry)
    pairs = [event for event in events if event['phase'] == 'checking_pairs']
    assert pairs[-1]['done'] == pairs[-1]['total']


def test_worker_progress_is_read_while_process_is_running(tmp_path):
    from app.inspections import InspectionService

    worker = tmp_path / 'worker.py'
    output = tmp_path / 'result.json'
    worker.write_text("import json,sys,time\nfrom pathlib import Path\np=Path(sys.argv[1])\np.with_name('progress.json').write_text(json.dumps({'phase':'building_geometry','done':1,'total':2}))\ntime.sleep(.4)\np.write_text(json.dumps({'status':'completed'}))\n", encoding='utf-8')
    async def connected():
        return False
    events = []
    result, error = asyncio.run(InspectionService(tmp_path, 5, 1024**3).run_job(
        SimpleNamespace(is_disconnected=connected), [str(output)], output, 1,
        command=[sys.executable, str(worker)], progress=events.append,
    ))
    assert error is None and result['status'] == 'completed'
    assert any(event['phase'] == 'building_geometry' for event in events)


def test_worker_memory_stop_keeps_measured_budget_and_elapsed_time(tmp_path, monkeypatch):
    import psutil
    from app.inspections import InspectionService

    worker = tmp_path / 'sleeping-worker.py'
    worker.write_text('import time\ntime.sleep(10)\n', encoding='utf-8')
    monkeypatch.setattr(psutil.Process, 'memory_info', lambda self: SimpleNamespace(rss=40 * 1024**2))
    async def connected():
        return False
    result, error = asyncio.run(InspectionService(tmp_path, 5, 1024**3).run_job(
        SimpleNamespace(is_disconnected=connected), [], tmp_path / 'missing.json', 20 / 1024,
        command=[sys.executable, str(worker)],
    ))
    assert error == 'processing_memory_limit'
    assert result['processing']['peak_memory_bytes'] >= 40 * 1024**2
    assert result['processing']['memory_limit_bytes'] == 20 * 1024**2
    assert result['processing']['elapsed_seconds'] >= 0


def test_progress_stream_starts_before_job_finishes_and_cancel_stops_job(monkeypatch):
    import app.clash_jobs as jobs

    async def check():
        stopped = asyncio.Event()
        async def slow_job(service, request, payload, progress=None):
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        monkeypatch.setattr(jobs, 'create_clash', slow_job)
        async def saved(report):
            raise AssertionError('Cancelled job must not be saved')
        stream = jobs.stream_clash(None, None, None, saved)
        first = json.loads(await asyncio.wait_for(anext(stream), 1))
        assert first['type'] == 'progress'
        await asyncio.sleep(0)
        await stream.aclose()
        assert stopped.is_set()
    asyncio.run(check())


def test_stream_returns_report_and_keeps_saved_json_compatible(workspace):
    from app.demo import demo_files

    factory, _, _ = workspace
    with factory() as client:
        identifier = project(client)
        reports = [upload(client, identifier, item) for item in demo_files() if item['name'].endswith('.ifc')]
        response = client.post('/api/inspections/clashes', headers={**AUTH, 'Accept': 'application/x-ndjson'}, json={
            'model_ids': [report['id'] for report in reports], 'coordinates_confirmed': True,
        })
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('application/x-ndjson')
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[0]['type'] == 'progress'
        assert events[-1]['type'] == 'result'
        report = events[-1]['report']
        assert report['status'] == 'completed' and len(report['issues']) == 2
        saved = client.get(report['report_url'], headers=AUTH)
        assert saved.status_code == 200 and saved.json() == report


def test_disconnect_cancel_scope_waits_for_child_worker_cleanup(monkeypatch):
    import anyio
    import app.clash_jobs as jobs

    async def check():
        entered, stopped = asyncio.Event(), asyncio.Event()
        async def slow_job(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(.05)
                stopped.set()
        monkeypatch.setattr(jobs, 'create_clash', slow_job)
        async def consume():
            stream = jobs.stream_clash(None, None, None, None)
            try:
                await anext(stream)
                await asyncio.Event().wait()
            finally:
                await stream.aclose()
        async with anyio.create_task_group() as group:
            group.start_soon(consume)
            await entered.wait()
            group.cancel_scope.cancel()
        assert stopped.is_set()
    asyncio.run(check())


def test_stream_failure_is_structured_without_fake_clear_result(monkeypatch):
    import app.clash_jobs as jobs
    from fastapi import HTTPException

    async def failed(*args, **kwargs):
        raise HTTPException(422, 'clash_frame_unconfirmed')
    monkeypatch.setattr(jobs, 'create_clash', failed)
    async def check():
        events = [json.loads(line) async for line in jobs.stream_clash(None, None, None, None)]
        assert events[-1] == {'type': 'error', 'code': 'clash_frame_unconfirmed'}
        assert not any(event['type'] == 'result' for event in events)
    asyncio.run(check())


def test_disconnect_stops_real_worker_before_stream_cleanup_finishes(tmp_path, monkeypatch):
    import anyio
    import psutil
    import app.clash_jobs as jobs
    from app.inspections import InspectionService

    worker = tmp_path / 'sleeping_worker.py'
    pidfile = tmp_path / 'worker.pid'
    worker.write_text("import json,os,subprocess,sys,time\nfrom pathlib import Path\nchild=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\nPath(sys.argv[1]).write_text(json.dumps([os.getpid(),child.pid]))\ntime.sleep(60)\n", encoding='utf-8')
    async def check():
        async def connected():
            return False
        service = InspectionService(tmp_path, 60, 1024**3)
        async def real_job(*args, progress=None, **kwargs):
            return await service.run_job(SimpleNamespace(is_disconnected=connected), [str(pidfile)], tmp_path / 'missing.json', 1,
                                         command=[sys.executable, str(worker)], progress=progress)
        monkeypatch.setattr(jobs, 'create_clash', real_job)
        async def consume():
            stream = jobs.stream_clash(None, None, None, None)
            try:
                await anext(stream)
                await asyncio.Event().wait()
            finally:
                await stream.aclose()
        with anyio.fail_after(10):
            async with anyio.create_task_group() as group:
                group.start_soon(consume)
                while not pidfile.is_file():
                    await asyncio.sleep(.02)
                pids = json.loads(pidfile.read_text())
                group.cancel_scope.cancel()
        assert all(not psutil.pid_exists(pid) for pid in pids)
    asyncio.run(check())


def test_memory_failure_report_keeps_measurements_and_is_saved(workspace, monkeypatch):
    from app.demo import demo_files
    from app.inspections import InspectionService

    factory, _, _ = workspace
    async def exhausted(*args, **kwargs):
        return {'processing': {'elapsed_seconds': 906.5, 'peak_memory_bytes': 4 * 1024**3,
                               'memory_limit_bytes': 3 * 1024**3, 'last_progress': {'phase': 'building_geometry'}}}, 'processing_memory_limit'
    with factory() as client:
        pid = project(client)
        ids = [upload(client, pid, item)['id'] for item in demo_files() if item['name'].endswith('.ifc')]
        monkeypatch.setattr(InspectionService, 'run_job', exhausted)
        response = client.post('/api/inspections/clashes', json={'model_ids': ids, **options()}, headers=AUTH)
        result = response.json()
        assert response.status_code == 200 and result['status'] == 'failed'
        assert result['diagnostics'][0]['peak_memory_bytes'] == 4 * 1024**3
        assert result['diagnostics'][0]['memory_limit_bytes'] == 3 * 1024**3
        assert result['elapsed_seconds'] == 906.5
        assert client.get(result['report_url'], headers=AUTH).json() == result
