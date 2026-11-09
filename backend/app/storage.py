import asyncio
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import tempfile
from threading import Event
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException
from anyio import CancelScope
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pymongo.errors import DuplicateKeyError
from pymongo import ReturnDocument

from app.settings import load_settings
from app.limits import FILE_LIMITS


MAX_FILE = max(FILE_LIMITS.values())
BYTE_LIMIT = 8_000_000_000
WARNING_BYTES = 7_000_000_000
REQUEST_LIMITS = {"a": 800_000, "b": 8_000_000}
MANAGED = re.compile(r"(?:reports|clashes|links)/[a-f0-9]{32}\.json|assets/[a-f0-9]{32}/(?:model\.glb|model\.json|drawing\.json|inspection\.json|converted\.dxf)|cache/models/[a-f0-9]{64}\.ifc|cache/files/[a-f0-9]{64}\.(?:pdf|dxf|dwg)")


class R2Config(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    endpoint: str = Field(pattern=r"^https://[a-f0-9]{32}(?:\.(?:eu|us|fedramp))?\.r2\.cloudflarestorage\.com$")
    bucket: str = Field(min_length=3, max_length=63, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])$")
    access_key_id: SecretStr = Field(min_length=16, max_length=128)
    secret_access_key: SecretStr = Field(min_length=32, max_length=256)

    def private_values(self):
        return {**self.model_dump(exclude={"access_key_id", "secret_access_key"}), "access_key_id": self.access_key_id.get_secret_value(), "secret_access_key": self.secret_access_key.get_secret_value()}


def s3_client(config):
    return boto3.client("s3", endpoint_url=config.endpoint, aws_access_key_id=config.access_key_id.get_secret_value(), aws_secret_access_key=config.secret_access_key.get_secret_value(), region_name="auto", config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=20, request_checksum_calculation="when_required", response_checksum_validation="when_required"))


def file_digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


class CancelReader:
    def __init__(self, handle, cancel):
        self.handle, self.cancel = handle, cancel

    def read(self, size=-1):
        if self.cancel.is_set():
            raise HTTPException(499, "storage_cancelled")
        return self.handle.read(size)

    def seek(self, *args):
        return self.handle.seek(*args)

    def tell(self):
        return self.handle.tell()


