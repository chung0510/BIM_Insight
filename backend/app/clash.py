from collections import Counter
import hashlib
import itertools
import json
import math
from pathlib import Path
import time

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.shape
import numpy as np

from app.demo import dataset_bundle, dataset_for_hash
from app.rules import canonical_reference, has_represented_ancestor, issue_group_key


from app.limits import MAX_ELEMENTS, MAX_ISSUES, ifc_geometry_threads
from app.ifc import inventory_ifc, account_aggregates, validate_openings, verified_unit_scale, closed_mesh
from app.ifc_policy import IFC_GEOMETRY_POLICY


SOURCE_MESH_BACKEND = "hybrid-cgal-simple-opencascade"


class IssueLimitReached(Exception):
    pass


def shared_reference_counts(groups, confirmed):
    counts = []
    for references in groups:
        by_guid = Counter()
        for (guid, family), amount in references.items():
            by_guid[guid] += amount
        counts.append((by_guid, references))
    total, unresolved = 0, 0
    for (a_guids, a_types), (b_guids, b_types) in itertools.combinations(counts, 2):
        pairs = sum(amount * b_guids.get(guid, 0) for guid, amount in a_guids.items())
        total += pairs
        unresolved += pairs - (sum(amount * b_types.get(key, 0) for key, amount in a_types.items()) if confirmed else 0)
    return total, unresolved


def precise_settings(linear_deflection_m=.0005):
    settings = ifcopenshell.geom.settings()
    settings.set("weld-vertices", True)
    settings.set("convert-back-units", False)
    settings.set("mesher-linear-deflection", linear_deflection_m)
    return settings


def source_mesh_body(product):
    pending, seen = [product], set()
    while pending:
        owner = pending.pop()
        if owner.id() in seen:
            continue
        seen.add(owner.id())
        if any(getattr(owner, kind, ()) for kind in ("HasOpenings", "HasProjections", "HasSurfaceFeatures")):
            return False
        pending.extend(relation.RelatingObject for relation in [*getattr(owner, "Decomposes", ()), *getattr(owner, "Nests", ())])
    representation = product.Representation
    if not representation:
        return False
    pending = [item for body in representation.Representations for item in body.Items]
    seen = set()
    leaves = 0
    while pending:
        item = pending.pop()
        if item.id() in seen:
            return False
        seen.add(item.id())
        if item.is_a() in {"IfcTriangulatedFaceSet", "IfcPolygonalFaceSet"}:
            leaves += 1
        elif item.is_a("IfcMappedItem"):
            pending.extend(item.MappingSource.MappedRepresentation.Items)
        else:
            return False
    return leaves > 0


