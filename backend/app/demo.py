"""Analytic smoke cases, deliberately separate from the user's project files."""
from functools import lru_cache
import hashlib
from io import StringIO
from uuid import NAMESPACE_URL, uuid5
from threading import Lock

import ifcopenshell


DATASET = "synthetic_clash_v1"
PILOT_DATASET = "synthetic_pilot_v1"
SPLIT_GROUP = "synthetic_geometry_family_v1"
_drawing_lock = Lock()
CASES = {
    "crossing": {"label": "Ống xuyên dầm", "hard": True, "clearance": True},
    "contained": {"label": "Ống nằm hoàn toàn trong khối", "hard": True, "clearance": True},
    "gap40": {"label": "Khoảng hở 40 mm", "hard": False, "clearance": True},
    "touch": {"label": "Tiếp xúc bề mặt", "hard": False, "clearance": True},
    "opening": {"label": "Ống đi qua lỗ mở", "hard": False, "clearance": False},
    "bbox_only": {"label": "AABB chồng, hình học rời nhau", "hard": False, "clearance": False},
}


def stable_guid(key):
    return ifcopenshell.guid.compress(uuid5(NAMESPACE_URL, f"bim-insight/{DATASET}/{key}").hex)


def demo_model(discipline):
    model = ifcopenshell.file(schema="IFC4")
    name = f"DEMO_{discipline}.ifc"
    model.header.file_name.name = name
    model.header.file_name.time_stamp = "2026-11-02T00:00:00"
    model.header.file_name.author = ("BIM Insight synthetic tests",)
    model.header.file_name.organization = ("Synthetic - not Nha02",)
    model.header.file_description.description = ("ViewDefinition [ReferenceView_V1.2]", DATASET)

    def point(values):
        return model.create_entity("IfcCartesianPoint", Coordinates=tuple(float(n) for n in values))

    def placement(position=(0, 0, 0), axis=(0, 0, 1)):
        return model.create_entity("IfcAxis2Placement3D", Location=point(position), Axis=model.create_entity("IfcDirection", DirectionRatios=tuple(float(n) for n in axis)), RefDirection=model.create_entity("IfcDirection", DirectionRatios=(1., 0., 0.)))

    context = model.create_entity("IfcGeometricRepresentationContext", ContextType="Model", CoordinateSpaceDimension=3, Precision=1e-6, WorldCoordinateSystem=placement())
    body = model.create_entity("IfcGeometricRepresentationSubContext", ContextIdentifier="Body", ContextType="Model", ParentContext=context, TargetView="MODEL_VIEW")
    unit = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE")
    project = model.create_entity("IfcProject", GlobalId=stable_guid("project"), Name="SYNTHETIC GEOMETRY LAB", RepresentationContexts=(context,), UnitsInContext=model.create_entity("IfcUnitAssignment", Units=(unit,)))
    building = model.create_entity("IfcBuilding", GlobalId=stable_guid(f"{discipline}/building"), Name="DEMO ONLY")
    storey = model.create_entity("IfcBuildingStorey", GlobalId=stable_guid("storey"), Name="DEMO Level 1", Elevation=0., ObjectPlacement=model.create_entity("IfcLocalPlacement", RelativePlacement=placement()))
    for key, parent, child in [("project", project, building), ("building", building, storey)]:
        model.create_entity("IfcRelAggregates", GlobalId=stable_guid(f"{discipline}/rel/{key}"), RelatingObject=parent, RelatedObjects=(child,))
    products = []

    def element(case, label, kind, position, size=None, polygon=None, pipe_axis=None, radius=0.05, length=1.4):
        if pipe_axis is not None:
            profile = model.create_entity("IfcCircleProfileDef", ProfileType="AREA", Radius=float(radius * 1000))
            solid_position = placement(axis=pipe_axis)
            depth = length * 1000
        else:
            outline = polygon or [(0, 0), (size[0], 0), (size[0], size[1]), (0, size[1])]
            curve = model.create_entity("IfcPolyline", Points=tuple(point((x * 1000, y * 1000)) for x, y in [*outline, outline[0]]))
            profile = model.create_entity("IfcArbitraryClosedProfileDef", ProfileType="AREA", OuterCurve=curve)
            solid_position = placement()
            depth = size[2] * 1000
        solid = model.create_entity("IfcExtrudedAreaSolid", SweptArea=profile, Position=solid_position, ExtrudedDirection=model.create_entity("IfcDirection", DirectionRatios=(0., 0., 1.)), Depth=float(depth))
        representation = model.create_entity("IfcShapeRepresentation", ContextOfItems=body, RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=(solid,))
        product = model.create_entity(kind, GlobalId=stable_guid(f"{discipline}/{case}/{label}"), Name=f"DEMO {case}: {label}", Tag=case, ObjectPlacement=model.create_entity("IfcLocalPlacement", RelativePlacement=placement(tuple(n * 1000 for n in position))), Representation=model.create_entity("IfcProductDefinitionShape", Representations=(representation,)))
        if not product.is_a("IfcFeatureElementSubtraction"):
            products.append(product)
        return product

    if discipline == "ARCH":
        host = element("opening", "wall with opening", "IfcWall", (8, 8, 0), (4, .4, 3))
        opening = element("opening", "void", "IfcOpeningElement", (9.8, 7.9, 1.2), (.4, .6, .6))
        model.create_entity("IfcRelVoidsElement", GlobalId=stable_guid("opening/relation"), RelatingBuildingElement=host, RelatedOpeningElement=opening)
    elif discipline == "STR":
        for case, position, size in [
            ("crossing", (0, 0, 2), (4, .4, .4)),
            ("contained", (8, 0, 0), (2, 2, 2)),
            ("gap40", (16, 0, 0), (1, 1, 1)),
            ("touch", (0, 8, 0), (1, 1, 1)),
        ]:
            element(case, "beam", "IfcBeam", position, size)
        element("bbox_only", "L beam", "IfcBeam", (16, 8, 0), (4, 4, 1), polygon=[(0, 0), (4, 0), (4, .5), (.5, .5), (.5, 4), (0, 4)])
    else:
        element("crossing", "pipe", "IfcPipeSegment", (2, -.5, 2.2), pipe_axis=(0, 1, 0))
        element("contained", "pipe", "IfcPipeSegment", (9, 1, .5), pipe_axis=(0, 0, 1), radius=.1, length=.5)
        element("gap40", "pipe", "IfcPipeSegment", (17.14, .5, .2), pipe_axis=(0, 0, 1), radius=.1, length=.5)
        element("touch", "duct", "IfcDuctSegment", (1, 8.3, .3), (.4, .4, .4))
        element("opening", "pipe in opening", "IfcPipeSegment", (10, 7.5, 1.5), pipe_axis=(0, 1, 0))
        element("bbox_only", "box in empty L region", "IfcBuildingElementProxy", (18, 10, .1), (1, 1, .4))
    model.create_entity("IfcRelContainedInSpatialStructure", GlobalId=stable_guid(f"{discipline}/containment"), RelatedElements=tuple(products), RelatingStructure=storey)
    axes = []
    for tag, start, end in [("1", (0, -1000, 0), (0, 15000, 0)), ("A", (-1000, 0, 0), (23000, 0, 0))]:
        axes.append(model.create_entity("IfcGridAxis", AxisTag=tag, AxisCurve=model.create_entity("IfcPolyline", Points=(point(start), point(end))), SameSense=True))
    model.create_entity("IfcGrid", GlobalId=stable_guid(f"{discipline}/grid"), UAxes=(axes[0],), VAxes=(axes[1],))
    return {"name": name, "discipline": discipline, "content": model.to_string()}


