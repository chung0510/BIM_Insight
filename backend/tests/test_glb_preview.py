import copy
import json
import struct

import pytest

from app.glb import CHUNK_BYTES, compact_glb, same_bytes
from test_ifc_probe import small_ifc


def write_glb(path, document, binary):
    encoded = json.dumps(document, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    binary += b"\0" * (-len(binary) % 4)
    path.write_bytes(struct.pack("<5I", 0x46546C67, 2, 28 + len(encoded) + len(binary), len(encoded), 0x4E4F534A)
                     + encoded + struct.pack("<2I", len(binary), 0x004E4942) + binary)


def read_glb(path):
    data = path.read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20:20 + length]), data[28 + length:]


def repeated_model(path):
    indices = struct.pack("<3I", 0, 1, 2)
    vertices = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    document = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 96}], "bufferViews": [],
                "accessors": [], "meshes": [], "nodes": [], "scene": 0, "scenes": [{"nodes": [0, 1]}],
                "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [1, 0, 0, 1]}},
                              {"pbrMetallicRoughness": {"baseColorFactor": [0, 0, 1, 1]}}]}
    for index in range(2):
        document["bufferViews"].extend([
            {"buffer": 0, "byteOffset": index * 48, "byteLength": 12, "target": 34963},
            {"buffer": 0, "byteOffset": index * 48 + 12, "byteLength": 36, "byteStride": 12, "target": 34962}])
        document["accessors"].extend([
            {"bufferView": index * 2, "componentType": 5125, "count": 3, "type": "SCALAR"},
            {"bufferView": index * 2 + 1, "componentType": 5126, "count": 3, "type": "VEC3"}])
        document["meshes"].append({"name": str(200 + index), "primitives": [
            {"indices": index * 2, "attributes": {"POSITION": index * 2 + 1}, "material": index, "mode": 4}]})
        document["nodes"].append({"name": f"source-guid-{index}", "mesh": index, "translation": [index * 10, 0, 0]})
    write_glb(path, document, (indices + vertices) * 2)
    return document


def expanded_primitives(path):
    document, binary = read_glb(path)
    output = []
    for mesh in document["meshes"]:
        for primitive in mesh["primitives"]:
            values = {}
            for name, index in {"indices": primitive["indices"], **primitive["attributes"]}.items():
                accessor = copy.deepcopy(document["accessors"][index])
                view = document["bufferViews"][accessor.pop("bufferView")]
                start = view.get("byteOffset", 0)
                values[name] = {"accessor": accessor, "bytes": binary[start:start + view["byteLength"]],
                                "stride": view.get("byteStride"), "target": view.get("target")}
            output.append({"values": values, "material": primitive["material"], "mode": primitive["mode"]})
    return output


def test_compaction_shares_exact_geometry_without_changing_guids_materials_or_placement(tmp_path):
    path = tmp_path / "model.glb"
    original = repeated_model(path)
    values = expanded_primitives(path)
    before = path.stat().st_size
    stats = compact_glb(path)
    packed, binary = read_glb(path)
    assert stats["before_bytes"] == before
    assert stats["after_bytes"] == path.stat().st_size < before
    assert stats["version"] == 1
    assert len(packed["bufferViews"]) == len(packed["accessors"]) == 2
    assert len(binary) == packed["buffers"][0]["byteLength"] == 48
    assert expanded_primitives(path) == values
    for key in ("nodes", "scenes", "materials"):
        assert packed[key] == original[key]
    assert [mesh["name"] for mesh in packed["meshes"]] == [mesh["name"] for mesh in original["meshes"]]
    saved = path.read_bytes()
    compact_glb(path)
    assert path.read_bytes() == saved


@pytest.mark.parametrize("mutation", ["out_of_bounds", "bad_accessor", "extension", "truncated"])
def test_invalid_or_unsupported_glb_never_replaces_the_original(tmp_path, mutation):
    path = tmp_path / "model.glb"
    repeated_model(path)
    document, binary = read_glb(path)
    if mutation == "out_of_bounds":
        document["bufferViews"][0]["byteLength"] = 1000
    elif mutation == "bad_accessor":
        document["meshes"][0]["primitives"][0]["indices"] = 999
    elif mutation == "extension":
        document["extensionsUsed"] = ["KHR_draco_mesh_compression"]
    write_glb(path, document, binary)
    if mutation == "truncated":
        path.write_bytes(path.read_bytes()[:-4])
    original = path.read_bytes()
    with pytest.raises(ValueError):
        compact_glb(path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_failed_promotion_keeps_original_and_cleans_temporary_file(tmp_path, monkeypatch):
    import app.glb

    path = tmp_path / "model.glb"
    repeated_model(path)
    original = path.read_bytes()
    monkeypatch.setattr(app.glb.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("test disk failure")))
    with pytest.raises(OSError):
        compact_glb(path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_optional_optimizer_failure_preserves_mapping_and_original_preview(tmp_path, monkeypatch, small_ifc):
    import app.ifc

    monkeypatch.setattr(app.ifc, "compact_glb", lambda *args: (_ for _ in ()).throw(OSError("test optimizer failure")))
    assets = tmp_path / "assets"
    assets.mkdir()
    report = app.ifc.inspect_ifc(small_ifc[0], assets)
    assert report["mapping_available"] is True
    assert report["viewer_available"] is True
    assert json.loads((assets / "model.json").read_text(encoding="utf-8"))["elements"][0]["guid"] == small_ifc[1]


def test_large_duplicate_comparison_uses_bounded_reads_and_checks_the_tail():
    block = b"geometry" * (CHUNK_BYTES // 8) + b"tail"
    class BoundedBuffer:
        def __init__(self, data):
            self.data = data
        def __getitem__(self, key):
            assert key.stop - key.start <= CHUNK_BYTES
            return self.data[key]
    assert same_bytes(BoundedBuffer(block * 2), 0, len(block), len(block))
    assert not same_bytes(BoundedBuffer(block + block[:-1] + b"X"), 0, len(block), len(block))
