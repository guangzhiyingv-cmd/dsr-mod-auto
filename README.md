# DSR Mod Auto

An agent skill and command-line workflow that builds Dead Space (2023) Isaac
character-replacement FBMODs from raw MMD models (PMX/PMD) or prepared Blender
scenes. It runs the full pipeline: A-pose to T-pose to DSR-pose conversion, one
base-color atlas, DSR rig cleanup, eleven-part splitting, configurable height
alignment, targeted hand/finger fitting, optional duplicate-layer cleanup, FBX
export, FBMOD packaging, and offline readback validation.

By default one package replaces two suits at once: **Isaac Lv1** and
**Isaac Legacy**.

Height alignment defaults to the native `Head` bone origin. Use
`--height-alignment shoulder` for mean shoulder height, or
`--height-alignment head` to select the default explicitly.

## What a job produces

- A reviewable Blender project (`stages/pose.blend`, `stages/cleanup.blend`, ...).
- Suit-specific FBX parts (eleven per suit), each with the correct section node.
- One canonical base-color atlas plus the flat/constant packed maps.
- One validated `.fbmod` containing the character and, by default, matched
  skeleton references without fixed Head visual compensation, plus the required
  independent Head/LeftForeArm animation translation repair. `--no-skeleton-correction` releases separate body and
  skeleton correction FBMODs; the body can be enabled independently. Without
  that flag, both are merged into one FBMOD. For an explicit body-only build,
  set `skeleton_correction: false` in JSON with merged delivery mode.

## Repository layout

```
SKILL.md                 Skill definition for agent runners
agents/                  Agent scaffolding
scripts/                 dsr_job.py CLI, blender_pipeline.py, private cores, tests
references/              workflow and contract documentation (Markdown)
references/data/         Bundled data: DSR pose, bone mapping, runtime patch
references/data/native/  Bundled native reference BLEND, skeleton XML/bank/EBX
runtime/                 Bundled DsrCli toolchain, key, cache and manifest
README.md  LICENSE  .gitignore
```

## Requirements

The scripts are pure Python + Blender and depend only on the standard library,
Blender's `bpy`/`mathutils`/`addon_utils`/`io_scene_fbx`, and `Pillow`/`numpy`.
Python needs Pillow. Blender needs NumPy and Pillow available to its Python.

The skill produces character content only. The animation translation repair is a
separate package (`dsr_animation_fix.fbmod`) that must be enabled together with
the character in the mod manager; `--animation-fix` records that requirement and
never merges the repair into a character build. See
[references/animation-fix.md](references/animation-fix.md).
Only Blender with its add-ons and the game installation are external; the
runtime and game-derived references ship with the skill.

- Blender 5.2.x with the MMD Tools add-on and the Material Combiner add-on
  (version 2.1.3.0 tested).
- The installed Dead Space (2023) game (read-only) so the CLI can read base
  assets. The bundled key only decrypts an installation you own.
- The bundled normalized-importer `DsrCli.exe` runtime in `runtime/` with its
  `manifest.json` checksum list, `deadspace.key`, the DSR profile SDK and the
  asset cache. Pass `--cli` and `--runtime-manifest` to use another runtime
  that satisfies the same normalized contract.
- The bundled native reference BLEND (`references/data/native/`) and
  `Player_Skeleton.xml`.
- The bundled Modding-Toolkit MMD import preset
  (`references/data/mmd_import.json`).
- No separate animation-repair installation is needed. Each build unpacks and
  merges the bundled repair; see [animation repair](references/animation-fix.md).
- For the default skeleton correction: the bundled original globals ANT bank
  and raw Player_Skeleton EBX. The C# compiler defaults to the Windows .NET
  Framework `csc.exe`. See
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
```

## Quick start (PMX input)

```powershell
& $python $job init --config '<work>\my_character.json' `
  --name my_character --input '<model>\character.pmx' `
  --workspace '<your working root>' `
  --blender '<path to blender.exe>' --game '<Dead Space install>'
```

`init` defaults `--cli`, `--runtime-manifest`, `--source-preset`,
`--native-blend`, `--skeleton-xml` and the skeleton bank/baseline references to
the bundled copies. Only the game installation and Blender remain external.

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

The skill's code, references and the normalized DsrCli runtime are
self-contained (about 220 MB total). Bundled game-derived payloads are the
pinned Head/LeftForeArm animation repair ZIP, the DSR asset cache, the native
reference BLEND/skeleton/ANT bank, and the game encryption key. Only Blender
with its add-ons and the installed game remain external. You must own Dead
Space (2023); the bundled key is only used to read your own installation. The
skill never installs mods, launches the game, or changes its Data tree.
Offline validation does not substitute for an in-game test.

Run the portable checks from any working directory:

```text
python <skill>/scripts/check_independence.py
python -m unittest discover -s <skill>/scripts -p "test_*.py"
blender --background --factory-startup --python-exit-code 1 --python <skill>/scripts/test_tpose.py
```

The import/link checker detects unresolved local modules and missing documentation
links. Relocation tests remove PYTHONPATH and run from an unrelated directory;
Blender and packaging tests additionally exercise the actual environment-dependent
branches. The repair archive stays below GitHub's regular-file size limit and
requires no Git LFS client.

## License

Source code is MIT licensed; see [LICENSE](LICENSE). The bundled game-derived
repair payload is separate from that source-code license.
