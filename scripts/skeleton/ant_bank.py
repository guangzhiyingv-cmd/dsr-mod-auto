"""Audit static ANT rig defaults against native EBX reference transforms.

This reader does not decode animation clips or claim runtime field ownership.
It supports only the checked little-endian GD.REF2/GD.DAT2 layouts and tagged
self-relative references used by the inspected DSR bank.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import struct
import uuid
import xml.etree.ElementTree as ET


class FormatError(ValueError):
    """Reject unsupported or inconsistent binary evidence."""


@dataclass
class Field:
    name: str
    type_hash: int
    element_size: int
    offset: int
    flags: int


@dataclass
class Layout:
    name: str
    type_hash: int
    size: int
    fields: list[Field]

    def field(self, name):
        matches = [field for field in self.fields if field.name == name]
        if len(matches) != 1:
            raise FormatError(f"Expected exactly one {self.name}.{name}")
        return matches[0]


@dataclass
class Object:
    layout: Layout
    base: int
    header: int
    end: int
    name: str
    key: int


class Bank:
    def __init__(self, data):
        self.data = data
        self.layouts = {}
        self.objects = []
        start = data.find(b"GD.REF2")
        if start < 0:
            raise FormatError("No GD.REF2 section")
        self.ref2_start = start
        count = self.unpack("I", start + 12)[0]
        if not 0 < count < 200000:
            raise FormatError("Invalid class count")
        self.check(start + 16, count * 8)
        for index in range(count):
            pointer = start + 16 + index * 8 + 4
            layout = self.read_layout(pointer + self.unpack("i", pointer)[0])
            if layout.type_hash in self.layouts:
                raise FormatError("Duplicate class hash")
            self.layouts[layout.type_hash] = layout
        position = 0
        while (position := data.find(b"GD.DAT2", position)) >= 0:
            section = position
            position += 1
            length = self.unpack("I", section + 8)[0]
            self.check(section, length)
            if length < 44:
                raise FormatError("Short GD.DAT2 section")
            self.objects.append(self.read_object(section + 12, section + length))

    def check(self, position, size, limit=None):
        end = len(self.data) if limit is None else min(limit, len(self.data))
        if position < 0 or size < 0 or position + size > end:
            raise FormatError(f"Out-of-bounds range: {position:#x} + {size}")

    def unpack(self, fmt, position):
        self.check(position, struct.calcsize("<" + fmt))
        return struct.unpack_from("<" + fmt, self.data, position)

    def string(self, position, end=None):
        self.check(position, 1, end)
        stop = self.data.find(b"\0", position, end)
        if stop < 0:
            raise FormatError("Unterminated string")
        return self.data[position:stop].decode("ascii")

    def read_layout(self, start, limit=None):
        self.check(start, 32, limit)
        first, last, size, alignment, strings, string_size = self.unpack("iiIIII", start)
        count = last - first + 1
        if not 0 <= count < 200000 or alignment == 0:
            raise FormatError("Invalid layout header")
        self.check(start + 32, count * 32, limit)
        string_start = start + strings
        self.check(string_start, string_size, limit)
        name = self.string(string_start + 1, string_start + string_size)
        fields = []
        for index in range(count):
            pos = start + 32 + index * 32
            kind, element_size, offset, name_offset, _, flags = self.unpack("IIIIHH", pos)
            field_name = self.string(string_start + name_offset, string_start + string_size)
            fields.append(Field(field_name, kind, element_size, offset, flags))
        return Layout(name, self.unpack("I", start + 28)[0], size, fields)

    def descriptor(self, position, stride, end=None):
        self.check(position, 16, end)
        count, capacity, relative, flags = self.unpack("IIiI", position)
        if count > capacity:
            raise FormatError("Array count exceeds capacity")
        if count == 0:
            return 0, None
        if flags != 0x10000000:
            raise FormatError(f"Unsupported nonempty descriptor tag: {flags:#x}")
        target = position + 8 + relative
        self.check(target, count * stride, end)
        return count, target

    def read_object(self, header, end):
        self.check(header, 32, end)
        if self.unpack("I", header)[0] != 0x030E6205:
            raise FormatError("Invalid object header")
        kind, _, _, relative = self.unpack("IIII", header + 16)
        if kind not in self.layouts:
            raise FormatError(f"Unknown object class: {kind:#x}")
        layout = self.layouts[kind]
        base = header + relative
        self.check(base, layout.size, end)
        name_position = base + layout.field("__name").offset
        count, target = self.descriptor(name_position, 1, end)
        name = self.string(target, target + count) if count else ""
        return Object(layout, base, header, end, name, self.unpack("Q", base)[0])

    def embedded(self, owner, field_name):
        position = owner.base + owner.layout.field(field_name).offset
        relative, tag = self.unpack("iI", position)
        if tag != 0x10000000:
            raise FormatError(f"Unsupported DataRef tag: {tag:#x}")
        header = position + relative
        if header < owner.header:
            raise FormatError("Embedded reference leaves owning object")
        return self.read_object(header, owner.end)

    def array(self, obj, field_name, fmt, stride=None):
        field = obj.layout.field(field_name)
        stride = stride or struct.calcsize("<" + fmt)
        count, target = self.descriptor(obj.base + field.offset, stride, obj.end)
        if count and target < obj.header:
            raise FormatError("Array leaves owning object")
        return [self.unpack(fmt, target + index * stride) for index in range(count)], target

    def scalar(self, obj, name, fmt="Q"):
        return self.unpack(fmt, obj.base + obj.layout.field(name).offset)[0]

    def by_name(self, name, class_name):
        objects = [obj for obj in self.objects if obj.name == name and obj.layout.name == class_name]
        if len(objects) != 1:
            raise FormatError(f"Expected one {class_name} named {name}, found {len(objects)}")
        return objects[0]

    def by_key(self, key, class_name):
        allowed = (class_name,) if isinstance(class_name, str) else class_name
        objects = [obj for obj in self.objects if obj.key == key and obj.layout.name in allowed]
        if len(objects) != 1:
            raise FormatError(f"Expected one {class_name} with key {key:016X}")
        return objects[0]


def unique_mapping(pairs, label):
    result = {}
    for key, value in pairs:
        if key in result:
            raise FormatError(f"Duplicate {label}: {key!r}")
        result[key] = value
    return result


def rig_names(bank, rig):
    keys, _ = bank.array(rig, "DofSets", "Q")
    indices, _ = bank.array(rig, "DofSetIdIndices", "I")
    ids, _ = bank.array(rig, "DofIds", "I")
    if len(keys) != len(indices) or not indices or indices[0] != (0,):
        raise FormatError("Invalid DOF set index table")
    pairs, sets = [], []
    for index, (key,) in enumerate(keys):
        obj = bank.by_key(key, ("DofSetAsset", "PA2DofSetLayoutAsset"))
        field = obj.layout.field("LayoutBytes")
        count, target = bank.descriptor(obj.base + field.offset, 1, obj.end)
        layout = bank.read_layout(target, target + count)
        start = indices[index][0]
        end = indices[index + 1][0] if index + 1 < len(indices) else len(ids)
        if end - start != len(layout.fields) or not 0 <= start <= end <= len(ids):
            raise FormatError(f"DOF set cardinality mismatch: {obj.name}")
        for dof, field in zip(ids[start:end], layout.fields):
            pairs.append((dof[0], field.name))
        sets.append({"name": obj.name, "class": obj.layout.name, "key": f"{key:016X}",
                     "start": start, "count": end - start})
    return unique_mapping(pairs, "DOF id"), sets


def read_native(path):
    root = ET.parse(path).getroot()
    skeletons = [child for child in root if child.tag == "SkeletonAsset"]
    if len(skeletons) != 1:
        raise FormatError("Expected one EBX SkeletonAsset")
    skeleton = skeletons[0]
    names = [item.text for item in skeleton.find("BoneNames")]
    parents = [int(item.text, 0) for item in skeleton.find("Hierarchy")]
    parents = [value - 0x100000000 if value >= 0x80000000 else value for value in parents]
    local = list(skeleton.find("LocalPose"))
    if len(names) != len(parents) or len(names) != len(local):
        raise FormatError("Native skeleton cardinality mismatch")
    result = []
    for name, parent, pose in zip(names, parents, local):
        transform = next(iter(pose))
        translation = [float(transform.findtext(f"trans/Vec3/{axis}")) for axis in "xyz"]
        rotation = [[float(transform.findtext(f"{row}/Vec3/{axis}")) for axis in "xyz"] for row in ("right", "up", "forward")]
        if parent < -1 or parent >= len(names):
            raise FormatError("Native parent index out of range")
        result.append({"name": name, "parent": names[parent] if parent >= 0 else None,
                       "translation": translation, "rotation_rows": rotation})
    return unique_mapping(((bone["name"], bone) for bone in result), "native bone name")


def quaternion_rows(values):
    x, y, z, w = values
    norm = math.sqrt(sum(component * component for component in values))
    if not math.isfinite(norm) or norm < 1e-8:
        raise FormatError("Invalid quaternion")
    x, y, z, w = (component / norm for component in values)
    return [[1 - 2*(y*y + z*z), 2*(x*y + z*w), 2*(x*z - y*w)],
            [2*(x*y - z*w), 1 - 2*(x*x + z*z), 2*(y*z + x*w)],
            [2*(x*z + y*w), 2*(y*z - x*w), 1 - 2*(x*x + y*y)]]


def trace_player_actor(globals_bank, actor_bank, character_xml):
    character = ET.parse(character_xml).getroot()
    entity = character.find("AntAnimatableEntityData")
    if entity is None:
        raise FormatError("No AntAnimatableEntityData in character blueprint")
    actor_guid = entity.findtext("Animatable/AntAnimatableData/Actor/AntRef/AssetGuid")
    actor_key = int.from_bytes(uuid.UUID(actor_guid).bytes_le[:8], "little")
    actor = actor_bank.by_key(actor_key, "ActorAsset")
    animatable = globals_bank.by_key(actor_bank.scalar(actor, "AnimatableAsset"), "AnimatableAsset")
    config = actor_bank.by_key(actor_bank.scalar(actor, "ConfigAsset"), "AnimatableConfigAsset")
    collections = [(globals_bank, globals_bank.by_key(globals_bank.scalar(animatable, "FeatureCollection"), "FeatureCollectionAsset")),
                   (actor_bank, actor_bank.by_key(actor_bank.scalar(config, "FeatureCollection"), "FeatureCollectionAsset"))]
    rig_paths = []
    for bank, collection in collections:
        keys, _ = bank.array(collection, "FeatureAssets", "Q")
        for (key,) in keys:
            matches = [obj for obj in bank.objects if obj.key == key]
            if len(matches) != 1:
                raise FormatError("Unresolved or ambiguous actor feature")
            feature = matches[0]
            if feature.layout.name == "PrimaryRigFeatureAsset":
                rig = globals_bank.by_key(bank.scalar(feature, "Rig"), "RigAsset")
                rig_paths.append({"collection": collection.name, "feature_key": f"{feature.key:016X}",
                                  "rig": rig.name, "rig_key": f"{rig.key:016X}"})
    if not rig_paths:
        raise FormatError("No primary rig reference")
    return {"ebx_actor_guid": actor_guid, "actor": actor.name, "actor_key": f"{actor.key:016X}",
            "animatable": animatable.name, "animatable_key": f"{animatable.key:016X}",
            "config_key": f"{config.key:016X}", "primary_rig_paths": rig_paths,
            "config_default_pose_key": f"{actor_bank.scalar(config, 'DefaultPose'):016X}",
            "evidence_status": "serialized_references_not_live_execution"}


def audit(bank, native, rig_name):
    rig = bank.by_name(rig_name, "RigAsset")
    skel = bank.by_key(bank.scalar(rig, "SkeletonAsset"), "AntSkeletonAsset")
    joints, joint_target = bank.array(skel, "Joints", "IIiiii")
    name_bytes, names_target = bank.array(skel, "NameTable", "B")
    name_end = names_target + len(name_bytes)
    named_joints = []
    for index, (name_offset, name_hash, parent, child, sibling, kind) in enumerate(joints):
        if not 0 <= name_offset < len(name_bytes) or not -1 <= parent < len(joints):
            raise FormatError("Invalid joint name or parent")
        name = bank.string(names_target + name_offset, name_end)
        named_joints.append({"name": name, "index": index, "parent_index": parent,
                             "name_hash": f"{name_hash:08X}", "type": kind,
                             "record_offset": joint_target + index * 24})
    ant_names = unique_mapping(((joint["name"], joint) for joint in named_joints), "ANT joint name")
    mapping, sets = rig_names(bank, rig)
    pose = bank.embedded(rig, "DefaultPoseAsset")
    if pose.layout.name != "DefaultPoseAsset":
        raise FormatError("Unexpected embedded default pose type")
    defaults, arrays = [], []
    for prefix, fmt, stride in (("Int", "i", 4), ("Float", "f", 4),
                                ("Vector3", "fff", 16), ("Vector4", "ffff", 16)):
        values, target = bank.array(pose, prefix + "Values", fmt, stride)
        ids, _ = bank.array(pose, prefix + "DofIds", "I")
        if len(values) != len(ids):
            raise FormatError(f"{prefix} default value/id mismatch")
        arrays.append({"kind": prefix, "count": len(values), "target": target, "stride": stride})
        for index, (value, (dof,)) in enumerate(zip(values, ids)):
            if not all(math.isfinite(component) for component in value):
                raise FormatError("Non-finite default pose value")
            defaults.append({"id": dof, "name": mapping.get(dof), "kind": prefix,
                             "value": list(value), "offset": target + index * stride})
    unique_mapping(((row["id"], row) for row in defaults), "default DOF id")
    named_defaults = unique_mapping(((row["name"], row) for row in defaults if row["name"]), "default DOF name")
    comparison = []
    for name, bone in native.items():
        ant = ant_names.get(name)
        parent = None if ant is None or ant["parent_index"] < 0 else named_joints[ant["parent_index"]]["name"]
        translation, rotation, scale = (named_defaults.get(name + suffix) for suffix in (".t", ".q", ".s"))
        row = {"name": name, "native_parent": bone["parent"], "ant_parent": parent,
               "parent_matches": bool(ant) and parent == bone["parent"],
               "native_translation": bone["translation"],
               "default_translation": translation["value"] if translation else None,
               "translation_offset": translation["offset"] if translation else None,
               "default_rotation": rotation["value"] if rotation else None,
               "rotation_offset": rotation["offset"] if rotation else None,
               "default_scale": scale["value"] if scale else None}
        if translation:
            if translation["kind"] != "Vector3":
                raise FormatError("Translation default is not Vector3")
            row["translation_error"] = max(abs(a-b) for a,b in zip(bone["translation"], translation["value"]))
        if rotation:
            if rotation["kind"] != "Vector4":
                raise FormatError("Rotation default is not Vector4")
            matrix = quaternion_rows(rotation["value"])
            row["rotation_matrix_error"] = max(abs(a-b) for expected, actual in zip(bone["rotation_rows"], matrix) for a,b in zip(expected, actual))
        comparison.append(row)
    translation_errors = [row["translation_error"] for row in comparison if "translation_error" in row]
    rotation_errors = [row["rotation_matrix_error"] for row in comparison if "rotation_matrix_error" in row]
    return {
        "evidence_status": "static_resource_audit_not_runtime_validation",
        "rig": {"name": rig.name, "key": f"{rig.key:016X}", "base": rig.base},
        "animation_skeleton": {"name": skel.name, "key": f"{skel.key:016X}", "base": skel.base},
        "default_pose": {"header": pose.header, "base": pose.base, "end": pose.end,
                         "class": pose.layout.name, "arrays": arrays},
        "counts": {"native_bones": len(native), "ant_joints": len(joints), "rig_dof_ids": len(mapping),
                   "default_values": len(defaults), "unresolved_default_ids": sum(row["name"] is None for row in defaults),
                   "matching_parents": sum(row["parent_matches"] for row in comparison),
                   "translation_compared": len(translation_errors), "rotation_compared": len(rotation_errors)},
        "ant_only_names": sorted(ant_names.keys() - native.keys()),
        "native_only_names": sorted(native.keys() - ant_names.keys()),
        "max_translation_error": max(translation_errors, default=None),
        "max_rotation_matrix_error": max(rotation_errors, default=None),
        "matching_local_translations_at_1e_5": sum(value <= 1e-5 for value in translation_errors),
        "matching_local_rotations_at_1e_5": sum(value <= 1e-5 for value in rotation_errors),
        "dof_sets": sets, "joints": named_joints, "defaults": defaults, "comparison": comparison,
        "limitations": ["No animation clip decoding used", "No live pose buffers inspected",
                        "Default-value presence does not prove runtime consumption or override rules"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--skeleton-xml", type=Path, required=True)
    parser.add_argument("--rig", default="Player_Rig")
    parser.add_argument("--actor-bank", type=Path)
    parser.add_argument("--character-xml", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise FormatError("Output directory must be new or empty")
    bank = Bank(args.bank.read_bytes())
    report = audit(bank, read_native(args.skeleton_xml), args.rig)
    inputs = [args.bank, args.skeleton_xml, Path(__file__)]
    if bool(args.actor_bank) != bool(args.character_xml):
        raise FormatError("Actor tracing needs both --actor-bank and --character-xml")
    if args.actor_bank:
        report["actor_trace"] = trace_player_actor(bank, Bank(args.actor_bank.read_bytes()), args.character_xml)
        if any(path["rig_key"] != report["rig"]["key"] for path in report["actor_trace"]["primary_rig_paths"]):
            raise FormatError("Actor selects another rig")
        inputs.extend([args.actor_bank, args.character_xml])
    report["inputs"] = [{"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                        for path in inputs]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "audit.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    with (args.out / "native_comparison.tsv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["name", "native_parent", "ant_parent", "parent_matches", "translation_error",
                  "rotation_matrix_error", "translation_offset", "rotation_offset"]
        writer = csv.DictWriter(stream, fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["comparison"])
    print(json.dumps({key: report[key] for key in ("counts", "ant_only_names", "native_only_names",
                                                  "max_translation_error", "max_rotation_matrix_error")}, indent=2))


if __name__ == "__main__":
    main()
