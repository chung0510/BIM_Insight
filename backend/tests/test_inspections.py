import hashlib
import json
import os
import stat
import subprocess
import sys
import urllib.request
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from test_api import AUTH, TOKEN, AccountClient, database_name_for as database_for
from test_ifc_probe import small_ifc


def pdf_bytes(text=True, password=None):
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    if text:
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 50 750 Td (ARCH Level 1 - grid A) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    if password:
        writer.encrypt(password)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def inspection_client(tmp_path, **options):
    from app.main import create_app

    options.setdefault("database_name", database_for(tmp_path))
    return AccountClient(create_app(api_token=TOKEN, data_dir=tmp_path, **options), base_url="http://127.0.0.1", mongo_uri=options.get("mongo_uri", "mongodb://127.0.0.1:27017"), database_name=options["database_name"])


def test_pdf_extracts_page_metadata_and_text_without_modifying_source(tmp_path):
    from app.pdf import inspect_pdf

    source = tmp_path / "drawing.pdf"
    original = pdf_bytes()
    source.write_bytes(original)
    report = inspect_pdf(source)
    assert report["status"] == "completed"
    assert report["page_count"] == 1
    assert report["processed_pages"] == 1
    assert report["pages"][0]["width_mm"] == pytest.approx(209.9, abs=0.2)
    assert "ARCH Level 1" in report["pages"][0]["text_preview"]
    assert source.read_bytes() == original


def test_pdf_without_text_requests_review_without_claiming_it_is_a_scan(tmp_path):
    from app.pdf import inspect_pdf

    source = tmp_path / "blank.pdf"
    source.write_bytes(pdf_bytes(text=False))
    report = inspect_pdf(source)
    assert report["status"] == "partial"
    assert report["text_status"] == "not_detected"
    assert {"code": "text_not_detected"} in report["diagnostics"]


def test_pdf_password_and_broken_file_are_reported_as_failures(tmp_path):
    from app.pdf import inspect_pdf

    source = tmp_path / "locked.pdf"
    source.write_bytes(pdf_bytes(password="private-test-password"))
    report = inspect_pdf(source)
    assert report["status"] == "failed"
    assert report["diagnostics"][0]["code"] == "pdf_password_required"
    source.write_bytes(b"not a pdf")
    report = inspect_pdf(source)
    assert report["status"] == "failed"
    assert report["diagnostics"][0]["code"] == "invalid_pdf"


def test_upload_requires_authentication_before_parsing_body(tmp_path):
    with inspection_client(tmp_path) as client:
        response = client.post("/api/inspections", content=b"malformed", headers={"Content-Type": "multipart/form-data"})
    assert response.status_code == 401
    assert not list(tmp_path.rglob("source.*"))


def test_ifc_upload_runs_real_worker_and_produces_downloadable_report(tmp_path, small_ifc):
    source, guid = small_ifc
    original = source.read_bytes()
    with inspection_client(tmp_path / "app-data") as client:
        response = client.post(
            "/api/inspections", files={"file": ("nhà mẫu.ifc", original, "application/octet-stream")},
            data={"discipline": "ARCH"}, headers=AUTH,
        )
        assert response.status_code == 200, response.text
        report = response.json()
        downloaded = client.get(report["report_url"], headers=AUTH)
        denied = client.get(report["report_url"])
    assert report["status"] == "completed"
    assert report["sha256"] == hashlib.sha256(original).hexdigest()
    assert report["discipline"] == "ARCH"
    assert report["result"]["element_count"] == 1
    assert report["result"]["elements"][0]["guid"] == guid
    assert report["clash_detection"] == "not_run"
    assert downloaded.status_code == 200
    assert downloaded.json() == report
    assert denied.status_code == 401
    assert source.read_bytes() == original
    assert not list((tmp_path / "app-data").rglob("source.*"))


@pytest.mark.parametrize("kind", ["ifc", "pdf", "dxf", "dwg"])
def test_cache_reuses_valid_readonly_file_without_replacing_it(tmp_path, kind):
    from app.inspections import InspectionService
    payload = b"already verified source bytes"
    digest = hashlib.sha256(payload).hexdigest()
    cache = tmp_path / "cache" / ("models" if kind == "ifc" else "files") / f"{digest}.{kind}"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(payload)
    modified = cache.stat().st_mtime_ns
    source = tmp_path / f"upload.{kind}"
    source.write_bytes(payload)
    cache.chmod(stat.S_IREAD)
    try:
        service = InspectionService(tmp_path, 120, 1024)
        service.cache_source(source, kind, digest)
        assert cache.read_bytes() == payload
        assert cache.stat().st_mtime_ns == modified
        assert source.read_bytes() == payload
    finally:
        cache.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_cache_replaces_corrupt_content_instead_of_trusting_filename(tmp_path):
    from app.inspections import InspectionService
    payload = b"verified replacement"
    digest = hashlib.sha256(payload).hexdigest()
    cache = tmp_path / "cache" / "models" / f"{digest}.ifc"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"corrupt bytes with a valid looking filename")
    source = tmp_path / "upload.ifc"
    source.write_bytes(payload)
    InspectionService(tmp_path, 120, 1024).cache_source(source, "ifc", digest)
    assert cache.read_bytes() == payload and not source.exists()


