"""Fit the scaled character's wrists and fingers without refitting the body."""

import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector


WORK = None
SOURCE = None
NATIVE = None
OUTPUT = None
MINIMUM_ELBOW_BEND = 15.0
MAXIMUM_STRETCH = 1.25
DIGITS = ("Thumb", "Index", "Middle", "Ring", "Pinky")


def solve_arm(root, elbow, wrist, target, minimum_bend_degrees=MINIMUM_ELBOW_BEND):
    """Solve a two-segment chain, transporting its original elbow pole."""
    upper, lower = (elbow - root).length, (wrist - elbow).length
    distance = (target - root).length
    if min(upper, lower, distance) < 1e-9:
        raise ValueError("Degenerate arm chain.")
    original_axis = (wrist - root).normalized()
    axis = (target - root).normalized()
    pole = elbow - root - original_axis * (elbow - root).dot(original_axis)
    if pole.length < 1e-9:
        raise ValueError("The source elbow does not define a stable bend plane.")
    pole = original_axis.rotation_difference(axis) @ pole.normalized()
    pole = (pole - axis * pole.dot(axis)).normalized()
    minimum_bend = math.radians(minimum_bend_degrees)
    bent_reach = math.sqrt(upper * upper + lower * lower + 2 * upper * lower * math.cos(minimum_bend))
    stretch = max(1.0, distance / bent_reach)
    upper_length, lower_length = upper * stretch, lower * stretch
    if distance < abs(upper_length - lower_length) + 1e-9:
        raise ValueError("Target is inside the chain's minimum reach.")
    along = (distance * distance + upper_length * upper_length - lower_length * lower_length) / (2 * distance)
    height = math.sqrt(max(0., upper_length * upper_length - along * along))
    solved = root + axis * along + pole * height
    turn = math.degrees((solved - root).angle(target - solved))
    return solved, {"stretch": stretch, "minimum_required_straight_stretch": distance / (upper + lower),
                    "upper_length_before": upper, "forearm_length_before": lower,
                    "upper_length_after": upper_length, "forearm_length_after": lower_length,
                    "elbow_bend_degrees": turn, "elbow_before_world": list(elbow),
                    "elbow_after_world": list(solved), "root_world": list(root), "target_wrist_world": list(target)}


def frame(direction, hint):
    y = direction.normalized()
    x = hint - y * hint.dot(y)
    if x.length < 1e-9:
        raise ValueError("An anatomical frame has a degenerate transverse direction.")
    x.normalize()
    return Matrix((x, y, x.cross(y).normalized())).transposed()


def segment_transform(start, end, new_start, new_end, hint, new_hint, cross_scale=1.):
    source = end - start
    target = new_end - new_start
    if min(source.length, target.length) < 1e-9:
        raise ValueError("An anatomical segment is too short.")
    linear = frame(target, new_hint) @ Matrix.Diagonal(
        (cross_scale, target.length / source.length, cross_scale)) @ frame(source, hint).transposed()
    result = linear.to_4x4()
    result.translation = new_start - linear @ start
    return result


def snapshot(rig):
    return {"world": list(map(list, rig.matrix_world)), "bones": {
        bone.name: {"matrix": list(map(list, bone.matrix_local)), "head": list(bone.head_local),
                    "tail": list(bone.tail_local), "parent": bone.parent.name if bone.parent else None,
                    "connected": bone.use_connect}
        for bone in rig.data.bones}}


def joint(rig, name):
    return rig.matrix_world @ rig.data.bones[name].head_local


