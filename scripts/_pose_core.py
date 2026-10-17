"""Reusable pose conversion engine; invoked by blender_pipeline.py."""

import json
import math
from pathlib import Path
import re
import sys

import bpy
from mathutils import Matrix, Vector


PRESET_ROOT = Path(__file__).resolve().parent.parent / "references/data"
REFERENCE_PATH = PRESET_ROOT / "dead_space_pose.json"
REQUIRED = ("pelvis", "head", "upperarm_L", "forearm_L", "hand_L", "upperarm_R", "forearm_R", "hand_R")


def normalized_name(name):
    return re.sub(r"[_.\s]", "", name).casefold()


def preset_directories():
    roots = [PRESET_ROOT / "import"]
    for module_name in bpy.context.preferences.addons.keys():
        if "modding" in module_name.casefold() and "toolkit" in module_name.casefold():
            module = sys.modules.get(module_name)
            if module and getattr(module, "__file__", None):
                roots.append(Path(module.__file__).parent / "assets/presets/import")
    for folder in bpy.utils.script_paths(subdir="addons"):
        roots.append(Path(folder) / "Modding-Toolkit/assets/presets/import")
    return list(dict.fromkeys(path for path in roots if path.is_dir()))


def match_mapping(armature, preset):
    names = set(armature.data.bones.keys())
    lookup = {}
    for name in sorted(names):
        lookup.setdefault(normalized_name(name), name)
    result = {}
    for key, entry in preset.get("mappings", {}).items():
        for candidate in entry.get("main", []):
            actual = candidate if candidate in names else lookup.get(normalized_name(candidate))
            if actual:
                result[key] = actual
                break
    if len(result.values()) != len(set(result.values())):
        raise ValueError("The selected preset assigns one bone to multiple humanoid joints.")
    return result


def resolve_mapping(armature, source_preset="AUTO", reference=None):
    directories = preset_directories()
    paths = list(dict.fromkeys(path for folder in directories for path in sorted(folder.glob("*.json"))))
    native = PRESET_ROOT / "dead_space_bones.json"
    if native.exists():
        paths.append(native)
    if source_preset != "AUTO":
        explicit = Path(source_preset).expanduser()
        if not explicit.is_file():
            explicit = next((path for path in paths if path.name.casefold() == source_preset.casefold()), None)
        if not explicit or not explicit.is_file():
            raise ValueError("Source preset not found: " + source_preset)
        mapping = match_mapping(armature, json.loads(explicit.read_text(encoding="utf-8")))
        missing = [key for key in REQUIRED if key not in mapping]
        if missing:
            raise ValueError("The preset is missing required joints: " + ", ".join(missing))
        return mapping, explicit.name

    candidates = []
    for path in paths:
        try:
            preset = json.loads(path.read_text(encoding="utf-8"))
            mapping = match_mapping(armature, preset)
        except (ValueError, OSError):
            continue
        if all(key in mapping for key in REQUIRED):
            candidates.append((len(mapping), preset.get("preset_info", {}).get("priority", 0), path.name, mapping))
    standard = {"mappings": {key: {"main": [key]} for key in reference["joint_positions"]}}
    mapping = match_mapping(armature, standard)
    if all(key in mapping for key in REQUIRED):
        candidates.append((len(mapping), 0, "STANDARD", mapping))
    if not candidates:
        raise ValueError("Cannot identify the rig. Choose its Modding-Toolkit source preset JSON explicitly.")
    candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
    best = candidates[0]
    return best[3], best[2]


def world_joint(armature, mapping, key):
    return armature.matrix_world @ armature.pose.bones[mapping[key]].head


def character_frame(armature, mapping):
    origin = world_joint(armature, mapping, "pelvis")
    up_key = "neck" if "neck" in mapping else "head"
    up = world_joint(armature, mapping, up_key) - origin
    left = world_joint(armature, mapping, "upperarm_L") - world_joint(armature, mapping, "upperarm_R")
    if up.length < 1e-8 or left.length < 1e-8:
        raise ValueError("The rig has coincident torso or shoulder joints.")
    up.normalize()
    left -= up * left.dot(up)
    if left.length < 1e-8:
        raise ValueError("Cannot determine the rig's left/right axis.")
    left.normalize()
    forward = left.cross(up).normalized()
    up = forward.cross(left).normalized()
    return Matrix((left, up, forward)).transposed()


