from contextlib import asynccontextmanager
import asyncio
from datetime import datetime, timezone
from secrets import compare_digest
from pathlib import Path
import re
from uuid import UUID, uuid4
from urllib.parse import urlsplit
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
import json
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.exceptions import RequestValidationError
from pymongo.errors import PyMongoError
from anyio import CancelScope
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.db import connect_database
from app.schemas import CaseReviewCreate, IssueReviewCreate, Project, ProjectCreate
from app.inspections import ASSET_FILES, FILE_LIMITS, InspectionService, UploadLimitMiddleware, stream_job
from app.alignment import DrawingLinkCreate, create_link
from app.clash_jobs import create_clash, stream_clash
from app.dwg import discover_converter
from app.limits import INSPECTION_TIMEOUT, MAX_REPORT_BYTES, processing_limits
from app.rules import ClashRequest
from app.projects import ProjectStore
from app.storage import configured_storage, cancellable_sync
from app.project_cleanup import project_data_lock
from app.ai import AiService, AdviceRequest, AdviceFeedback, configured_ai
from app.run_conclusions import RunConclusions
from app.access import AccessStore, actor_context
from app.access_routes import Registration, attach_access_routes
from app.account_management_routes import attach_account_management_routes
from app.practice_routes import attach_practice_routes

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "inspections"


