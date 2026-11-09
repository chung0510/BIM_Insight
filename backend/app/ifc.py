from collections import Counter
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import time

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.unit
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.shape
import numpy as np
from app.glb import compact_glb
from app.ifc_policy import IFC_GEOMETRY_POLICY
from app.limits import MAX_GLB_BYTES, MAX_MAPPING_BYTES, ifc_geometry_threads, ifc_geometry_batch_size


def world_bounds(shape, geometry):
    vertices = ifcopenshell.util.shape.get_vertices(geometry)
    if not len(vertices):
        raise ValueError("Empty mesh")
    matrix = ifcopenshell.util.shape.get_shape_matrix(shape)
    lower, upper = np.full(3, np.inf), np.full(3, -np.inf)
    for offset in range(0, len(vertices), 65536):
        world = vertices[offset:offset + 65536] @ matrix[:3, :3].T
        world += matrix[:3, 3]
        if not np.isfinite(world).all():
            raise ValueError("Invalid mesh")
        lower = np.minimum(lower, world.min(axis=0))
        upper = np.maximum(upper, world.max(axis=0))
    return {"min": lower.tolist(), "max": upper.tolist()}


def verified_unit_scale(model):
    projects = model.by_type("IfcProject")
    units = [unit for project in projects if project.UnitsInContext for unit in project.UnitsInContext.Units if getattr(unit, "UnitType", None) == "LENGTHUNIT"]
    scale = ifcopenshell.util.unit.calculate_unit_scale(model)
    if len(projects) != 1 or len(units) != 1 or not math.isfinite(scale) or scale <= 0:
        raise ValueError("ifc_units_unknown")
    return scale


def closed_mesh(vertices, faces):
    if len(faces) < 4:
        return False
    edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    if not np.all(counts == 2):
        return False
    local = vertices - vertices.mean(axis=0)
    volume = abs(np.einsum("ij,ij->i", local[faces[:, 0]], np.cross(local[faces[:, 1]], local[faces[:, 2]])).sum()) / 6
    return math.isfinite(volume) and volume > 1e-12


def only_reference_items(items, visiting=None):
    if not items:
        return False
    visiting = set() if visiting is None else visiting
    for item in items:
        if item.id() in visiting:
            return False
        if item.is_a("IfcCurve") or item.is_a("IfcPoint"):
            continue
        if item.is_a("IfcMappedItem"):
            children = item.MappingSource.MappedRepresentation.Items
        elif item.is_a("IfcGeometricSet"):
            children = item.Elements
        else:
            return False
        if not only_reference_items(children, visiting | {item.id()}):
            return False
    return True


def select_physical_body(model, product):
    representation = product.Representation
    representations = tuple(representation.Representations)
    bodies = [item for item in representations if (item.RepresentationIdentifier or "").lower() == "body"]
    if not bodies:
        reference = bool(representations) and all(only_reference_items(item.Items) for item in representations)
        # A wall/pipe with only curves is still an unresolved physical object, never a safe exclusion.
        if reference and product.is_a("IfcBuildingElementProxy") and all(
            (item.RepresentationIdentifier or "").lower() in {"annotation", "axis", "footprint"} for item in representations
        ):
            raise ValueError("ifc_reference_only")
        candidates = [item for item in representations if (item.RepresentationIdentifier or "").lower() not in {"box", "clearance", "axis", "footprint"}]
        if not candidates:
            raise ValueError("ifc_body_missing")
        bodies = candidates
    if not any(body.Items for body in bodies) or all(only_reference_items(body.Items) for body in bodies):
        raise ValueError("ifc_body_nonphysical")
    if len(bodies) > 1:
        def frame(context):
            while getattr(context, "ParentContext", None):
                context = context.ParentContext
            placement = getattr(context, "WorldCoordinateSystem", None)
            return ifcopenshell.util.placement.get_axis2placement(placement) if placement else np.eye(4)
        reference = frame(bodies[0].ContextOfItems)
        if any(not np.allclose(reference, frame(item.ContextOfItems), rtol=0, atol=1e-9) for item in bodies[1:]):
            raise ValueError("ifc_body_context_ambiguous")
        items = tuple({item.id(): item for body in bodies for item in body.Items}.values())
        kinds = {body.RepresentationType for body in bodies}
        bodies = [model.create_entity("IfcShapeRepresentation", ContextOfItems=bodies[0].ContextOfItems,
                  RepresentationIdentifier="Body", RepresentationType=next(iter(kinds)) if len(kinds) == 1 else None, Items=items)]
    if tuple(bodies) != representations:
        # Filter only this in-memory geometry view; the original IFC and its hash stay unchanged.
        product.Representation = model.create_entity("IfcProductDefinitionShape", Name=representation.Name,
                                                    Description=representation.Description, Representations=tuple(bodies))


