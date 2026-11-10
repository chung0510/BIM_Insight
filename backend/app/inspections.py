import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from fastapi import HTTPException, Request
from anyio import CancelScope
from pymongo.errors import PyMongoError
import psutil
from starlette.datastructures import UploadFile

from app.demo import dataset_for_hash
from app.schemas import ASSET_FILES, SourceContext
from app.dwg import discover_converter
from app.limits import FILE_LIMITS, WORKER_RESULT_BYTES, geometry_memory_gb
from app.projects import utc_now
from pydantic import ValidationError


def infer_discipline(name):
    tokens = set(re.split(r"[^A-Z0-9]+", Path(name).stem.upper()))
    matches = [discipline for discipline, markers in {
        "ARCH": {"ARCH", "ARCHITECTURE", "ARCHITECTURAL", "ARK"},
        "STR": {"STR", "STRUC", "STRUCT", "STRUCTURAL", "RAK"},
        "MEP": {"MEP", "HVAC", "ELE", "ELECTRICAL", "MECHANICAL", "PLUMBING"},
    }.items() if tokens & markers]
    return matches[0] if len(matches) == 1 else "OTHER"


def discard_session(directory: Path, session: Path):
    base = Path(directory).resolve()
    temporary = (base / "tmp").resolve()
    target = Path(session).resolve()
    if temporary.parent == base and target.parent == temporary and target.name.startswith("session-") and target.is_dir():
        shutil.rmtree(target)


def recover_abandoned_sessions(directory: Path):
    for session in (Path(directory) / "tmp").glob("session-*"):
        owner_file = session / "owner.json"
        try:
            if owner_file.stat().st_size > 1024:
                continue
            owner = json.loads(owner_file.read_text(encoding="utf-8"))
            if type(owner["pid"]) is not int or owner["pid"] <= 0:
                continue
            try:
                alive = abs(psutil.Process(owner["pid"]).create_time() - float(owner["created_at"])) < 0.001
            except psutil.NoSuchProcess:
                alive = False
            if not alive:
                discard_session(directory, session)
        except (OSError, ValueError, KeyError, TypeError, psutil.AccessDenied):
            continue


class UploadLimitMiddleware:
    def __init__(self, app, limit):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        total = 0

        async def bounded_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                limit = self.limit if scope["path"] == "/api/inspections" else 64 * 1024
                if scope["path"] == "/api/admin/provision/preview":
                    limit = 2 * 1024 * 1024 + 64 * 1024
                elif scope["path"] == "/api/admin/provision/batches":
                    limit = 10 * 1024 * 1024
                elif scope["path"].startswith("/api/practice/"):
                    limit = 2*1024*1024+64*1024 if scope['path'].startswith('/api/practice/classes/') and scope['path'].endswith('/members/preview') else 1024*1024
                if total > limit:
                    raise HTTPException(413, "file_too_large")
            return message

        if scope["type"] == "http" and (scope["path"] in {"/api/inspections", "/api/inspections/clashes", "/api/inspections/alignments"} or scope["path"].startswith(("/api/projects", "/api/auth", "/api/admin", "/api/practice/"))):
            await self.app(scope, bounded_receive, send)
        else:
            await self.app(scope, receive, send)


def stop_worker(process):
    if process.poll() is not None:
        process.wait()
        return
    try:
        children = psutil.Process(process.pid).children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        children = []
    for child in reversed(children):
        try:
            child.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)
    psutil.wait_procs(children, timeout=5)


async def stream_job(operation, cleanup=None):
    queue = asyncio.Queue(maxsize=1)
    latest = {"phase": "preparing"}
    started = time.monotonic()
    def notify(value):
        nonlocal latest
        latest = value
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(value)
    task = asyncio.create_task(operation(notify))
    try:
        yield json.dumps({"type": "progress", **latest, "elapsed_seconds": 0}) + "\n"
        while not task.done():
            try:
                await asyncio.wait_for(queue.get(), 2)
            except asyncio.TimeoutError:
                pass
            yield json.dumps({"type": "progress", **latest, "elapsed_seconds": round(time.monotonic() - started, 1)}, ensure_ascii=False) + "\n"
        yield json.dumps({"type": "result", "report": await task}, ensure_ascii=False, allow_nan=False) + "\n"
    except HTTPException as error:
        yield json.dumps({"type": "error", "code": error.detail}) + "\n"
    except PyMongoError:
        yield json.dumps({"type": "error", "code": "database_unavailable"}) + "\n"
    except Exception:
        yield json.dumps({"type": "error", "code": "processing_failed"}) + "\n"
    finally:
        with CancelScope(shield=True):
            if not task.done():
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            if cleanup:
                await cleanup()


