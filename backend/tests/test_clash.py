import hashlib
import json
from pathlib import Path
from uuid import uuid4

import ifcopenshell
import pytest

from app.ifc import inspect_ifc
from test_ifc_probe import small_ifc


@pytest.fixture
def demo_sources(tmp_path):
    from app.demo import demo_files

    sources = []
    for item in demo_files():
        if not item["name"].endswith(".ifc"):
            continue
        path = tmp_path / item["name"]
        path.write_text(item["content"], encoding="utf-8", newline="")
        assets = tmp_path / item["discipline"]
        assets.mkdir()
        metadata = inspect_ifc(path, assets_dir=assets)
        assert metadata["status"] == "completed", metadata
        sources.append({"id": uuid4().hex, "name": item["name"], "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "path": str(path), "mapping_path": str(assets / "model.json"), "result": metadata, "dataset": "synthetic_clash_v1"})
    assert len(sources) == 3
    return sources


def options(**changes):
    return {"mode": "hard", "tolerance_mm": 1, "clearance_mm": 50, "coordinates_confirmed": True, "shared_references_confirmed": False, **changes}


def add_missing_geometry(source, count=1):
    model = ifcopenshell.open(source['path'])
    for _ in range(count):
        model.create_entity('IfcBeam', GlobalId=ifcopenshell.guid.new(), Name='Missing physical beam')
    model.write(source['path'])
    source['sha256'] = hashlib.sha256(Path(source['path']).read_bytes()).hexdigest()
    source['result'] = inspect_ifc(Path(source['path']))
    mapping = json.loads(Path(source['mapping_path']).read_text(encoding='utf-8'))
    mapping['source_sha256'] = source['sha256']
    Path(source['mapping_path']).write_text(json.dumps(mapping), encoding='utf-8')


def test_demo_hard_clashes_are_measured_geometry_not_bbox(demo_sources):
    from app.clash import check_clashes

    result = check_clashes(demo_sources, options())
    assert result["status"] == "completed", result
    assert result["clash_detection"] == "completed"
    assert len(result["issues"]) == 2
    assert {item["case_id"] for item in result["issues"]} == {"crossing", "contained"}
    assert all(item["kind"] == "intersection" and item["distance_m"] > 0 for item in result["issues"])
    assert all(len(item["point_m"]) == 3 for item in result["issues"])
    assert all(item["a"]["source_id"] != item["b"]["source_id"] for item in result["issues"])
    assert result["coverage"]["candidate_pairs"] > len(result["issues"])
    assert result["evaluation"]["precision"] == 1
    assert result["evaluation"]["recall"] == 1
    assert result["evaluation"]["scope"] == "synthetic_only"
    assert result["coverage"]["routing_elements"] > 0
    assert all("quy tắc" not in item["recommendation"] and len(item["recommendation"]) > 30 for item in result["issues"])


def test_clearance_40mm_is_not_mislabeled_as_penetration(demo_sources):
    from app.clash import check_clashes

    result = check_clashes(demo_sources, options(mode="clearance"))
    gap = [item for item in result["issues"] if item["case_id"] == "gap40"]
    assert len(gap) == 1, result
    assert gap[0]["kind"] == "clearance"
    assert gap[0]["distance_m"] == pytest.approx(0.04, abs=0.001)
    assert gap[0]["required_clearance_m"] == pytest.approx(0.05)
    assert {item["case_id"] for item in result["issues"]} == {"crossing", "contained", "gap40", "touch"}


def test_valid_opening_and_touch_do_not_become_hard_clashes(demo_sources):
    from app.clash import check_clashes

    result = check_clashes(demo_sources, options())
    assert not {"opening", "touch", "bbox_only"} & {item["case_id"] for item in result["issues"]}
    model = ifcopenshell.open(demo_sources[0]["path"])
    assert len(model.by_type("IfcRelVoidsElement")) == 1


def test_clearance_representation_does_not_fill_a_physical_opening(demo_sources, tmp_path):
    import ifcopenshell.api.context
    import ifcopenshell.api.geometry
    from app.clash import check_clashes

    source = demo_sources[0]
    model = ifcopenshell.open(source["path"])
    wall = model.by_type("IfcWall")[0]
    wall_guid = wall.GlobalId
    parent = next(item for item in model.by_type("IfcGeometricRepresentationContext") if not item.is_a("IfcGeometricRepresentationSubContext"))
    context = ifcopenshell.api.context.add_context(model, context_type="Model", context_identifier="Clearance", target_view="MODEL_VIEW", parent=parent)
    clearance = ifcopenshell.api.geometry.add_wall_representation(model, context=context, length=4, height=3, thickness=.4)
    clearance.RepresentationIdentifier = "Clearance"
    wall.Representation.Representations = (*wall.Representation.Representations, clearance)
    model.write(source["path"])
    assets = tmp_path / "clearance-representation"
    assets.mkdir()
    source.update(result=inspect_ifc(Path(source["path"]), assets_dir=assets), mapping_path=str(assets / "model.json"), sha256=hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest())
    result = check_clashes(demo_sources, options())
    assert result["status"] == "completed", result["diagnostics"]
    assert len(result["issues"]) == 2
    assert all(wall_guid not in {issue["a"]["guid"], issue["b"]["guid"]} for issue in result["issues"])


def test_multiple_opening_bodies_cut_the_same_holes_in_import_and_clash(demo_sources, tmp_path):
    import ifcopenshell.api.geometry
    import ifcopenshell.api.root
    from app.clash import check_clashes

    arch = demo_sources[0]
    model = ifcopenshell.open(arch["path"])
    opening = model.by_type("IfcOpeningElement")[0]
    body = opening.Representation.Representations[0]
    extra = ifcopenshell.api.geometry.add_wall_representation(model, context=body.ContextOfItems, length=.4, height=.6, thickness=.6)
    extra.Items[0].Position.Location.Coordinates = (-1000., 0., 0.)
    opening.Representation.Representations = (body, extra)
    model.write(arch["path"])

    mep = demo_sources[2]
    model = ifcopenshell.open(mep["path"])
    existing = next(product for product in model.by_type("IfcPipeSegment") if product.Tag == "opening")
    probe = ifcopenshell.api.root.create_entity(model, ifc_class="IfcPipeSegment", name="Probe in second opening")
    probe.Representation = existing.Representation
    matrix = ifcopenshell.util.placement.get_local_placement(existing.ObjectPlacement)
    matrix[0, 3] -= 1000
    ifcopenshell.api.geometry.edit_object_placement(model, product=probe, matrix=matrix, is_si=False)
    probe_guid = probe.GlobalId
    model.write(mep["path"])
    for index, source in enumerate([arch, mep]):
        assets = tmp_path / f"multiple-opening-{index}"
        assets.mkdir()
        source.update(result=inspect_ifc(Path(source["path"]), assets_dir=assets), mapping_path=str(assets / "model.json"), sha256=hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest())
    result = check_clashes(demo_sources, options())
    assert result["status"] == "completed", result["diagnostics"]
    assert all(probe_guid not in {issue["a"]["guid"], issue["b"]["guid"]} for issue in result["issues"])


def test_clash_hash_mismatch_is_failure_not_empty_success(demo_sources):
    from app.clash import check_clashes

    Path(demo_sources[0]["path"]).write_bytes(b"tampered source")
    result = check_clashes(demo_sources, options())
    assert result["status"] == "failed"
    assert result["verdict"] == "unavailable"
    assert result["diagnostics"][0]["code"] == "clash_source_hash_mismatch"


def test_missing_geometry_prevents_complete_clear_verdict(demo_sources):
    from app.clash import check_clashes

    add_missing_geometry(demo_sources[0])
    result = check_clashes(demo_sources, options())
    assert result["status"] == "partial"
    assert result["verdict"] == "incomplete"
    assert result["coverage"]["missing_geometry"] == 1


def test_source_frame_must_be_explicitly_confirmed(demo_sources):
    from app.clash import check_clashes

    result = check_clashes(demo_sources, options(coordinates_confirmed=False))
    assert result["status"] == "failed"
    assert result["verdict"] == "unavailable"


def test_changed_demo_rule_is_not_scored_as_the_locked_benchmark(demo_sources):
    from app.clash import check_clashes

    result = check_clashes(demo_sources, options(tolerance_mm=2))
    assert result["evaluation"] is None


def test_geometry_limit_fails_instead_of_silently_omitting_elements(demo_sources, monkeypatch):
    import app.clash as engine

    monkeypatch.setattr(engine, "MAX_ELEMENTS", 1)
    result = engine.check_clashes(demo_sources, options())
    assert result["status"] == "failed"
    assert result["verdict"] == "unavailable"
    assert result["diagnostics"][-1]["code"] == "clash_scope_limit"


def test_result_limit_keeps_partial_findings_and_does_not_claim_full_coverage(demo_sources, monkeypatch):
    import app.clash as engine

    monkeypatch.setattr(engine, "MAX_ISSUES", 1)
    result = engine.check_clashes(demo_sources, options())
    assert len(result["issues"]) == 1
    assert result["status"] == "partial"
    assert result["verdict"] == "incomplete"
    assert {"code": "clash_issue_limit", "limit": 1} in result["diagnostics"]
    assert result["evaluation"] is None


def test_open_and_degenerate_meshes_are_not_treated_as_closed_solids():
    import numpy as np
    from app.clash import closed_mesh

    vertices = np.array([[0., 0, 0], [1., 0, 0], [0., 1, 0], [0., 0, 1.]])
    faces = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]])
    assert closed_mesh(vertices, faces)
    assert not closed_mesh(vertices, faces[:3])
    assert not closed_mesh(vertices * 0, faces)


