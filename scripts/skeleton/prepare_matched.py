"""Match native bind positions and ANT defaults to an existing prepared mesh rig."""

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import struct

from ant_bank import Bank, FormatError, audit, quaternion_rows, read_native
from skeleton_math import read_pose, multiply, matrix_error


def inverse(matrix):
    work = [list(row) + [float(i == j) for j in range(4)] for i, row in enumerate(matrix)]
    for column in range(4):
        pivot = max(range(column, 4), key=lambda row: abs(work[row][column]))
        if abs(work[pivot][column]) < 1e-12:
            raise FormatError("Singular transform")
        work[column], work[pivot] = work[pivot], work[column]
        scale = work[column][column]
        work[column] = [value / scale for value in work[column]]
        for row in range(4):
            if row != column:
                factor = work[row][column]
                work[row] = [a - factor * b for a, b in zip(work[row], work[column])]
    return [row[4:] for row in work]


def point(matrix, value):
    return [sum(matrix[row][column] * value[column] for column in range(3)) + matrix[row][3]
            for row in range(3)]


def vector(matrix, value):
    return [sum(matrix[row][column] * value[column] for column in range(3)) for row in range(3)]


def accumulate(local, parents):
    result, pending = {}, set()

    def visit(name):
        if name in result:
            return result[name]
        if name in pending:
            raise FormatError("Cyclic hierarchy")
        pending.add(name)
        parent = parents[name]
        if parent is not None and parent not in local:
            raise FormatError("Unresolved parent")
        result[name] = multiply(visit(parent), local[name]) if parent is not None else local[name]
        pending.remove(name)
        return result[name]

    for name in local:
        visit(name)
    return result


def inherit_deltas(parents, anchors):
    result, pending = {}, set()

    def visit(name):
        if name in pending:
            raise FormatError("Cyclic hierarchy")
        if name not in result:
            pending.add(name)
            parent = parents[name]
            if name in anchors:
                result[name] = list(anchors[name])
            elif parent is None:
                result[name] = [0.0, 0.0, 0.0]
            elif parent not in parents:
                raise FormatError("Unresolved parent")
            else:
                result[name] = list(visit(parent))
            pending.remove(name)
        return result[name]

    for name in parents:
        visit(name)
    return result


def default_matrices(report):
    values = {row["name"]: row for row in report["defaults"] if row["name"]}
    joints = report["joints"]
    local, parents = {}, {}
    for joint in joints:
        name = joint["name"]
        parent = joint["parent_index"]
        parents[name] = joints[parent]["name"] if parent >= 0 else None
        translation, quaternion, scale = (values[name + suffix]["value"] for suffix in (".t", ".q", ".s"))
        rows = quaternion_rows(quaternion)
        matrix = [[rows[column][row] * scale[column] for column in range(3)] + [translation[row]]
                  for row in range(3)] + [[0.0, 0.0, 0.0, 1.0]]
        local[name] = matrix
    return local, parents, values


