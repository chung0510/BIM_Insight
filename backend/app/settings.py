import json
from pathlib import Path
import tempfile

from app.db import _dpapi


def load_settings(directory, component):
    if component not in {"r2", "ai", "mail"}:
        raise ValueError("Unknown settings component")
    path = Path(directory) / f"{component}.dpapi"
    if not path.exists():
        return None
    try:
        if not 0 < path.stat().st_size <= 32768:
            raise ValueError
        return json.loads(_dpapi(path.read_bytes(), decrypt=True))
    except Exception:
        raise ValueError(f"Cannot read private {component} settings") from None


def save_settings(directory, component, settings):
    if component not in {"r2", "ai", "mail"}:
        raise ValueError("Unknown settings component")
    encrypted = _dpapi(json.dumps(settings, ensure_ascii=False).encode("utf-8"), decrypt=False)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=f"{component}-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encrypted)
        temporary.replace(directory / f"{component}.dpapi")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
