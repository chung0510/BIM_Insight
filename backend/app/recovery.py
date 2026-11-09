from datetime import timedelta
import hmac
import secrets
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.access import now, password_hash
from app.account_mail import normalize_email


class RecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    identifier: str = Field(min_length=3, max_length=254)


class CodeConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    code: SecretStr = Field(min_length=6, max_length=6)

    @field_validator("code")
    @classmethod
    def numeric(cls, value):
        if not value.get_secret_value().isascii() or not value.get_secret_value().isdigit():
            raise ValueError("Use the six-digit code")
        return value


class RecoveryConfirmation(CodeConfirmation):
    new_password: SecretStr = Field(min_length=12, max_length=128)


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def address(cls, value):
        return normalize_email(value)


class RecoveryService:
    def __init__(self, access, mailer):
        self.access = access; self.db = access.db; self.mailer = mailer

    def request(self, payload, background, *, verification=False):
        self.mailer.require_configuration()
        if verification:
            actor = self.access.actor
            self.access.rate("email-verify-request-" + actor["id"], 6, 3600)
            user = self.db.auth_users.find_one({"_id": actor["id"], "disabled": False})
            recipient = payload.email; kind = "verify_email"
        else:
            identifier = payload.identifier.strip().lower()
            self.access.rate("recovery-request-" + identifier, 3, 600)
            self.access.rate("recovery-request-all", 30, 60)
            user = self.db.auth_users.find_one({"$or": [{"login_keys": identifier}, {"username": identifier}], "disabled": False, "email_verified": True})
            recipient = user.get("login_email", "") if user else ""; kind = "recovery"
        challenge_id = uuid4().hex; code = f"{secrets.randbelow(1_000_000):06d}"; salt = secrets.token_hex(16)
        subject = f"{kind}:{user['_id']}" if user else uuid4().hex
        self.db.auth_challenges.create_index("expires_at", expireAfterSeconds=0)
        self.db.auth_challenges.create_index("challenge_id", unique=True)
        self.db.auth_challenges.replace_one({"_id": subject}, {"_id": subject, "challenge_id": challenge_id, "kind": kind, "user_id": user["_id"] if user else None, "auth_version": user.get("auth_version", 1) if user else None, "recipient": recipient, "salt": salt, "code_hash": password_hash(code, salt), "attempts": 0, "consumed": False, "expires_at": now() + timedelta(minutes=10)}, upsert=True)
        if user and recipient:
            background.add_task(self.deliver, challenge_id, recipient, code, kind)
        return {"challenge_id": challenge_id, "message": "Nếu thông tin phù hợp, mã xác nhận sẽ được gửi qua email. Mã có hiệu lực 10 phút."}

    def deliver(self, identifier, recipient, code, kind):
        current = self.db.auth_challenges.find_one({"challenge_id": identifier, "consumed": False, "expires_at": {"$gt": now()}})
        if not current: return
        try:
            self.mailer.send(recipient, code, recovery=kind == "recovery")
            self.db.auth_challenges.update_one({"challenge_id": identifier}, {"$set": {"delivery": "sent"}})
        except Exception:
            # Provider errors may contain credentials; retain only a generic delivery state.
            self.db.auth_challenges.update_one({"challenge_id": identifier}, {"$set": {"delivery": "failed"}})

    def take(self, payload, kind, *, user_id=None):
        self.access.rate("code-check-all", 60, 60)
        query = {"challenge_id": payload.challenge_id, "kind": kind, "attempts": {"$lt": 5}, "consumed": False, "expires_at": {"$gt": now()}}
        if user_id is not None: query["user_id"] = user_id
        challenge = self.db.auth_challenges.find_one_and_update(query, {"$inc": {"attempts": 1}}, return_document=ReturnDocument.AFTER)
        if not challenge or not hmac.compare_digest(password_hash(payload.code.get_secret_value(), challenge["salt"]), challenge["code_hash"]):
            raise HTTPException(400, "verification_code_invalid")
        return challenge

    def claim(self, challenge):
        claimed = self.db.auth_challenges.update_one({"challenge_id": challenge["challenge_id"], "consumed": False, "expires_at": {"$gt": now()}}, {"$set": {"consumed": True}})
        if not claimed.modified_count: raise HTTPException(400, "verification_code_invalid")

    def reset(self, payload):
        challenge = self.take(payload, "recovery")
        user = self.db.auth_users.find_one({"_id": challenge["user_id"], "auth_version": challenge["auth_version"], "disabled": False})
        if user is None: raise HTTPException(400, "verification_code_invalid")
        if user.get("must_change_password") and hmac.compare_digest(password_hash(payload.new_password.get_secret_value(), user["salt"]), user["password_hash"]):
            raise HTTPException(422, "password_must_differ")
        self.claim(challenge)
        salt = secrets.token_hex(16)
        updated = self.db.auth_users.find_one_and_update({"_id": challenge["user_id"], "auth_version": challenge["auth_version"], "disabled": False, "email_verified": True, "login_email": challenge["recipient"]}, {"$set": {"salt": salt, "password_hash": password_hash(payload.new_password.get_secret_value(), salt), "must_change_password": False}, "$inc": {"auth_version": 1, "revision": 1}}, return_document=ReturnDocument.AFTER)
        if updated is None: raise HTTPException(400, "verification_code_invalid")
        self.db.auth_sessions.delete_many({"user_id": updated["_id"]})
        self.db.auth_challenges.delete_many({"user_id": updated["_id"]})
        self.access.audit(updated["_id"], "password_recovered", updated["_id"])
        return {"status": "password_reset"}

    def verify_email(self, payload):
        challenge = self.take(payload, "verify_email", user_id=self.access.actor["id"])
        self.claim(challenge)
        user = self.db.auth_users.find_one({"_id": challenge["user_id"]})
        try:
            updated = self.db.auth_users.find_one_and_update({"_id": user["_id"], "auth_version": challenge["auth_version"], "disabled": False}, {"$set": {"login_keys": [user["username"], challenge["recipient"]], "login_email": challenge["recipient"], "email_verified": True, "pending_email": ""}, "$inc": {"revision": 1}}, return_document=ReturnDocument.AFTER)
        except DuplicateKeyError:
            raise HTTPException(409, "email_unavailable") from None
        if updated is None: raise HTTPException(400, "verification_code_invalid")
        self.access.audit(user["_id"], "email_verified", user["_id"])
        return self.access.public(updated)
