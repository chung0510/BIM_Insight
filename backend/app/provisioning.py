from datetime import timedelta
import hashlib
from io import BytesIO
import json
import re
import secrets
import unicodedata
from uuid import uuid4
from zipfile import ZipFile
from typing import Annotated

from fastapi import HTTPException
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.access import now, password_hash
from app.account_mail import normalize_email
from app.db import _dpapi


MAX_ROWS = 200
MAX_BYTES = 2 * 1024 * 1024


class ProvisionRow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role: str = Field(pattern=r"^(teacher|student)$")
    code: str = Field(min_length=3, max_length=48, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=2, max_length=80)
    email: str = Field(max_length=254)
    values: list[Annotated[str, StringConstraints(strip_whitespace=False)]] = Field(min_length=1, max_length=20)
    source_row: int = Field(default=2, ge=2, le=201)

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        return normalize_email(value)

    @field_validator("display_name")
    @classmethod
    def name(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Invalid name")
        return value

    @field_validator("values")
    @classmethod
    def original_values(cls, values):
        if any(len(value) > 500 or any(ord(char) < 32 and char not in "\n\r\t" for char in value) for value in values):
            raise ValueError("Invalid original cell")
        return values


class ProvisionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    columns: list[str] = Field(min_length=1, max_length=20)
    rows: list[ProvisionRow] = Field(min_length=1, max_length=MAX_ROWS)

    @field_validator("columns")
    @classmethod
    def column_names(cls, values):
        if any(not value.strip() or len(value) > 100 or any(ord(char) < 32 for char in value) for value in values):
            raise ValueError("Invalid columns")
        return values


def spreadsheet(columns, rows):
    workbook = Workbook(); sheet = workbook.active; sheet.title = "BIM Insight"
    for row in [columns, *rows]:
        sheet.append([str(value) for value in row])
        for cell in sheet[sheet.max_row]:
            cell.data_type = "s"  # Export all values as text so supplied cells never become formulas.
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="244B3E")
    sheet.freeze_panes = "A2"; sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = min(45, max(18, max(len(str(cell.value or "")) for cell in column) + 2))
        sheet.column_dimensions[column[0].column_letter].number_format = "@"
    output = BytesIO(); workbook.save(output); workbook.close()
    return output.getvalue()


def header_key(value):
    return "".join(char for char in unicodedata.normalize("NFD", value.lower().replace("đ", "d")) if char.isalnum())


def cell_text(cell):
    value = cell.value
    if cell.data_type == "f":
        raise HTTPException(422, "excel_formula_not_allowed")
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value).is_integer():
        text = str(int(value))
        return text.zfill(len(cell.number_format)) if re.fullmatch(r"0{1,48}", cell.number_format) else text
    return str(value)


