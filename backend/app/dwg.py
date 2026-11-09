from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


class ConversionError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def converter_environment():
    return {key: value for key, value in os.environ.items() if key.upper() in {
        "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "USERPROFILE", "PROGRAMDATA",
    }}


@lru_cache(maxsize=8)
def _signed_identity(filename, size, modified):
    powershell = Path(os.environ["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = subprocess.run([
            str(powershell), "-NoProfile", "-NonInteractive", "-Command",
            "$s=Get-AuthenticodeSignature -LiteralPath $env:BIM_ODA_EXE; "
            "if($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -match 'O=OPEN DESIGN ALLIANCE'){"
            "@{version=(Get-Item -LiteralPath $env:BIM_ODA_EXE).VersionInfo.ProductVersion}|ConvertTo-Json -Compress}",
        ], capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
            env={**converter_environment(), "BIM_ODA_EXE": filename})
        identity = json.loads(result.stdout)
        return {"path": filename, "version": identity["version"]} if result.returncode == 0 else None
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return None


def converter_identity(executable):
    if os.name != "nt" or not executable:
        return None
    try:
        path = Path(executable).resolve(strict=True)
        if path.name.lower() != "odafileconverter.exe" or str(path).startswith("\\\\"):
            return None
        stat = path.stat()
        return _signed_identity(str(path), stat.st_size, stat.st_mtime_ns)
    except OSError:
        return None


def discover_converter():
    for variable, suffix in [("LOCALAPPDATA", "Programs/ODA"), ("ProgramFiles", "ODA")]:
        if os.getenv(variable):
            for executable in sorted((Path(os.environ[variable]) / suffix).glob("ODAFileConverter */ODAFileConverter.exe"), reverse=True):
                identity = converter_identity(executable)
                if identity:
                    return identity
    return None


def convert_dwg(source: Path, assets: Path, executable):
    from app.limits import DWG_TIMEOUT, FILE_LIMITS
    identity = converter_identity(executable)
    if not identity:
        raise ConversionError("dwg_converter_not_installed")
    try:
        result = subprocess.run([
            identity["path"], str(source.parent), str(assets), "ACAD2018", "DXF", "0", "0", source.name,
        ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            shell=False, timeout=DWG_TIMEOUT, env=converter_environment(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        converted = assets / source.with_suffix(".dxf").name
        if result.returncode or not converted.is_file() or not 0 < converted.stat().st_size <= FILE_LIMITS["dxf"]:
            raise ConversionError("dwg_conversion_failed")
        with converted.open("rb") as handle:
            header = handle.read(1024).lstrip(b"\xef\xbb\xbf \t\r\n")
            if not (header.startswith(b"AutoCAD Binary DXF") or re.search(br"(?:^|\n)\s*0\s*\r?\nSECTION(?:\r?\n|$)", header)):
                raise ConversionError("dwg_conversion_failed")
            handle.seek(0)
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        converted.rename(assets / "converted.dxf")
        return {"converter": "ODA File Converter", "version": identity["version"],
                "output_format": "DXF ACAD2018", "output_sha256": digest,
                "output_bytes": (assets / "converted.dxf").stat().st_size, "audit": False}
    except subprocess.TimeoutExpired:
        raise ConversionError("dwg_conversion_timeout") from None
    except OSError:
        raise ConversionError("dwg_conversion_failed") from None