def test_mixed_millimetre_and_metre_models_give_the_same_clearance(demo_sources, tmp_path):
    from ifcopenshell.util.unit import convert_file_length_units
    from app.clash import check_clashes

    baseline = check_clashes(demo_sources, options(mode="clearance"))
    source = demo_sources[2]
    converted = convert_file_length_units(ifcopenshell.open(source["path"]), "METER")
    converted.write(source["path"])
    assets = tmp_path / "metre-assets"
    assets.mkdir()
    source.update(result=inspect_ifc(Path(source["path"]), assets_dir=assets), mapping_path=str(assets / "model.json"), sha256=hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest())
    result = check_clashes(demo_sources, options(mode="clearance"))
    assert result["status"] == "completed", result
    cached = check_clashes(demo_sources, options(mode="clearance"), cache_dir=tmp_path / "precise-cache")
    assert cached["status"] == "completed", cached
    def pair(item):
        return tuple(sorted([item["a"]["guid"], item["b"]["guid"]]))
    assert {pair(item) for item in result["issues"]} == {pair(item) for item in baseline["issues"]}
    expected = {pair(item): item["distance_m"] for item in baseline["issues"]}
    assert {pair(item) for item in cached["issues"]} == set(expected)
    for item in [*result["issues"], *cached["issues"]]:
        assert item["distance_m"] == pytest.approx(expected[pair(item)], abs=.001)


