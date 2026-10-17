"""Reusable atlas, skin cleanup, and partition stages derived from the verified workflow."""

import argparse
from collections import defaultdict
import hashlib
import importlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import addon_utils
import bpy
from mathutils import Matrix, Vector


WORK = None
ADDON = "material-combiner-addon-master"
MMD_PRESET = None
TARGET_PRESET = None
SKELETON_XML = None
PARTS = {}
ATLAS_SIZE = 8192
TRANSPARENT_POLICY = "remove_zero_opacity"
SOURCE_MESH_PARTS = {}


def write_report(name, data):
    path = WORK / "reports" / (name + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def save_stage(name):
    path = WORK / "stages" / (name + ".blend")
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    print("SAVED_STAGE " + str(path))


def get_character():
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(meshes) != 1:
        raise ValueError("This stage requires exactly one character mesh.")
    mesh = meshes[0]
    rig = next(mod.object for mod in mesh.modifiers if mod.type == "ARMATURE")
    return mesh, rig


def merge_character_meshes():
    """Join the configured character meshes into one before atlas preparation."""
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise ValueError("No character mesh is present.")
    names = [obj.name for obj in meshes]
    for index, obj in enumerate(meshes):
        attribute = obj.data.attributes.new("source_mesh_id", "INT", "FACE")
        for item in attribute.data:
            item.value = index
    if len(meshes) == 1:
        meshes[0]["dsr_source_mesh_names"] = json.dumps(names)
        return meshes[0]
    for obj in meshes:
        if obj.mode != "OBJECT":
            raise ValueError("Objects must be in object mode before merging.")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.hide_viewport = False
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    joined["dsr_source_mesh_names"] = json.dumps(names)
    joined.name = "CharacterMesh"
    return joined


def material_opacity(material):
    """Read the material's opacity from an MMD shader group or a Principled node."""
    shader = material.node_tree.nodes.get("mmd_shader")
    if shader is not None and "Alpha" in shader.inputs:
        return float(shader.inputs["Alpha"].default_value)
    principled = next((node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
    if principled is not None and "Alpha" in principled.inputs:
        return float(principled.inputs["Alpha"].default_value)
    return 1.0


def material_base_image(material):
    """Return the material's base-color image for either MMD or generic node setups."""
    node = material.node_tree.nodes.get("mmd_base_tex")
    if node is None:
        node = next((item for item in material.node_tree.nodes if item.type == "TEX_IMAGE" and item.image), None)
    return node.image if node is not None else None


def extract_faces(source, face_indices, name):
    """Copy complete faces with exact coordinates, UVs, normals, and weights."""
    data = source.data
    faces = [data.polygons[index] for index in face_indices]
    used = sorted({index for face in faces for index in face.vertices})
    remap = {old: index for index, old in enumerate(used)}
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata([data.vertices[index].co for index in used], [],
                     [[remap[index] for index in face.vertices] for face in faces])
    obj = source.copy()
    obj.data = mesh
    obj.name = name
    bpy.context.scene.collection.objects.link(obj)
    for group in source.vertex_groups:
        obj.vertex_groups.new(name=group.name)
    for material in data.materials:
        mesh.materials.append(material)
    for face, original in zip(mesh.polygons, faces):
        face.material_index = original.material_index
        face.use_smooth = original.use_smooth
    old_loops = [index for face in faces for index in face.loop_indices]
    for layer in data.uv_layers:
        target = mesh.uv_layers.new(name=layer.name)
        for point, index in zip(target.data, old_loops):
            point.uv = layer.data[index].uv
    mesh.uv_layers.active_index = data.uv_layers.active_index
    for attr in data.attributes:
        if attr.name.startswith("source_") and attr.data_type == "INT":
            target = mesh.attributes.new(attr.name, "INT", attr.domain)
            indices = used if attr.domain == "POINT" else face_indices
            for point, index in zip(target.data, indices):
                point.value = attr.data[index].value
    for index, old_index in enumerate(used):
        for group in data.vertices[old_index].groups:
            obj.vertex_groups[group.group].add([index], group.weight, "REPLACE")
    mesh.update()
    mesh.normals_split_custom_set([data.corner_normals[index].vector for index in old_loops])
    return obj


def atlas_material(material, textures):
    """Provide the add-on's material assignment for Blender 5.2's material API."""
    material.use_nodes = True
    material.use_backface_culling = True
    material.surface_render_method = "DITHERED"
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Roughness"].default_value = .8
    texture = tree.nodes.new("ShaderNodeTexImage")
    texture.image = textures["albedo"].image
    tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    tree.links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])
    tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])


