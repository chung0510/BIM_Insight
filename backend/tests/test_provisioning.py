from uuid import uuid4
from io import BytesIO
import json
from datetime import timedelta

from openpyxl import Workbook, load_workbook
import pytest

from test_access import access_workspace, account, headers, PASSWORD
from test_api import AUTH


def temporary_password(client, admin, identifier):
    result = client.get(f"/api/admin/provision/batches/{identifier}/export", headers=headers(admin))
    assert result.status_code == 200, result.text
    workbook = load_workbook(BytesIO(result.content))
    rows = list(workbook.active.values)
    value = rows[1][rows[0].index("Mật khẩu tạm")]
    workbook.close()
    return value


def batch(code="001234", role="teacher", email="teacher@example.org"):
    return {"batch_id": uuid4().hex, "columns": ["Full name", "Staff code", "email"], "rows": [{"role": role, "code": code, "display_name": "Test Teacher", "email": email, "values": ["Test Teacher", code, email], "source_row": 2}]}


def test_original_cell_whitespace_is_preserved_while_identity_is_normalized():
    from app.provisioning import ProvisionRow
    row = ProvisionRow(role="teacher", code=" 001234 ", display_name="  Teacher One  ", email=" TEACHER@example.org ", values=["  Teacher One  ", "001234", " TEACHER@example.org ", "  preserve original  "])
    assert row.display_name == "Teacher One" and row.email == "teacher@example.org"
    assert row.values[0] == "  Teacher One  " and row.values[-1] == "  preserve original  "


def test_only_admin_can_provision_and_admin_role_cannot_be_injected(access_workspace):
    client, database, _ = access_workspace
    admin = account(client, "administrator", bootstrap=True)
    user = account(client, "ordinary")
    assert client.post("/api/admin/provision/batches", headers=headers(user), json=batch()).status_code == 403
    assert client.post("/api/admin/provision/batches", headers=headers(admin), json=batch(role="admin")).status_code == 422
    assert database.auth_users.count_documents({}) == 2


