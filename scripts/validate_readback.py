"""Validate the actual FBMOD readback, rather than the submitted FBX alone."""

from collections import Counter
import csv
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

import bpy
from io_scene_fbx import parse_fbx
from mathutils.kdtree import KDTree
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dsr_common import PARTS, SUITS, load_config, sha256, write_json

GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def positions(obj):
    return [obj.matrix_world @ v.co for v in obj.data.vertices]


def tree(points):
    result = KDTree(len(points))
    for i, point in enumerate(points):
        result.insert(point, i)
    result.balance()
    return result


def vertex_weights(obj, index):
    return {obj.vertex_groups[g.group].name: g.weight for g in obj.data.vertices[index].groups if g.weight > 1e-8}


def frames(path, required):
    root, _ = parse_fbx.parse(str(path))
    result = {}
    def walk(element):
        if element.id in (b"Normals", b"Tangents", b"Binormals"):
            result.setdefault(element.id.decode(), []).extend(np.asarray(element.props[0], dtype=float).reshape(-1, 3))
        for child in element.elems:
            walk(child)
    walk(root)
    missing = set(required) - set(result)
    if missing:
        raise ValueError("Readback lacks required frame arrays: " + ", ".join(sorted(missing)))
    report = {}
    for name, values in result.items():
        vectors = np.asarray(values)
        if not np.all(np.isfinite(vectors)):
            raise ValueError("Non-finite tangent frame: " + name)
        lengths = np.linalg.norm(vectors, axis=1)
        nonzero = lengths > 1e-8
        if name == "Normals" and not np.all(nonzero):
            raise ValueError("Zero readback normals.")
        if not np.all((lengths[nonzero] > .999) & (lengths[nonzero] < 1.001)):
            raise ValueError("Stored vectors are not normalized: " + name)
        report[name] = {"vectors": len(lengths), "zero_vectors": int(np.count_nonzero(~nonzero))}
    return report


def geometry(config, exported):
    expected = {}
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        points = positions(obj)
        uv = [[tuple(p.uv) for p in layer.data] for layer in obj.data.uv_layers]
        loops = [[] for _ in points]
        for loop in obj.data.loops:
            loops[loop.vertex_index].append(tuple(layer[loop.index] for layer in uv))
        expected[obj["dsr_part"]] = {"positions": points, "weights": [vertex_weights(obj, i) for i in range(len(points))],
                                     "uvs": loops, "triangles": len(obj.data.polygons)}
    if set(expected) != set(PARTS):
        raise ValueError("Source BLEND does not contain the expected eleven parts.")
    report = []
    for target in config["targets"]:
        suit = SUITS[target]
        stem = suit["mesh_root"].rsplit("/", 1)[-1]
        for part in PARTS:
            source = expected[part]
            path = exported / "models" / ((stem + part + "_Mesh.fbx").lower())
            frame_report = frames(path, suit["frames"])
            bpy.ops.wm.read_factory_settings(use_empty=True)
            bpy.ops.import_scene.fbx(filepath=str(path), use_anim=False)
            meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and len(o.data.polygons)]
            if len(meshes) != 1:
                raise ValueError("Expected one active mesh per resource.")
            obj = meshes[0]
            node = suit["sections"][part] + ":lod.000"
            if not obj.name.startswith(node) or len(obj.data.polygons) != source["triangles"]:
                raise ValueError("Node or triangle-count mismatch: " + target + "/" + part)
            if len(obj.data.uv_layers) != 2:
                raise ValueError("Expected two readback UV layers.")
            for point in obj.data.uv_layers[1].data:
                if abs(point.uv[0]) > 5e-4 or abs(point.uv[1]) > 5e-4:
                    raise ValueError("Second readback UV channel is not zeroed.")
            actual = positions(obj)
            old_tree, new_tree = tree(source["positions"]), tree(actual)
            error = max(max(old_tree.find(p)[2] for p in actual), max(new_tree.find(p)[2] for p in source["positions"]))
            position_tolerance = .000025 if target == "isaac_legacy" else .000015
            if error >= position_tolerance:
                raise ValueError("Readback positions differ: " + target + "/" + part)
            weights = [vertex_weights(obj, i) for i in range(len(actual))]
            maximum_weight_error, maximum_uv_error = 0., 0.
            for loop in obj.data.loops:
                index = loop.vertex_index
                uv = [tuple(layer.data[loop.index].uv) for layer in obj.data.uv_layers]
                candidates = old_tree.find_range(actual[index], position_tolerance)
                matched_error, nearest_uv_error = None, float("inf")
                for _, old, _ in candidates:
                    uv_error = min(max(abs(a - b) for x, y in zip(uv, option) for a, b in zip(x, y))
                                   for option in source["uvs"][old])
                    nearest_uv_error = min(nearest_uv_error, uv_error)
                    if uv_error >= .0005:
                        continue
                    names = set(weights[index]) | set(source["weights"][old])
                    difference = max(abs(weights[index].get(n, 0) - source["weights"][old].get(n, 0)) for n in names)
                    if difference < .02:
                        matched_error = difference if matched_error is None else min(matched_error, difference)
                if matched_error is None or not weights[index]:
                    raise ValueError("Readback corner UV/skin influence mismatch: " + target + "/" + part
                                     + " vertex=" + str(index) + " nearest_uv_error=" + str(nearest_uv_error))
                maximum_weight_error = max(maximum_weight_error, matched_error)
                maximum_uv_error = max(maximum_uv_error, nearest_uv_error)
            report.append({"target": target, "part": part, "triangles": source["triangles"], "position_error": error,
                           "position_tolerance": position_tolerance,
                           "maximum_weight_error": maximum_weight_error, "maximum_uv_error": maximum_uv_error,
                           "uv_layers": 2, "frames": frame_report})
    return report


