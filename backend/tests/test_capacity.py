import asyncio
import json
import sys
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from test_api import TOKEN
from test_ifc_probe import small_ifc


def test_health_advertises_large_file_and_processing_limits(tmp_path):
    from app.main import create_app

    with TestClient(create_app(api_token=TOKEN, data_dir=tmp_path), base_url='http://127.0.0.1') as client:
        health = client.get('/api/health').json()
    assert health['file_limits'] == {'ifc': 2 * 1024**3, 'dwg': 256 * 1024**2, 'dxf': 256 * 1024**2, 'pdf': 100 * 1024**2}
    limits = health['processing_limits']
    assert limits['queue_files'] == 200
    assert limits['open_files'] == 200
    assert limits['clash_models'] == 50
    assert limits['clash_elements'] == 100_000
    assert limits['clash_issues'] == 50_000
    assert limits['timeout_seconds'] == 1800
    assert limits['pdf_pages'] == 500


def test_clash_accepts_more_than_five_models_and_still_bounds_requests():
    from app.rules import ClashRequest

    ids = [f'{index:032x}' for index in range(51)]
    assert len(ClashRequest(model_ids=ids[:50]).model_ids) == 50
    with pytest.raises(ValidationError):
        ClashRequest(model_ids=ids)
    with pytest.raises(ValidationError):
        ClashRequest(model_ids=[ids[0], ids[0]])


def test_memory_budget_preserves_system_headroom(monkeypatch):
    from app.limits import geometry_memory_gb
    import psutil

    monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(total=16 * 1024**3, available=12 * 1024**3))
    assert geometry_memory_gb() == 8
    monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(total=16 * 1024**3, available=3 * 1024**3))
    assert geometry_memory_gb() == 2


def test_shared_assemblies_count_billions_of_pairs_without_materializing_them():
    from collections import Counter
    from app.clash import shared_reference_counts

    groups = [Counter({('same-parent', 'IfcWall'): 50_000}) for _ in range(2)]
    assert shared_reference_counts(groups, False) == (2_500_000_000, 2_500_000_000)
    assert shared_reference_counts(groups, True) == (2_500_000_000, 0)
    groups[1] = Counter({('same-parent', 'IfcWall'): 40_000, ('same-parent', 'IfcBeam'): 10_000})
    assert shared_reference_counts(groups, True) == (2_500_000_000, 500_000_000)


def test_worker_protocol_keeps_results_larger_than_old_five_mib_limit(tmp_path):
    from app.inspections import InspectionService

    output = tmp_path / 'result.json'
    worker = tmp_path / 'large_worker.py'
    worker.write_text("import json,sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(json.dumps({'payload':'x'*(6*1024**2)}),encoding='utf-8')\n", encoding='utf-8')

    async def connected():
        return False

    service = InspectionService(tmp_path, 30, 1024**3)
    result, error = asyncio.run(service.run_job(SimpleNamespace(is_disconnected=connected), [str(output)], output, 1, command=[sys.executable, str(worker)]))
    assert error is None
    assert len(result['payload']) == 6 * 1024**2


def test_ifc_full_export_preserves_details_while_ui_summary_stays_small(tmp_path, monkeypatch):
    from app.inspection_worker import run_worker
    import app.ifc

    elements = [{'guid': str(index), 'ifc_type': 'IfcWall', 'triangle_count': 12} for index in range(35)]
    diagnostics = [{'code': 'geometry_failed', 'guid': str(index)} for index in range(150)]
    monkeypatch.setattr(app.ifc, 'inspect_ifc', lambda *args, **kwargs: {'status': 'partial', 'elements': elements, 'diagnostics': diagnostics})
    output = tmp_path / 'result.json'
    run_worker(tmp_path / 'source.ifc', output)
    summary = json.loads(output.read_text(encoding='utf-8'))
    full = json.loads((tmp_path / 'assets' / 'inspection.json').read_text(encoding='utf-8'))
    assert len(summary['elements']) == 20
    assert len(summary['diagnostics']) == 100
    assert summary['details_available'] is True
    assert full['elements'] == elements and full['diagnostics'] == diagnostics
    assert full['elements_truncated'] is False
    assert full['diagnostics_truncated'] is False