def make_atlas():
    mesh = merge_character_meshes()
    if mesh.data.shape_keys:
        raise ValueError("Shape-key copying needs an explicit policy before this workflow can run.")
    source_faces = mesh.data.attributes.new("source_face_id", "INT", "FACE")
    source_verts = mesh.data.attributes.new("source_vertex_id", "INT", "POINT")
    source_mats = mesh.data.attributes.new("source_material_index", "INT", "FACE")
    for index, item in enumerate(source_faces.data):
        item.value = index
    for index, item in enumerate(source_verts.data):
        item.value = index
    for face, item in zip(mesh.data.polygons, source_mats.data):
        item.value = face.material_index
    alpha = {}
    material_table = []
    for index, material in enumerate(mesh.data.materials):
        opacity = material_opacity(material)
        alpha[material.name] = opacity
        image = material_base_image(material)
        material_table.append({"index": index, "name": material.name, "opacity": opacity,
                               "image": image.name if image else None})
    keep = [face.index for face in mesh.data.polygons if TRANSPARENT_POLICY == "keep" or alpha[mesh.data.materials[face.material_index].name] > 1e-6]
    removed = sorted(set(range(len(mesh.data.polygons))) - set(keep))
    filtered = extract_faces(mesh, keep, "DSR_Atlas_Mesh")
    bpy.data.objects.remove(mesh, do_unlink=True)
    mesh = filtered
    if "UVMap" not in mesh.data.uv_layers:
        raise ValueError("Provide the intended texture UV layer as UVMap.")
    mesh.data.uv_layers.active_index = mesh.data.uv_layers.find("UVMap")
    addon_utils.enable(ADDON, default_set=False)
    ops = importlib.import_module(ADDON + ".operators.combiner.combiner_ops")
    materials = importlib.import_module(ADDON + ".utils.materials")
    original_diffuse = materials.get_diffuse

    def exact_opacity(material):
        color = original_diffuse(material)
        return (*color[:3], round(alpha.get(material.name, 1.0) * 255))

    materials.get_diffuse = exact_opacity
    ops.get_diffuse = exact_opacity
    ops._configure_material_multi = atlas_material

    def paste_with_repeat_padding(scene, item, material, image_or_color, atlas, margin):
        image = ops._get_gfx(scene, material, item, image_or_color)
        x = int(item["gfx"]["fit"]["x"] + margin)
        y = int(item["gfx"]["fit"]["y"] + margin)
        width, height = image.size
        atlas.paste(image, (x, y))
        if margin:
            for dx, sx in ((-margin, width-margin), (width, 0)):
                atlas.paste(image.crop((sx, 0, sx+margin, height)), (x+dx, y))
            for dy, sy in ((-margin, height-margin), (height, 0)):
                atlas.paste(image.crop((0, sy, width, sy+margin)), (x, y+dy))
                for dx, sx in ((-margin, width-margin), (width, 0)):
                    atlas.paste(image.crop((sx, sy, sx+margin, sy+margin)), (x+dx, y+dy))

    ops._paste_gfx = paste_with_repeat_padding
    for material in mesh.data.materials:
        material.smc_diffuse = True
    scene = bpy.context.scene
    scene.smc_size = "PO2"
    scene.smc_size_width = ATLAS_SIZE
    scene.smc_size_height = ATLAS_SIZE
    scene.smc_packer_type = "MAX_RECTS"
    scene.smc_gaps = 16
    scene.smc_pixel_art = True
    scene.smc_crop = False
    scene.smc_include_extra_textures = False
    scene.smc_ob_data.clear()
    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = mesh
    directory = WORK / "textures"
    directory.mkdir(parents=True, exist_ok=True)
    result = bpy.ops.smc.combiner(directory=str(directory))
    if result != {"FINISHED"} or len(mesh.data.materials) != 1:
        raise ValueError("Material Combiner did not produce one material.")
    material = mesh.data.materials[0]
    material.name = "DSR_Atlas"
    image = next(node.image for node in material.node_tree.nodes if node.type == "TEX_IMAGE")
    if tuple(image.size) != (ATLAS_SIZE, ATLAS_SIZE):
        raise ValueError("Unexpected atlas size.")
    atlas_path = directory / "character_atlas.png"
    generated_path = Path(bpy.path.abspath(image.filepath))
    if generated_path.resolve() != atlas_path.resolve():
        import shutil
        shutil.copy2(generated_path, atlas_path)
    image.filepath = str(atlas_path)
    image.name = "DSR_Atlas"
    image.pack()
    mesh.data.uv_layers["UVMap"].name = "UVChannel0"
    keep_uv = {"UVChannel0"}
    dropped_uv = [layer.name for layer in list(mesh.data.uv_layers) if layer.name not in keep_uv]
    for name in dropped_uv:
        mesh.data.uv_layers.remove(mesh.data.uv_layers[name])
    channel = mesh.data.uv_layers.new(name="UVChannel1")
    for point in channel.data:
        point.uv = (0.0, 0.0)
    mesh.data.uv_layers.active_index = mesh.data.uv_layers.find("UVChannel0")
    write_report("01_atlas", {"source_materials": material_table, "removed_transparent_face_ids": removed,
                               "remaining_vertices": len(mesh.data.vertices), "remaining_faces": len(mesh.data.polygons),
                               "dropped_uv_layers": dropped_uv,
                               "atlas": str(atlas_path), "sha256": hashlib.sha256(atlas_path.read_bytes()).hexdigest(),
                               "size": list(image.size), "addon_version": list(importlib.import_module(ADDON).bl_info["version"]),
                               "settings": {"size": "PO2", "dimensions": [ATLAS_SIZE,ATLAS_SIZE], "packer": "MAX_RECTS", "gaps": 16, "pixel_art_uv_margin": True, "texture_filter": "Linear", "crop": False, "extra_maps": False},
                               "compatibility_adapters": ["Blender 5.2 material API", "Explicit MMD opacity without gamma conversion", "Repeat-wrapped 8-pixel gutters; no UV inset"],
                               "uv_policy": "UVChannel0 carries the atlas coordinates; UVChannel1 is a zeroed copy so the second channel samples one texel."})
    save_stage("01_atlas")