def leg_character_frame(armature, mapping):
    # Use an object axis for vertical so anatomical torso lean cannot pitch legs.
    torso_frame = character_frame(armature, mapping)
    torso_up = torso_frame.col[1]
    axes = [axis.normalized() for axis in armature.matrix_world.to_3x3().col]
    up = max(axes, key=lambda axis: abs(axis.dot(torso_up))).copy()
    if up.dot(torso_up) < 0:
        up.negate()
    left = world_joint(armature, mapping, "upperarm_L") - world_joint(armature, mapping, "upperarm_R")
    left -= up * left.dot(up)
    if left.length < 1e-8:
        raise ValueError("Cannot determine the leg spread plane.")
    left.normalize()
    return Matrix((left, up, left.cross(up).normalized())).transposed()


def leg_spread_direction(initial, reference, frame):
    local = frame.transposed() @ initial
    sagittal = Vector((0.0, local.y, local.z))
    if sagittal.length < 1e-8:
        raise ValueError("Cannot preserve leg pitch for a horizontal sideways leg.")
    sagittal.normalize()
    spread = math.atan2(reference.x, math.hypot(reference.y, reference.z))
    return frame @ (Vector((math.sin(spread), 0.0, 0.0)) + sagittal * math.cos(spread))


def copy_character(source):
    bpy.context.view_layer.update()
    evaluated_matrices = {bone.name: bone.matrix.copy() for bone in source.pose.bones}
    collection = bpy.data.collections.new(source.name + "_DeadSpacePose")
    bpy.context.scene.collection.children.link(collection)
    target = source.copy()
    target.data = source.data.copy()
    target.name = source.name + "_DeadSpacePose"
    target.data.name = source.data.name + "_DeadSpacePose"
    target.animation_data_clear()
    collection.objects.link(target)
    for pose_bone in target.pose.bones:
        for constraint in list(pose_bone.constraints):
            pose_bone.constraints.remove(constraint)
        bone = target.data.bones[pose_bone.name]
        desired = evaluated_matrices[bone.name]
        if bone.parent:
            basis = bone.matrix_local.inverted() @ bone.parent.matrix_local @ evaluated_matrices[bone.parent.name].inverted() @ desired
        else:
            basis = bone.matrix_local.inverted() @ desired
        pose_bone.matrix_basis = basis
    meshes = []
    originals = []
    for original in list(bpy.context.scene.objects):
        if original.type != "MESH" or not any(mod.type == "ARMATURE" and mod.object == source for mod in original.modifiers):
            continue
        obj = original.copy()
        obj.data = original.data.copy()
        obj.name = original.name + "_DeadSpacePose"
        obj.animation_data_clear()
        collection.objects.link(obj)
        world = original.matrix_world.copy()
        if obj.parent == source:
            obj.parent = target
        obj.matrix_world = world
        for modifier in obj.modifiers:
            if modifier.type == "ARMATURE" and modifier.object == source:
                modifier.object = target
        obj.hide_viewport = False
        obj.hide_set(False)
        meshes.append(obj)
        originals.append(original)
    target.hide_viewport = False
    target.hide_set(False)
    bpy.context.view_layer.update()
    return target, meshes, originals


def rotate_about_joint(armature, bone_name, world_rotation):
    pose_bone = armature.pose.bones[bone_name]
    linear = armature.matrix_world.to_3x3()
    local_rotation = linear.inverted() @ world_rotation.to_matrix() @ linear
    current = pose_bone.matrix.copy()
    result = local_rotation.to_4x4() @ current
    result.translation = current.translation
    pose_bone.matrix = result
    bpy.context.view_layer.update()


def endpoint_world(armature, mapping, key, end_key):
    if end_key in mapping:
        return world_joint(armature, mapping, end_key)
    bone = armature.pose.bones[mapping[key]]
    children = [child for child in bone.children if child.name not in mapping.values()]
    if children:
        return armature.matrix_world @ children[0].head
    return armature.matrix_world @ bone.tail