def fit():
    assert Path(bpy.data.filepath).resolve() == SOURCE.resolve()
    WORK.mkdir(exist_ok=True)
    rig = bpy.data.objects["DSR_Rig"]
    native = bpy.data.objects["Original_Game_Rig_Comparison"]
    parts = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    assert len(parts) == 11
    assert all(not bone.constraints and max(abs(bone.matrix_basis[i][j] - (1 if i == j else 0))
               for i in range(4) for j in range(4)) < 1e-7 for bone in rig.pose.bones)
    assert all(obj.data.shape_keys is None for obj in parts)
    before = snapshot(rig)
    native_before = snapshot(native)
    old = {bone.name: joint(rig, bone.name) for bone in rig.data.bones}
    transforms, rest_targets, arm_reports = {}, {}, {}
    for side in ("Left", "Right"):
        arm, forearm, hand = (side + name for name in ("Arm", "ForeArm", "Hand"))
        target_wrist = joint(native, hand)
        solved_elbow, arm_reports[side] = solve_arm(old[arm], old[forearm], old[hand], target_wrist, MINIMUM_ELBOW_BEND)
        if arm_reports[side]["stretch"] > MAXIMUM_STRETCH:
            raise ValueError("Arm extension exceeds the configured review threshold.")
        old_axis = (old[hand] - old[arm]).normalized()
        old_pole = old[forearm] - old[arm] - old_axis * (old[forearm] - old[arm]).dot(old_axis)
        new_axis = (target_wrist - old[arm]).normalized()
        new_pole = old_axis.rotation_difference(new_axis) @ old_pole
        for name, start, end, new_start, new_end in (
            (arm, old[arm], old[forearm], old[arm], solved_elbow),
            (forearm, old[forearm], old[hand], solved_elbow, target_wrist)):
            transforms[name] = segment_transform(start, end, new_start, new_end, old_pole, new_pole)
            rotation = (end - start).rotation_difference(new_end - new_start).to_matrix()
            matrix = (rotation @ (rig.matrix_world @ rig.data.bones[name].matrix_local).to_3x3().normalized()).to_4x4()
            matrix.translation = new_start
            rest_targets[name] = {"matrix": matrix, "head": new_start, "tail": new_end}

        old_width = old[side + "HandIndex1"] - old[side + "HandPinky1"]
        new_width = joint(native, side + "HandIndex1") - joint(native, side + "HandPinky1")
        palm_scale = new_width.length / old_width.length
        transforms[hand] = segment_transform(old[hand], old[side + "HandMiddle1"], target_wrist,
                                             joint(native, side + "HandMiddle1"), old_width, new_width, palm_scale)
        hand_names = [hand] + [side + "Hand" + digit + str(index) for digit in DIGITS for index in (1, 2, 3)]
        assert set(hand_names[1:]) == {bone.name for bone in rig.data.bones[hand].children_recursive}
        for name in hand_names:
            bone = native.data.bones[name]
            matrix = (native.matrix_world @ bone.matrix_local).normalized()
            rest_targets[name] = {"matrix": matrix, "head": joint(native, name),
                                  "tail": native.matrix_world @ bone.tail_local}
            if name == hand:
                continue
            index = int(name[-1])
            following = name[:-1] + str(index + 1)
            source_end = old[following] if index < 3 else rig.matrix_world @ rig.data.bones[name].tail_local
            target_end = joint(native, following)
            # Anatomical frames avoid the approximately 90-degree FBX/MMD bone-axis mismatch.
            transforms[name] = segment_transform(old[name], source_end, joint(native, name), target_end,
                                                 old_width, new_width)
        arm_reports[side]["palm_width_scale"] = palm_scale

    mesh_reports = []
    for obj in parts:
        world, inverse = obj.matrix_world.copy(), obj.matrix_world.inverted()
        normals = [item.vector.copy() for item in obj.data.corner_normals]
        normal_matrices = {}
        maximum_displacement = 0.
        for vertex in obj.data.vertices:
            influences = [(obj.vertex_groups[item.group].name, item.weight) for item in vertex.groups
                          if item.weight > 0 and obj.vertex_groups[item.group].name in transforms]
            if not influences:
                continue
            point = world @ vertex.co
            delta = Vector((0., 0., 0.))
            linear = Matrix.Identity(3)
            for name, weight in influences:
                transform = transforms[name]
                delta += (transform @ point - point) * weight
                linear += (transform.to_3x3() - Matrix.Identity(3)) * weight
            vertex.co = inverse @ (point + delta)
            local_linear = inverse.to_3x3() @ linear @ world.to_3x3()
            if local_linear.determinant() <= 0:
                raise ValueError("The fitted skin transform folds a vertex frame.")
            normal_matrices[vertex.index] = local_linear.inverted().transposed()
            maximum_displacement = max(maximum_displacement, delta.length)
        if normal_matrices:
            obj.data.update()
            obj.data.normals_split_custom_set([
                (normal_matrices[loop.vertex_index] @ normals[loop.index]).normalized()
                if loop.vertex_index in normal_matrices else normals[loop.index]
                for loop in obj.data.loops])
        mesh_reports.append({"part": obj["dsr_part"], "vertices": len(obj.data.vertices),
                             "changed_vertices": len(normal_matrices), "maximum_world_displacement": maximum_displacement})

    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    inverse = rig.matrix_world.inverted()
    for name, target in rest_targets.items():
        bone = rig.data.edit_bones[name]
        bone.use_connect = False
        local = inverse @ target["matrix"]
        local = local.normalized()
        bone.matrix = local
        bone.length = (inverse @ target["tail"] - inverse @ target["head"]).length
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()
    after = snapshot(rig)
    assert snapshot(native) == native_before
    for name, value in before["bones"].items():
        if name not in rest_targets:
            assert after["bones"][name] == value, name
    for name, target in rest_targets.items():
        assert (joint(rig, name) - target["head"]).length < 1e-8, name
    maximum_rest_error = 0.
    for obj in parts:
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        data = evaluated.to_mesh()
        rest_error = max((obj.matrix_world.to_3x3() @ (a.co - b.co)).length for a, b in zip(obj.data.vertices, data.vertices))
        maximum_rest_error = max(maximum_rest_error, rest_error)
        if rest_error >= 2e-8:
            raise ValueError("Fitted rest mesh changed: " + obj.name + " error=" + str(rest_error)
                             + " modifiers=" + str([(m.name, m.object.name) for m in obj.modifiers if m.type == "ARMATURE"])
                             + " pose=" + str([(b.name, list(b.location)) for b in rig.pose.bones if b.location.length > 1e-7]))
        evaluated.to_mesh_clear()
    rig.show_in_front = False
    rig.data.display_type = "STICK"
    report = {"source": str(SOURCE), "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              "native_source": str(NATIVE), "native_source_sha256": hashlib.sha256(NATIVE.read_bytes()).hexdigest(),
              "minimum_elbow_bend_degrees": MINIMUM_ELBOW_BEND,
              "arms": arm_reports, "meshes": mesh_reports, "changed_bones": sorted(rest_targets),
              "native_skeleton_unchanged": True, "weights_uvs_topology_unchanged": True,
              "maximum_evaluated_rest_world_error": maximum_rest_error,
              "skeleton_override": False, "runtime_tested": False,
              "source_rig": before, "result_rig": after,
              "deformation_matrices_world": {name: list(map(list, matrix)) for name, matrix in transforms.items()}}
    (WORK / "fit_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT))
    print("HAND_IK_FIT " + json.dumps({"arms": arm_reports, "parts": len(parts), "changed_bones": len(rest_targets)}))

