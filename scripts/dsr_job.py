"""Create, prepare, package, and read back a local Isaac Lv1 replacement job."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys

from dsr_common import (DEFAULT_WORKSPACE, PARTS, SKELETON, SKILL, STAGES, SUITS,
                        check_runtime, load_config, sha256, write_json)


def initialize(args):
    workspace = Path(args.workspace).resolve()
    config_path = Path(args.config).resolve()
    if config_path.exists():
        raise FileExistsError("Existing job configuration will not be overwritten.")
    source = Path(args.input).resolve()
    raw = source.suffix.lower() in (".pmx", ".pmd")
    source_pose = args.source_pose or ("AUTO" if raw else "DSR")
    stages = list(STAGES)
    if not raw:
        stages.remove("import")
    if source_pose == "DSR":
        stages = [s for s in stages if s not in ("tpose", "pose")]
        if not raw:
            stages.remove("static")
    parts_map = {}
    for item in args.source_mesh_parts:
        name, separator, part = item.partition(":")
        if not separator or not name or not part:
            raise ValueError("--source-mesh-parts items must use the MESH:PART form.")
        parts_map[name] = part

    def environment(value, default):
        return str(Path(value).expanduser().resolve()) if value else str((workspace / default).resolve())

    config = {"schema": "dsr_mod_job_v1", "targets": list(args.targets), "name": args.name,
        "workspace": str(workspace), "input": str(source),
        "output": str((source.parent / (args.name + "_job")).resolve()),
        "release_dir": str(source.parent.resolve()),
        "rig_object": args.rig, "mesh_objects": args.mesh,
        "source_mesh_parts": parts_map,
        "source_preset": str(Path(args.source_preset).resolve()),
        "blender": str(Path(args.blender).expanduser().resolve()) if args.blender else "blender",
        "game": str(Path(args.game).expanduser().resolve()) if args.game else str((workspace / "game").resolve()),
        "cli": environment(args.cli, "extracted/huohua_hand_normal_fix/runtime/DsrCli.exe"),
        "runtime_manifest": environment(args.runtime_manifest, "extracted/huohua_hand_normal_fix/runtime/manifest.json"),
        "native_blend": environment(args.native_blend, "extracted/blender/isaac_protagonist_merged_skeleton.blend"),
        "native_rig_object": args.native_rig,
        "skeleton_xml": environment(args.skeleton_xml, "extracted/skeleton/Player_Skeleton.xml"),
        "skeleton_correction": not args.no_skeleton_correction,
        "skeleton_cli": environment(args.skeleton_cli, "tools/FrostyToolsuite-src/FrostyToolsuite-1.0.7/FrostyEditor/bin/Release/Final/DsrCli.exe"),
        "skeleton_globals_bank": environment(args.skeleton_globals_bank, "extracted/globals_shared.bin"),
        "skeleton_baseline_ebx": environment(args.skeleton_baseline_ebx, "extracted/skeleton/Player_Skeleton.original.ebx"),
        "skeleton_compiler": str(Path(args.skeleton_compiler).resolve()),
        "stages": stages, "source_pose": source_pose,
        "mmd_addon": "bl_ext.user_default.mmd_tools", "mmd_import_scale": 0.08,
        "static_morph_policy": "current_visible",
        "transparent_policy": "remove_zero_opacity", "atlas_size": 8192,
        "minimum_elbow_bend_degrees": 15, "maximum_arm_stretch": 1.25,
        "up_axis": 2, "scale_pivot": [0, 0, 0],
        "inner_material_pairs": [], "coincident_position_quantum": 1e-8}
    write_json(config_path, config)
    load_config(config_path)
    print(str(config_path))


def preflight(config):
    from skeleton_correction import dependencies
    for key in ("input", "blender", "cli", "runtime_manifest", "source_preset", "native_blend", "skeleton_xml"):
        if not Path(config[key]).is_file():
            raise FileNotFoundError(key + ": " + config[key])
    if not (Path(config["game"]) / "Data").is_dir():
        raise FileNotFoundError("Configured game Data directory is missing.")
    runtime = check_runtime(config)
    imported = Path(config["output"]) / "reports/import.json"
    if imported.exists():
        report = json.loads(imported.read_text(encoding="utf-8"))
        for image in report.get("images", []):
            if image.get("exists") and sha256(image["path"]) != image["sha256"]:
                raise ValueError("A source image changed after import: " + image["path"])
    return {"input_sha256": sha256(config["input"]), "native_sha256": sha256(config["native_blend"]),
            "source_preset_sha256": sha256(config["source_preset"]), "runtime": runtime,
            "normalized_importer": True, "skeleton_override": False,
            "skeleton_environment": dependencies(config)}


def invoke(command, log, cwd=None):
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as stream:
        completed = subprocess.run(list(map(str, command)), cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
    if completed.returncode:
        raise RuntimeError("Command failed; inspect " + str(log))
    return {"argv": list(map(str, command)), "cwd": str(cwd) if cwd else None,
            "log": str(log), "exit_code": completed.returncode}


def blender(config, config_path, stage, source, bootstrap=False, script="blender_pipeline.py"):
    command = [config["blender"], "--background", "--factory-startup"]
    if Path(source).suffix.lower() == ".blend":
        command.append(str(source))
    command += ["--python-exit-code", "1", "--python", str(SKILL / "scripts" / script),
               "--", str(config_path)]
    if script == "blender_pipeline.py":
        command.append(stage)
        if bootstrap:
            command.append("--bootstrap")
    return invoke(command, Path(config["output"]) / "logs" / (stage + ".log"))


def run(config, config_path, through):
    checks = preflight(config)
    work = Path(config["output"])
    work.mkdir(parents=True, exist_ok=True)
    state_path = work / "state.json"
    digest = sha256(config_path)
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if (state["config_sha256"] != digest
                or any(state.get(key) != checks[key] for key in
                       ("input_sha256", "native_sha256", "source_preset_sha256", "runtime", "skeleton_environment"))):
            raise ValueError("Job inputs changed; create a new output directory rather than mixing stages.")
        if sha256(state["current_blend"]) != state["current_sha256"]:
            raise ValueError("Saved working stage changed outside this job; start a new job from that copy.")
    else:
        if any((work / folder).exists() for folder in ("stages", "package")):
            raise FileExistsError("Untracked generated outputs already exist; use a fresh job output.")
        snapshot = work / "input" / Path(config["input"]).name
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config["input"], snapshot)
        state = {"config_sha256": digest, **checks, "completed": [],
                 "current_blend": config["input"], "current_sha256": checks["input_sha256"],
                 "input_snapshot": str(snapshot), "commands": []}
        write_json(work / "provenance.json", state)
    if through not in config["stages"]:
        raise ValueError("Requested stop stage is not enabled in this job.")
    for stage in config["stages"][:config["stages"].index(through) + 1]:
        if stage in state["completed"]:
            continue
        print("STAGE " + stage, flush=True)
        command = blender(config, config_path, stage, state["current_blend"], not state["completed"])
        if sha256(config["input"]) != state["input_sha256"]:
            raise ValueError("Original input changed during preparation.")
        if stage != "export":
            state["current_blend"] = str(work / "stages" / (stage + ".blend"))
            state["current_sha256"] = sha256(state["current_blend"])
        state["completed"].append(stage)
        state["commands"].append(command)
        write_json(state_path, state)
    print("READY " + state["current_blend"])


def plan(config):
    from PIL import Image
    work = Path(config["output"])
    package = work / "package"
    exports = json.loads((package / "exports.json").read_text(encoding="utf-8"))
    if sha256(exports["source"]) != exports["source_sha256"]:
        raise ValueError("Export source changed.")
    targets = config["targets"]
    if list(exports.get("targets", [])) != list(targets):
        raise ValueError("Export targets do not match the job configuration.")
    parts = {(entry["target"], entry["part"]): entry for entry in exports["parts"]}
    if (set(parts) != {(target, part) for target in targets for part in PARTS}
            or len(exports["parts"]) != len(targets) * len(PARTS)):
        raise ValueError("Mesh export manifest is incomplete.")
    atlas = work / "textures/character_atlas.png"
    with Image.open(atlas) as image:
        if image.size != (config["atlas_size"], config["atlas_size"]) or image.mode != "RGBA":
            raise ValueError("Canonical atlas dimensions or channels are incorrect.")
    normal, packed2 = work / "textures/packed_1_flat.png", work / "textures/packed_2.png"
    Image.new("RGBA", (512, 512), (128, 128, 255, 0)).save(normal)
    Image.new("RGBA", (2048, 2048), (255, 0, 255, 255)).save(packed2)
    rows, inputs = [], {}
    for target in targets:
        suit = SUITS[target]
        for part in PARTS:
            entry = parts[(target, part)]
            if sha256(entry["file"]) != entry["sha256"]:
                raise ValueError("FBX changed: " + entry["file"])
            if entry["asset"].casefold() != (suit["mesh_root"] + part + "_Mesh").casefold():
                raise ValueError("Unexpected target mesh identity: " + target + "/" + part)
            rows.append(("mesh", entry["asset"], entry["file"]))
        for family in suit["families"]:
            for index, path in enumerate((atlas, normal, packed2)):
                rows.append(("texture", suit["texture_root"] + family + "_PACKED_" + str(index), str(path)))
        rows.append(("suit-composition", suit["composition"], ",".join(suit["removals"])))
    for kind, asset, value in rows:
        if any("\t" in x or "\n" in x or "\r" in x for x in (asset, value)):
            raise ValueError("Plan fields cannot contain tabs or line breaks.")
        if kind != "suit-composition":
            inputs[value] = sha256(value)
    path = package / "character_plan.tsv"
    path.write_text("# kind\tasset\tpath_or_item_names\n" + "\n".join("\t".join(row) for row in rows) + "\n", encoding="utf-8")
    manifest = {"plan": str(path), "plan_sha256": sha256(path), "inputs": inputs,
                "exports_sha256": sha256(package / "exports.json"), "targets": list(targets),
                "skeleton_override": False}
    write_json(package / "plan_manifest.json", manifest)
    return manifest


def build(config, config_path):
    runtime = preflight(config)
    work = Path(config["output"])
    package = work / "package"
    state_path = work / "state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["input_sha256"] != runtime["input_sha256"] or state["config_sha256"] != sha256(config_path):
            raise ValueError("Job input or configuration changed since preparation.")
    if (package / "character").exists():
        raise FileExistsError("Build output already exists; preserve it and use a new job for rebuilds.")
    planned = plan(config)
    directory = package / "character"
    directory.mkdir(parents=True, exist_ok=True)
    commands = []
    def cli(stage, args):
        command = [config["cli"], "--game", config["game"], *map(str, args)]
        commands.append(invoke(command, work / "logs" / (stage + ".log"), Path(config["cli"]).parent))
    for target in config["targets"]:
        cli("baseline_" + target, ["export-xml", SUITS[target]["composition"],
            directory / ("composition_baseline_" + target + ".xml")])
    mod = directory / (config["name"] + ".fbmod")
    cli("build", ["package-character", planned["plan"], "--out", mod.parent, "--mod-name", config["name"]])
    cli("readback", ["export-mod-assets", mod, "--out", package / "verification/exported", "--skeleton", SKELETON])
    cli("inspect-package", ["inspect-mod-assets", mod, "--out", package / "verification/inspection"])
    for path, digest in planned["inputs"].items():
        if sha256(path) != digest:
            raise ValueError("A build input changed during packaging.")
    report = {"package": {"path": str(mod), "bytes": mod.stat().st_size, "sha256": sha256(mod)},
              "plan": planned, "preflight": runtime, "commands": commands,
              "installed": False, "runtime_tested": False, "config_sha256": sha256(config_path)}
    if config["skeleton_correction"]:
        from skeleton_correction import build as build_skeleton
        correction = build_skeleton(config, config_path, report["package"], invoke)
        report["body_package"] = report["package"]
        report["package"] = correction["package"]
        report["skeleton_correction"] = correction
    write_json(package / "build_manifest.json", report)
    print("BUILT " + report["package"]["path"])


def verify(config, config_path):
    package = Path(config["output"]) / "package"
    build_report = json.loads((package / "build_manifest.json").read_text(encoding="utf-8"))
    if build_report["config_sha256"] != sha256(config_path):
        raise ValueError("Configuration changed since build.")
    if sha256(build_report["package"]["path"]) != build_report["package"]["sha256"]:
        raise ValueError("Package changed since build.")
    exports = json.loads((package / "exports.json").read_text(encoding="utf-8"))
    command = blender(config, config_path, "verify", exports["source"], script="validate_readback.py")
    report = json.loads((package / "verification/final_validation.json").read_text(encoding="utf-8"))
    report["package_sha256"] = build_report["package"]["sha256"]
    report["verification_command"] = command
    if config["skeleton_correction"]:
        from skeleton_correction import verify as verify_skeleton
        report["skeleton_correction"] = verify_skeleton(build_report["skeleton_correction"])
        report["skeleton_override"] = build_report["skeleton_correction"]["applied"]
    write_json(package / "verification/final_validation.json", report)
    print("VERIFIED " + build_report["package"]["path"])


def release(config, config_path):
    package = Path(config["output"]) / "package"
    validation = json.loads((package / "verification/final_validation.json").read_text(encoding="utf-8"))
    build_report = json.loads((package / "build_manifest.json").read_text(encoding="utf-8"))
    mod = Path(build_report["package"]["path"])
    digest = sha256(mod)
    if (not validation.get("passed") or validation.get("package_sha256") != digest
            or build_report["config_sha256"] != sha256(config_path)):
        raise ValueError("Release requires successful validation of this exact package.")
    if config["skeleton_correction"]:
        from skeleton_correction import verify as verify_skeleton
        verify_skeleton(build_report["skeleton_correction"])
        if not validation.get("skeleton_correction", {}).get("passed"):
            raise ValueError("Release requires validated skeleton correction.")
    directory = Path(config["release_dir"])
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / mod.name
    if destination.exists():
        raise FileExistsError("A released package with this name already exists; preserve it.")
    shutil.copy2(mod, destination)
    write_json(directory / (config["name"] + ".release.json"), {"package": str(destination),
        "sha256": digest, "bytes": mod.stat().st_size,
        "validation": str(package / "verification/final_validation.json"),
        "installed": False, "runtime_tested": False,
        "skeleton_override": bool(build_report.get("skeleton_correction", {}).get("applied")),
        "skeleton_correction_mode": "matched_head_visual_offset" if config["skeleton_correction"] else "disabled",
        "single_package": True})
    print(str(destination))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    for name in ("config", "name", "input", "source-preset"):
        init.add_argument("--" + name, required=True)
    init.add_argument("--rig", default="DSR_Rig")
    init.add_argument("--targets", nargs="+", default=["isaac_lv1", "isaac_legacy"],
                      choices=sorted(SUITS), help="Suit contracts replaced by one package")
    init.add_argument("--blender", help="Blender executable; default resolves 'blender' on PATH")
    init.add_argument("--game", help="Dead Space install directory (containing Data/)")
    init.add_argument("--cli", help="DsrCli.exe path")
    init.add_argument("--runtime-manifest", help="runtime manifest.json path")
    init.add_argument("--native-blend", help="unedited native reference BLEND path")
    init.add_argument("--native-rig", default="Reference", help="native reference armature object name")
    init.add_argument("--skeleton-xml", help="Player_Skeleton.xml path")
    init.add_argument("--no-skeleton-correction", action="store_true", help="Disable the default matched skeleton plus Head visual compensation")
    init.add_argument("--skeleton-cli", help="CLI supporting skeleton translation import and package readback")
    init.add_argument("--skeleton-globals-bank", help="Unmodified globals ANT bank")
    init.add_argument("--skeleton-baseline-ebx", help="Original raw Player_Skeleton EBX")
    init.add_argument("--skeleton-compiler", default="D:/VisualStudio/MSBuild/Current/Bin/Roslyn/csc.exe")
    init.add_argument("--mesh", nargs="+", default=["CharacterMesh"])
    init.add_argument("--source-mesh-parts", nargs="*", default=[],
                      help="MESH:PART pairs whose whole source mesh maps to one DSR part")
    init.add_argument("--source-pose", choices=("AUTO", "A", "T", "DSR"))
    init.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    for command in ("preflight", "inspect", "run", "plan", "build", "verify", "release"):
        child = sub.add_parser(command)
        child.add_argument("config")
        if command == "run":
            child.add_argument("--through", choices=STAGES, default="export")
    args = parser.parse_args()
    if args.command == "init":
        initialize(args)
        return
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    if args.command == "preflight":
        print(json.dumps(preflight(config), indent=2))
    elif args.command == "inspect":
        blender(config, config_path, "inspect", config["input"])
        print(str(Path(config["output"]) / "reports/input_inspection.json"))
    elif args.command == "run":
        run(config, config_path, args.through)
    elif args.command == "plan":
        print(json.dumps(plan(config), indent=2))
    elif args.command == "build":
        build(config, config_path)
    elif args.command == "verify":
        verify(config, config_path)
    else:
        release(config, config_path)


if __name__ == "__main__":
    main()
