"""Run one auditable preparation stage inside a disposable Blender process."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dsr_common import LOWER, PARTS, SKILL, SUITS, load_config, sha256, write_json
import _prepare_core as prep


def meshes():
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def frame_review():
    points = [obj.matrix_world @ v.co for obj in meshes() for v in obj.data.vertices]
    if not points:
        return
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center, size = (low + high) * .5, max(high - low)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            space.clip_start = max(size * .0001, .000001)
            space.clip_end = max(size * 100, 100)
            space.region_3d.view_location = center
            space.region_3d.view_distance = size * 2
            space.region_3d.view_rotation = Quaternion((1, 0, 0), 1.57079632679)
            space.region_3d.view_perspective = "ORTHO"
            space.shading.type = "MATERIAL"


def inspect(config, output):
    result = {"source": config["input"], "source_sha256": sha256(config["input"]),
              "blender_version": bpy.app.version_string, "objects": []}
    for obj in bpy.context.scene.objects:
        item = {"name": obj.name, "type": obj.type, "hidden": obj.hide_get(),
                "world": list(map(list, obj.matrix_world))}
        if obj.type == "ARMATURE":
            item["bones"] = list(obj.data.bones.keys())
            item["constraints"] = sum(len(b.constraints) for b in obj.pose.bones)
        if obj.type == "MESH":
            obj.data.calc_loop_triangles()
            item.update(vertices=len(obj.data.vertices), triangles=len(obj.data.loop_triangles),
                        shape_keys=bool(obj.data.shape_keys), uv_layers=list(obj.data.uv_layers.keys()),
                        rigs=[m.object.name for m in obj.modifiers if m.type == "ARMATURE" and m.object],
                        materials=[m.name if m else None for m in obj.data.materials])
        result["objects"].append(item)
    write_json(output, result)


def bootstrap(config):
    rig = bpy.data.objects.get(config["rig_object"])
    if not rig or rig.type != "ARMATURE":
        raise ValueError("Configured deform rig was not found.")
    chosen = [bpy.data.objects.get(name) for name in config["mesh_objects"]]
    if any(obj is None or obj.type != "MESH" for obj in chosen):
        raise ValueError("Configured mesh was not found.")
    for obj in chosen:
        if obj.data.shape_keys:
            raise ValueError("Choose a visible static shape-key bake before atlas/splitting.")
        if any(m.type != "ARMATURE" for m in obj.modifiers):
            raise ValueError("Resolve non-armature modifiers on a copy before preparation.")
        if len([m for m in obj.modifiers if m.type == "ARMATURE" and m.object == rig]) != 1:
            raise ValueError("Each selected mesh must have exactly one modifier targeting the deform rig.")
    rig_world = rig.matrix_world.copy()
    mesh_world = {obj.name: obj.matrix_world.copy() for obj in chosen}
    rig.parent = None
    rig.matrix_world = rig_world
    retained = {rig, *chosen}
    # Remove unrelated objects only from this disposable in-memory working copy.
    for obj in list(bpy.context.scene.objects):
        if obj not in retained:
            bpy.data.objects.remove(obj, do_unlink=True)
    for obj in chosen:
        world = mesh_world[obj.name]
        obj.parent = rig
        obj.matrix_world = world
        obj.hide_set(False)
        obj.hide_viewport = False
    rig.hide_set(False)
    rig.hide_viewport = False
    rig.name = "DSR_Rig"
    if "pose" not in config["stages"]:
        if any(b.constraints or max(abs(b.matrix_basis[i][j] - (1 if i == j else 0))
               for i in range(4) for j in range(4)) > 1e-6 for b in rig.pose.bones):
            raise ValueError("Bake the intended visible pose to rest, or enable the pose conversion stage.")
    bpy.context.view_layer.update()


def native(config):
    obj = bpy.data.objects.get("Original_Game_Rig_Comparison")
    if obj:
        return obj
    with bpy.data.libraries.load(config["native_blend"], link=False) as (available, loaded):
        name = config.get("native_rig_object", "Reference")
        if name not in available.objects:
            raise ValueError("Native reference armature was not found in its BLEND.")
        loaded.objects = [name]
    obj = loaded.objects[0]
    if obj.type != "ARMATURE" or obj.parent:
        raise ValueError("Native reference must be a standalone armature with its world conversion intact.")
    obj.name = "Original_Game_Rig_Comparison"
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.update()
    obj.hide_set(True)
    obj.hide_render = True
    return obj


def pose(config, work):
    import _pose_core
    rig, converted, report = _pose_core.convert_armature(
        bpy.data.objects["DSR_Rig"], source_preset=config["source_preset"],
        reference_path=SKILL / "references/data/dead_space_pose.json")
    retained = {rig, *converted}
    for obj in list(bpy.context.scene.objects):
        if obj not in retained:
            bpy.data.objects.remove(obj, do_unlink=True)
    rig.name = "DSR_Rig"
    write_json(work / "reports/pose.json", report)


def tpose(config, work):
    import _tpose_core
    rig, converted, report = _tpose_core.convert(bpy.data.objects["DSR_Rig"], config["source_preset"],
                                               config.get("source_pose", "AUTO"))
    retained = {rig, *converted}
    for obj in list(bpy.context.scene.objects):
        if obj not in retained:
            bpy.data.objects.remove(obj, do_unlink=True)
    rig.name = "DSR_Rig"
    write_json(work / "reports/tpose.json", report)


def scale(config, work):
    rig = bpy.data.objects["DSR_Rig"]
    target = native(config)
    if any(obj.parent != rig for obj in meshes()):
        raise ValueError("Shoulder scaling requires every part to be parented to the mod rig.")
    axis = int(config.get("up_axis", 2))
    pivot = Vector(config.get("scale_pivot", [0, 0, 0]))
    names = ("LeftShoulder", "RightShoulder")
    height = lambda obj: sum((obj.matrix_world @ obj.data.bones[name].head_local - pivot)[axis]
                             for name in names) * .5
    source_height, target_height = height(rig), height(target)
    if min(source_height, target_height) <= 1e-9:
        raise ValueError("Shoulder heights must be positive above the configured common pivot.")
    before = {obj.name: prep.world_vertices(obj) for obj in meshes()}
    factor = target_height / source_height
    transform = Matrix.Translation(pivot) @ Matrix.Scale(factor, 4) @ Matrix.Translation(-pivot)
    rig.matrix_world = transform @ rig.matrix_world
    bpy.context.view_layer.update()
    error = max((point - transform @ old).length for obj in meshes()
                for point, old in zip(prep.world_vertices(obj), before[obj.name]))
    if error > 1e-7 or abs(height(rig) - target_height) > 1e-7:
        raise ValueError("Shoulder-height scaling failed its geometry check.")
    write_json(work / "reports/scale.json", {"uniform_scale": factor, "pivot": list(pivot),
               "source_height": source_height, "target_height": target_height,
               "maximum_world_scale_error": error, "skeleton_override": False})


def cleanup(config, work):
    pairs = {int(a): int(b) for a, b in config.get("inner_material_pairs", [])}
    if len(set(pairs.values())) != len(pairs) or set(pairs) & set(pairs.values()):
        raise ValueError("Inner/outer material pair identities must be unambiguous.")
    if not pairs:
        write_json(work / "reports/cleanup.json", {"removed_faces": 0, "reason": "No confirmed inner material pairs"})
        return
    locations = defaultdict(list)
    quantum = float(config.get("coincident_position_quantum", 1e-8))
    if quantum <= 0:
        raise ValueError("Position quantum must be positive.")
    for obj in meshes():
        if "source_material_index" not in obj.data.attributes:
            raise ValueError("Cleanup needs the original source material face attribute.")
        for face in obj.data.polygons:
            material = obj.data.attributes["source_material_index"].data[face.index].value
            if material not in set(pairs) | set(pairs.values()):
                continue
            if len(face.vertices) != 3:
                raise ValueError("Confirmed duplicate-layer cleanup currently requires triangles.")
            points = [obj.matrix_world @ obj.data.vertices[i].co for i in face.vertices]
            keys = [tuple(round(v / quantum) for v in p) for p in points]
            weights = tuple(sorted((key, tuple(sorted((obj.vertex_groups[g.group].name, round(g.weight, 7))
                            for g in obj.data.vertices[i].groups))) for key, i in zip(keys, face.vertices)))
            normal = (points[1] - points[0]).cross(points[2] - points[0]).normalized()
            locations[tuple(sorted(keys))].append((obj, face.index, material, weights, normal))
    removed, matched = defaultdict(set), []
    for records in locations.values():
        for outer in records:
            if outer[2] not in pairs:
                continue
            candidates = [inner for inner in records if inner[2] == pairs[outer[2]]
                          and inner[3] == outer[3] and inner[4].dot(outer[4]) < -.99]
            if len(candidates) > 1:
                raise ValueError("Ambiguous duplicate layer requires inspection.")
            for inner in candidates:
                if inner[1] in removed[inner[0].name]:
                    raise ValueError("One inner triangle has multiple exterior matches.")
                removed[inner[0].name].add(inner[1])
                matched.append({"outer_face_id": outer[0].data.attributes["source_face_id"].data[outer[1]].value,
                                "inner_face_id": inner[0].data.attributes["source_face_id"].data[inner[1]].value,
                                "outer_material": outer[2], "inner_material": inner[2]})
    for obj in list(meshes()):
        if removed[obj.name]:
            name = obj.name
            filtered = prep.extract_faces(obj, [f.index for f in obj.data.polygons if f.index not in removed[name]], name + "_Filtered")
            bpy.data.objects.remove(obj, do_unlink=True)
            filtered.name = name
    write_json(work / "reports/cleanup.json", {"removed_faces": len(matched), "matches": matched,
               "position_quantum": quantum, "weight_decimal_places": 7,
               "selection": "Explicit pairs, opposite winding, coincident positions, matching skin weights"})


def export(config, work):
    rig = bpy.data.objects["DSR_Rig"]
    parts = {obj.get("dsr_part"): obj for obj in meshes()}
    if set(parts) != set(PARTS) or len(meshes()) != len(PARTS):
        raise ValueError("Export requires eleven unique tagged Lv1 parts.")
    validate_scene(work)
    directory = work / "package/fbx"
    records = []
    old_rig_name = rig.name
    conflicts = bpy.data.objects.get("Reference")
    if conflicts and conflicts != rig:
        raise ValueError("An unrelated object occupies the required Reference export name.")
    rig.name = "Reference"
    try:
        for target in config["targets"]:
            section = SUITS[target]["sections"]
            target_directory = directory / target
            target_directory.mkdir(parents=True, exist_ok=True)
            for part in PARTS:
                obj = parts[part]
                name, parent, world = obj.name, obj.parent, obj.matrix_world.copy()
                node = section[part] + ":lod.000"
                path = target_directory / (config["name"] + "_" + part + ".fbx")
                try:
                    obj.parent = None
                    obj.matrix_world = world
                    obj.name = node
                    if obj.name != node:
                        raise ValueError("Exact FBX node name could not be assigned.")
                    bpy.ops.object.select_all(action="DESELECT")
                    rig.select_set(True)
                    obj.select_set(True)
                    bpy.context.view_layer.objects.active = rig
                    bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True,
                        object_types={"ARMATURE", "MESH"}, add_leaf_bones=False, bake_anim=False,
                        use_tspace=True, use_triangles=True, use_mesh_modifiers=False,
                        use_armature_deform_only=True, path_mode="STRIP")
                    records.append({"target": target, "part": part, "file": str(path), "sha256": sha256(path),
                                    "asset": SUITS[target]["mesh_root"] + part + "_Mesh", "node": node,
                                    "triangles": len(obj.data.polygons)})
                finally:
                    obj.name, obj.parent = name, parent
                    obj.matrix_world = world
    finally:
        rig.name = old_rig_name
    write_json(work / "package/exports.json", {"source": bpy.data.filepath,
               "source_sha256": sha256(bpy.data.filepath), "targets": list(config["targets"]),
               "parts": records, "skeleton_override": False, "runtime_tested": False})


def validate_scene(work):
    rig = bpy.data.objects["DSR_Rig"]
    face_ids = []
    for obj in meshes():
        if obj.data.shape_keys or list(obj.data.uv_layers.keys()) != ["UVChannel0", "UVChannel1"]:
            raise ValueError("Final meshes need exactly UVChannel0 and UVChannel1 and a static shape.")
        for point in obj.data.uv_layers["UVChannel1"].data:
            if abs(point.uv[0]) > 1e-6 or abs(point.uv[1]) > 1e-6:
                raise ValueError("UVChannel1 must be a zeroed copy of the first channel.")
        if any(len(face.vertices) != 3 for face in obj.data.polygons):
            raise ValueError("Triangulate on a working copy before these stages.")
        for vertex in obj.data.vertices:
            weights = [(obj.vertex_groups[g.group].name, g.weight) for g in vertex.groups if g.weight > 1e-8]
            if not weights or any(name not in rig.data.bones for name, _ in weights):
                raise ValueError("Missing or unmapped skin weights.")
            if abs(sum(weight for _, weight in weights) - 1) > 1e-4:
                raise ValueError("Skin weights are not normalized.")
        face_ids.extend(item.value for item in obj.data.attributes["source_face_id"].data)
    if len(face_ids) != len(set(face_ids)):
        raise ValueError("Partitioning duplicated source faces.")
    report = work / "reports/03_parts.json"
    if report.exists():
        expected = {i for part in json.loads(report.read_text(encoding="utf-8"))["parts"] for i in part["source_face_ids"]}
        clean = work / "reports/cleanup.json"
        removed = {m["inner_face_id"] for m in json.loads(clean.read_text(encoding="utf-8")).get("matches", [])} if clean.exists() else set()
        if set(face_ids) != expected - removed:
            raise ValueError("Surviving faces differ from the recorded partition and cleanup.")
    write_json(work / "reports/scene_validation.json", {"parts": len(meshes()),
               "triangles": len(face_ids), "rig_bones": len(rig.data.bones), "unique_source_faces": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    parser.add_argument("stage", choices=("inspect", "import", "static", "tpose", "pose", "atlas", "rig", "split", "scale", "hands", "cleanup", "export"))
    parser.add_argument("--bootstrap", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    config = load_config(args.config)
    work = Path(config["output"])
    work.mkdir(parents=True, exist_ok=True)
    if args.stage == "inspect":
        if Path(config["input"]).suffix.lower() != ".blend":
            import _raw_model
            _raw_model.import_model(config, work)
        inspect(config, work / "reports/input_inspection.json")
        return
    if args.bootstrap and args.stage not in ("import", "static"):
        bootstrap(config)
    prep.WORK = work
    prep.MMD_PRESET = Path(config["source_preset"])
    prep.TARGET_PRESET = SKILL / "references/data/dead_space_bones.json"
    prep.SKELETON_XML = Path(config["skeleton_xml"])
    prep.PARTS = {p: "LowerBody" if p in LOWER else "TopBody" for p in PARTS}
    prep.TRANSPARENT_POLICY = config["transparent_policy"]
    prep.SOURCE_MESH_PARTS = config.get("source_mesh_parts", {})
    prep.ATLAS_SIZE = config.get("atlas_size", 8192)
    if args.stage in ("import", "static"):
        import _raw_model
        {"import": _raw_model.import_model, "static": _raw_model.freeze}[args.stage](config, work)
    elif args.stage in ("atlas", "rig", "split"):
        {"atlas": prep.make_atlas, "rig": prep.clean_rig, "split": prep.split_parts}[args.stage]()
    elif args.stage == "hands":
        import _hands_core as hands
        native(config)
        hands.WORK, hands.SOURCE = work, Path(bpy.data.filepath)
        hands.NATIVE = Path(config["native_blend"])
        hands.OUTPUT = work / "stages/hands.blend"
        hands.MINIMUM_ELBOW_BEND = config["minimum_elbow_bend_degrees"]
        hands.MAXIMUM_STRETCH = config["maximum_arm_stretch"]
        hands.fit()
    else:
        {"tpose": tpose, "pose": pose, "scale": scale, "cleanup": cleanup, "export": export}[args.stage](config, work)
    if args.stage != "export":
        destination = work / "stages" / (args.stage + ".blend")
        destination.parent.mkdir(parents=True, exist_ok=True)
        frame_review()
        bpy.ops.wm.save_as_mainfile(filepath=str(destination))


if __name__ == "__main__":
    main()