def patch_defaults(data, report, deltas):
    local, parents, values = default_matrices(report)
    before_world = copy.deepcopy(accumulate(local, parents))
    full_deltas = inherit_deltas(parents, deltas)
    patched = bytearray(data)
    edits = []
    for name, matrix in local.items():
        parent = parents[name]
        relative = [full_deltas[name][axis] - (full_deltas[parent][axis] if parent else 0.0) for axis in range(3)]
        if max(map(abs, relative)) < 1e-10:
            continue
        increment = vector(inverse(before_world[parent]), relative) if parent else relative
        original = values[name + ".t"]
        new = [value + delta for value, delta in zip(original["value"], increment)]
        packed = struct.pack("<3f", *new)
        offset = original["offset"]
        patched[offset:offset + 12] = packed
        actual = list(struct.unpack("<3f", packed))
        for axis in range(3):
            matrix[axis][3] = actual[axis]
        edits.append({"name": name, "offset": offset, "before": original["value"], "after": actual})
    if not edits:
        return bytes(data), [], before_world, copy.deepcopy(before_world), 0.0
    after_world = accumulate(local, parents)
    error = max(abs(after_world[name][axis][3] - before_world[name][axis][3] - full_deltas[name][axis])
                for name in local for axis in range(3))
    orientation_error = max(abs(after_world[name][row][column] - before_world[name][row][column])
                            for name in local for row in range(3) for column in range(3))
    allowed = {offset for edit in edits for offset in range(edit["offset"], edit["offset"] + 12)}
    if len(data) != len(patched) or any(a != b and index not in allowed for index, (a,b) in enumerate(zip(data, patched))):
        raise FormatError("Unexpected bank byte changes")
    if error > 2e-5 or orientation_error != 0:
        raise FormatError(f"ANT world-position or orientation validation failed: {error}, {orientation_error}")
    return bytes(patched), edits, before_world, after_world, error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspection", type=Path, required=True)
    parser.add_argument("--skeleton-xml", type=Path, required=True)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--base-release", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise FormatError("Output directory must be new or empty")
    release = json.loads(args.base_release.read_text(encoding="utf-8"))
    base_mod = Path(release["package"])
    if hashlib.sha256(base_mod.read_bytes()).hexdigest() != release["sha256"]:
        raise FormatError("Existing character package identity changed")
    scene = json.loads(args.inspection.read_text(encoding="utf-8"))
    names, parent_indices, poses = read_pose(args.skeleton_xml)
    parent_indices = [-1 if value == 0xFFFFFFFF else value for value in parent_indices]
    parents = {name: names[index] if index >= 0 else None for name,index in zip(names,parent_indices)}
    native_model = dict(zip(names, poses["ModelPose"]))
    baseline_inverse = dict(zip(names, poses["InverseModelPose"]))
    source = scene["source_rig"]
    reference = scene["native_rig"]
    source_to_native = multiply(inverse(reference["world"]), source["world"])
    anchors, targets = {}, {}
    native_error = max(matrix_error(native_model[name], bone["matrix"]) for name,bone in reference["bones"].items())
    if native_error > 5e-6:
        raise FormatError(f"Native Blender reference differs from XML: {native_error}")
    weighted = set().union(*(set(mesh["weighted_groups"]) for mesh in scene["meshes"]))
    if weighted - source["bones"].keys() or source["bones"].keys() - native_model.keys():
        raise FormatError("Source rig/weight names do not resolve to native bones")
    for name, bone in source["bones"].items():
        target = point(source_to_native, bone["head"])
        delta = [target[axis] - native_model[name][axis][3] for axis in range(3)]
        anchors[name] = delta if max(map(abs, delta)) > 1e-5 else [0.0, 0.0, 0.0]
        targets[name] = target
    if "Reference" in anchors:
        raise FormatError("Reference root must remain unchanged")
    deltas = inherit_deltas(parents, anchors)
    new_model = copy.deepcopy(native_model)
    for name, delta in deltas.items():
        for axis in range(3):
            new_model[name][axis][3] += delta[axis]
    original_bank = args.bank.read_bytes()
    bank_report = audit(Bank(original_bank), read_native(args.skeleton_xml), "Player_Rig")
    if bank_report["counts"]["matching_parents"] != len(names):
        raise FormatError("ANT/native hierarchy mismatch")
    patched, edits, ant_before, ant_after, ant_error = patch_defaults(original_bank, bank_report, deltas)
    readback = audit(Bank(patched), read_native(args.skeleton_xml), "Player_Rig")
    if readback["joints"] != bank_report["joints"] or readback["counts"] != bank_report["counts"]:
        raise FormatError("ANT structure changed")
    identity_error = max(matrix_error(multiply(new_model[name], inverse(new_model[name])),
                                     [[float(i==j) for j in range(4)] for i in range(4)]) for name in names)
    skin_errors = {name: matrix_error(multiply(ant_before[name], baseline_inverse[name]),
                                      multiply(ant_after[name], inverse(new_model[name]))) for name in weighted}
    if max(skin_errors.values()) > 2e-5:
        raise FormatError(f"Matched static skinning relationship changed: {max(skin_errors.values())}")
    report = {"base_mod": release, "source_blend": scene["source"], "source_rig": source["name"],
              "strategy": "Keep existing geometry; native joint positions follow prepared rig anchors; unmapped joints inherit nearest mapped ancestor displacement",
              "native_rotations_preserved": True, "geometry_modified": False,
              "weighted_bones": sorted(weighted), "anchors": targets, "native_model_before": native_model,
              "native_model_after": new_model, "deltas": deltas, "ant_edits": edits,
              "counts": {"native_bones": len(names), "source_anchors": len(anchors),
                         "changed_anchors": sum(any(value) for value in anchors.values()),
                         "changed_bind_positions": sum(any(value) for value in deltas.values()), "ant_translation_edits": len(edits)},
              "checks": {"native_reference_matrix_error": native_error,
                         "ant_world_displacement_error": ant_error, "bind_inverse_error": identity_error,
                         "maximum_matched_static_skinning_error": max(skin_errors.values())},
              "baseline_bank_sha256": hashlib.sha256(original_bank).hexdigest(),
              "patched_bank_sha256": hashlib.sha256(patched).hexdigest(),
              "inputs": {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (args.inspection,args.skeleton_xml,args.bank,args.base_release,Path(scene["source"]),Path(__file__))},
              "runtime_tested": False,
              "limitations": ["Static matrix validation only; animation overrides and procedural behavior remain unverified",
                              "Existing height scaling and hand fitting are retained for a controlled comparison",
                              "Unmapped helper offsets are translated with ancestors, not individually refitted"]}
    args.out.mkdir(parents=True, exist_ok=True)
    rows = ["# bone\tparent\tbaseline_x\tbaseline_y\tbaseline_z\tdelta_x\tdelta_y\tdelta_z"]
    for name in names:
        if name != "Reference":
            position = [native_model[name][axis][3] for axis in range(3)]
            rows.append("\t".join([name, parents[name]] + [format(value,".9g") for value in position + deltas[name]]))
    (args.out/"translations.tsv").write_text("\n".join(rows)+"\n",encoding="utf-8")
    (args.out/"patched_globals.res").write_bytes(patched)
    (args.out/"trial.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"counts":report["counts"],"checks":report["checks"]},indent=2))


if __name__ == "__main__":
    main()
