"""Build and validate one character package with optional matched reference correction."""

import json
from pathlib import Path
import sys

from dsr_common import SKILL, SKELETON, sha256, write_json


def dependencies(config):
    if not config["skeleton_correction"]:
        return None
    result = {}
    for name in ("skeleton_cli", "skeleton_globals_bank", "skeleton_baseline_ebx", "skeleton_compiler"):
        path = Path(config[name])
        if not path.is_file():
            raise FileNotFoundError(name + ": " + str(path))
        result[name] = {"path": str(path), "sha256": sha256(path)}
    return result


def validate_payload(config, root):
    core = SKILL / "scripts/skeleton"
    if str(core) not in sys.path:
        sys.path.insert(0, str(core))
    from skeleton_math import read_pose
    matched = root / "matched_bind/imported.xml"
    actual = next((root / "addon/matched/readback").glob("*.xml"))
    if read_pose(matched) != read_pose(actual):
        raise ValueError("Skeleton differs from matched references; Head compensation is forbidden.")
    expected_ebx = next((root / "matched_readback").glob("*.ebx"))
    actual_ebx = next((root / "addon/matched/readback").glob("*.ebx"))
    if sha256(expected_ebx) != sha256(actual_ebx):
        raise ValueError("Packaged skeleton differs from the matched EBX.")
    raw = next((root / "addon/matched/readback").glob("*.res"))
    if sha256(raw) != sha256(root / "matched/patched_globals.res"):
        raise ValueError("Packaged ANT defaults differ from matched.")
    return {"matched_skeleton_exact": True, "ant_matches_matched_exactly": True,
            "head_visual_offset": False}



def verify(report):
    if report.get("mode", "matched_references") != "matched_references" or report.get("head_visual_offset", False):
        raise ValueError("Fixed Head visual compensation is no longer supported.")
    for path, expected in report["artifacts"].items():
        if not Path(path).is_file() or sha256(path) != expected:
            raise ValueError("Skeleton/merged artifact changed: " + path)
    if not report.get("passed"):
        raise ValueError("Skeleton correction did not validate.")
    return {"passed": True, "mode": "matched_references",
            "applied": report["applied"], "single_package": report.get("single_package", True),
            "runtime_tested": False, "validation": report["validation"]}


def build(config, config_path, body, invoke):
    core = SKILL / "scripts/skeleton"
    work = Path(config["output"])
    root = work / "package/skeleton"
    if root.exists():
        raise FileExistsError("Preserve existing skeleton outputs; use a fresh job.")
    root.mkdir(parents=True)
    commands = []

    def run(name, args):
        commands.append(invoke(args, work / "logs" / ("skeleton_" + name + ".log")))

    def python(name, *args):
        run(name, [sys.executable, core / (name + ".py"), *args])

    def cli(name, *args):
        run(name, [config["skeleton_cli"], "--game", config["game"], *args])

    exports = json.loads((work / "package/exports.json").read_text())
    source = exports["source"]
    if sha256(source) != exports["source_sha256"]:
        raise ValueError("Prepared source changed before skeleton construction.")
    run("inspect", [config["blender"], "--background", "--factory-startup", source,
        "--python-exit-code", "1", "--python", core / "inspect_skeleton.py", "--",
        "--native", config["native_blend"], "--native-rig", config["native_rig_object"],
        "--rig", "DSR_Rig", "--out", root / "inspection.json"])
    write_json(root / "base_identity.json", {"package": body["path"], "sha256": body["sha256"]})
    python("prepare_matched", "--inspection", root / "inspection.json", "--skeleton-xml", config["skeleton_xml"],
           "--bank", config["skeleton_globals_bank"], "--base-release", root / "base_identity.json", "--out", root / "matched")
    trial = json.loads((root / "matched/trial.json").read_text())
    if trial["counts"]["changed_bind_positions"] == 0 and not trial["ant_edits"]:
        report = {"mode": "matched_references", "head_visual_offset": False, "enabled": True, "applied": False, "passed": True, "single_package": True,
                  "reason": "Prepared anchors already match the native reference",
                  "package": body, "commands": commands, "dependencies": dependencies(config),
                  "artifacts": {body["path"]: body["sha256"],
                                str(root / "matched/trial.json"): sha256(root / "matched/trial.json")},
                  "validation": str(root / "validation.json"), "runtime_tested": False, "installed": False}
        write_json(root / "validation.json", report)
        return report
    cli("matched_bind", "import-skeleton-translations", SKELETON, root / "matched/translations.tsv",
        "--baseline-ebx", config["skeleton_baseline_ebx"], "--skeleton-mode", "bind", "--mod-name", "matched",
        "--out", root / "matched_bind")
    bind_mod = root / "matched_bind/matched_bind.fbmod"
    cli("matched_readback", "extract-mod", bind_mod, "--out", root / "matched_readback")
    for name in ("package_skeleton", "merge_character"):
        run("compile_" + name, [config["skeleton_compiler"], "/nologo", "/target:exe",
            "/out:" + str(root / (name + ".exe")), core / (name + ".cs")])
    split = config.get("skeleton_package_mode", "merged") == "split"
    addon_name = config["name"] + "_skeleton" if split else "skeleton_internal"
    addon = root / "addon/matched" / (addon_name + ".fbmod")
    run("package", [root / "package_skeleton.exe", Path(config["skeleton_cli"]).parent, config["game"],
        config["skeleton_globals_bank"], root / "matched/patched_globals.res", bind_mod, root / "addon",
        addon_name, config["name"] + " - Skeleton correction",
        "Matched skeleton references without fixed Head visual compensation. Enable with its matching character body package."])
    checks = validate_payload(config, root)
    run("merge", [root / "merge_character.exe", Path(config["skeleton_cli"]).parent, config["game"],
        body["path"], addon, root / "combined", config["name"],
        config["name"] + " - Character with matched skeleton references"])
    final = root / "combined" / (config["name"] + ".fbmod")
    artifacts = {str(path): sha256(path) for folder in (root / "combined/readback", root / "addon/matched/readback")
                 for path in folder.iterdir() if path.is_file()}
    artifacts[str(final)] = sha256(final)
    artifacts[str(addon)] = sha256(addon)
    artifacts[body["path"]] = body["sha256"]
    # Include numerical-validation inputs, generated profiles and all implementation sources.
    for path in [root / "matched_bind/imported.xml", root / "matched/trial.json"]:
        artifacts[str(path)] = sha256(path)
    report = {"mode": "matched_references", "head_visual_offset": False, "enabled": True, "applied": True, "passed": True,
              "single_package": config.get("skeleton_package_mode", "merged") == "merged",
              "package": {"path": str(final), "sha256": sha256(final), "bytes": final.stat().st_size},
              "skeleton_package": {"path": str(addon), "sha256": sha256(addon), "bytes": addon.stat().st_size},
              "body_package": body, "checks": checks, "commands": commands,
              "dependencies": dependencies(config), "source_sha256": {str(p): sha256(p) for p in core.iterdir() if p.is_file()},
              "artifacts": artifacts, "validation": str(root / "validation.json"),
              "runtime_tested": False, "installed": False}
    write_json(root / "validation.json", report)
    return report