def inventory_ifc(model):
    products = model.by_type("IfcElement")
    counts = Counter(product.GlobalId for product in products)
    represented, parents, inventory, diagnostics = [], [], {}, []
    for product in products:
        guid = product.GlobalId
        item = {"step_id": product.id(), "guid": guid, "ifc_type": product.is_a(), "name": product.Name,
                "classification": "unassessed", "geometry_status": "pending"}
        inventory[product.id()] = item
        code = None
        if not guid or counts[guid] > 1:
            code = "missing_or_duplicate_guid"
        elif not re.fullmatch(r"[0-3][0-9A-Za-z_$]{21}", guid):
            code = "invalid_guid"
        elif product.Representation is None:
            parents.append(product)
            continue
        else:
            try:
                select_physical_body(model, product)
                item["classification"] = "subtraction" if product.is_a("IfcFeatureElementSubtraction") else "physical"
                represented.append(product)
            except ValueError as error:
                code = str(error)
                if code == "ifc_reference_only":
                    item.update(classification="reference", geometry_status="not_applicable")
                    continue
        if code:
            item.update(geometry_status="unassessed", reason=code)
            diagnostics.append({"guid": guid, "code": code})
    return represented, parents, inventory, diagnostics


def account_aggregates(parents, successful_ids, inventory, diagnostics):
    for parent in parents:
        pending, visited, represented = [parent], {parent.id()}, False
        while pending:
            current = pending.pop()
            for relation in [*getattr(current, "IsDecomposedBy", ()), *getattr(current, "IsNestedBy", ())]:
                for child in relation.RelatedObjects:
                    if child.id() not in visited:
                        visited.add(child.id())
                        pending.append(child)
                        represented |= child.id() in successful_ids
        item = inventory[parent.id()]
        if represented and not parent.is_a("IfcFeatureElementSubtraction"):
            item.update(classification="aggregate", geometry_status="represented_by_children")
        else:
            item.update(geometry_status="unassessed", reason="missing_representation")
            diagnostics.append({"guid": parent.GlobalId, "code": "missing_representation"})