def create_app(
    *,
    api_token: str,
    mongo_uri: str = "mongodb://127.0.0.1:27017",
    database_name: str = "bim_insight",
    data_dir: Path = DEFAULT_DATA_DIR,
    upload_limit_bytes: int = FILE_LIMITS["ifc"],
    inspection_timeout: float = INSPECTION_TIMEOUT,
    session_id: str | None = None,
    web_origin: str | None = None,
    initial_admin: Registration | None = None,
    web_demo: bool = False,
    frontend_origin: str | None = None,
) -> FastAPI:
    if len(api_token) < 32:
        raise ValueError("A local session token of at least 32 characters is required")
    mongo = connect_database(mongo_uri, database_name)
    database = mongo[database_name]
    storage = {"database": database_name, "host": urlsplit(mongo_uri).hostname}
    r2_error = None
    try:
        r2 = configured_storage(database, Path(data_dir))
    except ValueError:
        r2, r2_error = None, "storage_configuration_invalid"
    access = AccessStore(database, Path(data_dir))
    projects = ProjectStore(database, Path(data_dir), storage=r2, access=access)
    inspections = InspectionService(data_dir, inspection_timeout, upload_limit_bytes, session_id, projects=projects)
    try:
        ai = AiService(projects, inspections, configured_ai(Path(data_dir)))
    except ValueError:
        ai = AiService(projects, inspections, None, "ai_configuration_invalid")
    conclusions = RunConclusions(ai)
    origins = [
        "http://localhost:1420", "http://127.0.0.1:1420", "tauri://localhost",
        "http://tauri.localhost", "https://tauri.localhost",
    ]
    if web_origin:
        origins = [web_origin]
        if frontend_origin:
            origins.append(frontend_origin)

    @asynccontextmanager
    async def lifespan(_app):
        try:
            if web_origin:
                def ensure_admin():
                    if access.state()["setup_required"]:
                        if initial_admin is None:
                            raise ValueError("Initial web administrator is required")
                        session = access.create_account(initial_admin, bootstrap=True)
                        access.logout(session["session_token"])
                await asyncio.to_thread(ensure_admin)
            yield
        finally:
            mongo.close()
            inspections.cleanup()

    app = FastAPI(title="BIM Insight Local API", version="0.12.0", lifespan=lifespan)
    app.add_middleware(UploadLimitMiddleware, limit=upload_limit_bytes + 64 * 1024)
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-BIM-Session"],
    )
    allowed_hosts = ["localhost", "127.0.0.1", "[::1]"]
    if web_origin:
        allowed_hosts.append(urlsplit(web_origin).hostname)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def guard_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in origins:
            return JSONResponse(status_code=403, content={"detail": "origin_not_allowed"})
        if request.url.path.startswith(("/api/inspections", "/api/projects", "/api/auth", "/api/admin", "/api/practice", "/api/ready")) and request.method != "OPTIONS":
            scheme, _, credential = request.headers.get("authorization", "").partition(" ")
            if not web_origin and (scheme.lower() != "bearer" or not compare_digest(credential.encode("utf-8"), api_token.encode("utf-8"))):
                return JSONResponse(status_code=401, content={"detail": "invalid_session_token"})
            if web_origin and request.url.path == "/api/auth/bootstrap":
                return JSONResponse(status_code=403, content={"detail": "setup_already_completed"})
            public = {"/api/auth/state", "/api/auth/bootstrap", "/api/auth/register", "/api/auth/login", "/api/auth/recovery/request", "/api/auth/recovery/confirm", "/api/ready"}
            if request.url.path not in public:
                try:
                    actor = await asyncio.to_thread(access.authenticate, request.headers.get("x-bim-session", ""))
                    if actor.get("must_change_password") and request.url.path not in {"/api/auth/me", "/api/auth/logout", "/api/auth/password"}:
                        raise HTTPException(403, "password_change_required")
                except HTTPException as error:
                    return JSONResponse(status_code=error.status_code, content={"detail": error.detail}, headers=error.headers)
                except PyMongoError:
                    return JSONResponse(status_code=503, content={"detail": "database_unavailable"})
                context = actor_context.set(actor)
                try:
                    return await call_next(request)
                finally:
                    actor_context.reset(context)
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, error):
        # Validation errors must never echo passwords or other submitted credentials.
        return JSONResponse(status_code=422, content={"detail": [{key: row[key] for key in ("loc", "msg", "type")} for row in error.errors()]})

    attach_access_routes(app, access)
    attach_account_management_routes(app, access)
    attach_practice_routes(app, projects, ai)

    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False))):
        if web_origin:
            # Account authentication and project permissions are enforced by guard_origin and routes.
            return
        if credentials is None or not compare_digest(credentials.credentials.encode("utf-8"), api_token.encode("utf-8")):
            raise HTTPException(status_code=401, detail="invalid_session_token")

    @app.exception_handler(PyMongoError)
    async def database_unavailable(_request, _error):
        return JSONResponse(status_code=503, content={"detail": "database_unavailable"})

    @app.get("/api/health")
    def health():
        return {
            "status": "ok", "version": "0.12.0",
            "deployment": "web_demo" if web_demo else "web" if web_origin else "desktop",
            "capabilities": {"clash_detection": "cross_source_ifc_geometry", "trained_ai": "not_verified", "file_inspection": True, "cad_preview": True, "ifc_viewer": True, "grid_alignment": True},
            "file_limits": {kind: min(limit, upload_limit_bytes) for kind, limit in FILE_LIMITS.items()},
            "processing_limits": {**processing_limits(), "timeout_seconds": inspection_timeout},
        }

    @app.post("/api/inspections", dependencies=[Depends(authorize)])
    async def inspect_upload(request: Request):
        if "application/x-ndjson" in request.headers.get("accept", ""):
            await request.form(max_files=1, max_fields=4, max_part_size=1024)
            async def execute(progress):
                report = await inspections.inspect(request, progress=progress)
                await asyncio.to_thread(access.register_artifact, "report", report)
                return report
            return StreamingResponse(stream_job(execute, cleanup=request.close), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        report = await inspections.inspect(request)
        await asyncio.to_thread(access.register_artifact, "report", report)
        return report

    @app.get("/api/inspections/dwg-converter", dependencies=[Depends(authorize)])
    def dwg_converter_status():
        converter = discover_converter()
        return {"available": converter is not None, "engine": "ODA File Converter", "version": converter["version"] if converter else None}

    @app.post("/api/inspections/clashes", dependencies=[Depends(authorize)])
    async def clash_models(payload: ClashRequest, request: Request):
        for identifier in payload.model_ids:
            await asyncio.to_thread(access.require_artifact, "report", identifier, "edit")
        if payload.link_id:
            await asyncio.to_thread(access.require_artifact, "link", payload.link_id, "edit")
        if "application/x-ndjson" in request.headers.get("accept", ""):
            async def save_report(report):
                await asyncio.to_thread(access.register_artifact, "clash", report)
            return StreamingResponse(stream_clash(inspections, request, payload, save_report), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        report = await create_clash(inspections, request, payload)
        await asyncio.to_thread(access.register_artifact, "clash", report)
        return report

    @app.get("/api/inspections/clashes/{clash_id}", dependencies=[Depends(authorize)])
    def clash_report(clash_id: str):
        access.require_artifact("clash", clash_id)
        if not re.fullmatch(r"[a-f0-9]{32}", clash_id):
            raise HTTPException(404, "report_not_found")
        path = projects.ensure_local(f"clashes/{clash_id}.json")
        if not path.is_file():
            raise HTTPException(404, "report_not_found")
        return FileResponse(path, media_type="application/json", filename=f"clashes-{clash_id}.json")

    def save_alignment(payload):
        for identifier in [payload.model_id, payload.drawing_id]:
            access.require_artifact("report", identifier, "edit")
            projects.ensure_local(f"reports/{identifier}.json")
        link = create_link(Path(data_dir), payload)
        if link.get("id") and link.get("project_id"):
            database.project_links.insert_one({"_id": link["id"], "project_id": link["project_id"]})
        if link.get("id"):
            access.register_artifact("link", link)
        return link

    async def finish_thread(operation, *args):
        task = asyncio.create_task(asyncio.to_thread(operation, *args))
        try:
            return await asyncio.shield(task)
        finally:
            with CancelScope(shield=True):
                await task

    @app.post("/api/inspections/alignments", dependencies=[Depends(authorize)])
    async def align_drawing(payload: DrawingLinkCreate):
        async with inspections.slot:
            return await finish_thread(save_alignment, payload)

    @app.get("/api/inspections/alignments/{link_id}", dependencies=[Depends(authorize)])
    def get_drawing_link(link_id: str):
        access.require_artifact("link", link_id)
        if not re.fullmatch(r"[a-f0-9]{32}", link_id):
            raise HTTPException(404, "link_not_found")
        path = projects.ensure_local(f"links/{link_id}.json")
        if not path.is_file():
            raise HTTPException(404, "link_not_found")
        return FileResponse(path, media_type="application/json", filename=f"drawing-link-{link_id}.json")

    @app.get("/api/inspections/{inspection_id}/report", dependencies=[Depends(authorize)])
    def inspection_report(inspection_id: str, full: bool = False):
        access.require_artifact("report", inspection_id)
        if not re.fullmatch(r"[a-f0-9]{32}", inspection_id):
            raise HTTPException(404, "report_not_found")
        path = projects.ensure_local(f"reports/{inspection_id}.json")
        if not path.is_file():
            raise HTTPException(404, "report_not_found")
        if full:
            report = projects.read_report(inspection_id)
            if report.get("assets", {}).get("details"):
                details = projects.ensure_local(f"assets/{inspection_id}/inspection.json")
                if not details.is_file() or details.stat().st_size > MAX_REPORT_BYTES:
                    raise HTTPException(409, "project_artifact_missing")

                def stream():
                    envelope = {key: value for key, value in report.items() if key != "result"}
                    yield (json.dumps(envelope, ensure_ascii=False, allow_nan=False)[:-1] + ',"result":').encode("utf-8")
                    with details.open("rb") as handle:
                        while chunk := handle.read(64 * 1024):
                            yield chunk
                    yield b"}"

                return StreamingResponse(stream(), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="inspection-{inspection_id}.json"', "X-Content-Type-Options": "nosniff"})
        return FileResponse(path, media_type="application/json", filename=f"inspection-{inspection_id}.json")

    @app.get("/api/inspections/{inspection_id}/assets/{asset_name}", dependencies=[Depends(authorize)])
    def inspection_asset(inspection_id: str, asset_name: str):
        access.require_artifact("report", inspection_id)
        if not re.fullmatch(r"[a-f0-9]{32}", inspection_id) or asset_name not in ASSET_FILES:
            raise HTTPException(404, "asset_not_found")
        path = projects.ensure_local(f"assets/{inspection_id}/{asset_name}")
        if not path.is_file() or not projects.ensure_local(f"reports/{inspection_id}.json").is_file():
            raise HTTPException(404, "asset_not_found")
        return FileResponse(path, media_type="model/gltf-binary" if asset_name.endswith(".glb") else "application/dxf" if asset_name.endswith(".dxf") else "application/json", filename="converted.dxf" if asset_name.endswith(".dxf") else None, headers={"X-Content-Type-Options": "nosniff"})

    @app.get("/api/ready", dependencies=[Depends(authorize)])
    def ready():
        mongo.admin.command("ping")
        return {"status": "ready", "mongodb": "connected", "storage": storage}

    @app.post("/api/projects", response_model=Project, status_code=201, dependencies=[Depends(authorize)])
    def create_project(payload: ProjectCreate):
        document = {"_id": str(uuid4()), "created_at": datetime.now(timezone.utc).isoformat(), **payload.model_dump(), "owner_id": access.actor["id"], "members": []}
        database.projects.insert_one(document)
        return access.project_info(document)

    @app.get("/api/projects", dependencies=[Depends(authorize)])
    def list_projects(offset: int = Query(default=0, ge=0, le=100000), limit: int = Query(default=20, ge=1, le=100), scope: Literal["all", "owned", "shared"] = "all"):
        return {**projects.list_projects(offset, limit, scope), "storage": storage}

    @app.get("/api/projects/storage", dependencies=[Depends(authorize)])
    def storage_status():
        return r2.status() if r2 else {"configured": False, "error": r2_error}

    @app.get("/api/projects/ai/runtime", dependencies=[Depends(authorize)])
    def ai_runtime():
        return ai.status()

    @app.get("/api/projects/{project_id}/runs/{run_id}/conclusions", dependencies=[Depends(authorize)])
    def conclusion_history(project_id: UUID, run_id: str, offset: int = Query(default=0, ge=0, le=100000), limit: int = Query(default=5, ge=1, le=20)):
        return conclusions.history(project_id, run_id, offset, limit)

    @app.post("/api/projects/{project_id}/runs/{run_id}/conclusions", dependencies=[Depends(authorize)])
    async def generate_conclusion(project_id: UUID, run_id: str, request: Request):
        await asyncio.to_thread(access.require_project, project_id, "review")
        return await conclusions.generate(request, project_id, run_id)

    @app.get("/api/projects/{project_id}/runs/{run_id}/issues/{issue_id}/advice", dependencies=[Depends(authorize)])
    def ai_history(project_id: UUID, run_id: str, issue_id: str, offset: int = Query(default=0, ge=0, le=100000), limit: int = Query(default=5, ge=1, le=20)):
        return ai.history(project_id, run_id, issue_id, offset, limit)

    @app.post("/api/projects/{project_id}/runs/{run_id}/issues/{issue_id}/advice", dependencies=[Depends(authorize)])
    async def generate_advice(project_id: UUID, run_id: str, issue_id: str, payload: AdviceRequest, request: Request):
        await asyncio.to_thread(access.require_project, project_id, "review")
        return await ai.generate(request, project_id, run_id, issue_id, payload)

    @app.post("/api/projects/{project_id}/runs/{run_id}/issues/{issue_id}/advice/{advice_id}/feedback", dependencies=[Depends(authorize)])
    def advice_feedback(project_id: UUID, run_id: str, issue_id: str, advice_id: str, payload: AdviceFeedback):
        access.require_project(project_id, "review")
        return ai.feedback(project_id, run_id, issue_id, advice_id, payload)

    @app.get("/api/projects/{project_id}/storage", dependencies=[Depends(authorize)])
    def project_storage(project_id: UUID, offset: int = Query(default=0, ge=0, le=100000), limit: int = Query(default=20, ge=1, le=100)):
        projects.require_project(project_id)
        if not r2:
            return {"configured": False, "error": r2_error, "items": [], "total": 0}
        query = {"namespace": r2.namespace, "project_id": str(project_id)}
        references = list(database.storage_refs.find(query).sort("_id").skip(offset).limit(limit))
        records = list(database.storage_files.find({"_id": {"$in": [item["file_id"] for item in references]}}, {"_id": 0, "relative": 1, "sha256": 1, "size_bytes": 1, "status": 1, "verified_at": 1}))
        return {**r2.status(), "items": records, "total": database.storage_refs.count_documents(query), "offset": offset, "limit": limit}

    @app.post("/api/projects/{project_id}/storage/sync", dependencies=[Depends(authorize)])
    async def sync_project(project_id: UUID, request: Request):
        await asyncio.to_thread(access.require_project, project_id, "edit")
        if not r2:
            raise HTTPException(409, r2_error or "storage_not_configured")
        def sync_files(cancel, check_lock):
            paths = projects.backup_paths(project_id)
            verified = 0
            for relative in paths:
                check_lock()
                try:
                    r2.backup_file(str(project_id), relative, cancel)
                    verified += 1
                except HTTPException as error:
                    if error.status_code == 499:
                        raise
                    return {"status": "partial", "verified_files": verified, "total_files": len(paths), "failed_file": relative, "error": error.detail}
            return {"status": "verified", "verified_files": verified, "total_files": len(paths)}
        def sync(cancel):
            with project_data_lock(database) as check_lock:
                return sync_files(cancel, check_lock)
        async with inspections.slot:
            return await cancellable_sync(request, sync)

    @app.get("/api/projects/{project_id}/inspections", dependencies=[Depends(authorize)])
    def project_inspections(project_id: UUID, offset: int = Query(default=0, ge=0, le=100000), limit: int = Query(default=20, ge=1, le=100), revision: str | None = Query(default=None, min_length=1, max_length=80)):
        return projects.inspections(project_id, offset, limit, revision)

    @app.get("/api/projects/{project_id}/runs", dependencies=[Depends(authorize)])
    def project_runs(project_id: UUID, offset: int = Query(default=0, ge=0, le=100000), limit: int = Query(default=20, ge=1, le=100)):
        return projects.runs(project_id, offset, limit)

    @app.get("/api/projects/{project_id}/runs/{run_id}", dependencies=[Depends(authorize)])
    def restore_project_run(project_id: UUID, run_id: str):
        return projects.restore_run(project_id, run_id)

    @app.get("/api/projects/{project_id}/runs/{run_id}/reviews", dependencies=[Depends(authorize)])
    def project_run_reviews(project_id: UUID, run_id: str):
        return projects.reviews(project_id, run_id)

    @app.post("/api/projects/{project_id}/runs/{run_id}/issues/{issue_id}/review", dependencies=[Depends(authorize)])
    def review_project_issue(project_id: UUID, run_id: str, issue_id: str, payload: IssueReviewCreate):
        access.require_project(project_id, "review")
        return projects.review_issue(project_id, run_id, issue_id, payload)

    @app.post("/api/projects/{project_id}/runs/{run_id}/cases/{case_id}/review", dependencies=[Depends(authorize)])
    def review_project_case(project_id: UUID, run_id: str, case_id: str, payload: CaseReviewCreate):
        access.require_project(project_id, "review")
        return projects.review_case(project_id, run_id, case_id, payload)

    @app.get("/api/projects/{project_id}/runs/{run_id}/dataset", dependencies=[Depends(authorize)])
    def export_project_dataset(project_id: UUID, run_id: str):
        return JSONResponse(projects.export_dataset(project_id, run_id), headers={"Content-Disposition": f'attachment; filename="dataset-{run_id}.json"', "X-Content-Type-Options": "nosniff"})

    @app.get("/api/projects/{project_id}", response_model=Project, dependencies=[Depends(authorize)])
    def get_project(project_id: UUID):
        return access.project_info(access.require_project(project_id, allow_deleting=True))

    @app.delete("/api/projects/{project_id}", dependencies=[Depends(authorize)])
    async def delete_project(project_id: UUID):
        await asyncio.to_thread(access.require_project, project_id, "delete")
        if inspections.slot.locked():
            raise HTTPException(409, "project_busy")
        async with inspections.slot:
            return await finish_thread(projects.delete_project, project_id)

    return app
