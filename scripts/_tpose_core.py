"""Normalize A-pose arms to a measured T-pose before DSR pose conversion."""

import json
import math

from mathutils import Vector

import _pose_core as pose


def arm_measurements(rig, mapping):
    frame = pose.character_frame(rig, mapping)
    result = {}
    for side, sign in (("L", 1), ("R", -1)):
        arm, elbow, wrist = (pose.world_joint(rig, mapping, key + "_" + side)
                             for key in ("upperarm", "forearm", "hand"))
        direction = frame.transposed() @ (elbow - arm).normalized()
        lower = frame.transposed() @ (wrist - elbow).normalized()
        result[side] = {"upper_elevation_degrees": math.degrees(math.atan2(direction.y, sign * direction.x)),
                        "upper_forward_degrees": math.degrees(math.asin(max(-1., min(1., direction.z)))),
                        "upper_t_error_degrees": math.degrees(direction.angle(Vector((sign, 0, 0)))),
                        "forearm_t_error_degrees": math.degrees(lower.angle(Vector((sign, 0, 0))))}
    return result


def classify(measurements):
    if all(item["upper_t_error_degrees"] < 6 and item["forearm_t_error_degrees"] < 12
           for item in measurements.values()):
        return "T"
    if all(-70 < item["upper_elevation_degrees"] < -5 and abs(item["upper_forward_degrees"]) < 30
           for item in measurements.values()):
        return "A"
    raise ValueError("The source pose is neither a clear A-pose nor a T-pose; inspect it and choose an explicit pose policy.")


def convert(source, source_preset, source_pose="AUTO"):
    reference = json.loads(pose.REFERENCE_PATH.read_text(encoding="utf-8"))
    mapping, preset_name = pose.resolve_mapping(source, source_preset, reference)
    before = arm_measurements(source, mapping)
    classification = classify(before) if source_pose == "AUTO" else source_pose
    if classification == "DSR":
        raise ValueError("An already converted DSR pose must skip T-pose and DSR conversion stages.")
    if classification == "T" and any(item["upper_t_error_degrees"] > 12 for item in before.values()):
        raise ValueError("The input does not match the declared T-pose.")
    target, meshes, originals = pose.copy_character(source)
    frame = pose.character_frame(target, mapping)
    rotated = []
    # A-pose conversion rotates upper arm and forearm about their own joints.
    # Descendants follow; fingers retain their local articulation and hand roll.
    if classification == "A":
        for side, sign in (("L", 1), ("R", -1)):
            desired = frame @ Vector((sign, 0, 0))
            for start, end in (("upperarm", "forearm"), ("forearm", "hand")):
                key, endpoint = start + "_" + side, end + "_" + side
                current = pose.world_joint(target, mapping, endpoint) - pose.world_joint(target, mapping, key)
                pose.rotate_about_joint(target, mapping[key], current.normalized().rotation_difference(desired))
                rotated.append(key)
    after = arm_measurements(target, mapping)
    if any(max(item["upper_t_error_degrees"], item["forearm_t_error_degrees"]) > 12
           for item in after.values()):
        raise ValueError("T-pose normalization did not produce straight lateral arms.")
    pose.bake_rest_pose(target, meshes)
    return target, meshes, {"source_pose": classification, "requested_pose": source_pose,
        "source_preset": preset_name, "arms_before": before, "arms_after": after,
        "rotated_semantic_joints": rotated, "baked_to_rest": True,
        "sequence": "A -> T -> DSR" if classification == "A" else "T -> DSR"}
