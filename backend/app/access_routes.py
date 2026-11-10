import re
from typing import Literal

from fastapi import Query, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from app.account_mail import normalize_email


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("username")
    @classmethod
    def identifier(cls, value):
        if "@" in value:
            return normalize_email(value)
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,47}", value):
            raise ValueError("Invalid username or identity code")
        return value


class Registration(Login):
    username: str = Field(min_length=3, max_length=48, pattern=r"^[a-z0-9][a-z0-9_.-]+$")
    password: SecretStr = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=2, max_length=80)
    email: str = Field(default="", max_length=254)

    @field_validator("email")
    @classmethod
    def registration_email(cls, value):
        return normalize_email(value) if value.strip() else ""

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value):
        if len(value.strip()) < 2 or any(ord(char) < 32 for char in value):
            raise ValueError("Invalid display name")
        return value.strip()


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=12, max_length=128)


class RoleChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["admin", "teacher", "student", "user"]
    expected_revision: int = Field(ge=1)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    display_name: str = Field(min_length=2, max_length=80)
    email: str = Field(default="", max_length=254)
    phone: str = Field(default="", max_length=25)
    organization: str = Field(default="", max_length=120)
    job_title: str = Field(default="", max_length=80)
    bio: str = Field(default="", max_length=500)
    expected_revision: int = Field(ge=1)

    @field_validator("display_name", "email", "phone", "organization", "job_title", "bio")
    @classmethod
    def clean_text(cls, value, info):
        if any((ord(char) < 32 and not (info.field_name == "bio" and char in "\n\r\t")) or ord(char) == 127 for char in value):
            raise ValueError("Invalid profile text")
        if info.field_name == "email" and value and not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", value):
            raise ValueError("Invalid contact email")
        if info.field_name == "phone" and value and (not re.fullmatch(r"[0-9+(). -]+", value) or len(re.sub(r"\D", "", value)) < 6):
            raise ValueError("Invalid contact phone")
        return value


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disabled: bool
    expected_revision: int = Field(ge=1)


class ShareProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=48, pattern=r"^[a-z0-9][a-z0-9_.-]+$")
    access: Literal["view", "review"]


def attach_access_routes(app, access):
    @app.get("/api/auth/state")
    def state():
        return access.state()

    @app.post("/api/auth/bootstrap", status_code=201)
    def bootstrap(payload: Registration):
        return access.create_account(payload, bootstrap=True)

    @app.post("/api/auth/register", status_code=201)
    def register(payload: Registration):
        return access.create_account(payload)

    @app.post("/api/auth/login")
    def login(payload: Login):
        return access.login(payload)

    @app.get("/api/auth/me")
    def me():
        return access.actor

    @app.post("/api/auth/logout")
    def logout(request: Request):
        return access.logout(request.headers.get("x-bim-session", ""))

    @app.post("/api/auth/password")
    def password(payload: PasswordChange):
        return access.change_password(payload)

    @app.get("/api/auth/profile")
    def profile():
        return access.profile()

    @app.post("/api/auth/profile")
    def update_profile(payload: ProfileUpdate):
        return access.update_profile(payload)

    @app.get("/api/auth/summary")
    def summary():
        return access.summary()

    @app.get("/api/admin/users")
    def users(offset: int = Query(0, ge=0, le=100000), limit: int = Query(20, ge=1, le=100), q: str = Query('',max_length=100), role: Literal['admin','teacher','student','user'] | None = None, status: Literal['active','disabled','pending'] | None = None):
        return access.users(offset, limit, q, role, status)

    @app.get('/api/admin/overview')
    def admin_overview():
        access.require_admin()
        return {'accounts':access.summary()['accounts'],
                'disabled':access.db.auth_users.count_documents({'disabled':True}),
                'pending_password':access.db.auth_users.count_documents({'must_change_password':True,'disabled':False}),
                'provision_batches':access.db.auth_provision_batches.count_documents({}),
                'audit_events':access.db.auth_audit.count_documents({})}

    @app.get('/api/admin/audit')
    def admin_audit(offset: int = Query(0,ge=0,le=100000), limit: int = Query(20,ge=1,le=100)):
        access.require_admin()
        rows = list(access.db.auth_audit.find({}, {'actor_id':1,'action':1,'target':1,'created_at':1,'role':1,'disabled':1}).sort([('created_at',-1),('_id',-1)]).skip(offset).limit(limit))
        names = {row['_id']:row['display_name'] for row in access.db.auth_users.find({'_id':{'$in':[row['actor_id'] for row in rows]}},{'display_name':1})}
        return {'items':[{'id':str(row.pop('_id')),**row,'actor_name':names.get(row['actor_id'],row['actor_id'])} for row in rows], 'total':access.db.auth_audit.count_documents({}),'offset':offset,'limit':limit}

    @app.post("/api/admin/users/{user_id}/role")
    def role(user_id: str, payload: RoleChange):
        return access.set_role(user_id, payload)

    @app.post("/api/admin/users/{user_id}/status")
    def status(user_id: str, payload: StatusChange):
        return access.set_status(user_id, payload)

    @app.get("/api/projects/{project_id}/members")
    def members(project_id: str):
        return access.members(project_id)

    @app.post("/api/projects/{project_id}/members")
    def share(project_id: str, payload: ShareProject):
        return access.share(project_id, payload)

    @app.post("/api/projects/{project_id}/members/{user_id}/remove")
    def unshare(project_id: str, user_id: str):
        return access.unshare(project_id, user_id)