def validate_openings(model, represented, inventory, settings, diagnostics):
    invalid = set()
    for opening in model.by_type("IfcFeatureElementSubtraction"):
        item = inventory[opening.id()]
        if item["classification"] != "subtraction":
            invalid.add(opening.id())
            continue
        shape = None
        try:
            shape = ifcopenshell.geom.create_shape(settings, opening)
            vertices = ifcopenshell.util.shape.get_shape_vertices(shape, shape.geometry)
            faces = ifcopenshell.util.shape.get_faces(shape.geometry)
            if not len(vertices) or not len(faces) or not np.isfinite(vertices).all() or faces.min() < 0 or faces.max() >= len(vertices) or not closed_mesh(vertices, faces):
                raise ValueError("Opening does not define a valid closed volume")
            item["geometry_status"] = "validated_subtraction"
        except (RuntimeError, ValueError, TypeError) as error:
            item.update(geometry_status="unassessed", reason="ifc_opening_geometry_failed", detail=str(error)[:1000])
            invalid.add(opening.id())
            diagnostics.append({"guid": opening.GlobalId, "code": "ifc_opening_geometry_failed"})
        finally:
            del shape
    valid = []
    for product in represented:
        if product.id() in invalid:
            continue
        pending, visited, blocked = [product], set(), False
        while pending:
            owner = pending.pop()
            if owner.id() in visited:
                continue
            visited.add(owner.id())
            blocked |= any(relation.RelatedOpeningElement.id() in invalid for relation in getattr(owner, "HasOpenings", ()))
            pending.extend(relation.RelatingObject for relation in [*getattr(owner, "Decomposes", ()), *getattr(owner, "Nests", ())])
        if blocked:
            inventory[product.id()].update(geometry_status="unassessed", reason="ifc_opening_geometry_failed",
                                          detail="Host or ancestor has an invalid opening; uncut geometry is not accepted")
            diagnostics.append({"guid": product.GlobalId, "code": "ifc_opening_geometry_failed"})
        else:
            valid.append(product)
    return valid


def select_opening_bodies(model, products):
    pending, visited, normalized = list(products), set(), set()
    while pending:
        product = pending.pop()
        if product.id() in visited:
            continue
        visited.add(product.id())
        for relation in getattr(product, "HasOpenings", ()):
            opening = relation.RelatedOpeningElement
            if opening.id() not in normalized:
                if opening.Representation is None:
                    raise ValueError("ifc_body_missing")
                select_physical_body(model, opening)
                normalized.add(opening.id())
        for relation in [*getattr(product, "Decomposes", ()), *getattr(product, "Nests", ())]:
            pending.append(relation.RelatingObject)



def inspect_ifc(path: Path, assets_dir: Path | None = None, progress=None) -> dict:
    started = time.perf_counter()
    # Release the native IFC/conversion graph before parsing and packing GLB buffers.
    report = _read_ifc(path, assets_dir, progress)
    if assets_dir is not None and report["mapping_available"] and report["element_count"]:
        if progress:
            progress({"phase": "optimizing_preview"})
        try:
            report["viewer_optimization"] = compact_glb(assets_dir / "model.glb")
        except Exception:
            report["viewer_optimization_error"] = "ifc_preview_optimization_failed"
        report["viewer_available"] = (assets_dir / "model.glb").stat().st_size <= MAX_GLB_BYTES
        if report["viewer_available"]:
            report["diagnostics"] = [item for item in report["diagnostics"] if item["code"] != "ifc_viewer_limit"]
        report["status"] = "partial" if report["diagnostics"] else "completed"
    report["elapsed_seconds"] = time.perf_counter() - started
    return report


