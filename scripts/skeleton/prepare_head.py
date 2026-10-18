"""Prepare Head-subtree inverse-bind compensation over the matched skeleton.

The compensation models an original Head local translation evaluated under
the matched parent reference. It is not a measured final-renderer transform.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path

from ant_bank import FormatError
from prepare_matched import accumulate, default_matrices
from skeleton_math import read_pose


def head_compensation(audit, edits):
    local, parents, _ = default_matrices(audit)
    seen = set()
    for edit in edits:
        name = edit["name"]
        if name in seen or name not in local:
            raise FormatError("Invalid or duplicate ANT edit")
        seen.add(name)
        for axis in range(3):
            if abs(local[name][axis][3] - edit["before"][axis]) > 1e-7:
                raise FormatError("Original ANT translation does not match the trial")
            local[name][axis][3] = edit["after"][axis]
    head_edits = [edit for edit in edits if edit["name"] == "Head"]
    if not head_edits:
        target = accumulate(local, parents)
        return [0.0, 0.0, 0.0], target, copy.deepcopy(target)
    if len(head_edits) != 1:
        raise FormatError("Expected exactly one Head translation edit")
    head = head_edits[0]
    target = accumulate(local, parents)
    conditional = copy.deepcopy(local)
    for axis in range(3):
        conditional["Head"][axis][3] = head["before"][axis]
    animated = accumulate(conditional, parents)
    residual = [animated["Head"][axis][3] - target["Head"][axis][3] for axis in range(3)]
    return [-x for x in residual], target, animated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--matched-xml", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    trial = json.loads(args.trial.read_text(encoding="utf-8"))
    delta, target, animated = head_compensation(audit, trial["ant_edits"])
    names, indices, poses = read_pose(args.matched_xml)
    parents = {name: names[index] if index not in (-1, 0xFFFFFFFF) else None
               for name, index in zip(names, indices)}
    subtree = []
    for name in names:
        ancestor = name
        seen = set()
        while ancestor is not None:
            if ancestor in seen:
                raise FormatError("Cyclic native hierarchy")
            seen.add(ancestor)
            if ancestor == "Head":
                subtree.append(name)
                break
            ancestor = parents[ancestor]
    if not subtree or "Neck" in subtree:
        raise FormatError("Invalid Head subtree")
    target_error = max(abs(target[name][axis][3] - poses["ModelPose"][i][axis][3])
                       for i, name in enumerate(names) if name in subtree for axis in range(3))
    residual_error = max(abs(animated[name][axis][3] - target[name][axis][3] + delta[axis])
                         for name in subtree for axis in range(3))
    if target_error > 5e-6 or residual_error > 5e-6:
        raise FormatError(f"Head reference/subtree mismatch: {target_error}, {residual_error}")
    lines = []
    for index, name in enumerate(names):
        if parents[name] is None:
            continue
        position = [poses["ModelPose"][index][axis][3] for axis in range(3)]
        offset = delta if name in subtree else [0.0] * 3
        lines.append("\t".join([name, parents[name]] + [format(x, ".17g") for x in position + offset]))
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "translations.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = {"strategy": "Keep matched skeleton and ANT; compensate only Head-subtree inverse binds",
              "visual_delta_native_xyz": delta, "bind_translation_increment_native_xyz": [-x for x in delta],
              "head_subtree": subtree, "head_subtree_count": len(subtree),
              "reference_position_error": target_error, "subtree_residual_error": residual_error,
              "local_pose_to_preserve": "Matched skeleton LocalPose, not original LocalPose",
              "ant_payload_to_preserve_sha256": trial["patched_bank_sha256"],
              "inputs": {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in (args.audit, args.trial, args.matched_xml)},
              "runtime_tested": False,
              "limits": ["Original Head local translation under matched reference parent is a conditional model",
                         "Animated head rotations can change compensation behavior",
                         "No final skinning palette measurement"]}
    (args.out / "compensation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("visual_delta_native_xyz", "head_subtree_count", "reference_position_error")}))


if __name__ == "__main__":
    main()
