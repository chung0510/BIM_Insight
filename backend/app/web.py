"""Production browser entry point; desktop startup continues to use app.__main__."""

import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from fastapi.staticfiles import StaticFiles

from app.access_routes import Registration
from app.main import create_app


def https_origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or "*" in value):
        raise ValueError("A single HTTPS web origin without a path is required")
    return value


def create_web_app():
    origin = https_origin(os.getenv("BIM_WEB_ORIGIN") or os.getenv("RENDER_EXTERNAL_URL", ""))
    frontend_origin = os.getenv("BIM_FRONTEND_ORIGIN")
    if frontend_origin:
        frontend_origin = https_origin(frontend_origin)
    secret = os.getenv("BIM_SETTINGS_KEY", "")
    if len(secret) < 32:
        raise ValueError("BIM_SETTINGS_KEY must contain at least 32 characters")
    uri = os.getenv("BIM_MONGODB_URI")
    if not uri:
        raise ValueError("BIM_MONGODB_URI is required for web deployment")
    try:
        admin = Registration(username=os.getenv("BIM_ADMIN_USERNAME", ""),
                             password=os.getenv("BIM_ADMIN_PASSWORD", ""), display_name="Administrator")
    except ValueError:
        raise ValueError("Set a valid BIM_ADMIN_USERNAME and BIM_ADMIN_PASSWORD (at least 12 characters)") from None
    frontend = Path(os.getenv("BIM_FRONTEND_DIR", str(Path(__file__).resolve().parents[2] / "frontend" / "dist")))
    if not (frontend / "index.html").is_file():
        raise ValueError("Build the frontend before starting the web service")
    upload_mb = int(os.getenv("BIM_UPLOAD_LIMIT_MB", "20"))
    if not 1 <= upload_mb <= 2048:
        raise ValueError("BIM_UPLOAD_LIMIT_MB must be between 1 and 2048")
    app = create_app(api_token=secrets.token_urlsafe(32), mongo_uri=uri,
                     database_name=os.getenv("BIM_DATABASE", "bim_insight_render_demo"),
                     data_dir=Path(os.getenv("BIM_DATA_DIR", "/tmp/bim-insight")),
                     upload_limit_bytes=upload_mb * 1024**2, web_origin=origin, initial_admin=admin,
                     web_demo=os.getenv("BIM_WEB_DEMO") == "1", frontend_origin=frontend_origin)
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


if __name__ == "__main__":
    import uvicorn

    # One worker preserves the existing process-local IFC/AI queue and locks.
    uvicorn.run(create_web_app(), host="0.0.0.0", port=int(os.getenv("PORT", "10000")), access_log=False)