def test_large_clash_report_can_be_reopened_and_exported_without_losing_issues(tmp_path):
    from pymongo import MongoClient
    from app.projects import ProjectStore
    from test_inspections import inspection_client
    from test_api import AUTH

    with inspection_client(tmp_path) as client, MongoClient(client.mongo_uri) as mongo:
        project_id = client.post('/api/projects', headers=AUTH, json={'name': 'Large report regression'}).json()['id']
        store = ProjectStore(mongo[client.database_name], tmp_path)
        run_id = 'b' * 32
        report = {'id': run_id, 'project_id': project_id, 'revision': 'R01', 'created_at': '2026-11-07T00:00:00+00:00', 'status': 'completed', 'verdict': 'findings', 'dataset': None, 'parameters': {}, 'sources': [], 'coverage': {}, 'evaluation': None, 'counts': {'intersection': 1800}, 'issues': [{'id': f'{index:024x}', 'kind': 'intersection', 'recommendation': 'evidence ' * 400} for index in range(1800)]}
        path = tmp_path / 'clashes' / f'{run_id}.json'
        path.parent.mkdir()
        path.write_text(json.dumps(report), encoding='utf-8')
        assert path.stat().st_size > 5 * 1024**2
        store.save_run(report)
        assert len(store.restore_run(project_id, run_id)['report']['issues']) == 1800
        exported = store.export_dataset(project_id, run_id)
        assert len(exported['issues']) == 1800
        assert exported['issues'][-1]['id'] == report['issues'][-1]['id']


def test_full_inspection_detail_is_managed_for_r2_backup():
    from app.schemas import ASSET_FILES
    from app.storage import MANAGED, MAX_FILE

    assert ASSET_FILES['inspection.json'] == 'details'
    assert MANAGED.fullmatch('assets/' + 'a' * 32 + '/inspection.json')
    assert MAX_FILE >= 2 * 1024**3


def test_full_report_download_keeps_all_ifc_elements_and_access_control(tmp_path, small_ifc):
    import ifcopenshell
    from test_api import AUTH
    from test_inspections import inspection_client

    path, guid = small_ifc
    model = ifcopenshell.open(str(path))
    wall = model.by_guid(guid)
    for index in range(25):
        model.create_entity('IfcWall', GlobalId=ifcopenshell.guid.new(), Name=f'Additional wall {index}', ObjectPlacement=wall.ObjectPlacement, Representation=wall.Representation)
    model.write(str(path))
    original = path.read_bytes()
    with inspection_client(tmp_path / 'app') as client:
        report = client.post('/api/inspections', headers=AUTH, files={'file': ('many-walls.ifc', original)}).json()
        assert len(report['result']['elements']) == 20
        assert report['result']['elements_truncated'] is True
        full = client.get(report['report_url'] + '?full=true', headers=AUTH)
        assert full.status_code == 200, full.text
        assert len(full.json()['result']['elements']) == 26
        assert full.json()['result']['elements_truncated'] is False
        assert client.get(report['report_url'] + '?full=true').status_code == 401
        assert report['assets']['details']
    assert path.read_bytes() == original


def test_upload_reports_insufficient_disk_before_creating_work(tmp_path, monkeypatch):
    import shutil
    from test_api import AUTH
    from test_inspections import inspection_client, pdf_bytes

    monkeypatch.setattr(shutil, 'disk_usage', lambda path: SimpleNamespace(free=256 * 1024**2))
    with inspection_client(tmp_path) as client:
        response = client.post('/api/inspections', headers=AUTH, files={'file': ('drawing.pdf', pdf_bytes())})
    assert response.status_code == 507
    assert response.json()['detail'] == 'processing_disk_space'
    assert not list(tmp_path.rglob('source.*'))


def test_geometry_mapping_survives_a_viewer_size_limit(tmp_path, small_ifc, monkeypatch):
    import app.ifc

    assets = tmp_path / 'assets'
    assets.mkdir()
    monkeypatch.setattr(app.ifc, 'MAX_GLB_BYTES', 1)
    report = app.ifc.inspect_ifc(small_ifc[0], assets)
    assert report['viewer_available'] is False
    assert report['mapping_available'] is True
    assert json.loads((assets / 'model.json').read_text(encoding='utf-8'))['elements'][0]['guid'] == small_ifc[1]


@pytest.mark.skipif(os.getenv('BIM_RUN_LARGE_INPUT_TEST') != '1', reason='Opt-in large-transfer test')
def test_real_ifc_reader_accepts_a_file_over_previous_100_mib_limit(tmp_path, small_ifc):
    from test_api import AUTH
    from test_inspections import inspection_client

    # Large transfer with simple geometry, not a complex-building performance benchmark.
    source = tmp_path / 'large-transfer.ifc'
    with source.open('wb') as handle:
        handle.write(small_ifc[0].read_bytes())
        for _ in range(101):
            handle.write(b' ' * 1024**2)
    with inspection_client(tmp_path / 'app') as client, source.open('rb') as handle:
        response = client.post('/api/inspections', headers=AUTH, files={'file': ('large-transfer.ifc', handle)})
        assert response.status_code == 200, response.text[:1000]
        report = response.json()
        assert report['status'] == 'completed', report
        assert report['size_bytes'] > 100 * 1024**2
        assert report['result']['element_count'] == 1
        assert client.get(report['report_url'] + '?full=true', headers=AUTH).json()['result']['elements'][0]['guid'] == small_ifc[1]
