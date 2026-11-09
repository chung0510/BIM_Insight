import argparse
import hashlib
import json
from pathlib import Path

import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import numpy as np


def make_fixture(directory: Path):
    directory = Path(directory)
    specifications = {
        "ARCH": [("IfcWall", "Synthetic wall", (0, 0, 0), (4, 0.2, 3))],
        "STR": [("IfcBeam", "Synthetic beam", (0, -0.1, 2.5), (4, 0.3, 0.4))],
        "MEP": [
            ("IfcPipeSegment", "Synthetic pipe envelope", (0.5, -0.05, 2.6), (1, 0.1, 0.1)),
            ("IfcDuctSegment", "Synthetic duct", (2, -0.2, 2.45), (1, 0.3, 0.3)),
            ("IfcCableCarrierSegment", "Synthetic tray", (2, -0.1, 2.6), (1, 0.2, 0.08)),
        ],
    }
    targets = [directory / f"{discipline}.ifc" for discipline in specifications]
    if any(path.exists() for path in [*targets, directory / "manifest.json"]):
        raise FileExistsError("Use an empty fixture directory; existing source files are preserved")
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "synthetic": True, "purpose": "technical_smoke_only", "engineering_review": "not_performed",
        "limitations": "Rectangular envelopes, including the pipe. Not real project data or validated clash labels.",
        "files": [],
    }
    for discipline, elements in specifications.items():
        model = ifcopenshell.api.project.create_file(version="IFC4")
        project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name=f"Synthetic {discipline}")
        length = ifcopenshell.api.unit.add_si_unit(model, unit_type="LENGTHUNIT", prefix="MILLI")
        ifcopenshell.api.unit.assign_unit(model, units=[length])
        context = ifcopenshell.api.context.add_context(model, context_type="Model")
        body = ifcopenshell.api.context.add_context(
            model, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=context
        )
        parent = project
        for ifc_class in ["IfcSite", "IfcBuilding", "IfcBuildingStorey"]:
            child = ifcopenshell.api.root.create_entity(model, ifc_class=ifc_class, name=f"Synthetic {ifc_class}")
            ifcopenshell.api.aggregate.assign_object(model, products=[child], relating_object=parent)
            parent = child
        for ifc_class, name, position, size in elements:
            element = ifcopenshell.api.root.create_entity(model, ifc_class=ifc_class, name=name)
            representation = ifcopenshell.api.geometry.add_wall_representation(
                model, context=body, length=size[0], thickness=size[1], height=size[2]
            )
            ifcopenshell.api.geometry.assign_representation(model, product=element, representation=representation)
            ifcopenshell.api.spatial.assign_container(model, products=[element], relating_structure=parent)
            placement = np.eye(4)
            placement[:3, 3] = position
            ifcopenshell.api.geometry.edit_object_placement(model, product=element, matrix=placement)
        path = directory / f"{discipline}.ifc"
        model.write(str(path))
        manifest["files"].append({
            "file": path.name, "discipline": discipline,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate clearly labelled synthetic IFC smoke inputs")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(make_fixture(args.directory), ensure_ascii=False, indent=2))