def test_shared_references_require_explicit_confirmation(demo_sources, tmp_path):
    from app.clash import check_clashes

    source = demo_sources[1]
    duplicate = ifcopenshell.open(source["path"])
    duplicate.by_type("IfcProject")[0].Name = "A different export of shared reference objects"
    path = tmp_path / "reference-copy.ifc"
    duplicate.write(str(path))
    assets = tmp_path / "reference-assets"
    assets.mkdir()
    copy = {**source, "id": uuid4().hex, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "mapping_path": str(assets / "model.json"), "result": inspect_ifc(path, assets_dir=assets)}
    uncertain = check_clashes([source, copy], options())
    assert uncertain["status"] == "partial"
    assert uncertain["verdict"] == "incomplete"
    assert any(item["code"] == "clash_reference_ambiguous" for item in uncertain["diagnostics"])
    confirmed = check_clashes([source, copy], options(shared_references_confirmed=True))
    assert confirmed["status"] == "completed", confirmed
    assert confirmed["coverage"]["shared_reference_pairs"] == 5
    assert confirmed["issues"] == []


def test_coincident_solids_with_different_guids_are_not_reported_clear(demo_sources, tmp_path):
    from app.clash import check_clashes

    source = demo_sources[1]
    duplicate = ifcopenshell.open(source["path"])
    for product in duplicate.by_type("IfcBeam"):
        product.GlobalId = ifcopenshell.guid.new()
    path = tmp_path / "coincident.ifc"
    duplicate.write(str(path))
    assets = tmp_path / "coincident-assets"
    assets.mkdir()
    copy = {**source, "id": uuid4().hex, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "mapping_path": str(assets / "model.json"), "result": inspect_ifc(path, assets_dir=assets)}
    result = check_clashes([source, copy], options())
    assert result["verdict"] != "clear_in_scope", result
    assert len(result["issues"]) >= 5


