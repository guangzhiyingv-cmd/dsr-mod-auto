"""Configuration, provenance, and the verified Lv1 target contract."""

import hashlib
import json
from pathlib import Path
import re


SKILL = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = "."
PARTS = ("core", "spine", "head", "leftarm", "rightarm", "leftforearm",
         "rightforearm", "leftupleg", "rightupleg", "leftleg", "rightleg")
LOWER = {"core", "leftupleg", "rightupleg", "leftleg", "rightleg"}
STAGES = ("import", "static", "tpose", "pose", "atlas", "rig", "split", "scale", "hands", "cleanup", "export")
SKELETON = "Game/Anim/Rigging/Player/Player_Skeleton"

# Inspected target contracts. Only these suits may be packaged, and each was
# derived from the game's own resource, section, and composition layout.
# Lv1 section names come from the verified package; Legacy section names and
# removal set come from the inspected reference mod.
SUITS = {
    "isaac_lv1": {
        "mesh_root": "Game/Assets/Characters/Bodies/IsaacSuitLvl1/Parts/Cha_Body_IsaacSuit_Lvl1_",
        "texture_root": "Game/Assets/Characters/Bodies/IsaacSuitLvl1/Textures/T_Cha_Body_IsaacLvl1_",
        "families": ("TopBody", "LowerBody"),
        "composition": "Game/Gameplay/Items/Suit_Level1_VisualItem",
        "removals": (
            "SAPP_Cha_Body_IsaacSuit_Lvl1_LeftHand",
            "SAPP_Cha_Body_IsaacSuit_Lvl1_RightHand",
            "SAPP_Cha_Body_IsaacSuit_Lvl1_LeftFoot",
            "SAPP_Cha_Body_IsaacSuit_Lvl1_RightFoot",
            "SAPP_Cha_Body_IsaacSuit_LvlX_Collar",
        ),
        "sections": {
            "core": "LowerBody", "spine": "TopBody", "head": "TopBody",
            "leftarm": "TopBody", "rightarm": "TopBody", "leftforearm": "TopBody",
            "rightforearm": "TopBody", "leftupleg": "LowerBody", "rightupleg": "LowerBody",
            "leftleg": "LowerBody", "rightleg": "LowerBody",
        },
        "frames": ("Normals", "Tangents", "Binormals"),
    },
    "isaac_legacy": {
        "mesh_root": "Game/Assets/Characters/Bodies/IsaacLegacy/Parts/Cha_Body_IsaacSuitLegacy_",
        "texture_root": "Game/Assets/Characters/Bodies/IsaacLegacy/Textures/T_Cha_IsaacSuitLegacy_",
        "families": ("UpperBody", "LowerBody", "Backpack", "Helmet"),
        "composition": "Game/Gameplay/Items/Suit_Legacy_VisualItem",
        "removals": (
            "SAPP_Cha_Body_IsaacSuitLegacy_LeftHand",
            "SAPP_Cha_Body_IsaacSuitLegacy_RightHand",
            "SAPP_Cha_Body_IsaacSuitLegacy_LeftFoot",
            "SAPP_Cha_Body_IsaacSuitLegacy_RightFoot",
        ),
        "sections": {
            "core": "Backpack", "spine": "Backpack", "head": "UpperBody",
            "leftarm": "UpperBody", "rightarm": "UpperBody", "leftforearm": "UpperBody",
            "rightforearm": "UpperBody", "leftupleg": "LowerBody", "rightupleg": "LowerBody",
            "leftleg": "LowerBody", "rightleg": "LowerBody",
        },
        "frames": ("Normals", "Binormals"),
    },
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def inside(path, parent):
    return Path(path).resolve().is_relative_to(Path(parent).resolve())


def load_config(path):
    path = Path(path).resolve()
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if value.get("schema") != "dsr_mod_job_v1":
        raise ValueError("Only the dsr_mod_job_v1 character target is implemented.")
    targets = value.get("targets") or ([value["target"]] if value.get("target") else ["isaac_lv1"])
    if any(target not in SUITS for target in targets) or len(set(targets)) != len(targets):
        raise ValueError("Unknown or duplicated target suit: " + ", ".join(targets))
    value["targets"] = targets
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value["name"]):
        raise ValueError("Use a simple lowercase mod name without path separators.")
    for key in ("workspace", "input", "output", "release_dir", "blender", "game", "cli",
                "runtime_manifest", "source_preset", "native_blend", "skeleton_xml"):
        item = Path(value[key]).expanduser()
        value[key] = str((path.parent / item).resolve() if not item.is_absolute() else item.resolve())
    if not Path(value["release_dir"]).is_dir():
        raise ValueError("The configured release directory must already exist beside the source model.")
    if inside(value["release_dir"], value["output"]):
        raise ValueError("Release output cannot be inside the working job directory.")
    extension = Path(value["input"]).suffix.lower()
    if extension not in (".blend", ".pmx", ".pmd"):
        raise ValueError("Supported direct inputs are BLEND, PMX, and PMD; import other formats into BLEND first.")
    if inside(value["input"], value["output"]):
        raise ValueError("The original input must stay outside the generated job output.")
    for protected in ("game",):
        if inside(value["output"], value[protected]):
            raise ValueError("Job output cannot be inside the installed game.")
    for protected in ("source", "assets", "docs", "skill", "tests"):
        if inside(value["output"], Path(value["workspace"]) / protected):
            raise ValueError("Keep generated output outside source, assets, docs, skill, and tests.")
    stages = value["stages"]
    if not stages or any(stage not in STAGES for stage in stages):
        raise ValueError("Unknown or empty stage sequence.")
    if stages != sorted(set(stages), key=STAGES.index):
        raise ValueError("Stages must be unique and follow the documented dependency order.")
    if extension != ".blend" and stages[0] != "import":
        raise ValueError("A raw PMX/PMD job must begin with import.")
    if value.get("source_pose", "DSR") not in ("AUTO", "A", "T", "DSR"):
        raise ValueError("Source pose must be AUTO, A, T, or DSR.")
    if "tpose" in stages and "pose" not in stages:
        raise ValueError("T-pose normalization must be followed by DSR pose conversion.")
    if extension != ".blend" and "static" not in stages:
        raise ValueError("Raw model jobs require static preparation after import.")
    if value.get("source_pose", "DSR") == "DSR":
        if any(s in stages for s in ("tpose", "pose")):
            raise ValueError("Already converted DSR input must skip T-pose and DSR conversion.")
    elif not {"tpose", "pose"}.issubset(stages):
        raise ValueError("A/T/AUTO inputs require T-pose normalization before DSR pose conversion.")
    if value.get("transparent_policy") not in ("remove_zero_opacity", "keep"):
        raise ValueError("Choose an explicit transparent-layer policy.")
    if not value.get("mesh_objects") or not value.get("rig_object"):
        raise ValueError("Select the character mesh objects and the actual deform armature.")
    source_parts = value.get("source_mesh_parts", {})
    if not isinstance(source_parts, dict) or any(part not in PARTS for part in source_parts.values()):
        raise ValueError("source_mesh_parts must map configured mesh names to known DSR parts.")
    if len(set(source_parts.values())) != len(source_parts):
        raise ValueError("Each DSR part may be claimed by at most one source mesh.")
    if not 0 < value.get("minimum_elbow_bend_degrees", 0) < 90:
        raise ValueError("Minimum elbow bend must be between zero and ninety degrees.")
    if not 1 <= value.get("maximum_arm_stretch", 0) <= 3:
        raise ValueError("Set an explicit maximum arm extension ratio.")
    return value


def check_runtime(config):
    manifest = json.loads(Path(config["runtime_manifest"]).read_text(encoding="utf-8"))
    files = manifest.get("tools", [])
    root = Path(config["cli"]).parent
    normalized = manifest.get("normalized_plugin_source") or manifest.get("normalize_transformed_ntb")
    if not normalized:
        raise ValueError("A normalized-importer runtime manifest is required; old hand-only runtime is unsuitable.")
    seen = set()
    for entry in files:
        recorded = Path(entry["path"])
        if inside(recorded, root):
            candidate = recorded
        else:
            raise ValueError("Runtime manifest paths do not match the configured CLI directory.")
        if not candidate.is_file() or sha256(candidate) != entry["sha256"]:
            raise ValueError("Runtime checksum mismatch: " + str(candidate))
        seen.add(candidate.relative_to(root).as_posix().lower())
    if not {"dsrcli.exe", "plugins/meshsetplugin.dll"}.issubset(seen):
        raise ValueError("Runtime manifest must cover DsrCli.exe and Plugins/MeshSetPlugin.dll.")
    return {"manifest_sha256": sha256(config["runtime_manifest"]), "checked_files": len(files)}
