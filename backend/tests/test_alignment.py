import json
from uuid import uuid4

import pytest
from pymongo import MongoClient

from test_api import AUTH
from test_inspections import inspection_client


@pytest.fixture
def link_data(tmp_path):
    directory = tmp_path / "app-data"
    reports = directory / "reports"
    reports.mkdir(parents=True)
    with inspection_client(directory) as client:
        project_id = client.post("/api/projects", json={"name": "Alignment fixture"}, headers=AUTH).json()["id"]
    drawing_id, model_id = uuid4().hex, uuid4().hex
    lines = [{"start_m": [0, 0, 0], "end_m": [0, 10, 0]}, {"start_m": [0, 0, 0], "end_m": [10, 0, 0]}]
    for identifier, kind, result in [
        (drawing_id, "dxf", {"unit_scale_to_m": 0.001, "grid_lines": lines}),
        (model_id, "ifc", {"length_unit_verified": True, "project_unit_scale_to_m": 0.001, "storeys": [{"guid": "storey-2", "name": "Level 2", "elevation_m": 3.9}], "grids": [{"elevation_m": 3.9, "lines": lines}]}),
    ]:
        (reports / f"{identifier}.json").write_text(json.dumps({"id": identifier, "name": kind, "kind": kind, "sha256": identifier * 2, "status": "completed", "result": result, "project_id": project_id, "revision": "R01"}), encoding="utf-8")
    with inspection_client(directory) as client:
        with MongoClient(client.mongo_uri) as mongo:
            mongo[client.database_name].project_inspections.insert_many([
                {"_id": identifier, "project_id": project_id} for identifier in (drawing_id, model_id)
            ])
    return directory, {"drawing_id": drawing_id, "model_id": model_id, "storey_guid": "storey-2", "project_name": "Synthetic", "revision": "R01", "dx_m": 0, "dy_m": 0, "rotation_deg": 0, "confirmed": False, "same_revision_confirmed": False}


def test_alignment_preview_does_not_confirm_or_write_a_link(link_data):
    directory, payload = link_data
    with inspection_client(directory) as client:
        response = client.post("/api/inspections/alignments", json=payload, headers=AUTH)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["grid_xy_ready"] is True
    assert result["matched_axes"] == 2
    assert result["confirmed"] is False
    assert result["elevation_m"] == pytest.approx(3.9)
    assert result["clash_detection"] == "not_run"
    assert not list((directory / "links").glob("*.json"))


def test_converted_dwg_can_use_the_same_grid_alignment(link_data):
    directory, payload = link_data
    path = directory / "reports" / f"{payload['drawing_id']}.json"
    report = json.loads(path.read_text())
    report["kind"] = "dwg"
    report["result"]["conversion"] = {"converter": "ODA File Converter"}
    path.write_text(json.dumps(report))
    with inspection_client(directory) as client:
        response = client.post("/api/inspections/alignments", json=payload, headers=AUTH)
        assert response.status_code == 200, response.text
        assert response.json()["grid_xy_ready"] is True
        report["result"].pop("conversion")
        path.write_text(json.dumps(report))
        assert client.post("/api/inspections/alignments", json=payload, headers=AUTH).status_code == 422


def test_link_requires_revision_confirmation_and_keeps_source_hashes(link_data):
    directory, payload = link_data
    with inspection_client(directory) as client:
        response = client.post("/api/inspections/alignments", json={**payload, "confirmed": True}, headers=AUTH)
        assert response.status_code == 422
        response = client.post("/api/inspections/alignments", json={**payload, "confirmed": True, "same_revision_confirmed": True}, headers=AUTH)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["confirmed"] is True
        assert result["drawing_sha256"] == payload["drawing_id"] * 2
        saved = client.get(result["link_url"], headers=AUTH)
        assert saved.json() == result
        assert client.get(result["link_url"]).status_code == 401
    assert len(list((directory / "links").glob("*.json"))) == 1


@pytest.mark.parametrize("changes", [{"dx_m": 1}, {"rotation_deg": 20}, {"storey_guid": "wrong-floor"}])
def test_wrong_offset_rotation_or_floor_cannot_be_confirmed(link_data, changes):
    directory, payload = link_data
    with inspection_client(directory) as client:
        response = client.post("/api/inspections/alignments", json={**payload, **changes, "confirmed": True, "same_revision_confirmed": True}, headers=AUTH)
    assert response.status_code == 422
    assert not list((directory / "links").glob("*.json"))


def test_parallel_axes_alone_do_not_prove_xy_alignment(link_data):
    directory, payload = link_data
    path = directory / "reports" / f"{payload['model_id']}.json"
    report = json.loads(path.read_text())
    report["result"]["grids"][0]["lines"] = [report["result"]["grids"][0]["lines"][0]] * 2
    path.write_text(json.dumps(report))
    with inspection_client(directory) as client:
        result = client.post("/api/inspections/alignments", json=payload, headers=AUTH).json()
    assert result["grid_xy_ready"] is False


def test_unknown_units_and_nonfinite_transform_are_rejected(link_data):
    directory, payload = link_data
    path = directory / "reports" / f"{payload['drawing_id']}.json"
    report = json.loads(path.read_text())
    report["result"]["unit_scale_to_m"] = None
    path.write_text(json.dumps(report))
    with inspection_client(directory) as client:
        assert client.post("/api/inspections/alignments", json=payload, headers=AUTH).status_code == 422
        assert client.post("/api/inspections/alignments", json={**payload, "dx_m": "NaN"}, headers=AUTH).status_code == 422


def test_alignment_ids_cannot_read_outside_reports(link_data):
    directory, payload = link_data
    with inspection_client(directory) as client:
        assert client.post("/api/inspections/alignments", json={**payload, "drawing_id": "../../secret"}, headers=AUTH).status_code == 422


@pytest.mark.parametrize("incomplete", ["cad_grid_limit", "cad_xref_unresolved", "3d", "ifc_axis"])
def test_incomplete_or_3d_grid_scope_cannot_be_confirmed(link_data, incomplete):
    directory, payload = link_data
    kind = "model_id" if incomplete == "ifc_axis" else "drawing_id"
    path = directory / "reports" / f"{payload[kind]}.json"
    report = json.loads(path.read_text())
    if incomplete == "ifc_axis":
        report["result"]["grids"][0]["axis_count"] = 3
    elif incomplete == "3d":
        report["result"]["has_3d_entities"] = True
    else:
        report["result"]["diagnostics"] = [{"code": incomplete}]
    path.write_text(json.dumps(report))
    with inspection_client(directory) as client:
        response = client.post("/api/inspections/alignments", json={**payload, "confirmed": True, "same_revision_confirmed": True}, headers=AUTH)
    assert response.status_code == 422


def test_small_angle_that_exceeds_tolerance_at_axis_ends_is_rejected(link_data):
    import math
    directory, payload = link_data
    for identifier in [payload["drawing_id"], payload["model_id"]]:
        path = directory / "reports" / f"{identifier}.json"
        report = json.loads(path.read_text())
        lines = report["result"].get("grid_lines") or report["result"]["grids"][0]["lines"]
        for line in lines:
            line["end_m"] = [n * 10 for n in line["end_m"]]
        path.write_text(json.dumps(report))
    with inspection_client(directory) as client:
        response = client.post("/api/inspections/alignments", json={**payload, "rotation_deg": math.degrees(0.0001), "confirmed": True, "same_revision_confirmed": True}, headers=AUTH)
    assert response.status_code == 422
