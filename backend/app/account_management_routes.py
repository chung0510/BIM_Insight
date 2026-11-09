from fastapi import BackgroundTasks, HTTPException, Path, Request
from fastapi.responses import Response

from app.account_mail import GmailMailer, GmailSettings
from app.provisioning import MAX_BYTES, ProvisionBatch, ProvisionStore, spreadsheet
from app.recovery import CodeConfirmation, EmailRequest, RecoveryConfirmation, RecoveryRequest, RecoveryService


def attach_account_management_routes(app, access):
    provision = ProvisionStore(access); mailer = GmailMailer(access.directory); recovery = RecoveryService(access, mailer)

    def xlsx(data, filename):
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.get("/api/admin/provision/template")
    def template(role: str = "teacher"):
        access.require_admin()
        if role not in {"teacher", "student"}: raise HTTPException(422, "provision_role_invalid")
        code = "Mã giảng viên" if role == "teacher" else "Mã sinh viên"
        return xlsx(spreadsheet(["Họ và tên", code, "email"], []), f"bim-insight-{role}-template.xlsx")

    @app.post("/api/admin/provision/preview")
    async def preview(request: Request):
        access.require_admin()
        form = await request.form(max_files=1, max_fields=0)
        try:
            file = form.get("file")
            if file is None or not hasattr(file, "read"): raise HTTPException(422, "excel_file_invalid")
            data = await file.read(MAX_BYTES + 1)
            from starlette.concurrency import run_in_threadpool
            return await run_in_threadpool(provision.preview, data, file.filename or "")
        finally:
            await form.close()

    @app.post("/api/admin/provision/batches", status_code=201)
    def issue(payload: ProvisionBatch):
        return provision.issue(payload)

    @app.get("/api/admin/provision/batches")
    def recent():
        return provision.recent()

    @app.get("/api/admin/provision/batches/{identifier}/export")
    def export(identifier: str = Path(pattern=r"^[a-f0-9]{32}$")):
        return xlsx(provision.export(identifier), f"bim-insight-accounts-{identifier[:8]}.xlsx")

    @app.post("/api/admin/provision/batches/{identifier}/resume")
    def resume(identifier: str = Path(pattern=r"^[a-f0-9]{32}$")):
        return provision.resume(identifier)

    @app.get("/api/admin/mail")
    def mail_status():
        access.require_admin(); return mailer.status()

    @app.post("/api/admin/mail")
    def configure_mail(payload: GmailSettings):
        access.require_admin(); return mailer.configure(payload)

    @app.post("/api/auth/recovery/request")
    def request_recovery(payload: RecoveryRequest, background: BackgroundTasks):
        return recovery.request(payload, background)

    @app.post("/api/auth/recovery/confirm")
    def confirm_recovery(payload: RecoveryConfirmation):
        return recovery.reset(payload)

    @app.post("/api/auth/email/request")
    def request_email(payload: EmailRequest, background: BackgroundTasks):
        return recovery.request(payload, background, verification=True)

    @app.post("/api/auth/email/confirm")
    def confirm_email(payload: CodeConfirmation):
        return recovery.verify_email(payload)