class StorageService:
    def __init__(self, database, directory, config, *, client=None):
        self.database, self.directory, self.config = database, Path(directory), config
        self.client = client or s3_client(config)
        self.namespace = hashlib.sha256(f"{config.endpoint}/{config.bucket}/{database.name}".encode()).hexdigest()[:24]

    def managed_path(self, relative):
        if not isinstance(relative, str) or not MANAGED.fullmatch(relative):
            raise HTTPException(422, "storage_path_invalid")
        path = (self.directory / relative).resolve()
        if not path.is_relative_to(self.directory.resolve()):
            raise HTTPException(422, "storage_path_invalid")
        return path

    def file_id(self, relative):
        return self.namespace + ":" + hashlib.sha256(relative.encode()).hexdigest()

    def _quota(self):
        self.database.storage_quota.update_one({"_id": self.namespace}, {"$setOnInsert": {"allocated_bytes": 0, "external_bytes": 0}}, upsert=True)
        return self.database.storage_quota.find_one({"_id": self.namespace})

    def _call(self, category, operation, **params):
        if category is not None:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            identifier = f"{self.namespace}:{month}"
            self.database.storage_requests.update_one({"_id": identifier}, {"$setOnInsert": {"a": 0, "b": 0}}, upsert=True)
            result = self.database.storage_requests.find_one_and_update({"_id": identifier, category: {"$lt": REQUEST_LIMITS[category]}}, {"$inc": {category: 1}})
            if result is None:
                raise HTTPException(429, "storage_request_budget")
        try:
            return getattr(self.client, operation)(Bucket=self.config.bucket, **params)
        except ClientError as error:
            if operation == "head_object" and str(error.response.get("Error", {}).get("Code")) in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise HTTPException(503, "storage_unavailable") from None
        except (BotoCoreError, OSError):
            raise HTTPException(503, "storage_unavailable") from None

    def reconcile(self, cancel):
        quota = self._quota()
        checked = quota.get("checked_at")
        if checked and (datetime.now(timezone.utc) - checked.replace(tzinfo=timezone.utc)).total_seconds() < 86400:
            return
        known = set(self.database.storage_files.distinct("key", {"namespace": self.namespace}))
        external, continuation = 0, None
        while True:
            if cancel.is_set():
                raise HTTPException(499, "storage_cancelled")
            result = self._call("a", "list_objects_v2", **({"ContinuationToken": continuation} if continuation else {}))
            external += sum(item["Size"] for item in result.get("Contents", []) if item["Key"] not in known)
            if not result.get("IsTruncated"):
                break
            continuation = result["NextContinuationToken"]
        self.database.storage_quota.update_one({"_id": self.namespace}, {"$max": {"external_bytes": external}, "$set": {"checked_at": datetime.now(timezone.utc)}})

    def status(self):
        quota = self.database.storage_quota.find_one({"_id": self.namespace}) or {}
        verified = list(self.database.storage_files.aggregate([{"$match": {"namespace": self.namespace, "status": "verified"}}, {"$group": {"_id": None, "bytes": {"$sum": "$size_bytes"}}}]))
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        requests = self.database.storage_requests.find_one({"_id": f"{self.namespace}:{month}"}) or {}
        allocated, external = quota.get("allocated_bytes", 0), quota.get("external_bytes", 0)
        return {"configured": True, "bucket": self.config.bucket, "allocated_bytes": allocated, "external_bytes": external, "verified_bytes": verified[0]["bytes"] if verified else 0, "limit_bytes": BYTE_LIMIT, "warning": allocated + external >= WARNING_BYTES, "requests": {"month": month, "a": requests.get("a", 0), "b": requests.get("b", 0), "limits": REQUEST_LIMITS}, "last_reconciled_at": quota.get("checked_at")}

    def _reserve(self, relative, digest, size):
        identifier = self.file_id(relative)
        collection = self.database.storage_files
        existing = collection.find_one({"_id": identifier})
        if existing:
            if (existing["sha256"], existing["size_bytes"]) != (digest, size):
                raise HTTPException(409, "storage_immutable_conflict")
            return existing
        self._quota()
        reserved = self.database.storage_quota.find_one_and_update({"_id": self.namespace, "$expr": {"$lte": [{"$add": ["$allocated_bytes", "$external_bytes", size]}, BYTE_LIMIT]}}, {"$inc": {"allocated_bytes": size}})
        if reserved is None:
            raise HTTPException(413, "storage_byte_budget")
        record = {"_id": identifier, "namespace": self.namespace, "relative": relative, "sha256": digest, "size_bytes": size, "status": "reserved", "key": f"bim-insight/v1/{self.namespace}/{hashlib.sha256(relative.encode()).hexdigest()}/{digest}"}
        try:
            collection.insert_one(record)
        except DuplicateKeyError:
            self.database.storage_quota.update_one({"_id": self.namespace}, {"$inc": {"allocated_bytes": -size}})
            return self._reserve(relative, digest, size)
        # A crash between reservation and insert may overcount; never release uncertain uploaded bytes automatically.
        return record

    def _download(self, record, destination, cancel):
        response = self._call("b", "get_object", Key=record["key"])
        body, size, digest = response["Body"], 0, hashlib.sha256()
        try:
            if response.get("ContentLength") != record["size_bytes"]:
                raise HTTPException(502, "storage_hash_mismatch")
            while chunk := body.read(64 * 1024):
                if cancel.is_set():
                    raise HTTPException(499, "storage_cancelled")
                size += len(chunk)
                if size > record["size_bytes"]:
                    raise HTTPException(502, "storage_hash_mismatch")
                digest.update(chunk)
                if destination:
                    destination.write(chunk)
            if size != record["size_bytes"] or digest.hexdigest() != record["sha256"]:
                raise HTTPException(502, "storage_hash_mismatch")
        except (BotoCoreError, OSError):
            raise HTTPException(503, "storage_unavailable") from None
        finally:
            body.close()

    def backup_file(self, project_id, relative, cancel):
        path = self.managed_path(relative)
        if cancel.is_set():
            raise HTTPException(499, "storage_cancelled")
        if not path.is_file():
            self.ensure_local(relative, cancel)
        if not path.is_file():
            raise HTTPException(409, "project_artifact_missing")
        size = path.stat().st_size
        if not 0 < size <= MAX_FILE:
            raise HTTPException(413, "storage_file_too_large")
        digest = file_digest(path)
        self.reconcile(cancel)
        record = self._reserve(relative, digest, size)
        # Claim the blob in the same document used by deletion, including across Windows devices.
        record = self.database.storage_files.find_one_and_update(
            {"_id": record["_id"], "status": {"$ne": "deleting"}},
            {"$addToSet": {"project_ids": project_id}}, return_document=ReturnDocument.AFTER)
        if record is None:
            raise HTTPException(409, "storage_file_deleting")
        self.database.storage_refs.update_one({"_id": f"{self.namespace}:{project_id}:{record['_id']}"}, {"$setOnInsert": {"namespace": self.namespace, "project_id": project_id, "file_id": record["_id"], "relative": relative}}, upsert=True)
        if record["status"] != "verified":
            head = self._call("b", "head_object", Key=record["key"])
            if head is None:
                with path.open("rb") as handle:
                    self._call("a", "put_object", Key=record["key"], Body=CancelReader(handle, cancel), ContentLength=size, Metadata={"sha256": digest})
            self._download(record, None, cancel)
            self.database.storage_files.update_one({"_id": record["_id"]}, {"$set": {"status": "verified", "verified_at": datetime.now(timezone.utc)}})
            record["status"] = "verified"
        return {key: record[key] for key in ["relative", "status", "sha256", "size_bytes"]}

    def ensure_local(self, relative, cancel=None):
        path = self.managed_path(relative)
        record = self.database.storage_files.find_one({"_id": self.file_id(relative), "status": "verified"})
        if not record:
            return path
        if path.is_file() and path.stat().st_size == record["size_bytes"] and file_digest(path) == record["sha256"]:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix="recover-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                self._download(record, handle, cancel or Event())
            if not self.database.storage_files.find_one({"_id": record["_id"], "status": "verified", "sha256": record["sha256"]}):
                raise HTTPException(409, "project_artifact_missing")
            temporary.replace(path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        return path

    def delete_project_files(self, project_id, relatives, *, check_lock=None):
        """The caller holds project_data_lock across planning, cloud cleanup and metadata removal."""
        records = list(self.database.storage_files.find({"_id": {"$in": [self.file_id(relative) for relative in relatives]}}))
        for record in records:
            relative, digest = record.get("relative"), record.get("sha256", "")
            self.managed_path(relative)
            key = f"bim-insight/v1/{self.namespace}/{hashlib.sha256(relative.encode()).hexdigest()}/{digest}"
            if not re.fullmatch(r"[a-f0-9]{64}", digest) or record.get("namespace") != self.namespace or record["_id"] != self.file_id(relative) or record.get("key") != key or type(record.get("size_bytes")) is not int or not 0 <= record["size_bytes"] <= MAX_FILE:
                raise HTTPException(409, "project_delete_invalid_artifact")
            if record.get("delete_token") is not None and not re.fullmatch(r"[a-f0-9]{32}", record["delete_token"]):
                raise HTTPException(409, "project_delete_invalid_artifact")
        receipts = self._quota().get("delete_receipts", {})
        for token, receipt in receipts.items():
            if receipt["project_id"] == project_id and not self.database.storage_files.find_one({"_id": receipt["file_id"], "delete_token": token}):
                self.database.storage_quota.update_one({"_id": self.namespace}, {"$unset": {f"delete_receipts.{token}": ""}})
        claimed, retained = [], set()
        for record in records:
            if check_lock:
                check_lock()
            owners = [row["project_id"] for row in self.database.storage_refs.find({"namespace": self.namespace, "file_id": record["_id"]})]
            if owners:
                self.database.storage_files.update_one({"_id": record["_id"]}, {"$addToSet": {"project_ids": {"$each": owners}}})
            query = {"_id": record["_id"], "project_ids": {"$not": {"$elemMatch": {"$ne": project_id}}}}
            current = self.database.storage_files.find_one_and_update({**query, "delete_token": {"$exists": False}}, {"$set": {"status": "deleting", "delete_token": uuid4().hex}}, return_document=ReturnDocument.AFTER)
            current = current or self.database.storage_files.find_one({**query, "status": "deleting"})
            if current:
                claimed.append(current)
            else:
                retained.add(record["relative"])
        for record in claimed:
            if check_lock:
                check_lock()
            # DeleteObject is a free R2 operation and must remain usable when the A/B budget is exhausted.
            self._call(None, "delete_object", Key=record["key"])
        for record in claimed:
            if check_lock:
                check_lock()
            token = record["delete_token"]
            if not re.fullmatch(r"[a-f0-9]{32}", token):
                raise HTTPException(409, "project_delete_invalid_artifact")
            receipt = f"delete_receipts.{token}"
            # An atomic receipt makes the quota decrement retryable without requiring MongoDB transactions.
            self.database.storage_quota.update_one({"_id": self.namespace, receipt: {"$exists": False}}, {"$inc": {"allocated_bytes": -record["size_bytes"]}, "$set": {receipt: {"project_id": project_id, "file_id": record["_id"]}}})
            removed = self.database.storage_files.find_one_and_delete({"_id": record["_id"], "namespace": self.namespace, "delete_token": token})
            if removed:
                self.database.storage_quota.update_one({"_id": self.namespace}, {"$unset": {receipt: ""}})
        self.database.storage_files.update_many({"namespace": self.namespace, "project_ids": project_id}, {"$pull": {"project_ids": project_id}})
        self.database.storage_refs.delete_many({"namespace": self.namespace, "project_id": project_id})
        return retained


def configured_storage(database, directory):
    settings = load_settings(directory, "r2")
    return StorageService(database, directory, R2Config.model_validate(settings)) if settings else None


async def cancellable_sync(request, operation):
    cancel = Event()
    task = asyncio.create_task(asyncio.to_thread(operation, cancel))
    try:
        while not task.done():
            if await request.is_disconnected():
                cancel.set()
                raise HTTPException(499, "storage_cancelled")
            await asyncio.sleep(0.1)
        return await task
    finally:
        cancel.set()
        # Network calls have a bounded socket timeout; keep the thread owned until it stops.
        if not task.done():
            with CancelScope(shield=True):
                try:
                    await asyncio.shield(task)
                except Exception:
                    pass
