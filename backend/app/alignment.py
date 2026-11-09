from datetime import datetime, timezone
import json
import math
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat


class DrawingLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    drawing_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    model_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    storey_guid: str = Field(min_length=1, max_length=100)
    project_name: str = Field(min_length=1, max_length=120)
    revision: str | None = Field(default=None, min_length=1, max_length=80)
    dx_m: FiniteFloat = Field(default=0, ge=-10000000, le=10000000)
    dy_m: FiniteFloat = Field(default=0, ge=-10000000, le=10000000)
    rotation_deg: FiniteFloat = Field(default=0, ge=-360, le=360)
    confirmed: bool = False
    same_revision_confirmed: bool = False


def create_link(directory: Path, payload: DrawingLinkCreate):
    sources = []
    for identifier, kinds in [(payload.drawing_id, {"dxf", "dwg"}), (payload.model_id, {"ifc"})]:
        path = directory / "reports" / f"{identifier}.json"
        if not path.is_file():
            raise HTTPException(404, "report_not_found")
        report = json.loads(path.read_text(encoding="utf-8"))
        if report["kind"] not in kinds or report["status"] not in {"completed", "partial"} or not report.get("result") or (report["kind"] == "dwg" and not report["result"].get("conversion")):
            raise HTTPException(422, "alignment_source_invalid")
        sources.append(report)
    drawing, model = sources
    context = {source.get("project_id") for source in sources}
    if len(context) != 1 or drawing.get("dataset") != model.get("dataset"):
        raise HTTPException(422, "alignment_project_revision_mismatch")
    project_id, source_revision = model.get("project_id"), model.get("revision")
    if not project_id:
        raise HTTPException(422, "project_required")
    if payload.revision is not None and any(source.get("revision") != payload.revision for source in sources):
        raise HTTPException(422, "alignment_project_revision_mismatch")
    cad, bim = drawing["result"], model["result"]
    if not bim.get("length_unit_verified") or not bim.get("project_unit_scale_to_m"):
        raise HTTPException(422, "ifc_units_unknown")
    if not cad.get("unit_scale_to_m"):
        raise HTTPException(422, "cad_units_unknown")
    if cad.get("has_3d_entities") or any(item["code"] in {"cad_grid_limit", "cad_xref_unresolved", "cad_audit_review", "cad_entities_unsupported", "cad_preview_limit", "cad_preview_failed", "cad_empty_modelspace"} for item in cad.get("diagnostics", [])):
        raise HTTPException(422, "alignment_source_invalid")
    storey = next((item for item in bim.get("storeys", []) if item["guid"] == payload.storey_guid), None)
    if storey is None:
        raise HTTPException(422, "alignment_storey_invalid")
    angle = math.radians(payload.rotation_deg)
    cosine, sine = math.cos(angle), math.sin(angle)

    def point(coords):
        return (coords[0] * cosine - coords[1] * sine + payload.dx_m, coords[0] * sine + coords[1] * cosine + payload.dy_m)

    candidates = [(point(line["start_m"]), point(line["end_m"])) for line in cad.get("grid_lines", [])]
    grids = [grid for grid in bim.get("grids", []) if abs(grid["elevation_m"] - storey["elevation_m"]) < 1e-6]
    complete = all(grid.get("axis_count", len(grid["lines"])) == len(grid["lines"]) for grid in grids)
    axes = [line for grid in grids for line in grid["lines"]]
    matches, directions, used = [], [], set()
    for axis in axes:
        start, end = axis["start_m"], axis["end_m"]
        vx, vy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(vx, vy)
        if length < 1e-9:
            continue
        vx, vy = vx / length, vy / length
        options = []
        for index, (a, b) in enumerate(candidates):
            dx, dy = b[0] - a[0], b[1] - a[1]
            norm = math.hypot(dx, dy)
            if norm < 1e-9 or index in used:
                continue
            dx, dy = dx / norm, dy / norm
            if abs(dx * vx + dy * vy) > 1 - 1e-8:
                distance = max(
                    *(abs(dx * (p[1] - a[1]) - dy * (p[0] - a[0])) for p in [start, end]),
                    *(abs(vx * (p[1] - start[1]) - vy * (p[0] - start[0])) for p in [a, b]),
                )
                options.append((distance, index))
        if options:
            distance, index = min(options)
            if distance <= 0.001:
                used.add(index)
                directions.append((vx, vy))
                matches.append({"tag": axis.get("tag", ""), "distance_m": distance})
    independent = any(abs(a[0] * b[1] - a[1] * b[0]) > 0.1 for a in directions for b in directions)
    ready = complete and len(matches) >= 2 and len(matches) == len(axes) and independent
    if payload.confirmed and (not payload.same_revision_confirmed or not ready):
        raise HTTPException(422, "alignment_not_ready")
    result = {
        "project_id": project_id, "source_revision": source_revision,
        **payload.model_dump(), "scope": "floorplan_grid_xy_and_selected_storey", "clash_detection": "not_run",
        "drawing_sha256": drawing["sha256"], "model_sha256": model["sha256"],
        "drawing_name": drawing["name"], "model_name": model["name"], "storey_name": storey["name"],
        "elevation_m": storey["elevation_m"], "unit_scale_to_m": cad["unit_scale_to_m"],
        "grid_xy_ready": ready, "matched_axes": len(matches), "total_axes": len(axes), "matches": matches,
        "tolerance_m": 0.001, "max_distance_m": max((item["distance_m"] for item in matches), default=None),
        "confirmed": payload.confirmed,
    }
    if payload.confirmed:
        identifier = uuid4().hex
        result.update({"id": identifier, "created_at": datetime.now(timezone.utc).isoformat(), "link_url": f"/api/inspections/alignments/{identifier}"})
        links = directory / "links"
        links.mkdir(parents=True, exist_ok=True)
        with (links / f"{identifier}.json").open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, allow_nan=False)
    return result
