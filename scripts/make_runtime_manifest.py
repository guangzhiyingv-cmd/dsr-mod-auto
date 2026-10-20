"""Generate a portable runtime manifest with paths relative to the CLI directory."""

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(runtime, plugin_source="Plugins/MeshSetPlugin.dll",
                   frame_patch="references/data/frosty_unit_frame.patch"):
    runtime = Path(runtime).resolve()
    plugin = runtime / "Plugins/MeshSetPlugin.dll"
    cli = runtime / "DsrCli.exe"
    for required in (cli, plugin):
        if not required.is_file():
            raise FileNotFoundError("Missing runtime component: " + str(required))
    tools = [{"path": path.relative_to(runtime).as_posix(), "sha256": sha256(path)}
             for path in sorted(runtime.rglob("*"))
             if path.is_file() and path.suffix.lower() in (".dll", ".exe")]
    return {"schema": "dsr_runtime_manifest_v1",
            "normalized_plugin_source": plugin_source,
            "normalized_plugin_sha256": sha256(plugin),
            "frame_patch": frame_patch,
            "tools": tools}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True,
                        help="Directory containing DsrCli.exe and Plugins/MeshSetPlugin.dll")
    parser.add_argument("--out", type=Path, help="Manifest path; default <runtime>/manifest.json")
    parser.add_argument("--plugin-source", default="Plugins/MeshSetPlugin.dll",
                        help="Recorded provenance of the normalized MeshSetPlugin")
    parser.add_argument("--frame-patch", default="references/data/frosty_unit_frame.patch")
    args = parser.parse_args()
    manifest = build_manifest(args.runtime, args.plugin_source, args.frame_patch)
    out = args.out or Path(args.runtime) / "manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(str(out))


if __name__ == "__main__":
    main()
