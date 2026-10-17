# Running a DSR job

## Environment and input contract

The tested environment is Windows, Blender 5.2.2 LTS, Material Combiner 2.1.3.0,
Python with Pillow, and the repository's DsrCli/Frosty fork. NumPy and Pillow
must also be available to Blender. External resources are not bundled.

`init` writes absolute paths into the job config. `--workspace` defaults to the
current directory; the CLI, runtime manifest, native BLEND, and skeleton XML
resolve under it unless overridden. Pass `--blender`, `--game`, `--cli`,
`--runtime-manifest`, `--native-blend`, `--skeleton-xml`, and `--native-rig` to
point at another installation. The listed paths are the author's example
workstation, not requirements:

| Dependency | Example path |
| --- | --- |
| Workspace | current directory (`--workspace`) |
| Python | `D:/python/python.exe` (needs Pillow) |
| Blender | `blender` on PATH (`--blender`) |
| Game | `--game` (must contain a `Data/` directory) |
| Normalized CLI runtime | `<workspace>/extracted/huohua_hand_normal_fix/runtime/DsrCli.exe` |
| Runtime checksums | `<workspace>/extracted/huohua_hand_normal_fix/runtime/manifest.json` |
| Original native BLEND | `<workspace>/extracted/blender/isaac_protagonist_merged_skeleton.blend` |
| Original skeleton XML | `<workspace>/extracted/skeleton/Player_Skeleton.xml` |
| MMD source mapping | `%APPDATA%/Blender Foundation/Blender/5.2/scripts/addons/Modding-Toolkit/assets/presets/import/MMD.json` |

The normalized runtime is a dependency inherited from the successful build,
not a Huohua-specific mesh processor. `preflight` verifies all 73 recorded binary
hashes, including the CLI and MeshSetPlugin. An alternative runtime needs a
matching manifest and verified N/T/B normalization. Do not satisfy the check
by simply marking an old runtime normalized.

PMX/PMD inputs now run directly through `import`, `static`, `tpose`, and `pose`
before the original preparation stages. See [raw-input.md](raw-input.md) for
the base-model command and policies. Other formats still need a working BLEND.

The atlas/rig/split branch expects one triangulated character mesh,
one deform rig, an active `UVMap` texture layer, MMD-compatible material nodes,
and no shape keys or non-armature modifiers. It produces exactly two final
channels: `UVChannel0` (atlas UVs) and `UVChannel1` (that UV scaled to zero). The
supported static preparation policy must be resolved before joining/baking more
complex inputs.
Generic Principled materials need an audited material adapter; do not pretend
the MMD shader reader supports them. Source bone presets use Modding-Toolkit's
semantic `mappings` format with `main` and `aux` name lists.

## Create and inspect

Use absolute paths when invoking the installed skill from another directory.
This example runs from the repository root and uses illustrative object names;
replace them with names discovered in Blender or the inspection JSON.

```powershell
$dsrPython = 'D:\python\python.exe'
$dsrJob = 'E:\mod\DeadSpace\skill\dsr-mod-auto\scripts\dsr_job.py'
& $dsrPython $dsrJob init --config 'E:\mod\DeadSpace\extracted\dsr_jobs\my_character.json' `
  --name my_character --input 'E:\work\character.blend' `
  --rig 'CharacterArmature' --mesh 'CharacterMesh' `
  --source-preset 'C:\Users\123\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\Modding-Toolkit\assets\presets\import\MMD.json'
