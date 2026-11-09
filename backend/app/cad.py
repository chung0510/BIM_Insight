from collections import Counter
import json
import math
from pathlib import Path
import re

import ezdxf
from ezdxf import units


MAX_PREVIEW_BYTES = 64 * 1024 * 1024
MAX_PREVIEW_PATHS = 200000
UNICODE_ESCAPE = re.compile(r"\\U\+([0-9a-fA-F]{4})")


def decode_text(text):
    return UNICODE_ESCAPE.sub(lambda match: chr(int(match[1], 16)), text)


def drawing_preview(doc):
    from ezdxf.addons.drawing import Frontend, RenderContext, config, layout, svg

    class LayerRenderer(svg.SVGRenderBackend):
        def add_strokes(self, d, properties):
            before = len(self.entities)
            super().add_strokes(d, properties)
            if len(self.entities) > before:
                self.entities[-1].set("data-layer", properties.layer)

        def add_filling(self, d, properties):
            before = len(self.entities)
            super().add_filling(d, properties)
            if len(self.entities) > before:
                self.entities[-1].set("data-layer", properties.layer)

    class LayerBackend(svg.SVGBackend):
        @staticmethod
        def make_backend(page, settings):
            return LayerRenderer(page, settings)

    # Draw hidden layers in RAM too; the viewer applies the source visibility.
    for layer in doc.layers:
        layer.on()
        layer.thaw()
    for entity in doc.entitydb.values():
        if entity.dxftype() == "MTEXT":
            entity.text = decode_text(entity.text)
        elif entity.dxftype() in {"TEXT", "ATTRIB", "ATTDEF"}:
            entity.dxf.text = decode_text(entity.dxf.text)
    backend = LayerBackend()
    configuration = config.Configuration(background_policy=config.BackgroundPolicy.BLACK, hatching_timeout=3, image_policy=config.ImagePolicy.IGNORE)
    Frontend(RenderContext(doc), backend, config=configuration).draw_layout(doc.modelspace(), finalize=True)
    root = backend.get_xml_root_element(layout.Page(420, 297, margins=layout.Margins.all(8)))
    styles = {}
    for element in root.iter("style"):
        for name, declarations in re.findall(r"\.([A-Za-z0-9]+)\s*\{([^}]*)\}", element.text or ""):
            styles[name] = dict(part.strip().split(":", 1) for part in declarations.split(";") if ":" in part)
    paths = []
    for element in root.iter("path"):
        style = styles.get(element.get("class"), {})
        entry = {"d": element.get("d", ""), "layer": element.get("data-layer", "0")}
        # Only inert path geometry and validated paint values cross into React.
        for name in ["fill", "stroke"]:
            value = style.get(name, "none").strip()
            entry[name] = value if re.fullmatch(r"#[0-9a-fA-F]{6}|none", value) else "none"
        for name, default in [("stroke-width", 0), ("fill-opacity", 1), ("stroke-opacity", 1)]:
            raw = str(style.get(name, default)).strip()
            value = float(default if raw == "none" else raw)
            if not math.isfinite(value) or value < 0:
                raise ValueError("Invalid preview style")
            entry[name.replace("-", "_")] = value
        paths.append(entry)
        if len(paths) > MAX_PREVIEW_PATHS:
            raise OverflowError("Preview path limit")
    origin, x_axis, y_axis = [backend.transformation_matrix.transform(point) for point in [(0, 0, 0), (1, 0, 0), (0, 1, 0)]]
    affine = [x_axis.x - origin.x, x_axis.y - origin.y, y_axis.x - origin.x, y_axis.y - origin.y, origin.x, origin.y]
    if not all(math.isfinite(value) for value in affine):
        raise ValueError("Invalid preview transform")
    return {"version": 1, "kind": "dxf", "view_box": [float(value) for value in root.get("viewBox").split()], "source_to_svg": affine, "background": "#000000", "paths": paths}