def test_cache_permission_failure_is_controlled_and_does_not_publish_artifacts(tmp_path, small_ifc, monkeypatch):
    import app.inspections as module
    source, _ = small_ifc
    def denied(*args):
        raise PermissionError("private local cache path")
    monkeypatch.setattr(module.os, "replace", denied)
    directory = tmp_path / "app-data"
    with inspection_client(directory) as client:
        response = client.post("/api/inspections", files={"file": ("test.ifc", source.read_bytes())}, headers=AUTH)
    assert response.status_code == 503
    assert response.json() == {"detail": "source_cache_unavailable"}
    assert not list((directory / "reports").glob("*.json"))
    assert not list((directory / "assets").glob("*"))
    assert not list(directory.rglob("source.*"))


def test_ifc_can_be_uploaded_again_when_existing_cache_is_readonly(tmp_path, small_ifc):
    payload = small_ifc[0].read_bytes()
    directory = tmp_path / "app-data"
    digest = hashlib.sha256(payload).hexdigest()
    cache = directory / "cache" / "models" / f"{digest}.ifc"
    with inspection_client(directory) as client:
        first = client.post("/api/inspections", files={"file": ("first.ifc", payload)}, headers=AUTH)
        assert first.status_code == 200 and first.json()["clash_ready"] is True
        modified = cache.stat().st_mtime_ns
        cache.chmod(stat.S_IREAD)
        try:
            repeated = client.post("/api/inspections", files={"file": ("again.ifc", payload)}, headers=AUTH)
            assert repeated.status_code == 200, repeated.text
            assert repeated.json()["clash_ready"] is True
            assert cache.stat().st_mtime_ns == modified
        finally:
            cache.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_pdf_upload_checks_real_file_and_normalizes_unsafe_name(tmp_path):
    with inspection_client(tmp_path) as client:
        response = client.post(
            "/api/inspections", files={"file": ("../../bản vẽ.pdf", pdf_bytes(), "application/pdf")}, headers=AUTH,
        )
    assert response.status_code == 200
    report = response.json()
    assert report["name"] == "bản vẽ.pdf"
    assert report["status"] == "completed"
    assert report["result"]["page_count"] == 1
    assert report["result"]["text_status"] == "detected"
    assert not list(tmp_path.rglob("source.*"))


@pytest.mark.parametrize("name,content,expected", [
    ("model.rvt", b"revit", 422), ("drawing.pdf", b"fake PDF", 422),
    ("model.ifc", b"not IFC", 422), ("empty.pdf", b"", 422),
])
def test_upload_rejects_unsupported_or_mislabeled_inputs(tmp_path, name, content, expected):
    with inspection_client(tmp_path) as client:
        response = client.post("/api/inspections", files={"file": (name, content)}, headers=AUTH)
    assert response.status_code == expected
    assert not list(tmp_path.rglob("source.*"))


def test_upload_size_limit_is_enforced_on_actual_stream(tmp_path):
    with inspection_client(tmp_path, upload_limit_bytes=1024) as client:
        response = client.post("/api/inspections", files={"file": ("drawing.pdf", b"%PDF-" + b"x" * 4096)}, headers=AUTH)
    assert response.status_code == 413
    assert not list(tmp_path.rglob("source.*"))


