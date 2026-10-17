"""Import a base MMD model and freeze its visible static state on a copy."""

from pathlib import Path

import addon_utils
import bpy

from dsr_common import sha256, write_json
import _pose_core as pose


def enable_mmd(config):
    name = config.get("mmd_addon", "bl_ext.user_default.mmd_tools")
    module = addon_utils.enable(name, default_set=False)
    if module is None or not getattr(module, "__addon_enabled__", False):
        raise RuntimeError("The configured MMD Tools add-on could not be enabled: " + name)
    return name


def image_inputs():
    result = []
    for image in bpy.data.images:
        if image.source != "FILE":
            continue
        path = Path(bpy.path.abspath(image.filepath))
        result.append({"name": image.name, "path": str(path), "packed": bool(image.packed_file),
                       "size": list(image.size), "exists": path.is_file(),
                       "sha256": sha256(path) if path.is_file() else None})
    return result


def import_model(config, work):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon = enable_mmd(config)
    settings = {"types": {"MESH", "ARMATURE", "MORPHS"},
        "scale": config.get("mmd_import_scale", .08), "clean_model": False,
        "remove_doubles": False, "fix_bone_order": False, "fix_ik_links": False,
        "apply_bone_fixed_axis": False, "rename_bones": True, "save_log": False,
        "log_level": "WARNING"}
    result = bpy.ops.mmd_tools.import_model(filepath=config["input"], **settings)
    rigs = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    # MMD Tools can return FINISHED after logging an import exception.
    if result != {"FINISHED"} or len(rigs) != 1 or len(meshes) != 1 or not meshes[0].data.polygons:
        raise ValueError("Raw MMD import must produce one nonempty character mesh and one rig.")
    rig, mesh = rigs[0], meshes[0]
    if len(config["mesh_objects"]) != 1:
        raise ValueError("Direct PMX import currently expects a single configured mesh name.")
    original_names = {b.name: b.mmd_bone.name_j for b in rig.pose.bones}
    rig.name, mesh.name = config["rig_object"], config["mesh_objects"][0]
    missing_base = []
    for material in mesh.data.materials:
        node = material.node_tree.nodes.get("mmd_base_tex")
        if node and node.image and (not node.image.size[0] or not node.image.size[1]):
            missing_base.append(material.name)
    if missing_base:
        raise ValueError("Missing base-color images for: " + str(missing_base))
    report = {"source": config["input"], "source_sha256": sha256(config["input"]),
        "addon": addon, "settings": {k: sorted(v) if isinstance(v, set) else v for k, v in settings.items()},
        "rig": rig.name, "mesh": mesh.name, "bones": len(rig.data.bones),
        "vertices": len(mesh.data.vertices), "triangles": len(mesh.data.polygons),
        "shape_keys": [{"name": k.name, "value": k.value} for k in mesh.data.shape_keys.key_blocks]
                      if mesh.data.shape_keys else [],
        "original_pmx_bone_names": original_names,
        "material_order": [{"index": i, "name": m.name} for i, m in enumerate(mesh.data.materials)],
        "images": image_inputs(), "physics_imported": False}
    for image in bpy.data.images:
        if image.source == "FILE" and image.size[0] and image.size[1]:
            image.pack()
    write_json(work / "reports/import.json", report)


def evaluated_points(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    data = evaluated.to_mesh()
    try:
        return [obj.matrix_world @ v.co for v in data.vertices]
    finally:
        evaluated.to_mesh_clear()


def freeze(config, work):
    if config.get("static_morph_policy", "current_visible") != "current_visible":
        raise ValueError("Static preparation currently supports the explicit current_visible morph policy.")
    if Path(config["input"]).suffix.lower() in (".pmx", ".pmd"):
        enable_mmd(config)
    source = bpy.data.objects[config["rig_object"]]
    originals = [bpy.data.objects[name] for name in config["mesh_objects"]]
    if any(any(m.type != "ARMATURE" for m in obj.modifiers) for obj in originals):
        raise ValueError("Resolve non-armature modifiers before freezing a static model.")
    bpy.context.view_layer.update()
    before = {obj.name: evaluated_points(obj) for obj in originals}
    morphs = {obj.name: [{"name": k.name, "value": k.value} for k in obj.data.shape_keys.key_blocks]
              if obj.data.shape_keys else [] for obj in originals}
    target, meshes, copied_sources = pose.copy_character(source)
    if set(copied_sources) != set(originals):
        raise ValueError("Selected meshes do not cover exactly the source rig's bound character meshes.")
    pose.bake_rest_pose(target, meshes)
    for obj in meshes:
        obj.animation_data_clear()
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        data = evaluated.to_mesh()
        try:
            points = [v.co.copy() for v in data.vertices]
            normals = [n.vector.copy() for n in data.corner_normals]
        finally:
            evaluated.to_mesh_clear()
        obj.shape_key_clear()
        for vertex, point in zip(obj.data.vertices, points):
            vertex.co = point
        obj.data.update()
        obj.data.normals_split_custom_set(normals)
    world = target.matrix_world.copy()
    mesh_world = [obj.matrix_world.copy() for obj in meshes]
    target.parent = None
    target.matrix_world = world
    for obj, matrix in zip(meshes, mesh_world):
        obj.parent = target
        obj.matrix_world = matrix
    bpy.context.view_layer.update()
    errors = []
    for original, obj in zip(copied_sources, meshes):
        after = evaluated_points(obj)
        prior = before[original.name]
        if len(after) != len(prior):
            raise ValueError("Freezing changed source topology.")
        error = max((a - b).length for a, b in zip(after, prior))
        extent = max((p - prior[0]).length for p in prior)
        if error > max(1e-7, extent * 2e-5):
            raise ValueError("Static freeze changed the visible mesh: " + str(error))
        errors.append({"source": original.name, "maximum_world_error": error})
    retained = {target, *meshes}
    for obj in list(bpy.context.scene.objects):
        if obj not in retained:
            bpy.data.objects.remove(obj, do_unlink=True)
    target.name = "DSR_Rig"
    for name, obj in zip(config["mesh_objects"], meshes):
        obj.name = name
    write_json(work / "reports/static.json", {"policy": "current_visible",
        "source_morphs": morphs, "mesh_errors": errors,
        "constraints_removed_from_copy": True, "source_snapshots_preserved": True,
        "shape_keys_baked_to_static_mesh": True, "physics_simulated": False})