def load_source_geometry(source, settings, threads, consume, update, remaining=MAX_ELEMENTS):
    path = Path(source["path"])
    if not path.is_file():
        raise ValueError("clash_source_missing")
    with path.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != source["sha256"]:
            raise ValueError("clash_source_hash_mismatch")
    mapping = json.loads(Path(source["mapping_path"]).read_text(encoding="utf-8"))
    if mapping["source_sha256"] != source["sha256"]:
        raise ValueError("clash_source_hash_mismatch")
    if not source["result"].get("length_unit_verified"):
        raise ValueError("ifc_units_unknown")
    model = ifcopenshell.open(str(path))
    verified_unit_scale(model)
    represented, parents, inventory, diagnostics = inventory_ifc(model)
    source_dataset = dataset_for_hash(source["sha256"])
    source_cases = dataset_bundle(source_dataset)["cases"] if source_dataset else {}
    represented = validate_openings(model, represented, inventory, settings, diagnostics)
    chosen = [product for product in represented if not product.is_a("IfcFeatureElementSubtraction")]
    represented_ids = {product.id() for product in chosen}
    counts = {"represented_children": sum(has_represented_ancestor(product, represented_ids) for product in chosen),
              "missing_geometry": 0, "tested_elements": 0, "nonmanifold": 0, "routing_elements": 0,
              "reference_elements": sum(item["classification"] == "reference" for item in inventory.values()),
              "subtraction_elements": 0,
              "aggregate_elements": 0, "source_elements": len(inventory), "geometry_fallback_count": 0}
    if len(chosen) + len(diagnostics) > remaining:
        raise ValueError("clash_scope_limit")
    update("building_geometry", done=0, total=len(chosen))
    group, emitted, errors = [], set(), {}

    def record_shape(shape):
        product = model.by_id(shape.id)
        if product.id() in emitted:
            return
        vertices = ifcopenshell.util.shape.get_shape_vertices(shape, shape.geometry)
        faces = ifcopenshell.util.shape.get_faces(shape.geometry)
        if not len(vertices) or not len(faces) or not np.isfinite(vertices).all() or faces.min() < 0 or faces.max() >= len(vertices):
            raise ValueError("Invalid triangle mesh")
        canonical, family = canonical_reference(product)
        container = ifcopenshell.util.element.get_container(product)
        record = {"source_id": source["id"], "source_name": source["name"], "guid": product.GlobalId,
                  "ifc_type": product.is_a(), "name": product.Name,
                  "case_id": product.Tag if product.Tag in source_cases else None,
                  "storey_guid": container.GlobalId if container else None, "canonical_guid": canonical,
                  "canonical_type": family, "closed": closed_mesh(vertices, faces),
                  "min": vertices.min(axis=0), "max": vertices.max(axis=0)}
        consume(shape, product, record)
        group.append(product)
        emitted.add(product.id())
        inventory[product.id()]["geometry_status"] = "built"
        if not record["closed"]:
            counts["nonmanifold"] += 1
        if any(product.is_a(kind) for kind in ["IfcPipeSegment", "IfcDuctSegment", "IfcCableCarrierSegment", "IfcCableSegment"]):
            counts["routing_elements"] += 1
        update("building_geometry", done=len(emitted), total=len(chosen))

    # Release each native conversion cache before another batch or individual fallback.
    for batch in itertools.batched(chosen, 128):
        mesh_ids = {product.id() for product in batch if source_mesh_body(product)}
        for backend, products in ((SOURCE_MESH_BACKEND, [p for p in batch if p.id() in mesh_ids]),
                                  ("opencascade", [p for p in batch if p.id() not in mesh_ids])):
            if not products:
                continue
            iterator = None
            try:
                iterator = ifcopenshell.geom.iterator(settings, model, threads, include=products, geometry_library=backend)
                for shape in iterator:
                    try:
                        record_shape(shape)
                    except (RuntimeError, ValueError) as error:
                        errors[shape.id] = str(error)[:1000]
            except (RuntimeError, ValueError) as error:
                for product in products:
                    errors[product.id()] = str(error)[:1000]
            finally:
                del iterator
        for product in batch:
            if product.id() in emitted:
                continue
            try:
                record_shape(ifcopenshell.geom.create_shape(settings, product))
                counts["geometry_fallback_count"] += 1
            except (RuntimeError, ValueError) as error:
                errors[product.id()] = str(error)[:1000]
    for product in chosen:
        if product.id() not in emitted:
            inventory[product.id()].update(geometry_status="unassessed", reason="geometry_failed",
                                           detail=errors.get(product.id(), "No triangulated geometry returned"))
    account_aggregates(parents, emitted, inventory, diagnostics)
    counts["aggregate_elements"] = sum(item["classification"] == "aggregate" for item in inventory.values())
    counts["subtraction_elements"] = sum(item["geometry_status"] == "validated_subtraction" for item in inventory.values())
    failures = [item for item in inventory.values() if item["geometry_status"] == "unassessed"]
    counts["missing_geometry"] = len(failures)
    counts["tested_elements"] = len(group)
    if counts["source_elements"] != sum(counts[key] for key in ("tested_elements", "missing_geometry", "reference_elements", "subtraction_elements", "aggregate_elements")):
        raise ValueError("ifc_inventory_incomplete")
    return model, group, counts, {"inventory": list(inventory.values()), "diagnostics": failures}

