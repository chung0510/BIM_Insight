"""Delete app-owned project artifacts; original inputs, settings and accounts are outside this scope."""
import json
import re
import shutil
from contextlib import contextmanager
from threading import Event, Thread
from uuid import uuid4

from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.limits import MAX_REPORT_BYTES
from app.schemas import ASSET_FILES
from app.storage import MANAGED


@contextmanager
def project_data_lock(database):
    collection = database.project_data_locks
    token = uuid4().hex
    stop, lost = Event(), Event()
    deadline = {"$add": ["$$NOW", 120000]}
    expired = {"$lte": [{"$ifNull": ["$expires_at", "$$NOW"]}, "$$NOW"]}
    try:
        # MongoDB's clock keeps devices with different system times from stealing an active lease.
        owner = collection.find_one_and_update({"_id": "storage-and-delete"}, [{"$set": {"token": {"$cond": [expired, token, "$token"]}, "expires_at": {"$cond": [expired, deadline, "$expires_at"]}}}], upsert=True, return_document=ReturnDocument.AFTER)
    except DuplicateKeyError:
        raise HTTPException(409, "project_busy") from None
    if owner["token"] != token:
        raise HTTPException(409, "project_busy")
    def renew():
        while not stop.wait(10):
            try:
                if collection.update_one({"_id": "storage-and-delete", "token": token}, [{"$set": {"expires_at": deadline}}]).matched_count:
                    continue
            except PyMongoError:
                pass
            lost.set(); return
    def check():
        if lost.is_set():
            raise HTTPException(503, "database_unavailable")
        if not collection.find_one({"_id": "storage-and-delete", "token": token, "$expr": {"$gt": ["$expires_at", "$$NOW"]}}):
            raise HTTPException(409, "project_busy")
    thread = Thread(target=renew, daemon=True)
    thread.start()
    try:
        check()
        yield check
    finally:
        stop.set(); thread.join()
        collection.delete_one({"_id": "storage-and-delete", "token": token})


def delete_project(store, identifier):
    store.require_project(identifier, "delete")
    with project_data_lock(store.database) as check_lock:
        return _delete_project(store, identifier, check_lock)


