import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from test_api import AUTH
from test_inspections import inspection_client, pdf_bytes


def test_upload_requires_persistent_project_before_creating_work(tmp_path):
    from fastapi.testclient import TestClient

    with inspection_client(tmp_path) as client:
        response = TestClient.post(client, "/api/inspections", headers=AUTH,
                                   files={"file": ("drawing.pdf", pdf_bytes())})
    assert response.status_code == 422
    assert response.json()["detail"] == "project_required"
    assert not list((tmp_path / "reports").glob("*.json"))
    assert not list(tmp_path.rglob("source.*"))


def test_production_does_not_offer_generated_demo_files(tmp_path):
    with inspection_client(tmp_path) as client:
        assert client.get("/api/inspections/demo", headers=AUTH).status_code == 404


def test_converter_bounds_process_and_keeps_original(tmp_path, monkeypatch):
    import app.dwg as dwg

    source = tmp_path / "input" / "source.dwg"
    source.parent.mkdir()
    original = b"AC1032-real-input-placeholder-for-unit-test"
    source.write_bytes(original)
    assets = tmp_path / "assets"
    assets.mkdir()
    executable = tmp_path / "ODAFileConverter.exe"
    executable.write_bytes(b"unit-test-only")
    identity = {"path": str(executable), "version": "27.10.0"}
    monkeypatch.setenv("MONGODB_URI", "must-not-reach-converter")
    monkeypatch.setattr(dwg, "converter_identity", lambda path: identity)

    def run(command, **options):
        assert command == [str(executable), str(source.parent), str(assets), "ACAD2018", "DXF", "0", "0", "source.dwg"]
        assert options["timeout"] == 600 and options["shell"] is False
        assert "MONGODB_URI" not in options["env"]
        assert options["stdout"] == subprocess.DEVNULL
        (assets / "source.dxf").write_bytes(b"0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nEOF\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(dwg.subprocess, "run", run)
    conversion = dwg.convert_dwg(source, assets, executable)
    assert source.read_bytes() == original
    assert (assets / "converted.dxf").is_file()
    assert not (assets / "source.dxf").exists()
    assert conversion["output_sha256"] == hashlib.sha256((assets / "converted.dxf").read_bytes()).hexdigest()
    assert conversion["converter"] == "ODA File Converter"


@pytest.mark.parametrize("failure", ["missing", "timeout", "exit", "output", "header", "size"])
def test_converter_fails_explicitly_instead_of_accepting_header_only(tmp_path, monkeypatch, failure):
    import app.dwg as dwg

    source = tmp_path / "source.dwg"
    source.write_bytes(b"AC1032")
    assets = tmp_path / "assets"
    assets.mkdir()
    executable = tmp_path / "ODAFileConverter.exe"
    monkeypatch.setattr(dwg, "converter_identity", lambda path: None if failure == "missing" else {"path": str(executable), "version": "27.10.0"})

    def run(command, **options):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 90)
        if failure in {"header", "size"}:
            with (assets / "source.dxf").open("wb") as output:
                output.write(b"invalid" if failure == "header" else b"0\nSECTION\n")
                if failure == "size":
                    output.truncate(256 * 1024 * 1024 + 1)
        return subprocess.CompletedProcess(command, 1 if failure == "exit" else 0)

    monkeypatch.setattr(dwg.subprocess, "run", run)
    with pytest.raises(dwg.ConversionError) as error:
        dwg.convert_dwg(source, assets, executable)
    assert error.value.code == ("dwg_converter_not_installed" if failure == "missing" else "dwg_conversion_timeout" if failure == "timeout" else "dwg_conversion_failed")


def test_derived_dxf_is_managed_and_backed_up(tmp_path):
    from app.storage import MANAGED
    from app.schemas import ASSET_FILES

    assert ASSET_FILES["converted.dxf"] == "converted_dxf"
    assert MANAGED.fullmatch("assets/" + "a" * 32 + "/converted.dxf")
    assert not MANAGED.fullmatch("assets/" + "a" * 32 + "/../converted.dxf")


def test_upload_persists_dwg_dxf_and_preview_for_project_backup(tmp_path, monkeypatch):
    from app.inspections import InspectionService
    from app.projects import ProjectStore
    from pymongo import MongoClient

    converted = b"0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nEOF\n"

    async def worker(service, request, arguments, output, memory_gb, *, progress=None):
        assert "--dwg-converter" in arguments
        assets = output.parent / "assets"
        assets.mkdir()
        (assets / "converted.dxf").write_bytes(converted)
        (assets / "drawing.json").write_text('{"paths":[]}', encoding="utf-8")
        return {"status": "completed", "preview_available": True, "diagnostics": [],
                "conversion": {"output_sha256": hashlib.sha256(converted).hexdigest()}}, None

    monkeypatch.setattr("app.inspections.discover_converter", lambda: {"path": "trusted-unit-test.exe"})
    monkeypatch.setattr(InspectionService, "run_job", worker)
    original = b"AC1032" + b"\0" * 100
    with inspection_client(tmp_path) as client:
        report = client.post("/api/inspections", files={"file": ("floor.dwg", original)}, headers=AUTH).json()
        assert report["status"] == "completed"
        downloaded = client.get(report["assets"]["converted_dxf"], headers=AUTH)
        assert downloaded.status_code == 200 and downloaded.content == converted
        assert downloaded.headers["content-type"] == "application/dxf"
        assert client.get(report["assets"]["converted_dxf"]).status_code == 401
        with MongoClient(client.mongo_uri) as mongo:
            paths = ProjectStore(mongo[client.database_name], tmp_path).backup_paths(report["project_id"])
        assert f"assets/{report['id']}/converted.dxf" in paths
        assert f"assets/{report['id']}/drawing.json" in paths
        assert f"cache/files/{report['sha256']}.dwg" in paths
        assert (tmp_path / f"cache/files/{report['sha256']}.dwg").read_bytes() == original


def test_unsigned_converter_is_never_executed(tmp_path):
    from app.dwg import converter_identity

    executable = tmp_path / "ODAFileConverter.exe"
    executable.write_bytes(b"not a signed program")
    assert converter_identity(executable) is None
