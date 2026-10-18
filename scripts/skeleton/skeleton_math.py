"""Skeleton matrix and visual compensation validation helpers."""

import xml.etree.ElementTree as ET

def read_pose(path):
    root = ET.parse(path).getroot().find("SkeletonAsset")
    names = [item.text for item in root.find("BoneNames")]
    parents = [int(item.text, 0) for item in root.find("Hierarchy")]
    poses = {}
    for field in ("ModelPose", "InverseModelPose", "LocalPose"):
        matrices = []
        for item in root.find(field):
            transform = item.find("LinearTransform")
            columns = [[float(transform.find(row + "/Vec3/" + axis).text) for axis in "xyz"]
                       for row in ("right", "up", "forward", "trans")]
            matrices.append([[columns[j][i] for j in range(4)] for i in range(3)] + [[0., 0., 0., 1.]])
        poses[field] = matrices
    return names, parents, poses


def multiply(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def matrix_error(a, b):
    return max(abs(a[i][j] - b[i][j]) for i in range(4) for j in range(4))


def validate_offsets(names, parents, original, new_names, new_parents, modified, deltas):
    if names != new_names or parents != new_parents:
        raise ValueError("Bone names or hierarchy changed.")
    if original["LocalPose"] != modified["LocalPose"]:
        raise ValueError("Visual-offset mode must preserve LocalPose exactly.")
    identity = [[float(i == j) for j in range(4)] for i in range(4)]
    inverse_error = translation_error = prediction_error = 0.
    samples = {}
    for index, name in enumerate(names):
        requested = deltas.get(name, [0., 0., 0.])
        before = original["ModelPose"][index]
        after = modified["ModelPose"][index]
        if any(before[i][j] != after[i][j] for i in range(3) for j in range(3)):
            raise ValueError("Native bone rotation changed: " + name)
        actual = [after[i][3] - before[i][3] for i in range(3)]
        translation_error = max(translation_error, max(abs(actual[i] + requested[i]) for i in range(3)))
        inverse_error = max(inverse_error, matrix_error(multiply(after, modified["InverseModelPose"][index]), identity))
        skin = multiply(before, modified["InverseModelPose"][index])
        prediction_error = max(prediction_error, max(abs(skin[i][3] - requested[i]) for i in range(3)))
        if not any(requested):
            if before != after or original["InverseModelPose"][index] != modified["InverseModelPose"][index]:
                raise ValueError("An unedited bone changed: " + name)
        if name in ("Hips", "Head", "LeftHand", "RightHand", "LeftFoot", "RightFoot"):
            samples[name] = {"requested_visual_offset_native_xyz": requested, "actual_bind_delta_native_xyz": actual,
                             "predicted_mesh_offset_under_original_reference_animation": [skin[i][3] for i in range(3)]}
    if translation_error >= 2e-6 or inverse_error >= 2e-5 or prediction_error >= 4e-6:
        raise ValueError("Visual-offset sign, inverse bind or prediction check failed: " + str((translation_error, inverse_error, prediction_error)))
    counts = {field: sum(matrix_error(original[field][i], modified[field][i]) > 1e-6 for i in range(len(names)))
              for field in original}
    expected = sum(any(value != 0 for value in deltas.get(name, [])) for name in names)
    if counts != {"ModelPose": expected, "InverseModelPose": expected, "LocalPose": 0}:
        raise ValueError("Unexpected pose-change counts: " + str(counts))
    return {"mode": "visual-offset", "bones": len(names), "changed_entries": counts,
            "maximum_requested_translation_error": translation_error, "maximum_inverse_identity_error": inverse_error,
            "maximum_reference_animation_prediction_error": prediction_error, "local_pose_unchanged": True,
            "native_rotations_unchanged": True, "runtime_tested": False, "samples": samples}