class ProvisionStore:
    def __init__(self, access):
        self.access = access; self.db = access.db

    def errors(self, rows, columns):
        errors, seen_codes, seen_emails = [], set(), set()
        self.access.indexes()
        for row in rows:
            code = row.code.lower()
            if len(row.values) != len(columns):
                errors.append({"row": row.source_row, "code": "excel_columns_mismatch"})
            if code in seen_codes or row.email in seen_emails:
                errors.append({"row": row.source_row, "code": "provision_duplicate_in_file"})
            elif self.db.auth_users.find_one({"$or": [{"username": code}, {"login_keys": {"$in": [code, row.email]}}]}, {"_id": 1}):
                errors.append({"row": row.source_row, "code": "provision_identity_exists"})
            seen_codes.add(code); seen_emails.add(row.email)
        return errors

    def preview(self, data, filename):
        self.access.require_admin()
        if not filename.lower().endswith(".xlsx") or not data or len(data) > MAX_BYTES:
            raise HTTPException(422, "excel_file_invalid")
        workbook = None
        try:
            with ZipFile(BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 2000 or sum(entry.file_size for entry in entries) > 20 * 1024 * 1024 or any(entry.flag_bits & 1 or "vbaProject" in entry.filename or "externalLinks/" in entry.filename for entry in entries):
                    raise ValueError
            workbook = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
            if len(workbook.worksheets) != 1:
                raise HTTPException(422, "excel_one_sheet_required")
            sheet = workbook.active
            if (sheet.max_row or 0) > MAX_ROWS + 1 or (sheet.max_column or 0) > 20:
                raise HTTPException(422, "excel_scope_limit")
            raw = list(sheet.iter_rows(max_row=MAX_ROWS + 2, max_col=21))
            texts = [[cell_text(cell) for cell in row] for row in raw]
            while texts and not any(texts[-1]): texts.pop()
            if len(texts) < 2 or len(texts) > MAX_ROWS + 1:
                raise HTTPException(422, "excel_scope_limit")
            width = len(texts[0])
            while width and not texts[0][width - 1]: width -= 1
            columns = texts[0][:width]; keys = [header_key(value) for value in columns]
            if not 1 <= width <= 20 or len(set(keys)) != width or any(any(row[width:]) for row in texts):
                raise HTTPException(422, "excel_columns_invalid")
            find = lambda options: next((index for index, key in enumerate(keys) if key in options), None)
            name = find({"hovaten", "hoten", "fullname"}); email = find({"email", "gmail"})
            teacher = find({"magiangvien", "magiaovien", "teacherid"}); student = find({"masinhvien", "mahocvien", "studentid"})
            if name is None or email is None or (teacher is None and student is None):
                raise HTTPException(422, "excel_headers_required")
            rows, errors = [], []
            for number, values in enumerate(texts[1:], 2):
                values = values[:width]
                if not any(values): continue
                teacher_code = values[teacher].strip() if teacher is not None else ""
                student_code = values[student].strip() if student is not None else ""
                if bool(teacher_code) == bool(student_code):
                    errors.append({"row": number, "code": "excel_identity_required"}); continue
                code_value = raw[number - 1][teacher if teacher_code else student].value
                if isinstance(code_value, bool) or (isinstance(code_value, (int, float)) and (not float(code_value).is_integer() or abs(code_value) >= 10**15)):
                    errors.append({"row": number, "code": "excel_code_as_text_required"}); continue
                try:
                    rows.append(ProvisionRow(role="teacher" if teacher_code else "student", code=teacher_code or student_code, display_name=values[name], email=values[email], values=values, source_row=number))
                except ValidationError:
                    errors.append({"row": number, "code": "provision_row_invalid"})
            errors.extend(self.errors(rows, columns))
            return {"columns": columns, "rows": [row.model_dump() for row in rows], "errors": errors, "valid_count": len(rows) - len({error['row'] for error in errors if any(row.source_row == error['row'] for row in rows)})}
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "excel_file_invalid") from None
        finally:
            if workbook: workbook.close()

    def issue(self, payload):
        self.access.require_admin(); self.access.indexes()
        owner = self.access.actor["id"]
        self.db.auth_provision_batches.create_index("expires_at", expireAfterSeconds=0)
        digest = hashlib.sha256(payload.model_dump_json(exclude={"batch_id"}).encode()).hexdigest()
        current = self.db.auth_provision_batches.find_one({"_id": payload.batch_id})
        if current is None:
            self.access.rate("provision-" + owner, 12, 3600)
            if self.errors(payload.rows, payload.columns):
                raise HTTPException(422, "provision_rows_invalid")
            prepared = []
            for row in payload.rows:
                password = secrets.token_urlsafe(12); salt = secrets.token_hex(16); identifier = uuid4().hex
                prepared.append({"row": row.model_dump(), "password": password, "user": {"_id": identifier, "username": row.code.lower(), "identity_code": row.code, "login_keys": [row.code.lower(), row.email], "login_email": row.email, "email_verified": True, "display_name": row.display_name, "salt": salt, "password_hash": password_hash(password, salt), "role": row.role, "disabled": False, "revision": 1, "auth_version": 1, "must_change_password": True, "created_at": now().isoformat(), "provision_batch": payload.batch_id}})
            sealed = _dpapi(json.dumps({"columns": payload.columns, "prepared": prepared}, ensure_ascii=False).encode("utf-8"), decrypt=False)
            try:
                self.db.auth_provision_batches.insert_one({"_id": payload.batch_id, "owner_id": owner, "digest": digest, "sealed": sealed, "created_at": now(), "expires_at": now() + timedelta(hours=24), "state": "pending"})
            except DuplicateKeyError:
                pass
            current = self.db.auth_provision_batches.find_one({"_id": payload.batch_id})
        if current["owner_id"] != owner or current["digest"] != digest or current["expires_at"].replace(tzinfo=now().tzinfo) <= now():
            raise HTTPException(409, "provision_request_changed")
        if current["state"] == "completed": return self.summary(current)
        lease = uuid4().hex
        acquired = self.db.auth_provision_batches.find_one_and_update({"_id": payload.batch_id, "$or": [{"lease_until": {"$exists": False}}, {"lease_until": {"$lt": now()}}]}, {"$set": {"lease": lease, "lease_until": now() + timedelta(minutes=5)}}, return_document=ReturnDocument.AFTER)
        if acquired is None: raise HTTPException(409, "provision_in_progress")
        try:
            data = self.unseal(acquired); states = []
            for item in data["prepared"]:
                user = item["user"]
                if self.db.auth_users.find_one({"_id": user["_id"]}, {"_id": 1}):
                    states.append("created"); continue
                try:
                    self.db.auth_users.insert_one(user); states.append("created")
                    self.access.audit(owner, "account_provisioned", user["_id"], role=user["role"], batch_id=payload.batch_id)
                except DuplicateKeyError:
                    states.append("duplicate")
            current = self.db.auth_provision_batches.find_one_and_update({"_id": payload.batch_id, "lease": lease}, {"$set": {"state": "completed", "states": states}, "$unset": {"lease": "", "lease_until": ""}}, return_document=ReturnDocument.AFTER)
            return self.summary(current)
        finally:
            self.db.auth_provision_batches.update_one({"_id": payload.batch_id, "lease": lease}, {"$unset": {"lease": "", "lease_until": ""}})

    def unseal(self, batch):
        try: return json.loads(_dpapi(bytes(batch["sealed"]), decrypt=True))
        except Exception: raise HTTPException(409, "provision_export_machine") from None

    def summary(self, batch):
        states = batch.get("states", [])
        return {"batch_id": batch["_id"], "created": states.count("created"), "failed": states.count("duplicate"), "state": batch["state"], "created_at": batch["created_at"].isoformat(), "expires_at": batch["expires_at"].isoformat()}

    def recent(self):
        self.access.require_admin()
        return {"items": [self.summary(batch) for batch in self.db.auth_provision_batches.find({"owner_id": self.access.actor["id"], "expires_at": {"$gt": now()}}).sort("created_at", -1).limit(10)]}

    def resume(self, identifier):
        self.access.require_admin()
        batch = self.db.auth_provision_batches.find_one({"_id": identifier, "owner_id": self.access.actor["id"], "expires_at": {"$gt": now()}})
        if batch is None: raise HTTPException(404, "provision_export_unavailable")
        data = self.unseal(batch)
        return self.issue(ProvisionBatch(batch_id=identifier, columns=data["columns"], rows=[item["row"] for item in data["prepared"]]))

    def export(self, identifier):
        self.access.require_admin()
        batch = self.db.auth_provision_batches.find_one({"_id": identifier, "owner_id": self.access.actor["id"], "state": "completed", "expires_at": {"$gt": now()}})
        if batch is None: raise HTTPException(404, "provision_export_unavailable")
        data = self.unseal(batch)
        columns = [*data["columns"], "Tên đăng nhập", "Vai trò", "Mật khẩu tạm", "Kết quả"]
        rows = [[*item["row"]["values"], item["user"]["username"], "Giảng viên" if item["row"]["role"] == "teacher" else "Sinh viên", item["password"] if state == "created" else "", "Đã cấp — đổi mật khẩu khi đăng nhập" if state == "created" else "Trùng mã/email — chưa cấp"] for item, state in zip(data["prepared"], batch["states"])]
        return spreadsheet(columns, rows)
