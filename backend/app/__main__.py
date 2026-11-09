import os
from pathlib import Path
import secrets
import argparse
import json
from getpass import getpass
import socket
import threading
import time
from threading import Event

import psutil

from pymongo.errors import PyMongoError
from urllib.parse import urlsplit

from app.db import connect_database, database_settings, save_database_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--desktop", action="store_true")
    parser.add_argument("--inspect-worker", nargs=2, type=Path)
    parser.add_argument("--dwg-converter", type=Path)
    parser.add_argument("--clash-worker", nargs=2, type=Path)
    parser.add_argument("--clash-geometry-worker", nargs=2, type=Path)
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--configure-database", action="store_true")
    parser.add_argument("--configure-r2", action="store_true")
    parser.add_argument("--configure-ai", action="store_true")
    parser.add_argument("--ai-python", type=Path)
    parser.add_argument("--ai-model", type=Path)
    args = parser.parse_args()
    if args.parent_pid:
        parent = psutil.Process(args.parent_pid)

        def watch_parent():
            while True:
                time.sleep(1)
                if not parent.is_running():
                    for child in psutil.Process().children(recursive=True):
                        try:
                            child.kill()
                        except psutil.NoSuchProcess:
                            pass
                    os._exit(0)

        threading.Thread(target=watch_parent, daemon=True).start()
    if args.inspect_worker:
        from app.inspection_worker import run_worker

        run_worker(*args.inspect_worker, dwg_converter=args.dwg_converter)
        return
    if args.clash_worker:
        from app.clash_jobs import run_worker

        run_worker(*args.clash_worker)
        return
    if args.clash_geometry_worker:
        from app.clash_cache import write_source_cache

        write_source_cache(*args.clash_geometry_worker)
        return
    data_dir = Path(os.getenv("BIM_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data" / "inspections")))
    if args.configure_ai:
        from app.ai import AiConfig, MODEL
        from app.qwen_worker import verify_files
        from app.settings import save_settings
        try:
            python = args.ai_python or Path(input("AI Python executable: ").strip().strip('"'))
            model = args.ai_model or Path(input("Cached Qwen3-4B directory: ").strip().strip('"'))
            python, model = python.resolve(), model.resolve()
            if not python.is_file() or python.suffix.lower() != ".exe" or not model.is_dir():
                raise ValueError
            verify_files(model, MODEL)
            config = AiConfig(python=str(python), model_directory=str(model))
            directories = [data_dir]
            if os.name == "nt" and os.getenv("LOCALAPPDATA"):
                directories.append(Path(os.environ["LOCALAPPDATA"]) / "com.noodt.bim-insight" / "inspections")
            for directory in dict.fromkeys(directories):
                save_settings(directory, "ai", config.model_dump())
            print("Qwen3-4B configured. Model files match the pinned hashes; runtime/GPU is checked during generation. Restart the app.")
        except Exception:
            print("Cannot configure AI. Check the local AI Python, model directory and pinned model files.")
            raise SystemExit(1) from None
        return
    if args.configure_r2:
        from app.settings import save_settings
        from app.storage import R2Config, StorageService
        endpoint = input("R2 S3 endpoint (https://<account-id>.r2.cloudflarestorage.com): ").strip().rstrip("/")
        bucket = input("Private Standard bucket [bim-insight]: ").strip() or "bim-insight"
        access = getpass("R2 Access Key ID (hidden): ")
        secret = getpass("R2 Secret Access Key (hidden): ")
        client = None
        try:
            config = R2Config(endpoint=endpoint, bucket=bucket, access_key_id=access, secret_access_key=secret)
            uri, name = database_settings(data_dir)
            client = connect_database(uri, name)
            client.admin.command("ping")
            store = StorageService(client[name], data_dir, config)
            store.reconcile(Event())
            directories = [data_dir]
            if os.name == "nt" and os.getenv("LOCALAPPDATA"):
                directories.append(Path(os.environ["LOCALAPPDATA"]) / "com.noodt.bim-insight" / "inspections")
            for directory in dict.fromkeys(directories):
                save_settings(directory, "r2", config.private_values())
            print(f"R2 configured: private bucket {bucket}. Restart the app, then sync a project.")
        except Exception:
            print("Cannot configure R2. Check the endpoint, bucket-scoped Object Read & Write token, network, and MongoDB connection.")
            raise SystemExit(1) from None
        finally:
            if client is not None:
                client.close()
        return
    if args.configure_database:
        uri = getpass("MongoDB URI (hidden): ")
        name = input("Database [bim_insight]: ").strip() or "bim_insight"
        client = None
        try:
            client = connect_database(uri, name)
            client.admin.command("ping")
            directories = [data_dir]
            if os.name == "nt" and os.getenv("LOCALAPPDATA"):
                directories.append(Path(os.environ["LOCALAPPDATA"]) / "com.noodt.bim-insight" / "inspections")
            for directory in dict.fromkeys(directories):
                save_database_settings(directory, uri, name)
            print(f"MongoDB configured: {urlsplit(uri).hostname} / {name}")
        except (PyMongoError, ValueError, OSError):
            print("Cannot configure MongoDB. Check the connection, credentials, network access and writable data folders.")
            raise SystemExit(1) from None
        finally:
            if client is not None:
                client.close()
        return
    from app.main import DEFAULT_DATA_DIR, create_app
    import uvicorn

    mongo_uri, database_name = database_settings(data_dir)
    if args.desktop:
        token = secrets.token_urlsafe(32)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        app = create_app(
            api_token=token, data_dir=data_dir,
            mongo_uri=mongo_uri,
            database_name=database_name,
            session_id=os.getenv("BIM_SESSION_ID"),
        )
        print(json.dumps({"base_url": f"http://127.0.0.1:{port}", "token": token}), flush=True)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="warning"))
        server.run(sockets=[listener])
        return
    token = os.getenv("BIM_API_TOKEN")
    if not token:
        token_path = DEFAULT_DATA_DIR.parent / "runtime" / "backend-token"
        token_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with token_path.open("x", encoding="utf-8") as handle:
                handle.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
        token = token_path.read_text(encoding="utf-8").strip()
        print(f"Local API token file: {token_path.resolve()}")
    app = create_app(
        api_token=token,
        mongo_uri=mongo_uri,
        database_name=database_name,
        data_dir=data_dir,
        session_id=os.getenv("BIM_SESSION_ID"),
    )
    uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False)


if __name__ == "__main__":
    main()
