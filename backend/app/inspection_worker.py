from collections import Counter
import json
import os
from pathlib import Path
import time
from app.limits import WORKER_RESULT_BYTES


def run_worker(source: Path, output: Path, dwg_converter=None):
    last_write, last_phase = 0., None
    def progress(value):
        nonlocal last_write, last_phase
        now = time.monotonic()
        if value["phase"] != last_phase or now - last_write >= 1 or value.get("done") == value.get("total"):
            try:
                temporary = output.with_name("progress.tmp")
                temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                os.replace(temporary, output.with_name("progress.json"))
                last_write, last_phase = now, value["phase"]
            except OSError:
                pass
    progress({"phase": "starting_worker"})
    assets = output.parent / "assets"
    assets.mkdir()
    if source.suffix == ".ifc":
        from app.ifc import inspect_ifc

        result = inspect_ifc(source, assets_dir=assets, progress=progress)
        result["type_counts"] = dict(Counter(item["ifc_type"] for item in result["elements"]))
        result["triangle_count"] = sum(item["triangle_count"] for item in result["elements"])
        result.update(elements_truncated=False, diagnostics_truncated=False)
        progress({"phase": "writing_report"})
        details = assets / "inspection.json"
        with details.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, allow_nan=False)
        if details.stat().st_size <= WORKER_RESULT_BYTES:
            result["details_available"] = True
        else:
            details.unlink()
            result["diagnostics"].insert(0, {"code": "processing_output_limit"})
            if result["status"] == "completed":
                result["status"] = "partial"
        result["elements_truncated"] = len(result["elements"]) > 20
        result["elements"] = result["elements"][:20]
        for key, limit in (("inventory", 20), ("reference_elements", 20), ("geometry_failures", 100)):
            result[f"{key}_truncated"] = len(result.get(key, [])) > limit
            result[key] = result.get(key, [])[:limit]
        result["diagnostics_truncated"] = len(result["diagnostics"]) > 100
        result["diagnostics"] = result["diagnostics"][:100]
    elif source.suffix == ".dxf":
        progress({"phase": "reading_drawing"})
        from app.cad import inspect_dxf

        result = inspect_dxf(source, assets)
    elif source.suffix == ".dwg":
        progress({"phase": "converting_drawing"})
        from app.cad import inspect_dxf
        from app.dwg import ConversionError, convert_dwg

        try:
            conversion = convert_dwg(source, assets, dwg_converter)
            result = inspect_dxf(assets / "converted.dxf", assets)
            result["conversion"] = conversion
        except ConversionError as error:
            result = {"status": "failed", "scope": "dwg_conversion", "clash_detection": "not_run", "diagnostics": [{"code": error.code}]}
    else:
        progress({"phase": "reading_pdf"})
        from app.pdf import inspect_pdf

        result = inspect_pdf(source)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, allow_nan=False)