def test_provision_is_retry_safe_and_forces_password_change_server_side(access_workspace):
    client, database, _ = access_workspace
    admin = account(client, "administrator", bootstrap=True)
    payload = batch()
    response = client.post("/api/admin/provision/batches", headers=headers(admin), json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["created"] == 1
    again = client.post("/api/admin/provision/batches", headers=headers(admin), json=payload)
    assert again.status_code in {200, 201} and again.json()["created"] == 1
    assert database.auth_users.count_documents({"username": "001234"}) == 1
    user = database.auth_users.find_one({"username": "001234"})
    assert user["must_change_password"] is True and user["role"] == "teacher"
    assert "password" not in user and user["password_hash"]
    export = client.get(f"/api/admin/provision/batches/{payload['batch_id']}/export", headers=headers(admin))
    assert export.status_code == 200 and export.content.startswith(b"PK")
    password = temporary_password(client, admin, payload["batch_id"])
    assert len(password) >= 12 and password not in response.text
    assert password not in json.dumps(database.auth_users.find_one({"username": "001234"}), default=str)
    assert password not in json.dumps(database.auth_provision_batches.find_one({"_id": payload["batch_id"]}), default=str)
    login = client.post("/api/auth/login", headers=AUTH, json={"username": "001234", "password": password})
    assert login.status_code == 200 and login.json()["user"]["must_change_password"]
    session = login.json()
    assert client.get("/api/projects", headers=headers(session)).status_code == 403
    assert client.get("/api/auth/profile", headers=headers(session)).status_code == 403
    assert client.post("/api/auth/password", headers=headers(session), json={"current_password": password, "new_password": password}).status_code == 422
    changed = client.post("/api/auth/password", headers=headers(session), json={"current_password": password, "new_password": PASSWORD})
    assert changed.status_code == 200 and not changed.json()["user"]["must_change_password"]
    assert client.get("/api/projects", headers=headers(changed.json())).status_code == 200
    assert client.get("/api/auth/me", headers=headers(session)).status_code == 401
    assert client.post("/api/auth/login", headers=AUTH, json={"username": "TEACHER@example.org", "password": PASSWORD}).status_code == 200
    assert client.post("/api/auth/login", headers=AUTH, json={"username": "001234", "password": password}).status_code == 401


def test_batch_rejects_duplicate_email_or_request_reuse_with_different_data(access_workspace):
    client, database, _ = access_workspace
    admin = account(client, "administrator", bootstrap=True)
    payload = batch()
    assert client.post("/api/admin/provision/batches", headers=headers(admin), json=payload).status_code == 201
    assert client.post("/api/admin/provision/batches", headers=headers(admin), json={**payload, "rows": batch(code="001235")["rows"]}).status_code == 409
    result = client.post("/api/admin/provision/batches", headers=headers(admin), json=batch(code="001236"))
    assert result.status_code == 422
    assert database.auth_users.count_documents({}) == 2


def test_excel_preview_preserves_headers_extra_columns_and_leading_zero_codes(access_workspace):
    client, _, _ = access_workspace
    admin = account(client, "administrator", bootstrap=True)
    template = client.get("/api/admin/provision/template?role=teacher", headers=headers(admin))
    template_book = load_workbook(BytesIO(template.content))
    assert template_book.active.column_dimensions["B"].number_format == "@"
    template_book.close()
    book = Workbook(); sheet = book.active
    sheet.append(["Họ và tên", "Mã giảng viên", "email", "Đơn vị"])
    sheet.append(["Nguyễn Văn A", "001234", "gv@example.org", "Khoa Xây dựng"])
    sheet.append(["Trần Văn B", 12, "gv2@example.org", "Khoa Xây dựng"])
    sheet.cell(3, 2).number_format = "000000"
    stream = BytesIO(); book.save(stream); book.close()
    response = client.post("/api/admin/provision/preview", headers=headers(admin), files={"file": ("teachers.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["valid_count"] == 2 and not preview["errors"]
    assert preview["columns"][-1] == "Đơn vị"
    assert [row["code"] for row in preview["rows"]] == ["001234", "000012"]
    assert all(row["role"] == "teacher" for row in preview["rows"])
    assert preview["rows"][0]["values"][-1] == "Khoa Xây dựng"
    payload = {"batch_id": uuid4().hex, "columns": preview["columns"], "rows": preview["rows"]}
    assert client.post("/api/admin/provision/batches", headers=headers(admin), json=payload).json()["created"] == 2
    exported = client.get(f"/api/admin/provision/batches/{payload['batch_id']}/export", headers=headers(admin))
    book = load_workbook(BytesIO(exported.content)); rows = list(book.active.values); book.close()
    assert rows[0][:4] == tuple(preview["columns"])
    assert rows[1][:4] == tuple(preview["rows"][0]["values"])


def test_excel_preview_reports_duplicate_codes_and_rejects_formulas(access_workspace):
    client, database, _ = access_workspace
    admin = account(client, "administrator", bootstrap=True)
    book = Workbook(); sheet = book.active
    sheet.append(["Họ và tên", "Mã sinh viên", "email"])
    sheet.append(["Sinh viên A", "000123", "student1@example.org"])
    sheet.append(["Sinh viên B", "000123", "student2@example.org"])
    stream = BytesIO(); book.save(stream)
    response = client.post("/api/admin/provision/preview", headers=headers(admin), files={"file": ("students.xlsx", stream.getvalue())})
    assert response.status_code == 200 and response.json()["errors"]
    assert database.auth_users.count_documents({}) == 1
    sheet.cell(3, 2).value = '=HYPERLINK("https://example.org")'
    stream = BytesIO(); book.save(stream); book.close()
    response = client.post("/api/admin/provision/preview", headers=headers(admin), files={"file": ("students.xlsx", stream.getvalue())})
    assert response.status_code == 422


def test_long_numeric_codes_require_text_cells_instead_of_silent_rounding(access_workspace):
    client, _, _ = access_workspace
    admin = account(client, "administrator", bootstrap=True)
    book = Workbook(); sheet = book.active
    sheet.append(["Họ và tên", "Mã sinh viên", "email"])
    sheet.append(["Sinh viên A", 123456789012345678, "long@example.org"])
    sheet.append(["Sinh viên B", "00123456789012345678", "text@example.org"])
    stream = BytesIO(); book.save(stream); book.close()
    result = client.post("/api/admin/provision/preview", headers=headers(admin), files={"file": ("long-codes.xlsx", stream.getvalue())})
    assert result.status_code == 200
    assert result.json()["errors"] == [{"row": 2, "code": "excel_code_as_text_required"}]
    assert result.json()["valid_count"] == 1 and result.json()["rows"][0]["code"] == "00123456789012345678"


def test_large_excel_and_bulk_json_are_not_blocked_by_generic_64k_limit(access_workspace):
    import secrets
    client, _, _ = access_workspace
    admin = account(client, "administrator", bootstrap=True)
    book = Workbook(); sheet = book.active
    sheet.append(["Họ và tên", "Mã giảng viên", "email", *[f"Extra {index}" for index in range(17)]])
    for index in range(20):
        sheet.append([f"Teacher {index}", f"0023{index:02d}", f"teacher{index}@example.org", *[secrets.token_hex(250) for _ in range(17)]])
    stream = BytesIO(); book.save(stream); book.close(); data = stream.getvalue()
    assert 64 * 1024 < len(data) < 2 * 1024 * 1024
    result = client.post("/api/admin/provision/preview", headers=headers(admin), files={"file": ("large.xlsx", data)})
    assert result.status_code == 200, result.text
    preview = result.json(); assert not preview["errors"] and preview["valid_count"] == 20
    payload = {"batch_id": uuid4().hex, "columns": preview["columns"], "rows": preview["rows"]}
    assert len(json.dumps(payload)) > 64 * 1024
    issued = client.post("/api/admin/provision/batches", headers=headers(admin), json=payload)
    assert issued.status_code == 201 and issued.json()["created"] == 20
    oversized = client.post("/api/admin/provision/preview", headers=headers(admin), files={"file": ("too-big.xlsx", b"x"*(3*1024*1024))})
    assert oversized.status_code == 413


def test_export_is_admin_owned_expiring_and_has_no_executable_cells(access_workspace):
    client, database, _ = access_workspace
    admin = account(client, "administrator", bootstrap=True)
    user = account(client, "ordinary")
    payload = batch(); payload["columns"].append("Note"); payload["rows"][0]["values"].append("=1+1")
    assert client.post("/api/admin/provision/batches", headers=headers(admin), json=payload).status_code == 201
    url = f"/api/admin/provision/batches/{payload['batch_id']}/export"
    assert client.get(url, headers=headers(user)).status_code == 403
    result = client.get(url, headers=headers(admin)); book = load_workbook(BytesIO(result.content))
    assert book.active.cell(2, 4).value == "=1+1" and book.active.cell(2, 4).data_type == "s"
    book.close()
    from app.access import now
    database.auth_provision_batches.update_one({"_id": payload["batch_id"]}, {"$set": {"expires_at": now() - timedelta(seconds=1)}})
    assert client.get(url, headers=headers(admin)).status_code == 404


def test_interrupted_batch_can_resume_without_losing_original_passwords(access_workspace, monkeypatch):
    from pymongo.collection import Collection
    from pymongo.errors import PyMongoError
    client, database, _ = access_workspace
    admin = account(client, "administrator", bootstrap=True)
    payload = batch()
    second = batch(code="001235", email="second@example.org")["rows"][0]; second["source_row"] = 3
    payload["rows"].append(second)
    original = Collection.insert_one
    def interrupted(collection, document, *args, **kwargs):
        if collection.name == "auth_users" and document.get("username") == "001235":
            raise PyMongoError("Simulated local interruption")
        return original(collection, document, *args, **kwargs)
    monkeypatch.setattr(Collection, "insert_one", interrupted)
    assert client.post("/api/admin/provision/batches", headers=headers(admin), json=payload).status_code == 503
    assert database.auth_users.count_documents({"provision_batch": payload["batch_id"]}) == 1
    monkeypatch.setattr(Collection, "insert_one", original)
    resumed = client.post(f"/api/admin/provision/batches/{payload['batch_id']}/resume", headers=headers(admin), json={})
    assert resumed.status_code == 200 and resumed.json()["created"] == 2
    assert database.auth_users.count_documents({"provision_batch": payload["batch_id"]}) == 2
    assert temporary_password(client, admin, payload["batch_id"])

