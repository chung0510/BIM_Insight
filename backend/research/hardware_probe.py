import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading

import psutil


class ResourceMonitor:
    """Sample process-tree RSS; short spikes between samples may be missed."""

    def __init__(self):
        self.peak_rss_bytes = 0
        self.peak_system_used_bytes = 0
        self.stop = threading.Event()
        self.process = psutil.Process()

    def sample(self):
        processes = [self.process, *self.process.children(recursive=True)]
        rss = 0
        for process in processes:
            try:
                rss += process.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        self.peak_rss_bytes = max(self.peak_rss_bytes, rss)
        self.peak_system_used_bytes = max(self.peak_system_used_bytes, psutil.virtual_memory().used)

    def __enter__(self):
        self.sample()

        def watch():
            while not self.stop.wait(0.2):
                self.sample()

        self.thread = threading.Thread(target=watch, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop.set()
        self.thread.join()
        self.sample()

    def result(self):
        return {
            "process_tree_rss_peak_bytes": self.peak_rss_bytes,
            "system_used_peak_bytes": self.peak_system_used_bytes,
            "sampling_interval_seconds": 0.2,
        }


def probe():
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(Path.cwd())
    versions = {}
    for package in ["fastapi", "pymongo", "ifcopenshell", "torch", "transformers", "peft", "bitsandbytes"]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    gpu = {"status": "unavailable"}
    executable = shutil.which("nvidia-smi")
    if executable:
        try:
            result = subprocess.run(
                [executable, "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, check=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            name, total, free, driver = [part.strip() for part in result.stdout.splitlines()[0].split(",")]
            gpu = {"status": "available", "name": name, "total_mib": int(total), "free_mib": int(free), "driver": driver}
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            gpu = {"status": "query_failed"}
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "cpu": {"name": platform.processor(), "physical_cores": psutil.cpu_count(logical=False), "logical_cores": psutil.cpu_count()},
        "memory": {"total_bytes": memory.total, "available_bytes": memory.available},
        "disk": {"path": str(Path.cwd().anchor), "total_bytes": disk.total, "free_bytes": disk.free},
        "gpu": gpu, "python": {"version": platform.python_version(), "executable": sys.executable},
        "dependencies": versions,
    }


def main():
    parser = argparse.ArgumentParser(description="Measure local BIM/AI prerequisites")
    parser.add_argument("--output", type=Path, default=Path("data/artifacts/week1/hardware.json"))
    args = parser.parse_args()
    result = probe()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