def test_nested_parts_resolve_to_the_same_shared_reference(demo_sources, tmp_path):
    from app.clash import check_clashes
    from app.rules import canonical_reference

    source = demo_sources[1]
    model = ifcopenshell.open(source["path"])
    parent = model.by_type("IfcBeam")[0]
    copy_path = tmp_path / "nested-reference-copy.ifc"
    model.write(str(copy_path))
    child = model.create_entity("IfcBuildingElementPart", GlobalId=ifcopenshell.guid.new(), Name="Nested beam part", ObjectPlacement=parent.ObjectPlacement, Representation=parent.Representation)
    model.create_entity("IfcRelNests", GlobalId=ifcopenshell.guid.new(), RelatingObject=parent, RelatedObjects=(child,))
    assert canonical_reference(child) == (parent.GlobalId, "IfcBeam")
    model.write(source["path"])
    sources = []
    for index, path in enumerate([Path(source["path"]), copy_path]):
        assets = tmp_path / f"nested-assets-{index}"
        assets.mkdir()
        sources.append({**source, "id": uuid4().hex, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "mapping_path": str(assets / "model.json"), "result": inspect_ifc(path, assets_dir=assets)})
    result = check_clashes(sources, options(shared_references_confirmed=True))
    assert result["status"] == "completed", result
    assert result["issues"] == []
    assert result["coverage"]["shared_reference_pairs"] == 6


def test_ifc_cache_is_private_and_is_retained_for_subsequent_clash(tmp_path, small_ifc):
    from test_inspections import inspection_client
    from test_api import AUTH

    original = small_ifc[0].read_bytes()
    with inspection_client(tmp_path) as client:
        response = client.post("/api/inspections", files={"file": ("ARCH.ifc", original)}, headers=AUTH)
        report = response.json()
        assert report["clash_ready"] is True
        cached = tmp_path / "cache" / "models" / f"{report['sha256']}.ifc"
        assert cached.read_bytes() == original
        assert client.get(f"/api/inspections/{report['id']}/assets/{cached.name}", headers=AUTH).status_code == 404
    assert not list((tmp_path / "tmp").rglob("source.*"))


def test_offline_demo_fixtures_have_distinct_sources():
    from app.demo import DATASET, dataset_bundle
    result = dataset_bundle(DATASET)
    assert result["dataset"] == "synthetic_clash_v1"
    assert len(result["files"]) == 4
    assert len({item["sha256"] for item in result["files"]}) == 4


def test_demo_fingerprints_are_reproducible_across_processes():
    import difflib
    import os
    import subprocess
    import sys
    from app.demo import demo_files

    expected = demo_files()
    code = "import json; from app.demo import demo_files; print(json.dumps(demo_files()))"
    for seed in ["0", "1", "17"]:
        actual = subprocess.check_output([sys.executable, "-c", code], env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]), "PYTHONHASHSEED": seed})
        for left, right in zip(expected, json.loads(actual)):
            assert left["sha256"] == right["sha256"], "".join(difflib.unified_diff(left["content"].splitlines(True), right["content"].splitlines(True)))


def test_represented_child_is_not_discarded_when_parent_body_is_elsewhere(demo_sources, tmp_path):
    from app.clash import check_clashes

    arch = ifcopenshell.open(demo_sources[0]["path"])
    structural = ifcopenshell.open(demo_sources[1]["path"])
    beam = next(p for p in structural.by_type("IfcBeam") if p.Tag == "crossing")
    parent = arch.by_type("IfcWall")[0]
    child = arch.create_entity("IfcBuildingElementPart", GlobalId=ifcopenshell.guid.new(), Name="Child with additional geometry", ObjectPlacement=arch.add(beam.ObjectPlacement), Representation=arch.add(beam.Representation))
    arch.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(), RelatingObject=parent, RelatedObjects=(child,))
    arch.write(demo_sources[0]["path"])
    assets = tmp_path / "changed-assets"
    assets.mkdir()
    demo_sources[0]["result"] = inspect_ifc(Path(demo_sources[0]["path"]), assets_dir=assets)
    demo_sources[0]["mapping_path"] = str(assets / "model.json")
    demo_sources[0]["sha256"] = hashlib.sha256(Path(demo_sources[0]["path"]).read_bytes()).hexdigest()
    result = check_clashes(demo_sources, options())
    assert any(child.GlobalId in {issue["a"]["guid"], issue["b"]["guid"]} for issue in result["issues"])