class InspectionService:
    def __init__(self, directory: Path, timeout: float, file_limit: int, session_id: str | None = None, projects=None):
        self.directory = Path(directory)
        self.timeout = timeout
        self.file_limit = file_limit
        self.projects = projects
        self.slot = asyncio.Lock()
        session_id = session_id or f"session-{os.getpid()}-{uuid4().hex}"
        if not re.fullmatch(r"session-[A-Za-z0-9-]{1,100}", session_id):
            raise ValueError("Invalid inspection session")
        self.temporary_root = self.directory / "tmp" / session_id
        recover_abandoned_sessions(self.directory)

    def cleanup(self):
        discard_session(self.directory, self.temporary_root)

    def cache_source(self, source, kind, digest):
        cache = self.directory / "cache" / ("models" if kind == "ifc" else "files") / f"{digest}.{kind}"
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            if cache.is_file() and cache.stat().st_size == source.stat().st_size:
                with cache.open("rb") as handle:
                    if hashlib.file_digest(handle, "sha256").hexdigest() == digest:
                        return
            os.replace(source, cache)
        except OSError:
            raise HTTPException(503, "source_cache_unavailable") from None

    def new_work(self, prefix):
        self.temporary_root.mkdir(parents=True, exist_ok=True)
        owner_file = self.temporary_root / "owner.json"
        owner = {"pid": os.getpid(), "created_at": psutil.Process().create_time()}
        try:
            with owner_file.open("x", encoding="utf-8") as handle:
                json.dump(owner, handle)
        except FileExistsError:
            if json.loads(owner_file.read_text(encoding="utf-8")) != owner:
                raise HTTPException(409, "inspection_session_in_use")
        return Path(tempfile.mkdtemp(prefix=prefix, dir=self.temporary_root))

    async def run_job(self, request, arguments, output, memory_gb, *, command=None, timeout=None, extra_env=None, progress=None):
        if command is None:
            command = [sys.executable]
            if not getattr(sys, "frozen", False):
                command += ["-m", "app"]
        command += [*arguments, "--parent-pid", str(os.getpid())]
        started = time.monotonic()
        process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            env={**os.environ, "XDG_CACHE_HOME": str(self.directory.resolve() / "cache"), "XDG_CONFIG_HOME": str(self.directory.resolve() / "cache" / "config"), **(extra_env or {}), "BIM_WORKER_MEMORY_BYTES": str(int(memory_gb * 1024**3))},
        )
        last_progress = None
        peak_memory = 0
        current_memory = 0
        last_sent = 0
        last_sent_phase = None
        available_memory = psutil.virtual_memory().available
        def measurements():
            return {"elapsed_seconds": round(time.monotonic() - started, 3), "memory_bytes": current_memory,
                    "peak_memory_bytes": peak_memory, "memory_limit_bytes": int(memory_gb * 1024**3),
                    "system_available_bytes": available_memory}
        def stopped(code):
            return {"processing": {**measurements(), "last_progress": last_progress}}, code
        try:
            while process.poll() is None:
                if await request.is_disconnected():
                    raise HTTPException(499, "inspection_cancelled")
                if time.monotonic() - started >= (self.timeout if timeout is None else timeout):
                    return stopped("processing_timeout")
                try:
                    tree = psutil.Process(process.pid)
                    rss = sum(item.memory_info().rss for item in [tree, *tree.children(recursive=True)])
                    current_memory = rss
                    peak_memory = max(peak_memory, rss)
                    available_memory = psutil.virtual_memory().available
                    if rss > memory_gb * 1024 ** 3:
                        return stopped("processing_memory_limit")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                try:
                    path = output.with_name("progress.json")
                    if path.stat().st_size <= 8192:
                        current = json.loads(path.read_text(encoding="utf-8"))
                        if isinstance(current, dict):
                            last_progress = current
                except (OSError, ValueError):
                    pass
                phase = (last_progress or {}).get("phase", "starting_worker")
                if progress and (phase != last_sent_phase or time.monotonic() - last_sent >= .5):
                    progress({**(last_progress or {"phase": "starting_worker"}), **measurements()})
                    last_sent = time.monotonic()
                    last_sent_phase = phase
                await asyncio.sleep(0.1)
            current_memory = 0
            available_memory = psutil.virtual_memory().available
            if progress:
                progress({"phase": "saving", **measurements()})
            if process.returncode == 0 and output.is_file() and output.stat().st_size > WORKER_RESULT_BYTES:
                return stopped("processing_output_limit")
            if process.returncode == 0 and output.is_file():
                try:
                    result = json.loads(output.read_text(encoding="utf-8"))
                    if not isinstance(result, dict):
                        return stopped("processing_failed")
                    result["processing"] = {**measurements(), "last_progress": last_progress}
                    return result, None
                except (ValueError, OSError):
                    pass
            return stopped("processing_failed")
        finally:
            await asyncio.to_thread(stop_worker, process)

    async def inspect(self, request: Request, progress=None):
        async with self.slot:
            async with request.form(max_files=1, max_fields=4, max_part_size=1024) as form:
                file = form.get("file")
                if not isinstance(file, UploadFile):
                    raise HTTPException(422, "file_required")
                name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
                kind = Path(name).suffix.lower().lstrip(".")
                if kind not in FILE_LIMITS or len(name) > 255 or any(ord(char) < 32 for char in name):
                    raise HTTPException(422, "unsupported_file_type")
                discipline = form.get("discipline") or infer_discipline(name)
                if discipline not in {"ARCH", "STR", "MEP", "OTHER"}:
                    raise HTTPException(422, "invalid_discipline")
                if not form.get("project_id"):
                    raise HTTPException(422, "project_required")
                try:
                    context = SourceContext(project_id=form["project_id"], logical_source=form.get("logical_source", ""), **({"revision": form["revision"]} if form.get("revision") else {})).model_dump(mode="json")
                except ValidationError:
                    raise HTTPException(422, "source_context_invalid") from None
                if self.projects is None:
                    raise HTTPException(503, "database_unavailable")
                await asyncio.to_thread(self.projects.require_project, context["project_id"], "edit")
                converter = await asyncio.to_thread(discover_converter) if kind == "dwg" else None
                if kind == "dwg" and not converter:
                    raise HTTPException(503, "dwg_converter_not_installed")
                self.directory.mkdir(parents=True, exist_ok=True)
                if shutil.disk_usage(self.directory).free < (file.size or 0) * 3 + 512 * 1024**2:
                    raise HTTPException(507, "processing_disk_space")
                temporary_root = self.temporary_root
                work = self.new_work("inspection-")
                source = work / f"source.{kind}"
                try:
                    digest = hashlib.sha256()
                    size = 0
                    header = b""
                    with source.open("xb") as handle:
                        while chunk := await file.read(64 * 1024):
                            size += len(chunk)
                            if size > min(FILE_LIMITS[kind], self.file_limit):
                                raise HTTPException(413, "file_too_large")
                            if not header:
                                header = chunk[:1024].lstrip(b"\xef\xbb\xbf \t\r\n")
                            digest.update(chunk)
                            handle.write(chunk)
                    valid_header = {
                        "ifc": header.startswith(b"ISO-10303-21;"), "pdf": header.startswith(b"%PDF-"),
                        "dxf": header.startswith(b"AutoCAD Binary DXF") or bool(re.search(br"(?:^|\n)\s*0\s*\r?\nSECTION(?:\r?\n|$)", header)),
                        "dwg": bool(re.match(br"AC10[0-9]{2}", header)),
                    }[kind]
                    if not size or not valid_header:
                        raise HTTPException(422, "invalid_file_header")
                    if context:
                        existing = await asyncio.to_thread(self.projects.existing_version, context, digest.hexdigest(), automatic=not form.get("revision"))
                        if existing:
                            self.cache_source(source, kind, digest.hexdigest())
                            return existing
                    report = {
                        "id": uuid4().hex, "name": name, "kind": kind, "discipline": discipline,
                        "size_bytes": size, "sha256": digest.hexdigest(), "status": "failed",
                        "scope": "input_inspection", "clash_detection": "not_run", "result": None,
                        "assets": {}, "clash_ready": False, "dataset": dataset_for_hash(digest.hexdigest()),
                        "created_at": utc_now(), **(context or {}),
                    }
                    output = work / "result.json"
                    started = time.monotonic()
                    arguments = ["--inspect-worker", str(source), str(output)]
                    if converter:
                        arguments += ["--dwg-converter", converter["path"]]
                    result, error = await self.run_job(request, arguments, output, geometry_memory_gb(), progress=progress)
                    if result and result.get("processing"):
                        report["processing"] = result.pop("processing")
                    if error:
                        report["error_code"] = error
                    else:
                        report["result"] = result
                        report["status"] = result["status"]
                        available = []
                        if report["result"].get("preview_available"):
                            available.append("drawing.json")
                        if report["result"].get("viewer_available"):
                            available.append("model.glb")
                        if report["result"].get("mapping_available") or report["result"].get("viewer_available"):
                            available.append("model.json")
                        if report["result"].get("conversion"):
                            available.append("converted.dxf")
                        if report["result"].get("details_available"):
                            available.append("inspection.json")
                        if kind == "ifc" and "model.json" in available:
                            self.cache_source(source, kind, report["sha256"])
                            report["clash_ready"] = True
                        elif context and report["status"] in {"completed", "partial"}:
                            self.cache_source(source, kind, report["sha256"])
                        if available:
                            destination = self.directory / "assets" / report["id"]
                            destination.mkdir(parents=True)
                            for filename in available:
                                os.replace(work / "assets" / filename, destination / filename)
                                report["assets"][ASSET_FILES[filename]] = f"/api/inspections/{report['id']}/assets/{filename}"
                    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
                    report["report_url"] = f"/api/inspections/{report['id']}/report"
                    reports = self.directory / "reports"
                    reports.mkdir(exist_ok=True)
                    with (reports / f"{report['id']}.json").open("x", encoding="utf-8") as handle:
                        json.dump(report, handle, ensure_ascii=False, allow_nan=False)
                    return await asyncio.to_thread(self.projects.save_inspection, report) if context else report
                finally:
                    if work.resolve().parent == temporary_root.resolve():
                        shutil.rmtree(work)