def segment_specs():
    # Pelvis defines the character frame and remains anchored. In MMD rigs the
    # lower body and upper body can be siblings, so rotating pelvis cannot aim
    # the spine and would incorrectly rotate the legs instead.
    specs = [
        ("spine_01", ("spine_02", "spine_03", "neck")),
        ("spine_02", ("spine_03", "neck", "head")),
        ("spine_03", ("neck", "head")), ("neck", ("head",)),
    ]
    for side in ("L", "R"):
        specs.extend((
            ("clavicle_" + side, ("upperarm_" + side,)),
            ("upperarm_" + side, ("forearm_" + side,)),
            ("forearm_" + side, ("hand_" + side,)),
            ("hand_" + side, ("middle_01_" + side, "index_01_" + side)),
            ("thigh_" + side, ("shin_" + side, "foot_" + side)),
            ("shin_" + side, ("foot_" + side,)),
            ("foot_" + side, ("toe_" + side,)),
            ("toe_" + side, ("toe_end_" + side,)),
        ))
        for finger in ("thumb", "index", "middle", "ring", "pinky"):
            specs.extend((
                (finger + "_01_" + side, (finger + "_02_" + side,)),
                (finger + "_02_" + side, (finger + "_03_" + side,)),
                (finger + "_03_" + side, (finger + "_end_" + side,)),
            ))
    return specs


def align_hand_roll(armature, mapping, reference_positions, frame, side):
    keys = [name + side for name in ("hand_", "index_01_", "pinky_01_", "middle_01_")]
    if not all(key in mapping for key in keys):
        return False
    wrist, index, pinky, middle = [world_joint(armature, mapping, key) for key in keys]
    reference = [Vector(reference_positions[key]) for key in keys]
    axis = (middle - wrist).normalized()
    normal = (index - wrist).cross(pinky - wrist)
    desired = frame @ ((reference[1] - reference[0]).cross(reference[2] - reference[0]))
    normal -= axis * normal.dot(axis)
    desired -= axis * desired.dot(axis)
    if normal.length < 1e-10 or desired.length < 1e-10:
        return False
    normal.normalize()
    desired.normalize()
    angle = math.atan2(axis.dot(normal.cross(desired)), normal.dot(desired))
    from mathutils import Quaternion
    rotate_about_joint(armature, mapping["hand_" + side], Quaternion(axis, angle))
    return True


def bake_rest_pose(armature, meshes):
    baked = []
    for obj in meshes:
        states = [(modifier, modifier.show_viewport) for modifier in obj.modifiers]
        active_key = obj.active_shape_key_index
        show_only = obj.show_only_shape_key
        coordinates = []
        normals = None
        try:
            for modifier, _enabled in states:
                modifier.show_viewport = modifier.type == "ARMATURE" and modifier.object == armature
            keys = obj.data.shape_keys
            key_count = len(keys.key_blocks) if keys else 1
            if keys:
                obj.show_only_shape_key = True
            for index in range(key_count):
                if keys:
                    obj.active_shape_key_index = index
                bpy.context.view_layer.update()
                depsgraph = bpy.context.evaluated_depsgraph_get()
                evaluated = obj.evaluated_get(depsgraph)
                mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
                try:
                    if len(mesh.vertices) != len(obj.data.vertices):
                        raise ValueError("Armature evaluation changed topology: " + obj.name)
                    coordinates.append([vertex.co.copy() for vertex in mesh.vertices])
                    if index == 0 and obj.data.has_custom_normals:
                        normals = [normal.vector.copy() for normal in mesh.corner_normals]
                finally:
                    evaluated.to_mesh_clear()
            baked.append((obj, coordinates, normals))
        finally:
            obj.active_shape_key_index = active_key
            obj.show_only_shape_key = show_only
            for modifier, enabled in states:
                modifier.show_viewport = enabled
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    for obj, coordinate_sets, normals in baked:
        for vertex, coordinate in zip(obj.data.vertices, coordinate_sets[0]):
            vertex.co = coordinate
        if obj.data.shape_keys:
            for key, coordinates in zip(obj.data.shape_keys.key_blocks, coordinate_sets):
                for point, coordinate in zip(key.data, coordinates):
                    point.co = coordinate
        obj.data.update()
        if normals:
            obj.data.normals_split_custom_set(normals)
    bpy.context.view_layer.update()