@lru_cache(maxsize=1)
def demo_files():
    import ezdxf

    files = [demo_model(discipline) for discipline in ["ARCH", "STR", "MEP"]]
    drawing = ezdxf.new("R2018", units=4)
    drawing.layers.add("S-GRID", color=1)
    drawing.layers.add("DEMO-ZONES", color=3)
    drawing.modelspace().add_line((0, -1000), (0, 15000), dxfattribs={"layer": "S-GRID"})
    drawing.modelspace().add_line((-1000, 0), (23000, 0), dxfattribs={"layer": "S-GRID"})
    for case, x, y in [("crossing", 0, 0), ("contained", 8, 0), ("gap40", 16, 0), ("touch", 0, 8), ("opening", 8, 8), ("bbox_only", 16, 8)]:
        drawing.modelspace().add_lwpolyline([(x * 1000, y * 1000), ((x + 4) * 1000, y * 1000), ((x + 4) * 1000, (y + 4) * 1000), (x * 1000, (y + 4) * 1000)], close=True, dxfattribs={"layer": "DEMO-ZONES"})
        drawing.modelspace().add_text("DEMO: " + case, dxfattribs={"layer": "DEMO-ZONES", "height": 180, "insert": (x * 1000, (y + 4.5) * 1000)})
    files.append({"name": "DEMO_FLOOR.dxf", "discipline": "ARCH", "content": serialize_drawing(drawing, DATASET)})
    for item in files:
        item["sha256"] = hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
    return files


def serialize_drawing(drawing, dataset):
    import ezdxf

    stream = StringIO()
    drawing.ezdxf_metadata()["CREATED_BY_EZDXF"] = dataset
    for name in sorted(drawing.entitydb.dxf_types_in_use()):
        drawing.classes.add_class(name)
    with _drawing_lock:
        fixed_metadata = ezdxf.options.write_fixed_meta_data_for_testing
        try:
            ezdxf.options.write_fixed_meta_data_for_testing = True
            drawing.write(stream)
        finally:
            ezdxf.options.write_fixed_meta_data_for_testing = fixed_metadata
    return stream.getvalue()


@lru_cache(maxsize=2)
def dataset_bundle(identifier=DATASET):
    if identifier == PILOT_DATASET:
        from app.pilot import pilot_bundle

        return pilot_bundle()
    if identifier != DATASET:
        raise ValueError("Unknown synthetic dataset")
    references = {}
    for item in demo_files()[:3]:
        model = ifcopenshell.file.from_string(item["content"])
        for product in model.by_type("IfcElement"):
            if not product.is_a("IfcFeatureElementSubtraction"):
                references.setdefault(product.Tag, []).append(product.GlobalId)
    cases = {key: {**spec, "a_guid": references[key][0], "b_guid": references[key][1], "split_group": SPLIT_GROUP} for key, spec in CASES.items()}
    return {"dataset": DATASET, "files": demo_files(), "cases": cases, "label_origin": "analytic", "independent_projects": False}


def dataset_for_hash(digest):
    if any(item["sha256"] == digest for item in demo_files()):
        return DATASET
    return PILOT_DATASET if any(item["sha256"] == digest for item in dataset_bundle(PILOT_DATASET)["files"]) else None