def _delete_project(store, identifier, check_lock):
    store.require_project(identifier, "delete")
    database, root = store.database, store.directory.resolve()
    query = {"project_id": identifier}
    reports = list(database.project_inspections.find(query, {"sha256": 1}))
    ids = {"report": {row["_id"] for row in reports},
           "clash": {row["_id"] for row in database.project_runs.find(query, {"_id": 1})},
           "link": {row["_id"] for row in database.project_links.find(query, {"_id": 1})}}
    for row in database.auth_artifacts.find(query):
        if row.get("kind") not in ids:
            raise HTTPException(409, "project_delete_invalid_artifact")
        ids[row["kind"]].add(row["_id"].removeprefix(row["kind"] + ":"))
    hashes = {row.get("sha256", "") for row in reports}
    if any(not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value) for values in ids.values() for value in values) or any(not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value) for value in hashes):
        raise HTTPException(409, "project_delete_invalid_artifact")
    paths = set()
    for kind, folder in [("report", "reports"), ("clash", "clashes"), ("link", "links")]:
        paths.update(f"{folder}/{value}.json" for value in ids[kind])
    paths.update(f"assets/{value}/{name}" for value in ids["report"] for name in ASSET_FILES)
    paths.update(f"cache/models/{digest}.ifc" for digest in hashes)
    paths.update(f"cache/files/{digest}.{kind}" for digest in hashes for kind in ("dwg", "dxf", "pdf"))
    refs = list(database.storage_refs.find(query))
    paths.update(row.get("relative", "") for row in refs)

    def safe_path(relative):
        if not isinstance(relative, str):
            raise HTTPException(409, "project_delete_invalid_artifact")
        path = root / relative
        if not MANAGED.fullmatch(relative) or not path.resolve().is_relative_to(root) or any(parent.is_symlink() or parent.is_junction() for parent in [path, *path.parents] if parent != root and parent.is_relative_to(root)):
            raise HTTPException(409, "project_delete_invalid_artifact")
        return path

    # Validate the complete plan before deleting anything, including paths stored in MongoDB.
    for relative in paths:
        safe_path(relative)
    other = {"project_id": {"$ne": identifier}}
    shared_hashes = {digest for digest in hashes if database.project_inspections.find_one({**other, "sha256": digest})}

    def shared(relative):
        parts = relative.split("/")
        if parts[0] == "cache" and parts[-1].split(".")[0] in shared_hashes:
            return True
        collection = {"reports": "project_inspections", "assets": "project_inspections", "clashes": "project_runs", "links": "project_links"}.get(parts[0])
        if collection and database[collection].find_one({**other, "_id": parts[1].split(".")[0]}):
            return True
        return database.storage_refs.find_one({**other, "relative": relative}) is not None

    deletable = sorted(relative for relative in paths if not shared(relative))
    orphaned = list(database.storage_files.find({"$or": [{"relative": {"$in": deletable}}, {"project_ids": identifier}]}, {"namespace": 1}))
    if refs and (store.storage is None or any(row.get("namespace") != store.storage.namespace for row in refs)):
        raise HTTPException(409, "storage_not_configured" if store.storage is None else "storage_namespace_mismatch")
    if orphaned and (store.storage is None or any(row.get("namespace") != store.storage.namespace for row in orphaned)):
        raise HTTPException(409, "storage_not_configured" if store.storage is None else "storage_namespace_mismatch")
    geometry = []
    cache = root / "cache" / "clash-geometry"
    if cache.exists():
        if cache.is_symlink() or cache.is_junction() or not cache.resolve().is_relative_to(root):
            raise HTTPException(409, "project_delete_invalid_artifact")
        for directory in cache.iterdir():
            if not re.fullmatch(r"[a-f0-9]{64}", directory.name) or not directory.is_dir():
                continue
            if directory.is_symlink() or directory.is_junction() or not directory.resolve().is_relative_to(cache.resolve()):
                raise HTTPException(409, "project_delete_invalid_artifact")
            manifest = directory / "manifest.json"
            try:
                if manifest.stat().st_size > MAX_REPORT_BYTES or manifest.is_symlink():
                    continue
                definition = json.loads(manifest.read_text(encoding="utf-8"))["definition"]
                if definition["source_sha256"] in hashes - shared_hashes:
                    geometry.append(directory)
            except (OSError, ValueError, KeyError, TypeError):
                continue
    check_lock()
    database.projects.update_one({"_id": identifier}, {"$set": {"deleting": True}})
    # Keep all ownership records until cloud/local cleanup succeeds, so a failed deletion can be retried.
    if store.storage:
        retained = store.storage.delete_project_files(identifier, deletable, check_lock=check_lock)
        deletable = [relative for relative in deletable if relative not in retained]
    removed = 0
    try:
        for relative in deletable:
            check_lock()
            path = safe_path(relative)
            if path.is_file():
                path.unlink()
                removed += 1
        for directory in geometry:
            check_lock()
            if directory.exists():
                shutil.rmtree(directory)
            directory.with_suffix(".lock").unlink(missing_ok=True)
        for value in ids["report"]:
            directory = root / "assets" / value
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
    except OSError:
        raise HTTPException(503, "project_delete_failed") from None
    for collection in ["project_issues", "project_cases", "project_advice", "project_conclusions", "project_links", "project_runs", "project_inspections", "auth_artifacts"]:
        check_lock()
        database[collection].delete_many(query)
    database.auth_audit.delete_many({"target": identifier})
    database.projects.delete_one({"_id": identifier, "deleting": True})
    return {"status": "deleted", "id": identifier, "local_files_deleted": removed, "geometry_caches_deleted": len(geometry)}
