from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

backend = Path(SPECPATH)
root = backend.parent
a = Analysis(
    [str(backend / "app" / "__main__.py")],
    pathex=[str(backend)],
    binaries=[],
    datas=collect_data_files("ifcopenshell") + collect_data_files("ezdxf") + [(str(backend / "app" / "qwen_worker.py"), "app"), (str(backend / "app" / "qwen-model.json"), "app")],
    hiddenimports=["app.inspection_worker", "app.ifc", "app.pdf", "app.cad", "app.clash_jobs", "app.clash", "app.clash_cache", "app.projects", "app.pilot", "ifcopenshell.geom", "ifcopenshell.util.unit", "ifcopenshell.util.shape", "ezdxf.addons.drawing.svg", "defusedxml.ElementTree"],
    excludes=["torch", "transformers", "peft", "bitsandbytes", "pytest", "huggingface_hub"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="bim_backend", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="bim_backend")