& $dsrPython $dsrJob inspect 'E:\mod\DeadSpace\extracted\dsr_jobs\my_character.json'
& $dsrPython $dsrJob preflight 'E:\mod\DeadSpace\extracted\dsr_jobs\my_character.json'
```

Inspection reads all scene objects without saving the source. It reports mesh
names, bound armatures, bones, constraints, UVs, shape keys, materials and world
transforms. Correct the configuration before the first mutating stage.

## Output layout

`init` places generated output beside the source model rather than under the
repository. Intermediate artifacts (input snapshot, stage BLENDs, reports,
textures, package intermediates) go to `<model_dir>/<name>_job/`, and `release`
copies the final FBMOD to `<model_dir>/`, the same folder as the source model.
The job configuration still records `workspace` for the shared CLI, native
reference, and skeleton dependencies. `release_dir` must already exist.

For prepared BLEND inputs, `mesh_objects` may list several character meshes. The
atlas stage joins them into one working mesh (keeping materials, UVs, weights,
custom normals and source IDs) before Material Combiner runs, because
atlas/rig/split require a single mesh. Generic Principled materials are read by
an adapter that resolves opacity and the base-color image from an MMD shader
group when present, or from the connected Principled node otherwise; extra source
UV layers are dropped during atlas preparation and recorded in
`reports/01_atlas.json`, leaving `UVChannel0` and the zeroed `UVChannel1`.

To preserve a hand-made source split (for example the head mesh the user cut
separately), set `source_mesh_parts` (CLI `--source-mesh-parts MESH:PART`). Each
listed mesh is mapped whole to its declared DSR part, and faces in all other
meshes are allocated only among the non-reserved parts. Otherwise the atlas join
plus weight-based partition would recompute the head/body boundary and lose the
prepared one.

## Configuration decisions

`init` writes explicit local paths and these defaults:

- `stages` for an already converted BLEND: `atlas, rig, split, scale, hands,
  cleanup, export`. Raw PMX/PMD defaults prepend `import, static, tpose, pose`.
  A BLEND initialized with `--source-pose A`, `T`, or `AUTO` prepends `static,
  tpose, pose`. Never apply a T-pose normalizer to an existing DSR pose.
- For a prepared BLEND whose rig is still a raw MMD A/T armature, pass
  `--source-pose AUTO` (or `A`/`T`), `--rig <actual armature>`, and list every
  character mesh with `--mesh`. Non-raw inputs default to `DSR`, which skips the
  pose stages and is wrong for an unconverted MMD rig.
- `targets` selects the suit contracts replaced by the one package. Default is
  `isaac_lv1 isaac_legacy`; pass `--targets isaac_lv1` for a single suit. Each
  target exports its own section-named FBX set and contributes its own texture
  families and suit-composition removal, all packaged into one FBMOD.
- `source_pose`: raw inputs default to `AUTO`, prepared BLEND to `DSR`.
  `AUTO` accepts clear A/T cases and stops for ambiguous poses; inspect those
  cases instead of guessing. `DSR` skips both conversion stages.
- `transparent_policy`: `remove_zero_opacity`. Use `keep` if the visible-layer
  policy calls for it. Visible translucency remains; alpha-zero shader layers
  alone are removed by the default.
- `atlas_size`: 8192. The tested Material Combiner preset must actually produce
  this size; another layout/size needs an adjusted, validated atlas contract.
- `minimum_elbow_bend_degrees`: 15; `maximum_arm_stretch`: 1.25. The latter is
  a review stop threshold, not an anatomical optimum. Inspect an extreme fit
  before increasing it.
- `up_axis`: 2 (world Z); `scale_pivot`: `[0,0,0]`. Inspect both coordinate
  systems and ground origins. Record the native reference's intentional world
  conversion and the source import scale: the measured shoulder factor can
  legitimately bridge those units. Distinguish that from an accidental double
  conversion rather than rejecting every factor near 0.01 or 100.
- `inner_material_pairs`: empty. Set confirmed `[outer_index, inner_index]`
  pairs using the original pre-atlas material indices. Never copy another
  model's indices. Empty means no duplicate-face removal.

The static cleanup maps available source semantic joints to DSR and merges eye
weights into Head. If the user needs eye animation, clothing physics, morphs,
or a different bone-retention policy, adapt that branch explicitly before run.

For prepared input, omit completed stages, select the actual eleven mesh
objects, and point `rig_object` to their cleaned rig. A job starting with scale
or hands still needs compatible DSR bone names and part tags. Export/build also
needs `textures/character_atlas.png` under the new job output; copy the verified
canonical atlas and record its source hash rather than rebaking it needlessly.

## Prepare, inspect, and finish

```powershell
& $dsrPython $dsrJob run 'E:\mod\DeadSpace\extracted\dsr_jobs\my_character.json' --through cleanup
# Inspect the resulting stages/cleanup.blend and relevant stage reports.
& $dsrPython $dsrJob run 'E:\mod\DeadSpace\extracted\dsr_jobs\my_character.json' --through export
& $dsrPython $dsrJob plan 'E:\mod\DeadSpace\extracted\dsr_jobs\my_character.json'
& $dsrPython $dsrJob build 'E:\mod\DeadSpace\extracted\dsr_jobs\my_character.json'
& $dsrPython $dsrJob verify 'E:\mod\DeadSpace\extracted\dsr_jobs\my_character.json'
& $dsrPython $dsrJob release 'E:\mod\DeadSpace\extracted\dsr_jobs\my_character.json'
```

`state.json` records successful stages and input/config/current-BLEND hashes.
Resuming a stable job skips completed stages. Changed configuration or externally
edited stages need a new job/output; do not silently mix them with old exports.
Build output directories and releases are not overwritten. Blender inspection
and preparation may need host execution approval; use the normal tool mechanism.
The scripts never install mods, launch the game, or change installed add-ons.

For prepared BLEND inputs, the first working-copy stage retains only configured character objects;
unrelated objects are discarded from that in-memory copy. The original project
and an immutable input snapshot remain intact. A separately loaded unedited
native armature is hidden as `Original_Game_Rig_Comparison` for fitting.
For raw inputs, the imported snapshot retains MMD data, while `static` creates
the reduced character copy and removes controllers after freezing their evaluated
state. The scripts do not enable a physics simulation.
