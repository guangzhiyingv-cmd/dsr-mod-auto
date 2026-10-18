"""Build and validate one character package with optional matched/Head correction."""

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
    from skeleton_math import read_pose, validate_offsets
    matched = root / "matched_bind/imported.xml"
    hybrid = next((root / "addon/matched/readback").glob("*.xml"))
    profile = json.loads((root / "head/compensation.json").read_text())
    offsets = {name: profile["visual_delta_native_xyz"] for name in profile["head_subtree"]}
    result = validate_offsets(*read_pose(matched), *read_pose(hybrid), offsets)
    raw = next((root / "addon/matched/readback").glob("*.res"))
    if sha256(raw) != profile["ant_payload_to_preserve_sha256"]:
        raise ValueError("Hybrid ANT defaults differ from matched.")
    result["ant_matches_matched_exactly"] = True
    return result


def verify(report):
    for path, expected in report["artifacts"].items():
        if not Path(path).is_file() or sha256(path) != expected:
            raise ValueError("Skeleton/merged artifact changed: " + path)
    if not report.get("passed"):
        raise ValueError("Skeleton correction did not validate.")
    return {"passed": True, "mode": "matched_head_visual_offset",
            "applied": report["applied"], "single_package": True,
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
        report = {"enabled": True, "applied": False, "passed": True, "single_package": True,
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
    matched_ebx = next((root / "matched_readback").glob("*.ebx"))
    # The imported XML and extracted raw EBX refer to the same matched payload.
    python("ant_bank", "--bank", config["skeleton_globals_bank"], "--skeleton-xml", config["skeleton_xml"], "--out", root / "audit")
    python("prepare_head", "--audit", root / "audit/audit.json", "--trial", root / "matched/trial.json",
           "--matched-xml", root / "matched_bind/imported.xml", "--out", root / "head")
    head = json.loads((root / "head/compensation.json").read_text())
    if any(abs(x) > 1e-10 for x in head["visual_delta_native_xyz"]):
        cli("head_bind", "import-skeleton-translations", SKELETON, root / "head/translations.tsv",
            "--baseline-ebx", matched_ebx, "--skeleton-mode", "visual-offset", "--mod-name", "head",
            "--out", root / "head_bind")
        bind_mod = root / "head_bind/head_visual_offset.fbmod"
    for name in ("package_skeleton", "merge_character"):
        run("compile_" + name, [config["skeleton_compiler"], "/nologo", "/target:exe",
            "/out:" + str(root / (name + ".exe")), core / (name + ".cs")])
    run("package", [root / "package_skeleton.exe", Path(config["skeleton_cli"]).parent, config["game"],
        config["skeleton_globals_bank"], root / "matched/patched_globals.res", bind_mod, root / "addon",
        "skeleton_internal", "Matched skeleton with Head compensation", "Intermediate skeleton payload for a single character package."])
    checks = validate_payload(config, root)
    run("merge", [root / "merge_character.exe", Path(config["skeleton_cli"]).parent, config["game"],
        body["path"], root / "addon/matched/skeleton_internal.fbmod", root / "combined", config["name"],
        config["name"] + " - Character with matched skeleton and Head compensation"])
    final = root / "combined" / (config["name"] + ".fbmod")
    artifacts = {str(path): sha256(path) for folder in (root / "combined/readback", root / "addon/matched/readback")
                 for path in folder.iterdir() if path.is_file()}
    artifacts[str(final)] = sha256(final)
    # Include numerical-validation inputs, generated profiles and all implementation sources.
    for path in [root / "matched_bind/imported.xml", root / "head/compensation.json", root / "matched/trial.json"]:
        artifacts[str(path)] = sha256(path)
    report = {"enabled": True, "applied": True, "passed": True, "single_package": True,
              "package": {"path": str(final), "sha256": sha256(final), "bytes": final.stat().st_size},
              "body_package": body, "checks": checks, "commands": commands,
              "dependencies": dependencies(config), "source_sha256": {str(p): sha256(p) for p in core.iterdir() if p.is_file()},
              "artifacts": artifacts, "validation": str(root / "validation.json"),
              "runtime_tested": False, "installed": False}
    write_json(root / "validation.json", report)
    return report
