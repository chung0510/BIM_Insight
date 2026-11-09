import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from app.ifc import inspect_ifc
from app.clash import check_clashes
from test_inspections import inspection_client
from test_api import AUTH
from test_projects import workspace, project, upload, run_clash


def test_offline_pilot_provides_60_analytic_cases_without_claiming_human_labels():
    from app.demo import PILOT_DATASET, dataset_bundle
    bundle = dataset_bundle(PILOT_DATASET)
    assert bundle["dataset"] == "synthetic_pilot_v1"
    assert len(bundle["files"]) == 4
    assert len(bundle["cases"]) == 60
    assert bundle["label_origin"] == "analytic"
    assert bundle["independent_projects"] is False


def test_pilot_geometry_has_positive_negative_and_clearance_cases(tmp_path):
    from app.pilot import pilot_bundle

    bundle = pilot_bundle()
    sources = []
    for item in bundle["files"][:3]:
        path = tmp_path / item["name"]
        path.write_text(item["content"], encoding="utf-8", newline="")
        assets = tmp_path / item["discipline"]
        assets.mkdir()
        metadata = inspect_ifc(path, assets_dir=assets)
        assert metadata["status"] == "completed", metadata
        sources.append({"id": uuid4().hex, "name": item["name"], "sha256": item["sha256"], "path": str(path), "mapping_path": str(assets / "model.json"), "result": metadata})
    for mode, expected in [("hard", 29), ("clearance", 35)]:
        report = check_clashes(sources, {"mode": mode, "tolerance_mm": 1, "clearance_mm": 50, "coordinates_confirmed": True, "shared_references_confirmed": False})
        assert report["status"] == "partial", report
        assert report["coverage"]["tested_elements"] == 120
        assert report["counts"]["intersection"] == 20
        assert len(report["issues"]) == expected
        evaluation = report["evaluation"]
        assert evaluation["cases"] == 60
        assert evaluation["recall"] == 1
        assert evaluation["precision"] == (20 / 29 if mode == "hard" else 1)
        assert evaluation["positive_definition"] == "flagged_case_including_surface_review"
        assert len(evaluation["case_results"]) == 60
        assert sum(case["expected"] == "no_clash" for case in evaluation["case_results"]) == (40 if mode == "hard" else 25)
        assert len(evaluation["failed_cases"]) == 10
        assert evaluation["assessed_cases"] == 59
        assert evaluation["uncertain_cases"] == 10
        assert any(case["detected"] == "insufficient_data" for case in evaluation["case_results"])
        assert all(case["a"]["guid"] and case["b"]["guid"] for case in evaluation["case_results"])


def test_pilot_sources_are_reproducible_and_use_one_split_family():
    from app.pilot import pilot_bundle

    bundle = pilot_bundle()
    code = "import json; from app.pilot import pilot_bundle; print(json.dumps([f['sha256'] for f in pilot_bundle()['files']]))"
    actual = subprocess.check_output([sys.executable, "-c", code], env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "PYTHONHASHSEED": "17"})
    assert json.loads(actual) == [item["sha256"] for item in bundle["files"]]
    assert len({case["split_group"] for case in bundle["cases"].values()}) == 1


def test_analytic_negative_case_can_be_reviewed_and_exported_separately(workspace):
    from app.pilot import pilot_bundle

    factory, _, _ = workspace
    with factory() as client:
        identifier = project(client)
        reports = [upload(client, identifier, item) for item in pilot_bundle()["files"][:3]]
        run = run_clash(client, reports)
        base = f"/api/projects/{identifier}/runs/{run['id']}"
        reviews = client.get(base + "/reviews", headers=AUTH).json()
        assert len(reviews["cases"]) == 60
        assert all(item["review"]["label"] == "unreviewed" for item in reviews["cases"])
        case = next(item for item in reviews["cases"] if item["expected"] == "no_clash")
        payload = {"label": "no_clash", "reviewer": "Local reviewer", "note": "Checked opening and route in 3D", "expected_revision": 0}
        response = client.post(base + f"/cases/{case['case_id']}/review", json=payload, headers=AUTH)
        assert response.status_code == 200, response.text
        assert client.post(base + f"/cases/{case['case_id']}/review", json=payload, headers=AUTH).status_code == 409
        exported = client.get(base + "/dataset", headers=AUTH).json()
        assert len(exported["cases"]) == 60
        assert exported["reviewed_cases"] == 1
        assert exported["expert_accepted"] is False
        exported_case = next(item for item in exported["cases"] if item["case_id"] == case["case_id"])
        assert exported_case["expected_origin"] == "analytic"
        assert exported_case["review"]["origin"] == "human"
        assert exported["sources"][0]["sha256"]
