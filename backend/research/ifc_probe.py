import argparse
import json
from pathlib import Path

from app.ifc import inspect_ifc
from backend.research.hardware_probe import ResourceMonitor


def main():
    parser = argparse.ArgumentParser(description="Read a small IFC without modifying its source")
    parser.add_argument("ifc", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.ifc.resolve():
        parser.error("The report cannot overwrite the IFC source")
    if args.output.suffix.lower() != ".json":
        parser.error("Use a new .json path for the report")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = args.output.open("x", encoding="utf-8")
    except FileExistsError:
        parser.error("Report path already exists; choose a new .json path")
    with handle:
        with ResourceMonitor() as resources:
            report = inspect_ifc(args.ifc)
        report["resources"] = resources.result()
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({key: report[key] for key in ["status", "element_count", "excluded_count", "elapsed_seconds"]}))
    raise SystemExit(0 if report["status"] == "completed" else 2)


if __name__ == "__main__":
    main()