def textures(config, exported, inspection):
    atlas = Path(config["output"]) / "textures/character_atlas.png"
    with Image.open(atlas) as image:
        expected = np.asarray(image.convert("RGBA").resize((512, 512), Image.Resampling.NEAREST)).astype(np.int16)
    with (inspection / "texture_headers.tsv").open(encoding="utf-8-sig", newline="") as stream:
        headers = [r for r in csv.DictReader(stream, delimiter="\t") if r["state"] == "modified"]
    families = [(target, family) for target in config["targets"] for family in SUITS[target]["families"]]
    if len(headers) != 3 * len(families):
        raise ValueError("Expected exactly three modified texture headers per family.")
    report = []
    for target, family in families:
        suit = SUITS[target]
        for index in range(3):
            asset = (suit["texture_root"] + family + "_PACKED_" + str(index)).lower()
            header = next(r for r in headers if r["asset"].lower() == asset)
            size = config["atlas_size"] if index == 0 else 512 if index == 1 else 2048
            fmt = "BC7_SRGB" if index == 0 else "BC7_UNORM"
            if (int(header["width"]), int(header["height"]), header["format"]) != (size, size, fmt):
                raise ValueError("Unexpected texture format or size: " + asset)
            path = exported / "textures" / (asset.rsplit("/", 1)[-1] + ".png")
            with Image.open(path) as image:
                if image.size != (size, size):
                    raise ValueError("Decoded texture size mismatch.")
                image = image.convert("RGBA")
                if index:
                    allowed = ((128, 128, 254, 0), (128, 128, 255, 0)) if index == 1 else ((255, 0, 255, 255),)
                    colors = image.getcolors(maxcolors=2)
                    if not colors or len(colors) != 1 or colors[0][1] not in allowed:
                        raise ValueError("Decoded packed constant mismatch.")
                else:
                    actual = np.asarray(image.resize((512, 512), Image.Resampling.NEAREST)).astype(np.int16)
                    difference = np.abs(actual - expected)
                    visible = expected[:, :, 3] > 0
                    if not visible.any() or np.percentile(difference[:, :, :3][visible], 95) >= 16 or np.percentile(difference[:, :, 3], 95) >= 8:
                        raise ValueError("Decoded atlas differs beyond BC7 tolerance.")
            report.append({"target": target, "asset": asset, "format": fmt, "size": size, "sha256": sha256(path)})
    for index in range(3):
        if len({r["sha256"] for r in report if r["asset"].endswith("packed_" + str(index))}) != 1:
            raise ValueError("Replacement textures differ unexpectedly across families.")
    return report


