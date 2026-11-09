import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from test_api import AUTH
from test_ifc_probe import small_ifc
from test_inspections import inspection_client


def test_inspection_worker_does_not_import_the_web_server(tmp_path):
    script = """import sys
from pathlib import Path
import app.inspection_worker as worker
def run(source, output, **kwargs):
    assert 'app.main' not in sys.modules, 'IFC worker must not load the HTTP server'
    assert 'uvicorn' not in sys.modules
    assert 'app.ai' not in sys.modules
    output.write_text('ok')
worker.run_worker = run
sys.argv = ['bim_backend', '--inspect-worker', 'source.ifc', sys.argv[1]]
import app.__main__ as cli
cli.main()
"""
    output = tmp_path / 'result.txt'
    result = subprocess.run([sys.executable, '-c', script, str(output)], capture_output=True, text=True,
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}, timeout=15)
    assert result.returncode == 0, result.stderr
    assert output.read_text() == 'ok'


def test_failed_import_preserves_ram_measurements_and_download(tmp_path, monkeypatch, small_ifc):
    from app.inspections import InspectionService

    stats = {'elapsed_seconds': 4.4, 'peak_memory_bytes': 900 * 1024**2, 'memory_limit_bytes': 800 * 1024**2,
             'last_progress': {'phase': 'reading_ifc'}}
    async def stopped(*args, **kwargs):
        return {'processing': stats}, 'processing_memory_limit'
    monkeypatch.setattr(InspectionService, 'run_job', stopped)
    with inspection_client(tmp_path / 'app') as client:
        response = client.post('/api/inspections', files={'file': ('Snowdon.ifc', small_ifc[0].read_bytes())}, headers=AUTH)
        assert response.status_code == 200
        report = response.json()
        assert report['status'] == 'failed' and report['error_code'] == 'processing_memory_limit'
        assert report['processing'] == stats
        assert client.get(report['report_url'], headers=AUTH).json()['processing'] == stats
    assert not list((tmp_path / 'app').rglob('source.ifc'))


def test_worker_emits_runtime_ram_even_when_no_geometry_progress_file_exists(tmp_path):
    from app.inspections import InspectionService

    script = tmp_path / 'worker.py'
    output = tmp_path / 'result.json'
    script.write_text("import sys,time,json\nfrom pathlib import Path\ntime.sleep(.6)\nPath(sys.argv[1]).write_text(json.dumps({'status':'completed'}))\n", encoding='utf-8')
    async def connected():
        return False
    events = []
    result, error = asyncio.run(InspectionService(tmp_path, 5, 1024**3).run_job(
        SimpleNamespace(is_disconnected=connected), [str(output)], output, 1,
        command=[sys.executable, str(script)], progress=events.append))
    assert error is None
    assert events and any(event.get('memory_bytes', 0) > 0 for event in events)
    assert all(event['memory_limit_bytes'] == 1024**3 for event in events)
    assert result['processing']['peak_memory_bytes'] > 0
    assert result['processing']['elapsed_seconds'] >= .6
    assert result['processing']['memory_bytes'] == 0


def test_streamed_import_returns_progress_and_saved_report(tmp_path, small_ifc):
    with inspection_client(tmp_path / 'app') as client:
        response = client.post('/api/inspections', headers={**AUTH, 'Accept': 'application/x-ndjson'},
                               files={'file': ('Snowdon.ifc', small_ifc[0].read_bytes())})
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('application/x-ndjson')
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[0]['type'] == 'progress'
        assert any(event.get('memory_bytes', 0) > 0 for event in events if event['type'] == 'progress')
        report = events[-1]['report']
        assert report['status'] == 'completed' and report['clash_ready']
        assert report['processing']['peak_memory_bytes'] > 0
        downloaded = client.get(report['report_url'] + '?full=true', headers=AUTH).json()
        assert downloaded['processing'] == report['processing']
        assert len(downloaded['result']['elements']) == 1


def test_preview_optimizer_runs_after_the_native_ifc_model_is_released(tmp_path, small_ifc, monkeypatch):
    import weakref
    import ifcopenshell
    import app.ifc

    opened, released = [], []
    original_open, original_compact = ifcopenshell.open, app.ifc.compact_glb
    def load(*args, **kwargs):
        model = original_open(*args, **kwargs)
        opened.append(weakref.ref(model))
        return model
    def compact(path):
        released.append(all(reference() is None for reference in opened))
        return original_compact(path)
    monkeypatch.setattr(ifcopenshell, 'open', load)
    monkeypatch.setattr(app.ifc, 'compact_glb', compact)
    assets = tmp_path / 'assets'
    assets.mkdir()
    result = app.ifc.inspect_ifc(small_ifc[0], assets)
    assert result['status'] == 'completed'
    assert released == [True]


def test_ifc_import_reports_actual_phases_and_geometry_counts(tmp_path, small_ifc):
    from app.ifc import inspect_ifc

    events = []
    assets = tmp_path / 'assets'
    assets.mkdir()
    result = inspect_ifc(small_ifc[0], assets, progress=events.append)
    assert result['status'] == 'completed'
    assert {event['phase'] for event in events} >= {'reading_ifc', 'preparing_geometry', 'building_geometry', 'optimizing_preview'}
    built = [event for event in events if event['phase'] == 'building_geometry']
    assert built[-1]['done'] == built[-1]['total'] == 1


@pytest.mark.parametrize('cap,expected_batch,expected_threads', [(0.85,64,1),(2,128,1),(3,512,2)])
def test_worker_respects_its_assigned_budget_before_selecting_threads_and_batch(monkeypatch, cap, expected_batch, expected_threads):
    import psutil
    from app.limits import geometry_memory_gb, ifc_geometry_threads, ifc_geometry_batch_size

    monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(total=16*1024**3, available=12*1024**3))
    monkeypatch.setattr(psutil, 'cpu_count', lambda logical=True: 8)
    monkeypatch.setenv('BIM_WORKER_MEMORY_BYTES', str(int(cap*1024**3)))
    assert geometry_memory_gb() == pytest.approx(cap)
    assert ifc_geometry_threads() == expected_threads
    assert ifc_geometry_batch_size() == expected_batch


def test_stream_closes_uploaded_form_even_if_cancelled_before_operation_starts():
    from app.inspections import stream_job

    async def check():
        closed = []
        async def operation(progress):
            await asyncio.Event().wait()
        async def close():
            closed.append(True)
        stream = stream_job(operation, cleanup=close)
        await anext(stream)
        await stream.aclose()
        assert closed == [True]
    asyncio.run(check())


def test_invalid_worker_json_root_is_a_controlled_failure(tmp_path):
    from app.inspections import InspectionService

    script, output = tmp_path / 'worker.py', tmp_path / 'result.json'
    script.write_text("import sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text('[]')\n", encoding='utf-8')
    async def connected():
        return False
    result, error = asyncio.run(InspectionService(tmp_path, 5, 1024**3).run_job(
        SimpleNamespace(is_disconnected=connected), [str(output)], output, 1,
        command=[sys.executable, str(script)]))
    assert error == 'processing_failed'
    assert result['processing']['peak_memory_bytes'] > 0
