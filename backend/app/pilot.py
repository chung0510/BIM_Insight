"""Sixty analytic variants from one parametric family, never independent projects."""
from functools import lru_cache
import hashlib
import math
from uuid import NAMESPACE_URL, uuid5

import ezdxf
from ezdxf.math import Matrix44
import ifcopenshell

from app.demo import CASES, PILOT_DATASET, SPLIT_GROUP, demo_model, serialize_drawing


SCALES = (.6, .75, .9, 1.05, 1.2, 1.35, 1.5, 1.65, 1.8, 2.)
ANGLES = (0, 15, -20, 30, -35, 40, -15, 25, -30, 10)


def guid(key):
    return ifcopenshell.guid.compress(uuid5(NAMESPACE_URL, f"bim-insight/{PILOT_DATASET}/{key}").hex)


@lru_cache(maxsize=1)
def pilot_bundle():
    files, cases, references = [], {}, {}
    for discipline in ["ARCH", "STR", "MEP"]:
        base = demo_model(discipline)["content"]
        target = None
        for index, (scale, angle) in enumerate(zip(SCALES, ANGLES)):
            model = ifcopenshell.file.from_string(base)
            for entity in model.by_type("IfcRoot"):
                entity.GlobalId = guid(f"{index}/{entity.GlobalId}")
            for point in model.by_type("IfcCartesianPoint"):
                point.Coordinates = tuple(n * scale for n in point.Coordinates)
            for solid in model.by_type("IfcExtrudedAreaSolid"):
                solid.Depth *= scale
            for profile in model.by_type("IfcCircleProfileDef"):
                profile.Radius *= scale
            roots = [placement for placement in model.by_type("IfcLocalPlacement") if placement.PlacementRelTo is None]
            radians = math.radians(angle)
            axis = model.create_entity("IfcAxis2Placement3D", Location=model.create_entity("IfcCartesianPoint", Coordinates=(float(index % 5 * 100000), float(index // 5 * 100000), 0.)), RefDirection=model.create_entity("IfcDirection", DirectionRatios=(math.cos(radians), math.sin(radians), 0.)))
            placement = model.create_entity("IfcLocalPlacement", RelativePlacement=axis)
            for root in roots:
                root.PlacementRelTo = placement
            for grid in model.by_type("IfcGrid"):
                grid.ObjectPlacement = placement
            for product in model.by_type("IfcElement"):
                case = product.Tag
                product.Tag = f"v{index:02d}_{case}"
                product.Name = f"PILOT {index + 1:02d} {case}: {product.Name}"
                if not product.is_a("IfcFeatureElementSubtraction"):
                    references.setdefault(product.Tag, []).append(product.GlobalId)
                if product.Tag not in cases:
                    cases[product.Tag] = {**CASES[case], "label": f"{index + 1:02d} · {CASES[case]['label']}", "scale": scale, "rotation_deg": angle, "split_group": SPLIT_GROUP}
                    if case == "gap40":
                        cases[product.Tag]["clearance"] = .04 * scale < .05
            if target is None:
                target = model
            else:
                copied = {product.GlobalId: target.add(product) for product in model.by_type("IfcElement")}
                for void in model.by_type("IfcRelVoidsElement"):
                    target.create_entity("IfcRelVoidsElement", GlobalId=void.GlobalId, RelatingBuildingElement=copied[void.RelatingBuildingElement.GlobalId], RelatedOpeningElement=copied[void.RelatedOpeningElement.GlobalId])
                positive = tuple(product for product in copied.values() if not product.is_a("IfcFeatureElementSubtraction"))
                target.create_entity("IfcRelContainedInSpatialStructure", GlobalId=guid(f"{discipline}/{index}/containment"), RelatedElements=positive, RelatingStructure=target.by_type("IfcBuildingStorey")[0])
        name = f"PILOT_{discipline}.ifc"
        target.header.file_name.name = name
        target.header.file_description.description = ("ViewDefinition [ReferenceView_V1.2]", PILOT_DATASET)
        target.by_type("IfcProject")[0].Name = "SYNTHETIC PARAMETRIC FAMILY - NOT INDEPENDENT PROJECTS"
        files.append({"name": name, "discipline": discipline, "content": target.to_string()})
    for key, spec in cases.items():
        spec.update(a_guid=references[key][0], b_guid=references[key][1])

    drawing = ezdxf.new("R2018", units=4)
    drawing.layers.add("S-GRID", color=1)
    drawing.layers.add("PILOT-ZONES", color=3)
    for index, (scale, angle) in enumerate(zip(SCALES, ANGLES)):
        matrix = Matrix44.scale(scale) @ Matrix44.z_rotate(math.radians(angle)) @ Matrix44.translate(index % 5 * 100000, index // 5 * 100000, 0)
        for start, end in [((0, -1000, 0), (0, 15000, 0)), ((-1000, 0, 0), (23000, 0, 0))]:
            drawing.modelspace().add_line(matrix.transform(start), matrix.transform(end), dxfattribs={"layer": "S-GRID"})
        for case, x, y in [("crossing", 0, 0), ("contained", 8, 0), ("gap40", 16, 0), ("touch", 0, 8), ("opening", 8, 8), ("bbox_only", 16, 8)]:
            points = [matrix.transform((a * 1000, b * 1000, 0)) for a, b in [(x, y), (x + 4, y), (x + 4, y + 4), (x, y + 4)]]
            drawing.modelspace().add_lwpolyline([(p.x, p.y) for p in points], close=True, dxfattribs={"layer": "PILOT-ZONES"})
            drawing.modelspace().add_text(f"PILOT {index + 1:02d}: {case}", dxfattribs={"layer": "PILOT-ZONES", "height": 180 * scale, "insert": matrix.transform((x * 1000, (y + 4.5) * 1000, 0)), "rotation": angle})
    files.append({"name": "PILOT_FLOOR.dxf", "discipline": "ARCH", "content": serialize_drawing(drawing, PILOT_DATASET)})
    for item in files:
        item["sha256"] = hashlib.sha256(item["content"].encode()).hexdigest()
    return {"dataset": PILOT_DATASET, "files": files, "cases": cases, "label_origin": "analytic", "independent_projects": False}