def bone_plan(rig):
    source = json.loads(MMD_PRESET.read_text(encoding="utf-8"))["mappings"]
    target = json.loads(TARGET_PRESET.read_text(encoding="utf-8"))["mappings"]
    retained = {}
    keys = {}
    for key, entry in target.items():
        if key not in source:
            continue
        name = next((candidate for candidate in source[key]["main"] if candidate in rig.data.bones), None)
        if name:
            retained[name] = entry["main"][0]
            keys[key] = name
    aliases = {}
    for key, name in keys.items():
        if key.startswith(("thigh_", "shin_", "foot_", "toe_")):
            for alias in source[key].get("aux", []):
                if alias in rig.data.bones and alias not in retained:
                    aliases[alias] = name
    destinations = {}
    for bone in rig.data.bones:
        current = bone
        while current and current.name not in retained and current.name not in aliases:
            current = current.parent
        destination = retained[current.name] if current and current.name in retained else retained[aliases[current.name]] if current else None
        destinations[bone.name] = {"destination": destination, "rule": "retained" if bone.name in retained else "equivalent_leg_chain" if current and current.name in aliases else "nearest_retained_parent" if current else "unweighted_control_root"}
    if not retained or len(set(retained.values())) != len(retained):
        raise ValueError("Bone mapping is empty or assigns duplicate target names.")
    return retained, destinations


