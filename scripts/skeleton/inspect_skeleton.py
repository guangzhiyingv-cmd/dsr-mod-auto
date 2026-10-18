"""Read a prepared character and native rig without saving either input."""

import argparse
import json
from pathlib import Path
import sys

import bpy


def snapshot(rig):
    return {"name": rig.name, "world": [list(row) for row in rig.matrix_world],
            "bones": {bone.name: {"parent": bone.parent.name if bone.parent else None,
                                  "matrix": [list(row) for row in bone.matrix_local],
                                  "head": list(bone.head_local)} for bone in rig.data.bones}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--rig", required=True)
    parser.add_argument("--native-rig", default="Reference")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.out.exists():
        raise FileExistsError(args.out)
    rig = bpy.data.objects[args.rig]
    if any(b.constraints or max(abs(b.matrix_basis[i][j] - (1 if i == j else 0)) for i in range(4) for j in range(4)) > 1e-6 for b in rig.pose.bones):
        raise ValueError("Prepared rig must have an identity pose and no constraints")
    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH" and any(
        modifier.type == "ARMATURE" and modifier.object == rig for modifier in obj.modifiers)]
    output = {"source": bpy.data.filepath, "source_rig": snapshot(rig), "meshes": []}
    for obj in meshes:
        counts = {}
        for vertex in obj.data.vertices:
            for weight in vertex.groups:
                if weight.weight > 0:
                    name = obj.vertex_groups[weight.group].name
                    counts[name] = counts.get(name, 0) + 1
        output["meshes"].append({"name": obj.name, "vertices": len(obj.data.vertices),
                                  "triangles": sum(len(face.vertices)-2 for face in obj.data.polygons),
                                  "world": [list(row) for row in obj.matrix_world], "weighted_groups": counts})
    with bpy.data.libraries.load(str(args.native), link=False) as (available, loaded):
        loaded.objects = [args.native_rig]
    native = loaded.objects[0]
    bpy.context.scene.collection.objects.link(native)
    bpy.context.view_layer.update()
    output["native_rig"] = snapshot(native)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print("SAMPLE_INSPECTED " + json.dumps({"bones": len(rig.data.bones), "meshes": len(meshes), "out": str(args.out)}))


if __name__ == "__main__":
    main()
