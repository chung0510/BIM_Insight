from datetime import datetime, timezone
import asyncio
import json
from pathlib import Path
import re
import shutil
import time
from uuid import uuid4

from fastapi import HTTPException

from app.demo import dataset_for_hash
from app.limits import geometry_memory_gb
from app.inspections import stream_job


async def create_clash(service, request, payload, progress=None):
    if not payload.coordinates_confirmed:
        raise HTTPException(422, "clash_frame_unconfirmed")
    if progress:
        progress({"phase": "preparing"})
    async with service.slot:
        directory = service.directory
        sources = []
        contexts = []
        for identifier in payload.model_ids:
            path = await asyncio.to_thread(service.projects.ensure_local, f"reports/{identifier}.json")
            if not path.is_file():
                raise HTTPException(404, "report_not_found")
            report = json.loads(path.read_text(encoding="utf-8"))
            contexts.append((report.get("project_id"), report.get("revision")))
            digest = report.get("sha256", "")
            if report.get("kind") != "ifc" or not report.get("clash_ready") or not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise HTTPException(422, "clash_reimport_required")
            metadata = report.get("result") or {}
            if not metadata.get("length_unit_verified"):
                raise HTTPException(422, "ifc_units_unknown")
            cache = await asyncio.to_thread(service.projects.ensure_local, f"cache/models/{digest}.ifc")
            mapping = await asyncio.to_thread(service.projects.ensure_local, f"assets/{identifier}/model.json")
            if not cache.is_file() or not mapping.is_file():
                raise HTTPException(422, "clash_reimport_required")
            sources.append({"id": identifier, "name": report["name"], "sha256": digest, "discipline": report["discipline"], "result": metadata, "path": str(cache.resolve()), "mapping_path": str(mapping.resolve()), "dataset": dataset_for_hash(digest)})
        if len({source["sha256"] for source in sources}) != len(sources):
            raise HTTPException(422, "clash_duplicate_source")
        datasets = {source["dataset"] for source in sources}
        if len(datasets) != 1:
            raise HTTPException(422, "clash_mixed_datasets")
        if len({context[0] for context in contexts}) != 1:
            raise HTTPException(422, "clash_project_revision_mismatch")
        project_id = contexts[0][0]
        revision = contexts[0][1] if len(set(contexts)) == 1 else None
        if not project_id:
            raise HTTPException(422, "project_required")
        if project_id:
            await asyncio.to_thread(service.projects.require_project, project_id)
        link = None
        if payload.link_id:
            path = await asyncio.to_thread(service.projects.ensure_local, f"links/{payload.link_id}.json")
            if not path.is_file():
                raise HTTPException(422, "clash_link_invalid")
            link = json.loads(path.read_text(encoding="utf-8"))
            if not link.get("confirmed") or not any(source["id"] == link.get("model_id") and source["sha256"] == link.get("model_sha256") for source in sources):
                raise HTTPException(422, "clash_link_invalid")
            if project_id and link.get("project_id") != project_id:
                raise HTTPException(422, "clash_link_invalid")
        work = service.new_work("clash-")
        try:
            config, output = work / "config.json", work / "result.json"
            parameters = payload.model_dump()
            config.write_text(json.dumps({"sources": sources, "parameters": parameters, "geometry_cache": str((directory / "cache" / "clash-geometry").resolve())}, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            result, error = await service.run_job(request, ["--clash-worker", str(config), str(output)], output, geometry_memory_gb(), progress=progress)
            if error:
                processing = (result or {}).get("processing", {})
                result = {"status": "failed", "verdict": "unavailable", "clash_detection": "failed", "issues": [], "diagnostics": [{"code": error, **processing}], "coverage": None, "evaluation": None}
                if processing:
                    result["elapsed_seconds"] = processing["elapsed_seconds"]
            identifier = uuid4().hex
            result.update({"id": identifier, "created_at": datetime.now(timezone.utc).isoformat(), "scope": "cross_source_ifc_geometry", "dataset": sources[0]["dataset"], "parameters": parameters, "sources": [{key: source[key] for key in ["id", "name", "sha256", "discipline"]} for source in sources], "drawing_link": link, "report_url": f"/api/inspections/clashes/{identifier}", "project_id": project_id, "revision": revision})
            reports = directory / "clashes"
            if progress:
                progress({"phase": "saving", "issues": len(result["issues"])})
            reports.mkdir(parents=True, exist_ok=True)
            with (reports / f"{identifier}.json").open("x", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, allow_nan=False)
            if project_id:
                await asyncio.to_thread(service.projects.save_run, result)
            return result
        finally:
            if work.resolve().parent == service.temporary_root.resolve():
                shutil.rmtree(work)


def stream_clash(service, request, payload, save_report):
    async def execute(progress):
        report = await create_clash(service, request, payload, progress=progress)
        await save_report(report)
        return report
    return stream_job(execute)


def run_worker(config: Path, output: Path):
    from app.clash import check_clashes

    inputs = json.loads(config.read_text(encoding="utf-8"))
    last_write, last_phase = 0., None
    def progress(value):
        nonlocal last_write, last_phase
        now = time.monotonic()
        phase = (value["phase"], value.get("source_index"))
        if phase != last_phase or now - last_write >= 1 or value.get("done") == value.get("total"):
            try:
                output.with_name("progress.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                last_write, last_phase = now, phase
            except OSError:
                pass
    result = check_clashes(inputs["sources"], inputs["parameters"], progress=progress,
                           cache_dir=inputs.get("geometry_cache"), work_dir=config.parent)
    output.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