def world_vertices(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return [obj.matrix_world @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def clean_rig():
    mesh, rig = get_character()
    if any(bone.constraints for bone in rig.pose.bones):
        raise ValueError("Unexpected pose constraints; freeze them before removing controls.")
    retained, destinations = bone_plan(rig)
    original_matrices = {name: rig.data.bones[name].matrix_local.copy() for name in retained}
    before = world_vertices(mesh)
    merged = []
    per_vertex = []
    max_sum_error = 0.
    for vertex in mesh.data.vertices:
        weights = defaultdict(float)
        total = 0.
        for group in vertex.groups:
            name = mesh.vertex_groups[group.group].name
            if name not in destinations:
                if name not in ("mmd_edge_scale", "mmd_vertex_order") and group.weight > 1e-8:
                    raise ValueError("Unknown weighted vertex group: " + name)
                continue
            destination = destinations[name]["destination"]
            if group.weight > 1e-8 and not destination:
                raise ValueError("Weighted bone has no retained destination: " + name)
            if destination:
                weights[destination] += group.weight
                total += group.weight
        if total < 1e-8:
            raise ValueError("Unweighted source vertex.")
        max_sum_error = max(max_sum_error, abs(total - 1.))
        per_vertex.append({name: weight / total for name, weight in weights.items() if weight > 1e-8})
    mesh.vertex_groups.clear()
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for bone in list(rig.data.edit_bones):
        if bone.name not in retained:
            rig.data.edit_bones.remove(bone)
    for old, new in retained.items():
        rig.data.edit_bones[old].name = new
    xml = ET.parse(SKELETON_XML).getroot().find("SkeletonAsset")
    names = [item.text for item in xml.find("BoneNames")]
    parents = [int(item.text, 0) for item in xml.find("Hierarchy")]
    parent_lookup = {name: names[parent] if parent < len(names) else None for name, parent in zip(names, parents)}
    for bone in rig.data.edit_bones:
        ancestor = parent_lookup.get(bone.name)
        while ancestor and ancestor not in rig.data.edit_bones:
            ancestor = parent_lookup.get(ancestor)
        bone.use_connect = False
        bone.parent = rig.data.edit_bones.get(ancestor) if ancestor else None
        bone.use_deform = True
    bpy.ops.object.mode_set(mode="OBJECT")
    groups = {name: mesh.vertex_groups.new(name=name) for name in retained.values()}
    for index, weights in enumerate(per_vertex):
        for name, weight in weights.items():
            groups[name].add([index], weight, "REPLACE")
    rig.name = "DSR_Rig"
    rig.animation_data_clear()
    bpy.context.view_layer.update()
    after = world_vertices(mesh)
    error = max((a - b).length for a, b in zip(before, after))
    extent = max((point - before[0]).length for point in before)
    world_tolerance = max(1e-8, extent * 1e-6)
    if error > world_tolerance:
        raise ValueError("Rig cleanup changed the visible rest mesh: " + str(error))
    bind_error = max(abs(original_matrices[old][i][j] - rig.data.bones[new].matrix_local[i][j]) for old, new in retained.items() for i in range(4) for j in range(4))
    bind_position_error = max((original_matrices[old].translation - rig.data.bones[new].head_local).length for old, new in retained.items())
    bind_extent = max(matrix.translation.length for matrix in original_matrices.values())
    bind_position_tolerance = max(1e-8, bind_extent * 1e-6)
    if bind_error > 1e-4 or bind_position_error > bind_position_tolerance:
        raise ValueError("Retained bind transform changed beyond float precision: " + str((bind_error, bind_position_error)))
    write_report("02_rig", {"retained_bone_count": len(retained), "removed_bone_count": len(destinations) - len(retained),
                             "rename": retained, "merge_destinations": destinations,
                             "removed_metadata_groups": ["mmd_edge_scale", "mmd_vertex_order"],
                             "maximum_initial_weight_sum_error": max_sum_error, "maximum_visible_rest_mesh_error": error,
                             "world_error_tolerance": world_tolerance, "bind_position_tolerance": bind_position_tolerance,
                             "maximum_bind_matrix_float_error": bind_error, "maximum_bind_position_error": bind_position_error,
                             "eye_policy": "Merge into Head", "leg_policy": "Map ordinary leg-chain aliases to corresponding retained D deform bones before ancestor merging",
                             "hierarchy_policy": "Nearest retained ancestor in the DSR hierarchy; preserve each retained bind matrix"})
    save_stage("02_clean_rig")


def bone_region(name):
    if name == "Hips" or name == "Spine":
        return "core"
    if name.startswith(("Head", "LeftEye", "RightEye")):
        return "head"
    if name.startswith(("Spine", "Neck")):
        return "spine"
    for prefix, side in (("Left", "left"), ("Right", "right")):
        if name.startswith(prefix + "UpLeg"):
            return side + "upleg"
        if name.startswith((prefix + "Leg", prefix + "Foot", prefix + "Toe")):
            return side + "leg"
        if name.startswith((prefix + "ForeArm", prefix + "Hand")):
            return side + "forearm"
        if name.startswith((prefix + "Shoulder", prefix + "Arm")):
            return side + "arm"
    raise ValueError("No part allocation for bone: " + name)


def base_mesh_name(name):
    """Strip the pose-copy suffix so configured mesh names stay matchable."""
    while name.endswith("_DeadSpacePose"):
        name = name[: -len("_DeadSpacePose")]
    return name


def split_parts():
    mesh, rig = get_character()
    names = [base_mesh_name(name) for name in json.loads(mesh.get("dsr_source_mesh_names", "[]"))]
    unknown = set(SOURCE_MESH_PARTS) - set(names)
    if unknown:
        raise ValueError("source_mesh_parts references unknown meshes: " + str(sorted(unknown)))
    forced = {index: SOURCE_MESH_PARTS[name] for index, name in enumerate(names) if name in SOURCE_MESH_PARTS}
    claimed = set(forced.values())
    source_ids = mesh.data.attributes["source_mesh_id"].data
    assignments = defaultdict(list)
    for face in mesh.data.polygons:
        part = forced.get(source_ids[face.index].value)
        if part is None:
            scores = defaultdict(float)
            for index in face.vertices:
                for group in mesh.data.vertices[index].groups:
                    region = bone_region(mesh.vertex_groups[group.group].name)
                    if region not in claimed:
                        scores[region] += group.weight
            if not scores:
                raise ValueError("Face has weights only inside reserved parts: " + str(face.index))
            part = max(scores, key=lambda key: (scores[key], key))
        assignments[part].append(face.index)
    if set(assignments) != set(PARTS):
        raise ValueError("Part allocation is incomplete: " + str(sorted(assignments)))
    collection = bpy.data.collections.new("DSR_Parts")
    bpy.context.scene.collection.children.link(collection)
    report = []
    for part, section in PARTS.items():
        obj = extract_faces(mesh, assignments[part], "DSR_" + part)
        for owner in list(obj.users_collection):
            owner.objects.unlink(obj)
        collection.objects.link(obj)
        obj["dsr_part"] = part
        obj["dsr_node"] = section + ":lod.000"
        obj["dsr_asset"] = "Game/Assets/Characters/Bodies/IsaacSuitLvl1/Parts/Cha_Body_IsaacSuit_Lvl1_" + part + "_Mesh"
        obj.data.calc_loop_triangles()
        report.append({"part": part, "object": obj.name, "section": section, "asset": obj["dsr_asset"],
                       "vertices": len(obj.data.vertices), "polygons": len(obj.data.polygons), "triangles": len(obj.data.loop_triangles),
                       "source_face_ids": [item.value for item in obj.data.attributes["source_face_id"].data]})
    if sum(item["polygons"] for item in report) != len(mesh.data.polygons):
        raise ValueError("Face counts changed during partitioning.")
    bpy.data.objects.remove(mesh, do_unlink=True)
    for obj in bpy.context.scene.objects:
        if obj.type == "ARMATURE" and obj != rig:
            obj.hide_set(True)
            obj.hide_render = True
            obj["dsr_role"] = "User-aligned full game skeleton; preserved for skeleton mod export"
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    write_report("03_parts", {"method": "Whole-face assignment by summed cleaned DSR bone weights; no geometry is cut or moved", "parts": report})
    save_stage("03_parts")

