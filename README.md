# DSR Mod Auto

An agent skill and command-line workflow that builds Dead Space (2023) Isaac
character-replacement FBMODs from raw MMD models (PMX/PMD) or prepared Blender
scenes. It runs the full pipeline: A-pose to T-pose to DSR-pose conversion, one
base-color atlas, DSR rig cleanup, eleven-part splitting, shoulder-height
alignment, targeted hand/finger fitting, optional duplicate-layer cleanup, FBX
export, FBMOD packaging, and offline readback validation.

By default one package replaces two suits at once: **Isaac Lv1** and
**Isaac Legacy**.

## What a job produces

- A reviewable Blender project (`stages/pose.blend`, `stages/cleanup.blend`, ...).
- Suit-specific FBX parts (eleven per suit), each with the correct section node.
- One canonical base-color atlas plus the flat/constant packed maps.
- One validated `.fbmod` containing the character and, by default, matched
  skeleton references plus Head visual-offset compensation. Animation clips
  remain unchanged. Disable the correction with `--no-skeleton-correction`.

## Repository layout

```
SKILL.md                 Skill definition for agent runners
agents/                  Agent scaffolding
scripts/                 dsr_job.py CLI, blender_pipeline.py, private cores, tests
references/              workflow and contract documentation (Markdown)
references/data/         Bundled data: DSR pose, bone mapping, runtime patch
README.md  LICENSE  .gitignore
```

## Requirements

The scripts are pure Python + Blender and depend only on the standard library,
Blender's `bpy`/`mathutils`/`addon_utils`/`io_scene_fbx`, and `Pillow`/`numpy`.
Python needs Pillow. Blender needs NumPy and Pillow available to its Python.

External tools and assets are **not bundled** and must be supplied by you:

- Blender 5.2.x with the MMD Tools add-on and the Material Combiner add-on
  (version 2.1.3.0 tested).
- A normalized-importer `DsrCli.exe` runtime (this project's Frosty fork) plus
  its `manifest.json` checksum list, covering `DsrCli.exe` and
  `Plugins/MeshSetPlugin.dll`.
- The installed Dead Space (2023) game (read-only) so the CLI can read base
  assets.
- An unedited native reference BLEND containing the game rig and the
  `Player_Skeleton.xml`.
- The Modding-Toolkit MMD import preset JSON (`MMD.json`).
- For the default skeleton correction: the original globals ANT bank and raw
  Player_Skeleton EBX, a skeleton-capable CLI and the VS2022 C# compiler. See
  [skeleton correction](references/skeleton-correction.md) for configuration.

The DSR pose reference and bone mapping used by the pipeline are bundled under
`references/data/`.

## Install

Keep one Git checkout as the maintenance source. On Windows, point the shared
`%USERPROFILE%/.agents/skills/dsr-mod-auto` directory and the OpenCode-specific
`%USERPROFILE%/.config/opencode/skills/dsr-mod-auto` directory to that checkout
with directory junctions. Archive existing independent installations outside
skill discovery roots first. Codex already discovers the shared `.agents`
entry, so do not also install a duplicate under `.codex/skills`.

Changes in the checkout then reach both applications without copying or syncing
separate versions. Retain the checkout's `.git` directory and GitHub remote.
Reload the applications' skill lists after changing discovery entries. Local
consolidation does not automatically commit or push changes to GitHub.

Call the checkout's CLI with your Python:

```powershell
$python  = 'D:\python\python.exe'
$job     = '<repo>\scripts\dsr_job.py'
$preset  = "$env:APPDATA\Blender Foundation\Blender\5.2\scripts\addons\Modding-Toolkit\assets\presets\import\MMD.json"
```

## Quick start (PMX input)

```powershell
& $python $job init --config '<work>\my_character.json' `
  --name my_character --input '<model>\character.pmx' --source-preset $preset `
  --workspace '<your working root>' `
  --blender '<path to blender.exe>' --game '<Dead Space install>' `
  --cli '<runtime>\DsrCli.exe' --runtime-manifest '<runtime>\manifest.json' `
  --native-blend '<native>.blend' --skeleton-xml '<native>\Player_Skeleton.xml'

& $python $job preflight '<work>\my_character.json'
& $python $job inspect   '<work>\my_character.json'
& $python $job run       '<work>\my_character.json' --through pose   # review pose.blend
& $python $job run       '<work>\my_character.json' --through export
& $python $job build     '<work>\my_character.json'                  # requires DsrCli
& $python $job verify    '<work>\my_character.json'
& $python $job release   '<work>\my_character.json'
```

`init` writes absolute paths into the job config; `--workspace` defaults to the
current directory and the runtime/native paths resolve under it unless the
matching options above are given. Output is written beside the source model:
intermediates under `<model_dir>/<name>_job/` and the released `.fbmod` under
`<model_dir>/`.

For a prepared multi-mesh BLEND, add `--source-pose AUTO --rig <armature>
--mesh <a> <b>` and, to keep a hand-made head/body split, `--source-mesh-parts
head:head`. See `references/` for the full contract.

## Commands

`init`, `preflight`, `inspect`, `run`, `plan`, `build`, `verify`, `release`.
Blender stages run in separate background processes; C# `DsrCli` calls are
serialized. `build` reads the installed game but never applies the mod; `release`
only copies a package that passed offline readback validation.

## Independence and limits

This repository contains **no** game assets, no Blender binaries, no Frosty
binaries, and no keys. It does not install mods, launch the game, or modify the
game's Data tree. Offline validation does not substitute for an in-game test.

## License

MIT. See [LICENSE](LICENSE).
