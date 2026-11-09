from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import time
from uuid import uuid4

from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError


actor_context = ContextVar("bim_account", default=None)
ROLES = {"admin", "teacher", "student", "user"}
ITERATIONS = 600_000


def now():
    return datetime.now(timezone.utc)


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS).hex()


class AccessStore:
    def __init__(self, database, directory):
        self.db = database
        self.directory = Path(directory)
        self.indexed = False

    def indexes(self):
        if not self.indexed:
            self.db.auth_users.create_index("username", unique=True)
            self.db.auth_users.create_index("login_keys", unique=True, sparse=True)
            self.db.auth_users.update_many({"login_keys": {"$exists": False}}, [{"$set": {"login_keys": ["$username"]}}])
            self.db.auth_sessions.create_index("expires_at", expireAfterSeconds=0)
            self.db.auth_attempts.create_index("expires_at", expireAfterSeconds=0)
            self.db.projects.create_index("owner_id")
            self.db.projects.create_index("members.user_id")
            self.indexed = True

    @property
    def actor(self):
        value = actor_context.get()
        if value is None:
            raise HTTPException(401, "account_session_required")
        return value

    def state(self):
        return {"setup_required": self.db.auth_users.find_one({"_id": "bootstrap"}, {"_id": 1}) is None}

    def admins(self):
        return (self.db.auth_users.find_one({"_id": "bootstrap"}, {"admin_ids": 1}) or {}).get("admin_ids", [])

    def public(self, user, admin_ids=None):
        realm = self.db.auth_users.find_one({"_id": "bootstrap"}, {"realm_id": 1}) or {}
        admin_ids = self.admins() if admin_ids is None else admin_ids
        return {"id": user["_id"], "realm_id": realm.get("realm_id", ""), "username": user["username"], "display_name": user["display_name"], "role": "admin" if user["_id"] in admin_ids else user["role"], "disabled": user.get("disabled", False), "revision": user["revision"], "created_at": user["created_at"], "protected": user.get("admin_protected", False), "must_change_password": user.get("must_change_password", False), "identity_code": user.get("identity_code", ""), "login_email": user.get("login_email", ""), "pending_email": user.get("pending_email", "")}

    def rate(self, key, limit, seconds):
        self.indexes()
        identifier = hashlib.sha256(key.encode()).hexdigest() + ":" + str(int(time.time()) // seconds)
        record = self.db.auth_attempts.find_one_and_update({"_id": identifier}, {"$inc": {"count": 1}, "$setOnInsert": {"expires_at": now() + timedelta(seconds=seconds * 2)}}, upsert=True, return_document=ReturnDocument.AFTER)
        if record["count"] > limit:
            raise HTTPException(429, "auth_rate_limited", headers={"Retry-After": str(seconds)})

    def issue(self, user):
        token = secrets.token_urlsafe(32)
        self.db.auth_sessions.insert_one({"_id": hashlib.sha256(token.encode()).hexdigest(), "user_id": user["_id"], "version": user.get("auth_version", 1), "expires_at": now() + timedelta(hours=8)})
        return {"session_token": token, "user": self.public(user), "expires_in": 8 * 3600}

    def create_account(self, payload, *, bootstrap=False):
        self.rate("account-create", 20, 3600)
        if bootstrap != self.state()["setup_required"]:
            raise HTTPException(409, "setup_already_completed" if bootstrap else "setup_required")
        password = payload.password.get_secret_value()
        salt = secrets.token_hex(16)
        identifier = "bootstrap" if bootstrap else uuid4().hex
        user = {"_id": identifier, "username": payload.username, "login_keys": [payload.username], "pending_email": payload.email, "display_name": payload.display_name, "salt": salt, "password_hash": password_hash(password, salt), "role": "user", "disabled": False, "revision": 1, "auth_version": 1, "admin_protected": bootstrap, "created_at": now().isoformat()}
        if bootstrap:
            user["admin_ids"] = [identifier]
            user["realm_id"] = uuid4().hex
            user["legacy_adopted"] = False
        try:
            self.db.auth_users.insert_one(user)
        except DuplicateKeyError:
            raise HTTPException(409, "setup_already_completed" if bootstrap and self.db.auth_users.find_one({"_id": "bootstrap"}) else "username_unavailable") from None
        self.finish_setup(user)
        self.audit(identifier, "account_created", identifier)
        return self.issue(user)

    def login(self, payload):
        self.rate("login-all", 60, 60)
        self.rate("login-" + payload.username, 10, 60)
        user = self.db.auth_users.find_one({"$or": [{"login_keys": payload.username}, {"username": payload.username}]})
        salt = user["salt"] if user else "0" * 32
        candidate = password_hash(payload.password.get_secret_value(), salt)
        expected = user["password_hash"] if user else "0" * 64
        if not hmac.compare_digest(candidate, expected) or user is None or user.get("disabled"):
            raise HTTPException(401, "invalid_credentials")
        self.finish_setup(user)
        return self.issue(user)

    def finish_setup(self, user):
        if user["_id"] == "bootstrap" and not user.get("legacy_adopted"):
            self.adopt_legacy(user)
            self.db.auth_users.update_one({"_id": "bootstrap"}, {"$set": {"legacy_adopted": True}})

    def authenticate(self, token):
        if not token or not re.fullmatch(r"[A-Za-z0-9_-]{40,128}", token):
            raise HTTPException(401, "account_session_required")
        session = self.db.auth_sessions.find_one({"_id": hashlib.sha256(token.encode()).hexdigest(), "expires_at": {"$gt": now()}})
        user = self.db.auth_users.find_one({"_id": session["user_id"]}) if session else None
        if user is None or user.get("disabled") or session["version"] != user.get("auth_version", 1):
            raise HTTPException(401, "account_session_expired")
        return self.public(user)

    def logout(self, token):
        self.db.auth_sessions.delete_one({"_id": hashlib.sha256(token.encode()).hexdigest()})
        return {"status": "signed_out"}

    def change_password(self, payload):
        user = self.db.auth_users.find_one({"_id": self.actor["id"]})
        if not hmac.compare_digest(password_hash(payload.current_password.get_secret_value(), user["salt"]), user["password_hash"]):
            raise HTTPException(401, "current_password_invalid")
        if user.get("must_change_password") and payload.current_password.get_secret_value() == payload.new_password.get_secret_value():
            raise HTTPException(422, "password_must_differ")
        salt = secrets.token_hex(16)
        updated = self.db.auth_users.find_one_and_update({"_id": user["_id"], "auth_version": user["auth_version"], "disabled": False}, {"$set": {"salt": salt, "password_hash": password_hash(payload.new_password.get_secret_value(), salt), "must_change_password": False}, "$inc": {"auth_version": 1, "revision": 1}}, return_document=ReturnDocument.AFTER)
        if updated is None:
            raise HTTPException(409, "account_changed")
        self.db.auth_sessions.delete_many({"user_id": user["_id"]})
        self.db.auth_challenges.delete_many({"user_id": user["_id"]})
        self.audit(user["_id"], "password_changed", user["_id"])
        return self.issue(updated)

    def require_admin(self):
        if self.actor["id"] not in self.admins():
            raise HTTPException(403, "admin_required")

    def profile(self, user=None):
        user = user or self.db.auth_users.find_one({"_id": self.actor["id"]})
        contact = user.get("profile", {})
        return {"user": self.public(user), **{key: contact.get(key, "") for key in ("email", "phone", "organization", "job_title", "bio")}}

    def update_profile(self, payload):
        fields = payload.model_dump(exclude={"expected_revision", "display_name"})
        updated = self.db.auth_users.find_one_and_update(
            {"_id": self.actor["id"], "revision": payload.expected_revision, "disabled": False},
            {"$set": {"display_name": payload.display_name, "profile": fields, "profile_updated_at": now().isoformat()}, "$inc": {"revision": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise HTTPException(409, "profile_changed")
        self.audit(self.actor["id"], "profile_updated", self.actor["id"])
        return self.profile(updated)

    def users(self, offset, limit):
        self.require_admin()
        ids = self.admins()
        return {"items": [self.public(user, ids) for user in self.db.auth_users.find({}).sort([("created_at", 1), ("_id", 1)]).skip(offset).limit(limit)], "total": self.db.auth_users.count_documents({}), "offset": offset, "limit": limit}

    def set_role(self, identifier, payload):
        self.require_admin()
        if identifier == self.actor["id"] and payload.role != "admin":
            raise HTTPException(409, "own_admin_role_protected")
        old = self.db.auth_users.find_one({"_id": identifier, "revision": payload.expected_revision, "disabled": False})
        if old is None:
            raise HTTPException(409, "account_changed")
        was_admin = identifier in self.admins()
        if old.get("admin_protected") and not was_admin and payload.role != "admin":
            raise HTTPException(409, "account_changed")
        updated = self.db.auth_users.find_one_and_update({"_id": identifier, "revision": payload.expected_revision, "disabled": False}, {"$set": {"role": "user" if payload.role == "admin" else payload.role, "admin_protected": payload.role == "admin" or was_admin}, "$inc": {"revision": 1}}, return_document=ReturnDocument.AFTER)
        if updated is None:
            raise HTTPException(409, "account_changed")
        if payload.role == "admin":
            self.db.auth_users.update_one({"_id": "bootstrap"}, {"$addToSet": {"admin_ids": identifier}})
        else:
            if was_admin:
                removed = self.db.auth_users.update_one({"_id": "bootstrap", "admin_ids.1": {"$exists": True}}, {"$pull": {"admin_ids": identifier}})
                if not removed.modified_count:
                    raise HTTPException(409, "last_admin_protected")
            self.db.auth_users.update_one({"_id": identifier, "revision": updated["revision"]}, {"$set": {"admin_protected": False}})
            updated = self.db.auth_users.find_one({"_id": identifier})
        self.audit(self.actor["id"], "role_changed", identifier, role=payload.role)
        return self.public(updated)

    def set_status(self, identifier, payload):
        self.require_admin()
        if identifier in self.admins():
            raise HTTPException(409, "account_protected_or_changed")
        updated = self.db.auth_users.find_one_and_update({"_id": identifier, "revision": payload.expected_revision, "admin_protected": {"$ne": True}}, {"$set": {"disabled": payload.disabled}, "$inc": {"revision": 1, "auth_version": 1}}, return_document=ReturnDocument.AFTER)
        if updated is None:
            raise HTTPException(409, "account_protected_or_changed")
        self.db.auth_sessions.delete_many({"user_id": identifier})
        self.audit(self.actor["id"], "account_status_changed", identifier, disabled=payload.disabled)
        return self.public(updated)

    def project_scope(self, scope="all"):
        own = {"owner_id": self.actor["id"]}
        shared = {"members.user_id": self.actor["id"]}
        return own if scope == "owned" else shared if scope == "shared" else {"$or": [own, shared]}

    def permissions(self, project):
        owner = project.get("owner_id") == self.actor["id"]
        membership = next((row for row in project.get("members", []) if row["user_id"] == self.actor["id"]), None)
        return {"view": owner or membership is not None, "edit": owner, "review": owner or bool(membership and membership["access"] == "review" and self.actor["role"] in {"teacher", "admin"}), "share": owner, "delete": owner}

    def require_project(self, identifier, permission="view", *, allow_deleting=False):
        project = self.db.projects.find_one({"_id": str(identifier)})
        if project is None or not self.permissions(project)["view"]:
            raise HTTPException(404, "project_not_found")
        if not self.permissions(project)[permission]:
            raise HTTPException(403, "project_permission_denied")
        if project.get("deleting") and permission != "delete" and not allow_deleting:
            raise HTTPException(409, "project_deleting")
        return project

    def project_info(self, project):
        owner = self.db.auth_users.find_one({"_id": project.get("owner_id")}, {"display_name": 1})
        return {"id": project["_id"], "name": project["name"], "description": project.get("description", ""), "created_at": project["created_at"], "owner_id": project.get("owner_id"), "owner_name": owner["display_name"] if owner else "", "deleting": bool(project.get("deleting")), "permissions": self.permissions(project)}

    def require_artifact(self, kind, identifier, permission="view"):
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise HTTPException(404, "report_not_found")
        record = self.db.auth_artifacts.find_one({"_id": f"{kind}:{identifier}"})
        if record is None:
            collection = {"report": "project_inspections", "clash": "project_runs", "link": "project_links"}[kind]
            record = self.db[collection].find_one({"_id": identifier}, {"project_id": 1})
        if record and record.get("project_id"):
            return self.require_project(record["project_id"], permission)
        if record is None or record.get("owner_id") != self.actor["id"]:
            raise HTTPException(404, "report_not_found")
        return None

    def register_artifact(self, kind, report, owner_id=None):
        self.db.auth_artifacts.update_one({"_id": f"{kind}:{report['id']}"}, {"$setOnInsert": {"kind": kind, "owner_id": owner_id or self.actor["id"], "project_id": report.get("project_id")}}, upsert=True)

    def members(self, identifier):
        project = self.require_project(identifier, "share")
        items = []
        for row in project.get("members", []):
            user = self.db.auth_users.find_one({"_id": row["user_id"]})
            if user:
                public = self.public(user)
                items.append({"user_id": public["id"], "username": public["username"], "display_name": public["display_name"], "role": public["role"], "access": row["access"], "disabled": public["disabled"]})
        return {"items": items}

    def share(self, identifier, payload):
        self.require_project(identifier, "share")
        user = self.db.auth_users.find_one({"username": payload.username, "disabled": False})
        if user is None or user["_id"] == self.actor["id"]:
            raise HTTPException(422, "member_unavailable")
        if payload.access == "review" and self.public(user)["role"] not in {"teacher", "admin"}:
            raise HTTPException(422, "reviewer_role_required")
        member = {"user_id": user["_id"], "access": payload.access}
        self.db.projects.update_one({"_id": str(identifier), "owner_id": self.actor["id"]}, [{"$set": {"members": {"$concatArrays": [{"$filter": {"input": {"$ifNull": ["$members", []]}, "as": "member", "cond": {"$ne": ["$$member.user_id", user["_id"]]}}}, {"$literal": [member]}]}}}])
        self.audit(self.actor["id"], "project_shared", str(identifier), member_id=user["_id"], access=payload.access)
        return self.members(identifier)

    def unshare(self, identifier, user_id):
        self.require_project(identifier, "share")
        self.db.projects.update_one({"_id": str(identifier), "owner_id": self.actor["id"]}, {"$pull": {"members": {"user_id": user_id}}})
        self.audit(self.actor["id"], "project_unshared", str(identifier), member_id=user_id)
        return self.members(identifier)

    def review_identity(self):
        return {"reviewer": self.actor["display_name"], "reviewer_id": self.actor["id"], "reviewer_role": self.actor["role"]}

    def summary(self):
        uid = self.actor["id"]
        result = {"owned_projects": self.db.projects.count_documents({"owner_id": uid}), "shared_projects": self.db.projects.count_documents({"members.user_id": uid})}
        if self.actor["role"] == "admin":
            admins = self.admins()
            result["accounts"] = {"admin": len(admins), **{role: self.db.auth_users.count_documents({"role": role, "_id": {"$nin": admins}}) for role in ["teacher", "student", "user"]}}
        return result

    def adopt_legacy(self, user):
        self.db.projects.update_many({"owner_id": None}, {"$set": {"owner_id": user["_id"], "members": []}})
        root = self.directory.resolve()
        for folder, kind in [("reports", "report"), ("clashes", "clash"), ("links", "link")]:
            directory = (root / folder).resolve()
            if directory.parent != root:
                continue
            for path in directory.glob("*.json"):
                if not re.fullmatch(r"[a-f0-9]{32}", path.stem) or path.resolve().parent != directory:
                    continue
                try:
                    from app.limits import MAX_REPORT_BYTES
                    if path.stat().st_size > MAX_REPORT_BYTES:
                        continue
                    report = json.loads(path.read_text(encoding="utf-8"))
                    if report.get("id") != path.stem:
                        continue
                    if report.get("project_id") and self.db.projects.find_one({"_id": report["project_id"], "owner_id": user["_id"]}) is None:
                        continue
                    self.register_artifact(kind, report, owner_id=user["_id"])
                except (OSError, ValueError, TypeError):
                    continue

    def audit(self, actor_id, action, target, **details):
        self.db.auth_audit.insert_one({"actor_id": actor_id, "action": action, "target": target, "created_at": now(), **details})
