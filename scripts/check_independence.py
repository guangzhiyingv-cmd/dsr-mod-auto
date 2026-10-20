"""Audit bundled imports and local documentation links without game dependencies."""

import argparse
import ast
import json
from pathlib import Path
import re
import sys


EXTERNAL_MODULES = {"PIL", "addon_utils", "bpy", "io_scene_fbx", "mathutils", "numpy"}


def audit_tree(root):
    root = Path(root).resolve()
    scripts = root / "scripts"
    files = sorted(scripts.rglob("*.py"))
    local = {path.stem for path in files}
    local |= {path.name for path in scripts.rglob("*") if path.is_dir() and (path / "__init__.py").exists()}
    used_local, used_external, errors = set(), set(), []
    for path in files:
        if not path.resolve().is_relative_to(root):
            errors.append("Bundled script escapes the skill root: " + str(path))
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                base = name.split(".")[0]
                if base in local:
                    used_local.add(base)
                elif base in EXTERNAL_MODULES:
                    used_external.add(base)
                elif base not in sys.stdlib_module_names:
                    errors.append(str(path.relative_to(root)) + ": unresolved import " + name)
    checked_links = 0
    for path in [root / "SKILL.md", root / "README.md", *(root / "references").rglob("*.md")]:
        if not path.is_file():
            errors.append("Missing documentation: " + str(path))
            continue
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8-sig")):
            target = target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(root) or not resolved.exists():
                errors.append(str(path.relative_to(root)) + ": missing or external local link " + target)
            checked_links += 1
    return {"passed": not errors, "skill_root": str(root), "python_files": len(files),
            "bundled_imports": sorted(used_local), "declared_external_imports": sorted(used_external),
            "local_document_links_checked": checked_links, "errors": errors,
            "limits": ["Static imports and local Markdown links only; dynamic Blender add-ons and tool/game resources remain explicit dependencies.",
                       "Relocated Python/Blender and packaging tests provide separate runtime evidence."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = audit_tree(args.root)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
