import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from app.main import create_app
from app.demo import demo_files
from test_api import AUTH, TOKEN, AccountClient


@pytest.fixture
def workspace(tmp_path):
    uri = os.getenv("BIM_TEST_MONGODB_URI", "mongodb://127.0.0.1:27017")
    mongo = MongoClient(uri, serverSelectionTimeoutMS=1000)
    name = "test_bim_workspace_" + uuid4().hex
    try:
        mongo.admin.command("ping")
    except PyMongoError:
        mongo.close()
        pytest.skip("Local MongoDB is required for project integration tests")
    def client():
        return AccountClient(create_app(api_token=TOKEN, mongo_uri=uri, database_name=name, data_dir=tmp_path), base_url="http://127.0.0.1", mongo_uri=uri, database_name=name)
    try:
        yield client, mongo[name], tmp_path
    finally:
        mongo.drop_database(name)
        mongo.close()


def project(client, name="Research project"):
    response = client.post("/api/projects", json={"name": name}, headers=AUTH)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(client, identifier, item, revision="R01", **extra):
    response = client.post("/api/inspections", files={"file": (item["name"], item["content"].encode())}, data={"discipline": item["discipline"], "project_id": identifier, "logical_source": item["name"], "revision": revision, **extra}, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def run_clash(client, reports):
    response = client.post("/api/inspections/clashes", json={"model_ids": [report["id"] for report in reports if report["kind"] == "ifc"], "coordinates_confirmed": True}, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def test_projects_list_is_authenticated_and_paginated(workspace):
    factory, _, _ = workspace
    with factory() as client:
        identifier = project(client)
        assert client.get("/api/projects").status_code == 401
        response = client.get("/api/projects?limit=1", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["items"][0]["id"] == identifier
        assert response.json()["total"] == 1
        assert client.get("/api/projects?limit=1000", headers=AUTH).status_code == 422


def test_project_sources_and_run_survive_backend_restart(workspace):
    factory, _, directory = workspace
    with factory() as client:
        identifier = project(client)
        reports = [upload(client, identifier, item) for item in demo_files()]
        result = run_clash(client, reports)
        assert result["project_id"] == identifier
        assert result["revision"] == "R01"
        assert len(result["issues"]) == 2
    with factory() as client:
        files = client.get(f"/api/projects/{identifier}/inspections", headers=AUTH).json()
        assert len(files["items"]) == 4
        assert all(item["project_id"] == identifier for item in files["items"])
        history = client.get(f"/api/projects/{identifier}/runs", headers=AUTH).json()
        assert history["items"][0]["id"] == result["id"]
        restored = client.get(f"/api/projects/{identifier}/runs/{result['id']}", headers=AUTH).json()
        assert restored["report"]["parameters"] == result["parameters"]
        assert {item["id"] for item in restored["inspections"]} == {item["id"] for item in reports if item["kind"] == "ifc"}
        assert client.get(reports[-1]["assets"]["drawing"], headers=AUTH).status_code == 200
        assert list((directory / "cache" / "files").glob("*.dxf"))


def test_source_revision_is_immutable_and_same_bytes_are_idempotent(workspace):
    factory, _, _ = workspace
    with factory() as client:
        identifier = project(client)
        item = demo_files()[0]
        first = upload(client, identifier, item)
        same = upload(client, identifier, item)
        assert same["id"] == first["id"]
        changed = item["content"].replace("SYNTHETIC GEOMETRY LAB", "New geometry export")
        response = client.post("/api/inspections", files={"file": (item["name"], changed.encode())}, data={"project_id": identifier, "logical_source": item["name"], "revision": "R01"}, headers=AUTH)
        assert response.status_code == 409
        assert response.json()["detail"] == "source_revision_conflict"
        newer = upload(client, identifier, {**item, "content": changed}, revision="R02")
        assert newer["id"] != first["id"]
        assert client.get(first["report_url"], headers=AUTH).json()["sha256"] == first["sha256"]


def test_review_persists_and_stale_update_cannot_overwrite_it(workspace):
    factory, _, _ = workspace
    with factory() as client:
        identifier = project(client)
        reports = [upload(client, identifier, item) for item in demo_files()[:3]]
        result = run_clash(client, reports)
        issue = result["issues"][0]
        url = f"/api/projects/{identifier}/runs/{result['id']}/issues/{issue['id']}/review"
        payload = {"state": "intentional", "reviewer": "Local reviewer", "note": "Reviewed against design intent", "expected_revision": 0}
        assert client.post(url, json=payload).status_code == 401
        saved = client.post(url, json=payload, headers=AUTH)
        assert saved.status_code == 200, saved.text
        assert saved.json()["review"]["revision"] == 1
        assert client.post(url, json={**payload, "state": "needs_fix"}, headers=AUTH).status_code == 409
        other = project(client, "Another project")
        assert client.post(url.replace(identifier, other), json=payload, headers=AUTH).status_code == 404
    with factory() as client:
        reviews = client.get(f"/api/projects/{identifier}/runs/{result['id']}/reviews", headers=AUTH).json()
        review = next(item["review"] for item in reviews["issues"] if item["issue_id"] == issue["id"])
        assert review["state"] == "intentional"
        assert review["note"] == payload["note"]
        assert client.get(result["report_url"], headers=AUTH).json()["issues"] == result["issues"]


def test_cross_project_mixing_is_rejected_but_source_versions_can_be_combined(workspace):
    factory, _, _ = workspace
    with factory() as client:
        first_project, second_project = project(client), project(client, "Other")
        first = upload(client, first_project, demo_files()[0])
        second = upload(client, second_project, demo_files()[1])
        payload = {"model_ids": [first["id"], second["id"]], "coordinates_confirmed": True}
        assert client.post("/api/inspections/clashes", json=payload, headers=AUTH).status_code == 422
        second = upload(client, first_project, demo_files()[1], revision="R02")
        combined = client.post("/api/inspections/clashes", json={**payload, "model_ids": [first["id"], second["id"]]}, headers=AUTH)
        assert combined.status_code == 200, combined.text
        assert combined.json()["project_id"] == first_project


def test_alignment_cannot_link_different_project_or_revision(workspace):
    factory, _, _ = workspace
    with factory() as client:
        first_project, second_project = project(client), project(client, "Other")
        model = upload(client, first_project, demo_files()[0])
        drawing = upload(client, second_project, demo_files()[3])
        payload = {"model_id": model["id"], "drawing_id": drawing["id"], "project_name": "Research project", "revision": "R01", "storey_guid": model["result"]["storeys"][0]["guid"]}
        assert client.post("/api/inspections/alignments", json=payload, headers=AUTH).status_code == 422
        drawing = upload(client, first_project, demo_files()[3], revision="R02")
        assert client.post("/api/inspections/alignments", json={**payload, "drawing_id": drawing["id"]}, headers=AUTH).status_code == 422


def test_group_key_preserves_source_and_kind_while_grouping_child_witnesses():
    from app.rules import issue_group_key

    first = {"source_id": "ARCH", "guid": "child-1", "canonical_guid": "wall-1"}
    second = {"source_id": "MEP", "guid": "pipe-1", "canonical_guid": "pipe-1"}
    key = issue_group_key(first, second, "intersection")
    assert key == issue_group_key({**first, "guid": "child-2"}, second, "intersection")
    assert key == issue_group_key(second, first, "intersection")
    assert key != issue_group_key(first, second, "clearance")
    assert key != issue_group_key({**first, "source_id": "STR"}, second, "intersection")