def inspect_dxf(path: Path, assets_dir: Path) -> dict:
    result = {"status": "failed", "scope": "cad_modelspace_preview", "clash_detection": "not_run", "diagnostics": [], "preview_available": False}
    try:
        doc = ezdxf.readfile(path)
        model = doc.modelspace()
        auditor = doc.audit()
        scale = units.conversion_factor(doc.units, units.M) if doc.units else None
        if scale is not None and (not math.isfinite(scale) or scale <= 0):
            scale = None
        result.update({
            "dxf_version": doc.dxfversion, "unit_name": units.unit_name(doc.units), "unit_scale_to_m": scale,
            "modelspace_count": len(model), "entity_types": dict(Counter(entity.dxftype() for entity in model)),
            "layouts": [{"name": space.name, "entity_count": len(space)} for space in doc.layouts],
            "layers": [{"name": layer.dxf.name, "visible": not layer.is_off() and not layer.is_frozen()} for layer in doc.layers],
            "block_count": len(doc.blocks), "audit_errors": len(auditor.errors), "audit_fixes": len(auditor.fixes),
            "external_references": [{"name": block.name, "path": block.block.dxf.get("xref_path", "")} for block in doc.blocks if block.block.is_xref or block.block.is_xref_overlay],
            "text_sample": [], "grid_lines": [],
        })
        for entity in model:
            if entity.dxftype() in {"TEXT", "MTEXT"} and len(result["text_sample"]) < 30:
                text = entity.plain_text() if entity.dxftype() == "MTEXT" else entity.dxf.text
                result["text_sample"].append(decode_text(text)[:250])
            if scale and entity.dxftype() == "LINE" and "GRID" in entity.dxf.layer.upper() and "IDEN" not in entity.dxf.layer.upper():
                if len(result["grid_lines"]) < 1000:
                    points = [[float(n) * scale for n in p] for p in [entity.dxf.start, entity.dxf.end]]
                    if all(math.isfinite(n) for p in points for n in p):
                        result["grid_lines"].append({"layer": entity.dxf.layer, "start_m": points[0], "end_m": points[1]})
                elif {"code": "cad_grid_limit"} not in result["diagnostics"]:
                    result["diagnostics"].append({"code": "cad_grid_limit"})
        if not scale:
            result["diagnostics"].append({"code": "cad_units_unknown"})
        if result["external_references"]:
            result["diagnostics"].append({"code": "cad_xref_unresolved"})
        if auditor.errors or auditor.fixes:
            result["diagnostics"].append({"code": "cad_audit_review"})
        unsupported = Counter(entity.dxftype() for block in doc.blocks for entity in block if entity.dxftype() in {"3DSOLID", "BODY", "REGION", "ACAD_PROXY_ENTITY", "IMAGE", "PDFUNDERLAY", "DGNUNDERLAY", "ACAD_TABLE", "RAY", "XLINE"})
        result["unsupported_types"] = dict(unsupported)
        result["has_3d_entities"] = any(
            entity.dxftype() in {"3DSOLID", "BODY", "MESH", "3DFACE"}
            or entity.dxftype() == "POLYLINE" and (entity.is_3d_polyline or entity.is_poly_face_mesh or entity.is_polygon_mesh)
            for block in doc.blocks for entity in block
        )
        if unsupported:
            result["diagnostics"].append({"code": "cad_entities_unsupported"})
    except Exception:
        result["diagnostics"].append({"code": "invalid_dxf"})
        return result
    try:
        preview = drawing_preview(doc)
        if not preview["paths"]:
            raise ValueError("No drawable geometry")
        content = json.dumps(preview, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(content) > MAX_PREVIEW_BYTES:
            raise OverflowError("Preview byte limit")
        with (assets_dir / "drawing.json").open("xb") as handle:
            handle.write(content)
        result["preview_available"] = True
    except OverflowError:
        result["diagnostics"].append({"code": "cad_preview_limit"})
    except Exception:
        result["diagnostics"].append({"code": "cad_preview_failed"})
    result["status"] = "partial" if result["diagnostics"] else "completed"
    if not len(model):
        result["status"] = "partial"
        result["diagnostics"].append({"code": "cad_empty_modelspace"})
    return result
