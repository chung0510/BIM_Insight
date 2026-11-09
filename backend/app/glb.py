"""Share byte-identical geometry in the static GLB emitted by IfcOpenShell."""

import hashlib
import json
import mmap
import os
from pathlib import Path
import struct
from uuid import uuid4

from app.limits import MAX_REPORT_BYTES


GLB_OPTIMIZATION_VERSION = 1
CHUNK_BYTES = 1024 * 1024


def same_bytes(data, first, second, size):
    for position in range(0, size, CHUNK_BYTES):
        end = min(position + CHUNK_BYTES, size)
        if data[first + position:first + end] != data[second + position:second + end]:
            return False
    return True


def compact_glb(path: Path) -> dict:
    before = path.stat().st_size
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    stats = {"version": GLB_OPTIMIZATION_VERSION, "before_bytes": before, "after_bytes": before}
    try:
        with path.open("rb") as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
            if before < 28:
                raise ValueError("Invalid GLB header")
            magic, version, length, json_length, json_type = struct.unpack_from("<5I", data)
            if (magic, version, length, json_type) != (0x46546C67, 2, before, 0x4E4F534A) or not 0 < json_length <= min(MAX_REPORT_BYTES, before - 28):
                raise ValueError("Invalid GLB header")
            document = json.loads(data[20:20 + json_length])
            binary_length, binary_type = struct.unpack_from("<2I", data, 20 + json_length)
            binary_start = 28 + json_length
            if binary_type != 0x004E4942 or binary_start + binary_length != before:
                raise ValueError("Invalid GLB binary chunk")
            # Only native static exports: unknown extensions may contain other buffer/accessor references.
            if set(document) - {"asset", "accessors", "bufferViews", "buffers", "materials", "meshes", "nodes", "scene", "scenes"}:
                raise ValueError("Unsupported GLB structure")
            buffers = document.get("buffers", [])
            if len(buffers) != 1 or set(buffers[0]) != {"byteLength"} or not 0 <= buffers[0]["byteLength"] <= binary_length:
                raise ValueError("Unsupported GLB buffers")
            views, view_indices, copies, shared_views = [], [], [], {}
            offset = 0
            for view in document["bufferViews"]:
                if set(view) - {"buffer", "byteOffset", "byteLength", "byteStride", "target"} or view.get("buffer") != 0:
                    raise ValueError("Unsupported GLB buffer view")
                start, size = view.get("byteOffset", 0), view["byteLength"]
                if not isinstance(start, int) or not isinstance(size, int) or start < 0 or size < 0 or start + size > buffers[0]["byteLength"]:
                    raise ValueError("Invalid GLB buffer range")
                start += binary_start
                descriptor = {key: value for key, value in view.items() if key != "byteOffset"}
                fingerprint = (json.dumps(descriptor, sort_keys=True), hashlib.sha256(memoryview(data)[start:start + size]).digest())
                index = shared_views.get(fingerprint)
                if index is not None:
                    prior_start, prior_size = copies[index]
                    if size != prior_size or not same_bytes(data, start, prior_start, size):
                        index = None
                if index is None:
                    index = len(views)
                    shared_views[fingerprint] = index
                    views.append({**descriptor, "byteOffset": offset})
                    copies.append((start, size))
                    offset += size + (-size % 4)
                view_indices.append(index)
            accessors, accessor_indices, shared_accessors = [], [], {}
            for accessor in document["accessors"]:
                if set(accessor) - {"bufferView", "byteOffset", "componentType", "count", "type", "min", "max", "normalized", "name"}:
                    raise ValueError("Unsupported GLB accessor")
                index = accessor.get("bufferView")
                if not isinstance(index, int) or not 0 <= index < len(view_indices):
                    raise ValueError("Invalid GLB accessor reference")
                updated = {**accessor, "bufferView": view_indices[index]}
                fingerprint = json.dumps(updated, sort_keys=True)
                if fingerprint not in shared_accessors:
                    shared_accessors[fingerprint] = len(accessors)
                    accessors.append(updated)
                accessor_indices.append(shared_accessors[fingerprint])

            def remap(index):
                if not isinstance(index, int) or not 0 <= index < len(accessor_indices):
                    raise ValueError("Invalid GLB primitive reference")
                return accessor_indices[index]

            for mesh in document["meshes"]:
                if set(mesh) - {"name", "primitives"}:
                    raise ValueError("Unsupported GLB mesh")
                for primitive in mesh["primitives"]:
                    if set(primitive) - {"indices", "attributes", "material", "mode"}:
                        raise ValueError("Unsupported GLB primitive")
                    if "indices" in primitive:
                        primitive["indices"] = remap(primitive["indices"])
                    primitive["attributes"] = {key: remap(value) for key, value in primitive["attributes"].items()}
            document.update(bufferViews=views, accessors=accessors, buffers=[{"byteLength": offset}])
            encoded = json.dumps(document, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
            encoded += b" " * (-len(encoded) % 4)
            size = 28 + len(encoded) + offset
            if size >= before:
                return stats
            with temporary.open("xb") as output:
                output.write(struct.pack("<5I", 0x46546C67, 2, size, len(encoded), 0x4E4F534A))
                output.write(encoded)
                output.write(struct.pack("<2I", offset, 0x004E4942))
                for start, length in copies:
                    for position in range(start, start + length, CHUNK_BYTES):
                        output.write(data[position:min(position + CHUNK_BYTES, start + length)])
                    output.write(b"\0" * (-length % 4))
        os.replace(temporary, path)
        stats["after_bytes"] = size
        return stats
    finally:
        temporary.unlink(missing_ok=True)
