import ctypes
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

from pymongo import MongoClient
from pymongo.uri_parser import parse_uri, split_options


def _validate_target(uri):
    try:
        parsed = urlsplit(uri)
        if parsed.fragment:
            raise ValueError
        if parsed.scheme == "mongodb+srv":
            if parsed.port is not None or not parsed.hostname:
                raise ValueError
            hosts = [parsed.hostname]
        elif parsed.scheme == "mongodb":
            hosts = [host for host, _ in parse_uri(uri)["nodelist"]]
        else:
            raise ValueError
        local = bool(hosts) and all(host.lower() in {"127.0.0.1", "localhost", "::1"} for host in hosts)
        if parsed.scheme == "mongodb+srv" and local:
            raise ValueError
        if not local:
            if not hosts or not all(host.lower().endswith(".mongodb.net") for host in hosts):
                raise ValueError
            options = split_options(parsed.query) if parsed.query else {}
            if options.get("tls", True) is not True:
                raise ValueError
            if any(options.get(key, False) is not False for key in ["tlsinsecure", "tlsallowinvalidcertificates", "tlsallowinvalidhostnames"]):
                raise ValueError
        return not local
    except Exception:
        raise ValueError("MongoDB requires a loopback host or Atlas with verified TLS") from None


def connect_database(uri: str, database_name: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", database_name):
        raise ValueError("Invalid database name")
    atlas = _validate_target(uri)
    options = {"appname": "BIM Insight", "serverSelectionTimeoutMS": 5000 if atlas else 1500, "connectTimeoutMS": 5000 if atlas else 1500, "timeoutMS": 10000 if atlas else 3000, "tz_aware": True, "connect": False}
    if atlas:
        options["tls"] = True
    try:
        return MongoClient(uri, **options)
    except Exception:
        raise ValueError("Invalid MongoDB connection configuration") from None


def _dpapi(data, *, decrypt):
    if os.name != "nt":
        raise ValueError("Windows is required for the private database configuration")

    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    library = ctypes.WinDLL("Crypt32", use_last_error=True)
    operation = library.CryptUnprotectData if decrypt else library.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    operation.restype = ctypes.c_int
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ValueError("Cannot access the private database configuration")
    free = ctypes.WinDLL("Kernel32").LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        free(output.data)


def save_database_settings(directory, uri, database_name):
    _validate_target(uri)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", database_name):
        raise ValueError("Invalid database name")
    encrypted = _dpapi(json.dumps({"uri": uri, "database": database_name}).encode("utf-8"), decrypt=False)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix="database-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encrypted)
        temporary.replace(directory / "database.dpapi")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def database_settings(directory):
    if "BIM_MONGODB_URI" in os.environ:
        return os.environ["BIM_MONGODB_URI"], os.getenv("BIM_DATABASE", "bim_insight")
    path = Path(directory) / "database.dpapi"
    if not path.exists():
        return "mongodb://127.0.0.1:27017", os.getenv("BIM_DATABASE", "bim_insight")
    try:
        if not 0 < path.stat().st_size <= 16384:
            raise ValueError
        settings = json.loads(_dpapi(path.read_bytes(), decrypt=True))
        if not isinstance(settings["uri"], str) or not isinstance(settings["database"], str):
            raise ValueError
        return settings["uri"], os.getenv("BIM_DATABASE", settings["database"])
    except Exception:
        raise ValueError("Cannot read the private database configuration") from None