def test_clash_api_runs_isolated_worker_and_persists_authenticated_report(tmp_path):
    from app.demo import demo_files
    from test_inspections import inspection_client
    from test_api import AUTH

    with inspection_client(tmp_path) as client:
        identifiers = []
        for item in demo_files():
            if not item["name"].endswith(".ifc"):
                continue
            response = client.post("/api/inspections", files={"file": (item["name"], item["content"].encode())}, data={"discipline": item["discipline"]}, headers=AUTH)
            report = response.json()
            assert report["dataset"] == "synthetic_clash_v1"
            identifiers.append(report["id"])
        payload = {"model_ids": identifiers, **options()}
        assert client.post("/api/inspections/clashes", json=payload).status_code == 401
        assert client.post("/api/inspections/clashes", json={**payload, "coordinates_confirmed": False}, headers=AUTH).status_code == 422
        response = client.post("/api/inspections/clashes", json=payload, headers=AUTH)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "completed", result
        assert len(result["issues"]) == 2
        assert result["dataset"] == "synthetic_clash_v1"
        assert client.get(result["report_url"]).status_code == 401
        assert client.get(result["report_url"], headers=AUTH).json() == result
        assert client.post("/api/inspections/clashes", json={**payload, "model_ids": [identifiers[0]] * 2}, headers=AUTH).status_code == 422
        assert client.post("/api/inspections/clashes", json={**payload, "model_ids": ["../../private", identifiers[0]]}, headers=AUTH).status_code == 422
        assert client.post("/api/inspections/clashes", json={**payload, "path": "C:/private.ifc"}, headers=AUTH).status_code == 422
        assert client.post("/api/inspections/clashes", content=b" " * 70000, headers={**AUTH, "content-type": "application/json"}).status_code == 413
    assert not list((tmp_path / "tmp").rglob("source.*"))


def test_clash_api_rejects_duplicate_bytes_and_mixed_synthetic_sources(tmp_path):
    from app.demo import demo_files
    from test_inspections import inspection_client
    from test_api import AUTH

    data = demo_files()[0]["content"].encode()
    with inspection_client(tmp_path) as client:
        def upload(content):
            return client.post("/api/inspections", files={"file": ("ARCH.ifc", content)}, headers=AUTH).json()["id"]

        first, duplicate = upload(data), upload(data)
        response = client.post("/api/inspections/clashes", json={"model_ids": [first, duplicate], **options()}, headers=AUTH)
        assert response.status_code == 422
        assert response.json()["detail"] == "clash_duplicate_source"
        different = upload(data.replace(b"SYNTHETIC GEOMETRY LAB", b"DIFFERENT EXPORT"))
        response = client.post("/api/inspections/clashes", json={"model_ids": [first, different], **options()}, headers=AUTH)
        assert response.status_code == 422
        assert response.json()["detail"] == "clash_mixed_datasets"


def test_timed_out_clash_is_saved_as_failed_and_cleans_worker_files(tmp_path):
    from app.demo import demo_files
    from test_inspections import inspection_client
    from test_api import AUTH

    with inspection_client(tmp_path) as client:
        ids = [client.post("/api/inspections", files={"file": (item["name"], item["content"].encode())}, headers=AUTH).json()["id"] for item in demo_files()[:2]]
    with inspection_client(tmp_path, inspection_timeout=0) as client:
        response = client.post("/api/inspections/clashes", json={"model_ids": ids, **options()}, headers=AUTH)
        result = response.json()
        assert result["status"] == "failed", result
        assert result["verdict"] == "unavailable"
        assert result["issues"] == []
        assert result["diagnostics"][0]["code"] == "processing_timeout"
        assert client.get(result["report_url"], headers=AUTH).json()["status"] == "failed"
    assert not list((tmp_path / "tmp").rglob("config.json"))