def test_worker_timeout_is_failure_and_removes_temporary_source(tmp_path):
    with inspection_client(tmp_path, inspection_timeout=0) as client:
        response = client.post("/api/inspections", files={"file": ("drawing.pdf", pdf_bytes())}, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "processing_timeout"
    assert not list(tmp_path.rglob("source.*"))


def test_report_route_rejects_path_traversal(tmp_path):
    with inspection_client(tmp_path) as client:
        response = client.get("/api/inspections/not-a-valid-id/report", headers=AUTH)
    assert response.status_code in {404, 422}


@pytest.mark.integration
def test_desktop_entry_starts_authenticated_api_on_an_ephemeral_port(tmp_path, small_ifc):
    if not os.getenv("BIM_RUN_DESKTOP_TEST"):
        pytest.skip("Set BIM_RUN_DESKTOP_TEST=1 to test a real loopback server")
    executable = os.getenv("BIM_BACKEND_EXECUTABLE")
    from test_api import TEST_DATABASES, TEST_PASSWORD
    database_name = database_for(tmp_path)
    mongo_uri = "mongodb://127.0.0.1:27017"
    TEST_DATABASES.add((mongo_uri, database_name))
    command = [executable] if executable else [sys.executable, "-m", "app"]
    process = subprocess.Popen(
        [*command, "--desktop"], cwd=tmp_path,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        env={**os.environ, "BIM_DATA_DIR": str(tmp_path), "BIM_MONGODB_URI": mongo_uri, "BIM_DATABASE": database_name},
    )
    try:
        connection = json.loads(process.stdout.readline())
        with urllib.request.urlopen(connection["base_url"] + "/api/health", timeout=5) as response:
            assert json.load(response)["capabilities"]["file_inspection"] is True
        request = urllib.request.Request(connection["base_url"] + "/api/inspections/not-an-id/report")
        with pytest.raises(urllib.error.HTTPError) as failure:
            urllib.request.urlopen(request, timeout=5)
        assert failure.value.code == 401
        assert len(connection["token"]) >= 32
        request = urllib.request.Request(connection["base_url"] + "/api/auth/bootstrap", data=json.dumps({"username": "desktoptester", "display_name": "Desktop tester", "password": TEST_PASSWORD}).encode(), headers={"Authorization": "Bearer " + connection["token"], "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            session_token = json.load(response)["session_token"]
        for filename, content, kind in [("ARCH.ifc", small_ifc[0].read_bytes(), "ifc"), ("drawing.pdf", pdf_bytes(), "pdf")]:
            boundary = "BimInsightIntegrationBoundary"
            body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + content + f'\r\n--{boundary}--\r\n'.encode())
            request = urllib.request.Request(connection["base_url"] + "/api/inspections", data=body, headers={
                "Authorization": "Bearer " + connection["token"], "X-BIM-Session": session_token, "Content-Type": f"multipart/form-data; boundary={boundary}",
            })
            with urllib.request.urlopen(request, timeout=30) as response:
                report = json.load(response)
            assert report["kind"] == kind
            assert report["status"] == "completed", report
            assert report["clash_detection"] == "not_run"
        assert not list(tmp_path.rglob("source.*"))
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_worker_memory_limit_is_a_failure(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import psutil

    monkeypatch.setattr(psutil.Process, "memory_info", lambda _self: SimpleNamespace(rss=10 * 1024 ** 3))
    with inspection_client(tmp_path) as client:
        response = client.post("/api/inspections", files={"file": ("drawing.pdf", pdf_bytes())}, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "processing_memory_limit"
    assert not list(tmp_path.rglob("source.*"))


def test_pdf_page_limit_is_exposed_as_partial_coverage(tmp_path):
    from app.pdf import inspect_pdf

    writer = PdfWriter()
    for _ in range(501):
        writer.add_blank_page(width=595, height=842)
    source = tmp_path / "many-pages.pdf"
    with source.open("wb") as handle:
        writer.write(handle)
    report = inspect_pdf(source)
    assert report["status"] == "partial"
    assert report["page_count"] == 501
    assert report["processed_pages"] == 500
    assert {"code": "page_limit", "limit": 500} in report["diagnostics"]


def test_chunked_body_limit_does_not_trust_content_length(tmp_path):
    boundary = "StreamBoundary"
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="drawing.pdf"\r\n\r\n%PDF-'.encode(), b"x" * 80000, f'\r\n--{boundary}--\r\n'.encode()]
    with inspection_client(tmp_path, upload_limit_bytes=1024) as client:
        response = client.post("/api/inspections", content=iter(parts), headers={**AUTH, "Content-Type": f"multipart/form-data; boundary={boundary}"})
    assert response.status_code == 413
    assert not list(tmp_path.rglob("source.*"))


def test_pdf_physical_dimensions_include_user_unit(tmp_path):
    from app.pdf import inspect_pdf

    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    page[NameObject("/UserUnit")] = NumberObject(2)
    source = tmp_path / "scaled.pdf"
    with source.open("wb") as handle:
        writer.write(handle)
    report = inspect_pdf(source)
    assert report["pages"][0]["width_mm"] == pytest.approx(419.81, abs=0.01)
    assert report["pages"][0]["height_mm"] == pytest.approx(594.08, abs=0.01)


def test_abandoned_sessions_are_cleaned_without_touching_live_or_unowned_files(tmp_path):
    import psutil
    from app.inspections import recover_abandoned_sessions

    root = tmp_path / "tmp"
    for name in ["session-dead", "session-live", "session-unknown"]:
        (root / name).mkdir(parents=True)
        (root / name / "source.ifc").write_bytes(b"preserve unless abandoned")
    (root / "session-dead" / "owner.json").write_text(json.dumps({"pid": 2147483647, "created_at": 0}), encoding="utf-8")
    (root / "session-live" / "owner.json").write_text(json.dumps({"pid": os.getpid(), "created_at": psutil.Process().create_time()}), encoding="utf-8")
    recover_abandoned_sessions(tmp_path)
    assert not (root / "session-dead").exists()
    assert (root / "session-live" / "source.ifc").is_file()
    assert (root / "session-unknown" / "source.ifc").is_file()


def test_session_cleanup_cannot_delete_outside_owned_temporary_root(tmp_path):
    from app.inspections import discard_session

    other = tmp_path / "source-project" / "session-not-owned"
    other.mkdir(parents=True)
    (other / "source.ifc").write_bytes(b"original")
    discard_session(tmp_path / "app-data", other)
    assert (other / "source.ifc").read_bytes() == b"original"