def composition(config, package, exported):
    report = []
    for target in config["targets"]:
        suit = SUITS[target]
        before = ET.parse(package / "character" / ("composition_baseline_" + target + ".xml")).getroot()
        slug = suit["composition"].replace("/", "_").lower()
        paths = list((exported / "raw").glob("*_ebx_" + slug + ".xml"))
        if len(paths) != 1:
            raise ValueError("Expected one exported composition EBX: " + target)
        after = ET.parse(paths[0]).getroot()
        old, new = before.find("VisualsItemData/Items"), after.find("VisualsItemData/Items")
        if old is None or new is None or len(old) - len(new) != len(suit["removals"]):
            raise ValueError("Composition item count mismatch: " + target)
        old_ids = [GUID.findall(member.text or "")[-1] for member in old]
        new_ids = [GUID.findall(member.text or "")[-1] for member in new]
        removed_ids = [item for item in old_ids if item not in set(new_ids)]
        if len(removed_ids) != len(suit["removals"]) or [item for item in old_ids if item in set(new_ids)] != new_ids:
            raise ValueError("Composition removals or order mismatch: " + target)
        before.find("VisualsItemData").remove(old)
        after.find("VisualsItemData").remove(new)
        for root in (before, after):
            for node in root.iter():
                node.text, node.tail = (node.text or "").strip(), ""
        if ET.tostring(before) != ET.tostring(after):
            raise ValueError("Unrelated composition fields changed: " + target)
        report.append({"target": target, "before": len(old), "after": len(new),
                       "removed": len(removed_ids), "other_fields_unchanged": True})
    return report


def main():
    config = load_config(sys.argv[sys.argv.index("--") + 1])
    package = Path(config["output"]) / "package"
    exported, inspection = package / "verification/exported", package / "verification/inspection"
    exports = json.loads((package / "exports.json").read_text(encoding="utf-8"))
    if sha256(exports["source"]) != exports["source_sha256"]:
        raise ValueError("Source changed since export.")
    table = package / "character" / (config["name"] + ".resources.tsv")
    with table.open(encoding="utf-8-sig", newline="") as stream:
        resources = list(csv.DictReader(stream, delimiter="\t"))
    targets = config["targets"]
    families = sum(len(SUITS[target]["families"]) for target in targets)
    expected_resources = 11 * len(targets) + 3 * families
    if Counter(r["kind"] for r in resources) != {"Ebx": len(targets), "Res": expected_resources, "Chunk": expected_resources}:
        raise ValueError("Unexpected modified-resource inventory.")
    res_names = {r["asset"].lower() for r in resources if r["kind"] == "Res"}
    allowed = {(SUITS[target]["mesh_root"] + part + "_Mesh").lower() for target in targets for part in PARTS}
    allowed |= {(SUITS[target]["texture_root"] + family + "_PACKED_" + str(i)).lower()
                for target in targets for family in SUITS[target]["families"] for i in range(3)}
    if res_names != allowed or {r["asset"].lower() for r in resources if r["kind"] == "Ebx"} != {SUITS[target]["composition"].lower() for target in targets}:
        raise ValueError("Unexpected resource identities or skeleton override.")
    result = {"geometry": geometry(config, exported), "textures": textures(config, exported, inspection),
              "composition": composition(config, package, exported), "skeleton_override": False,
              "runtime_tested": False, "installed": False, "passed": True}
    write_json(package / "verification/final_validation.json", result)
    print("READBACK_VALIDATED")


if __name__ == "__main__":
    main()