def _read_ifc(path: Path, assets_dir: Path | None, progress) -> dict:
    path = Path(path)
    started = time.perf_counter()
    threads = ifc_geometry_threads()
    batch_size = ifc_geometry_batch_size()
    def update(phase, **values):
        if progress:
            progress({"phase": phase, **values})
    report = {
        "status": "failed", "clash_detection": "not_run", "scope": "geometry_import_only",
        "elements": [], "element_count": 0, "excluded_count": 0, "aggregate_count": 0, "subtraction_count": 0, "diagnostics": [],
        "geometry_policy": IFC_GEOMETRY_POLICY, "reference_count": 0, "reference_elements": [], "inventory": [], "geometry_failures": [],
        "viewer_available": False, "mapping_available": False, "storeys": [], "grids": [],
    }
    try:
        update("reading_ifc")
        with path.open("rb") as handle:
            report["source_sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
            handle.seek(0)
            if not handle.read(4096).lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"ISO-10303-21;"):
                raise ValueError("Expected a STEP IFC file")
        model = ifcopenshell.open(str(path))
        report["ifc_schema"] = model.schema
        try:
            scale = verified_unit_scale(model)
        except ValueError:
            report["diagnostics"].append({"code": "ifc_units_unknown"})
            report["elapsed_seconds"] = time.perf_counter() - started
            return report
        report["project_unit_scale_to_m"] = scale
        report["length_unit_verified"] = True
        products = model.by_type("IfcElement")
        report["subtraction_count"] = sum(product.is_a("IfcFeatureElementSubtraction") for product in products)
        report["source_guids"] = [product.GlobalId for product in products if product.GlobalId]
        report["total_element_count"] = len(products)
        report["project_guids"] = [item.GlobalId for item in model.by_type("IfcProject")]
        scale = report["project_unit_scale_to_m"]
        for storey in model.by_type("IfcBuildingStorey"):
            elevation = float(ifcopenshell.util.placement.get_local_placement(storey.ObjectPlacement)[2, 3]) * scale
            if np.isfinite(elevation):
                report["storeys"].append({"guid": storey.GlobalId, "name": storey.Name or storey.GlobalId, "elevation_m": elevation})
        for grid in model.by_type("IfcGrid"):
            placement = ifcopenshell.util.placement.get_local_placement(grid.ObjectPlacement)
            lines = []
            axes = [*grid.UAxes, *grid.VAxes, *(grid.WAxes or [])]
            for axis in axes:
                curve = axis.AxisCurve
                coordinates = curve.Points.CoordList if curve.is_a("IfcIndexedPolyCurve") else [point.Coordinates for point in curve.Points] if curve.is_a("IfcPolyline") else []
                if len(coordinates) == 2 and (not curve.is_a("IfcIndexedPolyCurve") or not curve.Segments or all(segment.is_a("IfcLineIndex") for segment in curve.Segments)):
                    points = [(placement @ np.array([*p, *([0] if len(p) == 2 else []), 1]))[:3] * scale for p in coordinates]
                    if np.isfinite(points).all():
                        lines.append({"tag": axis.AxisTag, "start_m": points[0].tolist(), "end_m": points[1].tolist()})
            report["grids"].append({"guid": grid.GlobalId, "elevation_m": float(placement[2, 3] * scale), "axis_count": len(axes), "lines": lines})
    except Exception:
        report["diagnostics"].append({"code": "invalid_ifc"})
        report["elapsed_seconds"] = time.perf_counter() - started
        return report

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, False)
    settings.set(settings.CONVERT_BACK_UNITS, False)
    settings.set("apply-default-materials", True)
    report["geometry_settings"] = {"backend": "hybrid-cgal-simple-opencascade", "threads": threads, "batch_elements": batch_size, "linear_deflection_m": settings.get("mesher-linear-deflection"), "angular_deflection_rad": settings.get("mesher-angular-deflection"), "scope": "import_preview_only", "representation_scope": "physical_body_preferred", "clash_geometry": "rebuilt_from_source"}
    serializer = None
    if assets_dir is not None:
        serializer_options = ifcopenshell.geom.serializer_settings()
        serializer_options.set("use-element-guids", True)
        serializer = ifcopenshell.geom.serializers.gltf(str(assets_dir / "model.glb"), settings, serializer_options)
        serializer.setFile(model)
        serializer.setUnitNameAndMagnitude("METER", 1.0)
        serializer.writeHeader()
    update("preparing_geometry", done=0, total=len(products))
    represented, parents, inventory, diagnostics = inventory_ifc(model)
    report["inventory"] = list(inventory.values())
    report["diagnostics"].extend(diagnostics)
    report["reference_elements"] = [item for item in inventory.values() if item["classification"] == "reference"]
    report["reference_count"] = len(report["reference_elements"])
    report["excluded_count"] = len(diagnostics)

    emitted = set()
    report["geometry_fallback_count"] = 0
    represented = validate_openings(model, represented, inventory, settings, report["diagnostics"])

    def record_shape(shape):
        product = model.by_id(shape.id)
        guid = product.GlobalId
        faces = ifcopenshell.util.shape.get_faces(shape.geometry)
        if not len(faces):
            raise ValueError("Invalid mesh")
        bounds = world_bounds(shape, shape.geometry)
        is_void = product.is_a("IfcFeatureElementSubtraction")
        if is_void:
            emitted.add(product.id())
            inventory[product.id()]["geometry_status"] = "subtraction_geometry"
            return
        container = ifcopenshell.util.element.get_container(product)
        report["elements"].append({
            "guid": guid, "ifc_type": product.is_a(), "name": product.Name,
            "bounds_m": bounds, "triangle_count": len(faces),
            "storey_guid": container.GlobalId if container else None, "is_void": is_void,
        })
        emitted.add(product.id())
        inventory[product.id()]["geometry_status"] = "built"
        if serializer is not None:
            try:
                serializer.write(shape)
            except Exception:
                report["diagnostics"].append({"guid": guid, "code": "ifc_viewer_failed"})

    errors = {}
    update("building_geometry", done=0, total=len(represented))
    # Bound the native conversion cache instead of retaining every mesh until the end.
    for batch in itertools.batched(represented, batch_size):
        iterator = None
        try:
            iterator = ifcopenshell.geom.iterator(settings, model, threads, include=batch, geometry_library="hybrid-cgal-simple-opencascade")
            for shape in iterator:
                try:
                    record_shape(shape)
                    update("building_geometry", done=len(emitted), total=len(represented))
                except Exception as error:
                    errors[shape.id] = str(error)[:1000]
        except (RuntimeError, ValueError) as error:
            for product in batch:
                errors[product.id()] = str(error)[:1000]
        finally:
            del iterator
    for product in represented:
        if product.id() not in emitted:
            try:
                record_shape(ifcopenshell.geom.create_shape(settings, product))
                report["geometry_fallback_count"] += 1
                update("building_geometry", done=len(emitted), total=len(represented))
            except Exception as error:
                errors[product.id()] = str(error)[:1000]
    for product in represented:
        if product.id() not in emitted:
            report["excluded_count"] += 1
            report["diagnostics"].append({"guid": product.GlobalId, "code": "geometry_failed"})
            inventory[product.id()].update(geometry_status="unassessed", reason="geometry_failed")
            report["geometry_failures"].append({**inventory[product.id()], "detail": errors.get(product.id(), "No triangulated geometry returned")})

    account_aggregates(parents, {product.id() for product in represented if product.id() in emitted and not product.is_a("IfcFeatureElementSubtraction")}, inventory, report["diagnostics"])
    report["aggregate_count"] = sum(item["classification"] == "aggregate" for item in inventory.values())
    report["excluded_count"] = sum(item["geometry_status"] == "unassessed" for item in inventory.values())

    if serializer is not None:
        try:
            update("writing_preview")
            serializer.finalize()
            del serializer
            report["viewer_available"] = bool(report["elements"]) and (assets_dir / "model.glb").stat().st_size <= MAX_GLB_BYTES
            if report["elements"] and not report["viewer_available"]:
                report["diagnostics"].append({"code": "ifc_viewer_limit"})
        except Exception:
            report["diagnostics"].append({"code": "ifc_viewer_failed"})
        with (assets_dir / "model.json").open("x", encoding="utf-8") as handle:
            json.dump({"world_up": "Z", "gltf_up": "Y", "source_sha256": report["source_sha256"],
                       "geometry_policy": IFC_GEOMETRY_POLICY, "elements": report["elements"]}, handle, ensure_ascii=False, allow_nan=False)
        report["mapping_available"] = (assets_dir / "model.json").stat().st_size <= MAX_MAPPING_BYTES
        report["viewer_available"] &= report["mapping_available"]

    report["element_count"] = len(report["elements"])
    report["status"] = "partial" if report["diagnostics"] else "completed"
    if not products:
        report["status"] = "partial"
        report["diagnostics"].append({"code": "no_elements"})
    report["elapsed_seconds"] = time.perf_counter() - started
    return report


