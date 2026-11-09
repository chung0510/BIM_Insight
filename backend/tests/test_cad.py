import hashlib
import json

import ezdxf
import pytest

from test_inspections import inspection_client
from test_api import AUTH


@pytest.fixture
def cad_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    doc = ezdxf.new("R2018", units=4)
    doc.layers.add("A-WALL", color=7)
    doc.layers.add("S-GRID", color=1)
    doc.layers.add("LABELS", color=2)
    doc.modelspace().add_line((1000, 2000), (5000, 2000), dxfattribs={"layer": "A-WALL"})
    doc.modelspace().add_line((1000, 0), (1000, 8000), dxfattribs={"layer": "S-GRID"})
    doc.modelspace().add_line((0, 2000), (8000, 2000), dxfattribs={"layer": "S-GRID"})
    doc.modelspace().add_mtext(r"T\U+1EA6NG 1 <script>alert(1)</script>", dxfattribs={"layer": "LABELS"})
    block = doc.blocks.new("DOOR")
    block.add_circle((0, 0), 100, dxfattribs={"layer": "A-WALL"})
    doc.modelspace().add_blockref("DOOR", (2000, 2000), dxfattribs={"layer": "A-WALL"})
    path = tmp_path / "floor.dxf"
    doc.saveas(path)
    return path


def test_cad_reads_units_blocks_layers_and_safe_preview_without_changing_source(cad_file, tmp_path):
    from app.cad import inspect_dxf

    original = cad_file.read_bytes()
    assets = tmp_path / "assets"
    assets.mkdir()
    report = inspect_dxf(cad_file, assets)
    assert report["status"] == "completed", report
    assert report["clash_detection"] == "not_run"
    assert report["unit_scale_to_m"] == pytest.approx(0.001)
    assert report["modelspace_count"] == 5
    assert report["entity_types"]["INSERT"] == 1
    assert {p["name"] for p in report["layers"]} >= {"A-WALL", "S-GRID"}
    assert len(report["grid_lines"]) == 2
    assert report["grid_lines"][0]["start_m"] == pytest.approx([1, 0, 0])
    assert any("TẦNG 1" in text for text in report["text_sample"])
    drawing = json.loads((assets / "drawing.json").read_text(encoding="utf-8"))
    assert len(drawing["view_box"]) == 4
    assert {p["layer"] for p in drawing["paths"]} >= {"A-WALL", "S-GRID", "LABELS"}
    assert all(set(p) <= {"d", "layer", "fill", "stroke", "stroke_width", "fill_opacity", "stroke_opacity"} for p in drawing["paths"])
    assert "<script>" not in json.dumps(drawing)
    assert cad_file.read_bytes() == original


def test_cad_unitless_and_xref_remain_partial_and_external_file_is_not_opened(cad_file, tmp_path):
    from app.cad import inspect_dxf

    doc = ezdxf.readfile(cad_file)
    doc.units = 0
    block = doc.blocks.new("EXTERNAL")
    block.block.dxf.flags = 4
    block.block.dxf.xref_path = r"\\untrusted-server\private\missing.dwg"
    doc.modelspace().add_blockref("EXTERNAL", (0, 0))
    doc.saveas(cad_file)
    assets = tmp_path / "assets"
    assets.mkdir()
    report = inspect_dxf(cad_file, assets)
    assert report["status"] == "partial"
    assert report["unit_scale_to_m"] is None
    assert {p["code"] for p in report["diagnostics"]} >= {"cad_units_unknown", "cad_xref_unresolved"}
    assert len(report["external_references"]) == 1


def test_broken_cad_is_not_success(tmp_path):
    from app.cad import inspect_dxf

    path = tmp_path / "broken.dxf"
    path.write_bytes(b"not a drawing")
    report = inspect_dxf(path, tmp_path)
    assert report["status"] == "failed"
    assert report["diagnostics"][0]["code"] == "invalid_dxf"
    assert not (tmp_path / "drawing.json").exists()


def test_preview_affine_projects_source_points_to_the_same_svg_path():
    import re
    from app.cad import drawing_preview

    doc = ezdxf.new("R2018", units=4)
    doc.modelspace().add_line((1000, 2000), (5000, 3000))
    preview = drawing_preview(doc)
    a, b, c, d, tx, ty = preview["source_to_svg"]
    coordinates = [float(n) for n in re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", preview["paths"][0]["d"])]
    assert len(coordinates) == 4
    if " l " in preview["paths"][0]["d"]:
        coordinates[2] += coordinates[0]
        coordinates[3] += coordinates[1]
    for offset, (x, y) in [(0, (1000, 2000)), (2, (5000, 3000))]:
        assert coordinates[offset:offset + 2] == pytest.approx([a * x + c * y + tx, b * x + d * y + ty], abs=2)


def test_cad_upload_runs_worker_and_asset_is_authenticated(cad_file, tmp_path):
    original = cad_file.read_bytes()
    with inspection_client(tmp_path / "app-data") as client:
        response = client.post("/api/inspections", files={"file": ("floor.dxf", original)}, headers=AUTH)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["kind"] == "dxf" and report["status"] == "completed", report
        assert report["sha256"] == hashlib.sha256(original).hexdigest()
        asset = client.get(report["assets"]["drawing"], headers=AUTH)
        assert asset.status_code == 200
        assert len(asset.json()["paths"]) > 0
        assert client.get(report["assets"]["drawing"]).status_code == 401
        assert client.get(f"/api/inspections/{report['id']}/assets/owner.json", headers=AUTH).status_code == 404
    assert not list((tmp_path / "app-data" / "tmp").rglob("source.*"))
    assert cad_file.read_bytes() == original


def test_dwg_without_converter_is_blocked_explicitly(tmp_path, monkeypatch):
    monkeypatch.setattr("app.inspections.discover_converter", lambda: None)
    with inspection_client(tmp_path) as client:
        response = client.post("/api/inspections", files={"file": ("floor.dwg", b"AC1032" + b"\0" * 100)}, headers=AUTH)
    assert response.status_code == 503
    assert response.json()["detail"] == "dwg_converter_not_installed"
    assert not list((tmp_path / "reports").glob("*.json"))


def test_preview_limit_is_reported_instead_of_silent_coverage_loss(cad_file, tmp_path, monkeypatch):
    from app import cad

    monkeypatch.setattr(cad, "MAX_PREVIEW_BYTES", 100)
    assets = tmp_path / "assets"
    assets.mkdir()
    report = cad.inspect_dxf(cad_file, assets)
    assert report["status"] == "partial"
    assert {"code": "cad_preview_limit"} in report["diagnostics"]
    assert not (assets / "drawing.json").exists()


def test_external_image_resolver_is_never_called(cad_file, tmp_path, monkeypatch):
    from app.cad import inspect_dxf
    from ezdxf.addons.drawing import frontend

    doc = ezdxf.readfile(cad_file)
    image = doc.add_image_def(filename="untrusted-external.png", size_in_pixel=(10, 10))
    doc.modelspace().add_image(image, insert=(0, 0), size_in_units=(100, 100))
    doc.saveas(cad_file)
    calls = []
    def reject_external_access(*args):
        calls.append(args)
        raise AssertionError("External image lookup must be disabled")
    monkeypatch.setattr(frontend, "_find_image_path", reject_external_access)
    assets = tmp_path / "assets"
    assets.mkdir()
    report = inspect_dxf(cad_file, assets)
    assert not calls
    assert report["status"] == "partial"
    assert report["unsupported_types"]["IMAGE"] == 1