def convert_armature(source, source_preset="AUTO", apply_rest=True, hide_original=True, reference_path=REFERENCE_PATH):
    if not source or source.type != "ARMATURE":
        raise ValueError("Select the mod character's T-pose armature first.")
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    scale = source.matrix_world.to_scale()
    if min(abs(value) for value in scale) < 1e-8 or max(map(abs, scale)) - min(map(abs, scale)) > max(map(abs, scale)) * 1e-5:
        raise ValueError("Apply non-uniform object scale before conversion.")
    reference = json.loads(Path(reference_path).read_text(encoding="utf-8"))
    if reference.get("schema") != "dead_space_semantic_pose_v1":
        raise ValueError("Unsupported Dead Space pose reference schema.")
    if "upright_joint_positions" not in reference:
        raise ValueError("The pose reference needs upright joint positions for spread-only legs.")
    mapping, preset_name = resolve_mapping(source, source_preset, reference)
    target, meshes, originals = copy_character(source)
    frame = character_frame(target, mapping)
    positions = reference["joint_positions"]
    upright_positions = reference["upright_joint_positions"]
    leg_frame = leg_character_frame(target, mapping)
    original_matrices = {bone.name: bone.matrix.copy() for bone in target.pose.bones}
    original_directions = {}
    for key, candidates in segment_specs():
        if key not in mapping or not key.startswith(("thigh_", "shin_", "foot_", "toe_")):
            continue
        end_key = next((candidate for candidate in candidates if candidate in mapping), candidates[0])
        original_directions[key] = endpoint_world(target, mapping, key, end_key) - world_joint(target, mapping, key)
    aligned = []
    skipped = []
    hand_rolls = []
    desired_directions = {}
    try:
        for key, candidates in segment_specs():
            if key not in mapping:
                skipped.append(key)
                continue
            end_key = next((candidate for candidate in candidates if candidate in mapping), None)
            if end_key is None and (key.startswith("toe_") or "_03_" in key):
                end_key = candidates[0]
            if end_key is None or key not in positions or end_key not in positions:
                skipped.append(key)
                continue
            current = endpoint_world(target, mapping, key, end_key) - world_joint(target, mapping, key)
            desired = frame @ (Vector(positions[end_key]) - Vector(positions[key]))
            if key.startswith(("thigh_", "shin_")):
                native = Vector(upright_positions[end_key]) - Vector(upright_positions[key])
                desired = leg_spread_direction(original_directions[key], native, leg_frame)
            elif key.startswith(("foot_", "toe_")):
                # Restore the full orientation after ancestors move the ankle.
                # Keep its new location, including the source foot roll and pitch.
                bone = target.pose.bones[mapping[key]]
                restored = original_matrices[bone.name].copy()
                restored.translation = bone.matrix.translation.copy()
                bone.matrix = restored
                bpy.context.view_layer.update()
                desired = original_directions[key]
            if current.length < 1e-8 or desired.length < 1e-8:
                skipped.append(key)
                continue
            if not key.startswith(("foot_", "toe_")):
                rotation = current.normalized().rotation_difference(desired.normalized())
                rotate_about_joint(target, mapping[key], rotation)
            desired_directions[key] = desired.copy()
            aligned.append((key, end_key))
            if key.startswith("hand_"):
                side = key[-1]
                if align_hand_roll(target, mapping, positions, frame, side):
                    hand_rolls.append(side)
        errors = {}
        for key, end_key in aligned:
            current = endpoint_world(target, mapping, key, end_key) - world_joint(target, mapping, key)
            desired = desired_directions[key]
            errors[key] = math.degrees(current.angle(desired))
        if apply_rest:
            bake_rest_pose(target, meshes)
        if hide_original:
            source.hide_set(True)
            for obj in originals:
                obj.hide_set(True)
        bpy.ops.object.select_all(action="DESELECT")
        target.select_set(True)
        bpy.context.view_layer.objects.active = target
        target["dsr_pose_reference"] = str(reference_path)
        target["dsr_source_preset"] = preset_name
        target["dsr_pose_baked_to_rest"] = apply_rest
        report = {"source": source.name, "result": target.name, "source_preset": preset_name,
                  "joints_rotated": len(aligned), "hand_rolls_matched": hand_rolls,
                  "meshes_copied": len(meshes), "baked_to_rest": apply_rest,
                  "leg_mode": "spread_only_preserve_pitch_and_foot_orientation",
                  "skipped_optional_joints": skipped, "maximum_direction_error_degrees": max(errors.values(), default=0.0)}
        target["dsr_pose_conversion_report"] = json.dumps(report)
        print("DSR_POSE_CONVERSION " + json.dumps(report))
        return target, meshes, report
    except Exception:
        target["dsr_pose_conversion_incomplete"] = True
        raise

