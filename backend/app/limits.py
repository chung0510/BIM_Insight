import os
import psutil


MIB = 1024**2
GIB = 1024**3
FILE_LIMITS = {"ifc": 2 * GIB, "pdf": 100 * MIB, "dxf": 256 * MIB, "dwg": 256 * MIB}
QUEUE_FILES = 200
OPEN_FILES = 200
CLASH_MODELS = 50
MAX_ELEMENTS = 100_000
MAX_ISSUES = 50_000
INSPECTION_TIMEOUT = 1800
WORKER_RESULT_BYTES = 128 * MIB
MAX_REPORT_BYTES = 256 * MIB
MAX_GLB_BYTES = 256 * MIB
MAX_MAPPING_BYTES = 64 * MIB
MAX_VIEWER_BYTES = 512 * MIB
MAX_PDF_PAGES = 500
DWG_TIMEOUT = 600


def geometry_memory_gb():
    memory = psutil.virtual_memory()
    budget = max(0.5, min(8, memory.total / GIB / 2, memory.available / GIB - 1))
    try:
        inherited = int(os.environ.get("BIM_WORKER_MEMORY_BYTES", "0"))
        if inherited > 0:
            budget = min(budget, inherited / GIB)
    except ValueError:
        pass
    return budget


def ifc_geometry_threads():
    return 2 if (psutil.cpu_count(logical=False) or 1) >= 2 and geometry_memory_gb() >= 2.5 else 1


def ifc_geometry_batch_size():
    budget = geometry_memory_gb()
    return 64 if budget < 1.5 else 128 if budget < 2.5 else 512


def processing_limits():
    return {"queue_files": QUEUE_FILES, "open_files": OPEN_FILES, "clash_models": CLASH_MODELS,
            "clash_elements": MAX_ELEMENTS, "clash_issues": MAX_ISSUES, "timeout_seconds": INSPECTION_TIMEOUT,
            "pdf_pages": MAX_PDF_PAGES, "viewer_bytes": MAX_VIEWER_BYTES}