def check_clashes(sources, parameters, progress=None, cache_dir=None, work_dir=None):
    started = time.perf_counter()
    threads = ifc_geometry_threads()
    result = {"status": "failed", "verdict": "unavailable", "clash_detection": "failed", "issues": [], "diagnostics": [], "evaluation": None, "parameters": parameters, "engine": "ifcopenshell-0.8.5-triangle-bvh", "coverage": {"missing_geometry": 0, "nonmanifold": 0, "candidate_pairs": 0, "tested_elements": 0, "represented_children": 0, "shared_reference_pairs": 0, "routing_elements": 0}}
    coverage = result["coverage"]
    coverage.update(reference_elements=0, subtraction_elements=0, aggregate_elements=0, source_elements=0, geometry_fallback_count=0)
    result.update(geometry_policy=IFC_GEOMETRY_POLICY, geometry_diagnostics=[], source_inventories=[])
    def update(phase, **values):
        if progress:
            progress({"phase": phase, "issues": len(result["issues"]), **values})
    if not parameters.get("coordinates_confirmed"):
        result["diagnostics"].append({"code": "clash_frame_unconfirmed"})
        return result
    settings = precise_settings(min(.0005, parameters["tolerance_mm"] / 2000))
    result["geometry_settings"] = {"linear_deflection_m": settings.get("mesher-linear-deflection"), "angular_deflection_rad": settings.get("mesher-angular-deflection"), "coordinate_units": "metre", "threads": threads, "backend": "opencascade", "source_mesh_backend": SOURCE_MESH_BACKEND, "source_mesh_scope": "explicit_tessellation_without_boolean_features", "memory_scope": "two_cached_sources_per_pair" if cache_dir is not None else "direct_sources"}
    models, groups, records, manifests, all_records, reference_groups = [], [], {}, [], [], []
    tree = None

    def account_source(source, counts, details, elements):
        for key, amount in counts.items():
            coverage[key] += amount
        result["source_inventories"].append({"source_id": source["id"], "source_sha256": source["sha256"], "elements": details["inventory"]})
        result["geometry_diagnostics"].extend({"source_id": source["id"], "source_name": source["name"], **item} for item in details["diagnostics"])
        elements = [{**item, "source_id": source["id"], "source_name": source["name"]} for item in elements]
        all_records.extend(elements)
        reference_groups.append(Counter((item["canonical_guid"], item["canonical_type"]) for item in elements))

    try:
        if cache_dir is not None:
            from app.clash_cache import prepare_cached_geometry, load_cached_geometry
            # Prepare all meshes without holding any triangle tree; load only one source pair later.
            for source_index, source in enumerate(sources, 1):
                context = {"source_name": source["name"], "source_index": source_index, "source_count": len(sources)}
                update("loading_model", **context)
                def source_update(phase, **values):
                    update(phase, **values, **context)
                _, manifest = prepare_cached_geometry(source, cache_dir, work_dir, settings, threads, source_update,
                                                       MAX_ELEMENTS - coverage["tested_elements"] - coverage["missing_geometry"])
                manifests.append(manifest)
                account_source(source, manifest["counts"], manifest["details"], manifest["elements"])
        else:
            tree = ifcopenshell.geom.tree()
            for source_index, source in enumerate(sources, 1):
                context = {"source_name": source["name"], "source_index": source_index, "source_count": len(sources)}
                update("loading_model", **context)
                def consume(shape, product, record):
                    tree.add_element(shape)
                    records[product.wrapped_data.identity()] = record
                def source_update(phase, **values):
                    update(phase, **values, **context)
                model, group, counts, details = load_source_geometry(source, settings, threads, consume, source_update,
                                                                     MAX_ELEMENTS - coverage["tested_elements"] - coverage["missing_geometry"])
                models.append(model)
                groups.append(group)
                account_source(source, counts, details, [records[product.wrapped_data.identity()] for product in group])
        if not coverage["tested_elements"]:
            raise ValueError("clash_no_geometry")
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        code = "clash_cache_permission_denied" if isinstance(error, PermissionError) else str(error) if str(error).startswith(("clash_", "ifc_", "processing_")) else "clash_geometry_failed"
        result["diagnostics"].append({"code": code})
        result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        return result

    def load_pair(indices):
        pair_tree, pair_models, pair_groups, pair_records = ifcopenshell.geom.tree(), [], [], {}
        def consume(shape, product, record):
            pair_tree.add_element(shape)
            pair_records[product.wrapped_data.identity()] = record
        for index in indices:
            source = sources[index]
            def source_update(phase, **values):
                update(phase, **values, source_name=source["name"], source_index=index + 1, source_count=len(sources))
            model, group, _, _ = load_cached_geometry(source, cache_dir, work_dir, settings, threads, consume, source_update, MAX_ELEMENTS)
            pair_models.append(model)
            pair_groups.append(group)
        return pair_tree, pair_models, pair_groups, pair_records

    tolerance = parameters["tolerance_mm"] / 1000
    clearance = parameters["clearance_mm"] / 1000
    seen = set()
    issue_limit_reached = False
    public_keys = ["source_id", "source_name", "guid", "ifc_type", "name", "storey_guid", "canonical_guid"]
    ambiguous, unresolved_references = shared_reference_counts(reference_groups, parameters.get("shared_references_confirmed"))
    if unresolved_references:
        result["diagnostics"].append({"code": "clash_reference_ambiguous", "pair_count": unresolved_references})
    def append_issue(clash, kind):
        a, b = records[clash.a.identity()], records[clash.b.identity()]
        pair = tuple(sorted((a["source_id"] + ":" + a["guid"], b["source_id"] + ":" + b["guid"])))
        if pair in seen:
            return
        if a["canonical_guid"] == b["canonical_guid"]:
            return
        seen.add(pair)
        if len(result["issues"]) >= MAX_ISSUES:
            raise IssueLimitReached
        p1, p2 = list(clash.p1), list(clash.p2)
        distance = float(clash.distance)
        if not all(math.isfinite(n) for n in [*p1, *p2, distance]):
            result["diagnostics"].append({"code": "clash_invalid_measurement"})
            return
        if kind == "intersection" and (not a["closed"] or not b["closed"] or clash.clash_type == 2):
            kind = "surface_review"
        stable_key = "|".join(sorted([a["source_id"] + ":" + a["guid"], b["source_id"] + ":" + b["guid"]])) + "|" + kind
        result["issues"].append({"id": hashlib.sha256(stable_key.encode()).hexdigest()[:24], "kind": kind, "a": {key: a[key] for key in public_keys}, "b": {key: b[key] for key in public_keys}, "distance_m": None if kind == "surface_review" else distance, "measure_kind": "surface_distance" if kind == "clearance" else "kernel_protrusion_or_pierce" if kind == "intersection" else "not_established", "required_clearance_m": clearance if kind == "clearance" else None, "point_m": [(x + y) / 2 for x, y in zip(p1, p2)], "p1_m": p1, "p2_m": p2, "kernel_type": ["protrusion", "pierce", "collision", "clearance"][clash.clash_type], "case_id": a["case_id"] if a["case_id"] == b["case_id"] else None})
        result["issues"][-1]["group_id"] = issue_group_key(a, b, kind)
        routing = any(any(token in item["ifc_type"] for token in ["Pipe", "Duct", "Cable", "Flow"]) for item in [a, b])
        result["issues"][-1]["recommendation"] = (
            "Kiểm tra lại hình học và bề mặt chưa kín trước khi chọn phương án xử lý." if kind == "surface_review" else
            "Xem xét đổi tuyến hoặc cao độ, rồi chạy lại kiểm tra khoảng hở. Mọi lỗ xuyên kết cấu cần người thiết kế kết cấu chấp thuận." if routing else
            "Đối chiếu đối tượng chủ, tầng và ý đồ thiết kế để phân biệt giao có chủ ý với cấu kiện đặt sai; chỉnh mô hình nguồn rồi kiểm tra lại."
        )

    try:
        margin = clearance if parameters["mode"] == "clearance" else tolerance
        batches_done = 0
        sizes = [manifest["counts"]["tested_elements"] for manifest in manifests] if cache_dir is not None else [len(group) for group in groups]
        batches_total = sum(math.ceil(a / 64) for a, b in itertools.combinations(sizes, 2))
        update("checking_pairs", done=0, total=batches_total)
        pairs = itertools.combinations(range(len(sources)), 2) if cache_dir is not None else itertools.combinations(groups, 2)
        for pair in pairs:
            if cache_dir is not None and (not sizes[pair[0]] or not sizes[pair[1]]):
                batches_done += math.ceil(sizes[pair[0]] / 64)
                update("checking_pairs", done=batches_done, total=batches_total)
                continue
            if cache_dir is not None and len(sources) > 2:
                from app.clash_cache import check_cached_pair
                update("loading_geometry", source_name=sources[pair[0]]["name"], source_index=pair[0] + 1,
                       source_count=len(sources), done=0, total=sizes[pair[0]])
                def pair_update(value):
                    phase = value.get("phase", "checking_pairs")
                    if phase == "checking_pairs":
                        update(phase, done=batches_done + value.get("done", 0), total=batches_total)
                    else:
                        index = next((index for index in pair if sources[index]["name"] == value.get("source_name")), pair[0])
                        update(phase, **{key: item for key, item in value.items() if key not in {"phase", "source_index", "source_count", "issues"}}, source_index=index + 1, source_count=len(sources))
                checked = check_cached_pair([sources[index] for index in pair], parameters, cache_dir, work_dir, pair_update)
                coverage["candidate_pairs"] += checked["coverage"]["candidate_pairs"]
                remaining = MAX_ISSUES - len(result["issues"])
                result["issues"].extend(checked["issues"][:remaining])
                issue_limit_reached = len(checked["issues"]) > remaining or any(item["code"] == "clash_issue_limit" for item in checked["diagnostics"])
                unexpected = [item for item in checked["diagnostics"] if item["code"] not in {"clash_issue_limit", "clash_missing_geometry", "clash_nonmanifold", "clash_surface_review", "clash_reference_ambiguous"}]
                result["diagnostics"].extend(unexpected)
                batches_done += math.ceil(sizes[pair[0]] / 64)
                update("checking_pairs", done=batches_done, total=batches_total)
                if issue_limit_reached:
                    break
                continue
            if cache_dir is not None:
                tree, models, groups, records = load_pair(pair)
                group_a, group_b = groups
            else:
                group_a, group_b = pair
            bounds_b = [records[p.wrapped_data.identity()] for p in group_b]
            if bounds_b:
                b_min = np.array([item["min"] for item in bounds_b])
                b_max = np.array([item["max"] for item in bounds_b])
                for product in group_a:
                    item = records[product.wrapped_data.identity()]
                    coverage["candidate_pairs"] += int(np.sum(np.all(b_max >= item["min"] - margin, axis=1) & np.all(b_min <= item["max"] + margin, axis=1)))
            solid_b = [p for p in group_b if records[p.wrapped_data.identity()]["closed"]]
            open_b = [p for p in group_b if not records[p.wrapped_data.identity()]["closed"]]
            # Bound each kernel result list before it crosses from C++ into Python.
            for batch in itertools.batched(group_a, 64):
                batch = list(batch)
                solid_a = [p for p in batch if records[p.wrapped_data.identity()]["closed"]]
                if solid_a and solid_b:
                    for clash in tree.clash_intersection_many(solid_a, solid_b, tolerance=tolerance, check_all=True):
                        append_issue(clash, "intersection")
                    # Coincident faces need review without claiming a penetration depth.
                    for clash in tree.clash_clearance_many(solid_a, solid_b, clearance=tolerance, check_all=True):
                        a, b = records[clash.a.identity()], records[clash.b.identity()]
                        overlap = np.minimum(a["max"], b["max"]) - np.maximum(a["min"], b["min"])
                        if clash.distance <= 1e-7 and np.all(overlap > tolerance):
                            append_issue(clash, "surface_review")
                for open_group, other_group in [([p for p in batch if not records[p.wrapped_data.identity()]["closed"]], group_b), (solid_a, open_b)]:
                    if open_group and other_group:
                        for clash in tree.clash_collision_many(open_group, other_group, allow_touching=True):
                            append_issue(clash, "surface_review")
                if parameters["mode"] == "clearance":
                    for clash in tree.clash_clearance_many(batch, group_b, clearance=clearance, check_all=True):
                        append_issue(clash, "clearance")
                batches_done += 1
                update("checking_pairs", done=batches_done, total=batches_total)
            if cache_dir is not None:
                tree, models, groups, records = None, [], [], {}
    except IssueLimitReached:
        pass
    except Exception as error:
        code = "clash_cache_permission_denied" if isinstance(error, PermissionError) else str(error) if str(error).startswith(("clash_", "ifc_", "processing_")) else "clash_check_failed"
        result["diagnostics"].append({"code": code})
        result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        return result
    coverage["shared_reference_pairs"] = ambiguous
    if issue_limit_reached or len(seen) > MAX_ISSUES:
        result["diagnostics"].append({"code": "clash_issue_limit", "limit": MAX_ISSUES})
    if coverage["missing_geometry"]:
        result["diagnostics"].append({"code": "clash_missing_geometry"})
    if coverage["nonmanifold"]:
        result["diagnostics"].append({"code": "clash_nonmanifold"})
    if any(item["kind"] == "surface_review" for item in result["issues"]):
        result["diagnostics"].append({"code": "clash_surface_review"})
    partial = bool(result["diagnostics"])
    result["status"] = "partial" if partial else "completed"
    result["clash_detection"] = result["status"]
    result["verdict"] = "incomplete" if partial else "findings" if result["issues"] else "clear_in_scope"
    result["counts"] = dict(Counter(item["kind"] for item in result["issues"]))
    result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    datasets = {dataset_for_hash(source["sha256"]) for source in sources}
    eligible = not coverage["missing_geometry"] and all(item["code"] in {"clash_surface_review", "clash_nonmanifold"} for item in result["diagnostics"])
    if eligible and len(sources) == 3 and len(datasets) == 1 and None not in datasets and parameters["tolerance_mm"] == 1 and parameters["clearance_mm"] == 50:
        bundle = dataset_bundle(next(iter(datasets)))
        cases = bundle["cases"]
        by_guid = {item["guid"]: item for item in all_records}
        case_results = []
        for case_id, spec in cases.items():
            expected_kind = "intersection" if spec["hard"] else "clearance" if parameters["mode"] == "clearance" and spec["clearance"] else "no_clash"
            findings = [item["kind"] for item in result["issues"] if item["case_id"] == case_id]
            detected = next((kind for kind in ["intersection", "surface_review", "clearance"] if kind in findings), "no_clash")
            complete = bool(by_guid[spec["a_guid"]]["closed"] and by_guid[spec["b_guid"]]["closed"])
            case_results.append({"case_id": case_id, "label": spec["label"], "expected": expected_kind, "detected": detected if complete else "insufficient_data", "geometry_complete": complete, "expected_origin": "analytic", "split_group": spec["split_group"], "a": {key: by_guid[spec["a_guid"]][key] for key in public_keys}, "b": {key: by_guid[spec["b_guid"]][key] for key in public_keys}})
        assessed = [item for item in case_results if item["geometry_complete"]]
        expected = {item["case_id"] for item in assessed if item["expected"] != "no_clash"}
        actual = {item["case_id"] for item in assessed if item["detected"] != "no_clash"}
        tp, fp, fn = len(expected & actual), len(actual - expected), len(expected - actual)
        failures = [item["case_id"] for item in case_results if item["expected"] != item["detected"]]
        result["evaluation"] = {"scope": "synthetic_only", "unit": "analytic_case", "cases": len(cases), "assessed_cases": len(assessed), "tp": tp, "fp": fp, "fn": fn, "precision": tp / (tp + fp) if tp + fp else 1., "recall": tp / (tp + fn) if tp + fn else 1., "positive_definition": "flagged_case_including_surface_review", "typed_case_accuracy": (len(cases) - len(failures)) / len(cases), "uncertain_cases": sum(item["detected"] in {"surface_review", "insufficient_data"} for item in case_results), "failed_cases": failures, "case_results": case_results}
    return result
