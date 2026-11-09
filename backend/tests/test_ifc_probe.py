import hashlib
from pathlib import Path
import subprocess
import sys

import ifcopenshell
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.unit
import numpy as np
import pytest


@pytest.fixture
def small_ifc(tmp_path):
    model = ifcopenshell.api.project.create_file(version="IFC4")
    ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="Synthetic test")
    length = ifcopenshell.api.unit.add_si_unit(model, unit_type="LENGTHUNIT", prefix="MILLI")
    ifcopenshell.api.unit.assign_unit(model, units=[length])
    context = ifcopenshell.api.context.add_context(model, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        model, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=context
    )
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="Test wall")
    shape = ifcopenshell.api.geometry.add_wall_representation(
        model, context=body, length=4, height=3, thickness=0.2
    )
    ifcopenshell.api.geometry.assign_representation(model, product=wall, representation=shape)
    matrix = np.eye(4)
    matrix[:3, 3] = (10, 20, 0)
    ifcopenshell.api.geometry.edit_object_placement(model, product=wall, matrix=matrix)
    path = tmp_path / "nhà mẫu.ifc"
    model.write(str(path))
    return path, wall.GlobalId


def test_ifc_import_preserves_guid_and_converts_world_coordinates_to_metres(small_ifc):
    from backend.research.ifc_probe import inspect_ifc

    path, guid = small_ifc
    report = inspect_ifc(path)
    assert report["status"] == "completed"
    assert report["source_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert report["project_unit_scale_to_m"] == pytest.approx(0.001)
    assert report["clash_detection"] == "not_run"
    assert report["element_count"] == 1
    element = report["elements"][0]
    assert element["guid"] == guid
    assert element["ifc_type"] == "IfcWall"
    assert element["bounds_m"]["min"] == pytest.approx([10, 20, 0])
    assert element["bounds_m"]["max"] == pytest.approx([14, 20.2, 3])
    assert element["triangle_count"] > 0


def test_missing_geometry_is_reported_as_partial_not_empty_success(small_ifc):
    from backend.research.ifc_probe import inspect_ifc

    path, _ = small_ifc
    model = ifcopenshell.open(str(path))
    missing = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBeam", name="Missing geometry")
    model.write(str(path))
    report = inspect_ifc(path)
    assert report["status"] == "partial"
    assert report["excluded_count"] == 1
    assert {"guid": missing.GlobalId, "code": "missing_representation"} in report["diagnostics"]


def test_broken_ifc_is_reported_as_failure(tmp_path):
    from backend.research.ifc_probe import inspect_ifc

    path = tmp_path / "broken.ifc"
    path.write_text("not an IFC model", encoding="utf-8")
    report = inspect_ifc(path)
    assert report["status"] == "failed"
    assert report["clash_detection"] == "not_run"
    assert report["diagnostics"][0]["code"] == "invalid_ifc"


def test_duplicate_guids_are_excluded_instead_of_becoming_ambiguous_refs(small_ifc):
    from backend.research.ifc_probe import inspect_ifc

    path, guid = small_ifc
    model = ifcopenshell.open(str(path))
    duplicate = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBeam", name="Duplicate")
    duplicate.GlobalId = guid
    model.write(str(path))
    report = inspect_ifc(path)
    assert report["status"] == "partial"
    assert report["element_count"] == 0
    assert report["excluded_count"] == 2
    assert all(item["code"] == "missing_or_duplicate_guid" for item in report["diagnostics"])


def test_parent_geometry_is_accounted_for_without_hiding_missing_children(small_ifc):
    import ifcopenshell.api.aggregate
    from app.ifc import inspect_ifc

    path, guid = small_ifc
    model = ifcopenshell.open(str(path))
    parent = ifcopenshell.api.root.create_entity(model, ifc_class="IfcElementAssembly", name="Assembly")
    ifcopenshell.api.aggregate.assign_object(model, products=[model.by_guid(guid)], relating_object=parent)
    model.write(str(path))
    report = inspect_ifc(path)
    assert report["status"] == "completed"
    assert report["aggregate_count"] == 1
    assert report["excluded_count"] == 0
    missing = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBeam", name="Missing child")
    ifcopenshell.api.aggregate.assign_object(model, products=[missing], relating_object=parent)
    model.write(str(path))
    report = inspect_ifc(path)
    assert report["status"] == "partial"
    assert {"guid": missing.GlobalId, "code": "missing_representation"} in report["diagnostics"]


def test_ifc_viewer_glb_preserves_guid_and_mapping_and_metres(small_ifc, tmp_path):
    import json
    import struct
    from app.ifc import inspect_ifc

    path, guid = small_ifc
    assets = tmp_path / "assets"
    assets.mkdir()
    report = inspect_ifc(path, assets_dir=assets)
    assert report["status"] == "completed"
    glb = (assets / "model.glb").read_bytes()
    assert glb[:4] == b"glTF"
    length, kind = struct.unpack_from("<II", glb, 12)
    assert kind == 0x4E4F534A
    document = json.loads(glb[20:20+length])
    assert any(guid in node.get("name", "") for node in document["nodes"])
    mapping = json.loads((assets / "model.json").read_text(encoding="utf-8"))
    assert mapping["elements"][0]["guid"] == guid
    assert mapping["elements"][0]["bounds_m"]["min"] == pytest.approx([10, 20, 0])
    assert mapping["world_up"] == "Z"


def test_glb_uses_local_vertices_for_large_world_coordinates(small_ifc, tmp_path):
    import json
    import struct
    from app.ifc import inspect_ifc

    path, guid = small_ifc
    model = ifcopenshell.open(str(path))
    matrix = np.eye(4)
    matrix[:3, 3] = [1000000, 2000000, 0]
    ifcopenshell.api.geometry.edit_object_placement(model, product=model.by_guid(guid), matrix=matrix)
    model.write(str(path))
    assets = tmp_path / "assets"
    assets.mkdir()
    report = inspect_ifc(path, assets_dir=assets)
    assert report["elements"][0]["bounds_m"]["min"] == pytest.approx([1000000, 2000000, 0])
    raw = (assets / "model.glb").read_bytes()
    length = struct.unpack_from("<I", raw, 12)[0]
    document = json.loads(raw[20:20+length])
    assert max(max(accessor.get("max", [0])) for accessor in document["accessors"] if accessor["type"] == "VEC3") < 100


def test_ifc_without_declared_length_units_is_not_assumed_metres(small_ifc):
    from app.ifc import inspect_ifc
    path, _ = small_ifc
    model = ifcopenshell.open(str(path))
    model.by_type("IfcProject")[0].UnitsInContext = None
    model.write(str(path))
    report = inspect_ifc(path)
    assert report["status"] == "failed"
    assert {"code": "ifc_units_unknown"} in report["diagnostics"]
    assert report["element_count"] == 0


def test_malformed_ifc_guid_is_excluded_before_gltf_name_sanitization(small_ifc):
    from app.ifc import inspect_ifc
    path, guid = small_ifc
    model = ifcopenshell.open(str(path))
    model.by_guid(guid).GlobalId = "bad.guid"
    model.write(str(path))
    report = inspect_ifc(path)
    assert report["status"] == "partial"
    assert report["element_count"] == 0
    assert report["excluded_count"] == 1
    assert {"guid": "bad.guid", "code": "invalid_guid"} in report["diagnostics"]


@pytest.mark.parametrize("alias", [False, True])
def test_ifc_report_does_not_overwrite_existing_source_or_hardlink(small_ifc, tmp_path, alias):
    source, _ = small_ifc
    original = source.read_bytes()
    destination = tmp_path / ("alias.json" if alias else "STR.ifc")
    if alias:
        destination.hardlink_to(source)
    else:
        destination.write_bytes(original)
    result = subprocess.run(
        [sys.executable, "-m", "backend.research.ifc_probe", str(source), "--output", str(destination)],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, timeout=20,
    )
    assert result.returncode != 0
    assert source.read_bytes() == original
    assert destination.read_bytes() == original
