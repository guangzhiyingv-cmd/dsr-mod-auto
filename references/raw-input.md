# Starting from a base MMD model

The skill must not rely on Huohua's earlier manual preparation. Direct PMX/PMD
jobs include that missing front end and preserve all generated intermediates.

## Initialize from PMX

From the repository root:

```powershell
$dsrPython = 'D:\python\python.exe'
$dsrJob = 'E:\mod\DeadSpace\skill\dsr-mod-auto\scripts\dsr_job.py'
$dsrPreset = 'C:\Users\123\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\Modding-Toolkit\assets\presets\import\MMD.json'
& $dsrPython $dsrJob init --config 'E:\mod\DeadSpace\extracted\dsr_jobs\lossi_raw.json' `
  --name lossi_raw --input 'E:\mod\DeadSpace\Mods\Lossi\Lossi.pmx' --source-preset $dsrPreset
& $dsrPython $dsrJob run 'E:\mod\DeadSpace\extracted\dsr_jobs\lossi_raw.json' --through pose
```

Inspect `stages/import.blend`, `static.blend`, `tpose.blend`, `pose.blend` and
their reports. Then continue the ordinary job through cleanup/export, build,
verify and release. Use a new name/config/output for another trial; do not
overwrite an existing job with this example command.

## Import settings and source assets

The current installed importer is `bl_ext.user_default.mmd_tools`, enabled only
in the background process. `mmd_addon` config can select another installed module.
Import MESH, ARMATURE and MORPHS at recorded scale `0.08`; do not import physics
or display-frame objects. Disable model cleaning, merge-by-distance, bone-order
fixing, IK link fixing and fixed-axis rewriting. This preserves topology and
material boundaries rather than applying unknown importer cleanup.

Enable Blender L/R bone renaming. The current MMD semantic preset expects those
names (for example a suffix form) rather than every PMX's original Japanese
prefix convention. Record the original PMX name for each imported bone so the
mapping remains auditable. Do not translate names through an unspecified
dictionary. The imported character is assigned the configured canonical names
`DSR_Rig` and `CharacterMesh` unless the config selects others.

MMD Tools can report FINISHED after logging an exception. Check actual output:
one nonempty mesh, one armature, expected faces/bones, material table, and usable
base texture images. Missing base textures stop the job. Missing shared toon
files are recorded and do not block a base-color-only atlas that excludes toon
and sphere lighting. Record texture paths/hashes and pack available images in
the imported BLEND. Do not write logs or changed files beside the PMX.

## Freeze the static appearance

`static_morph_policy=current_visible` freezes the imported visible expression
on a working copy. The import snapshot retains the morphs and constraints.
Evaluate IK/append/controller effects, copy the evaluated pose, remove copied
constraints/drivers, bake that pose to rest, and bake the current shape-key mix
to static geometry. Record every source morph value and the before/after mesh
error. Preserve UVs, weights, topology, material order and custom normals.

This branch intentionally builds a static character replacement. Eye animation,
expression animation, skirt/hair physics and arbitrary morph conversion are
separate requested capabilities. If the user wants a different expression or
outfit, establish that visible state first; do not select a non-default variant
or simulate physics without an actual reason.

## Pose routing

The default `source_pose=AUTO` measures both arms:

- A clear A-pose has depressed upper arms on both sides with limited forward
  deviation. Convert A to T, bake, and check straight lateral arms.
- An existing T-pose passes the intermediate without A-to-T rotations.
- An ambiguous pose stops with measurements for inspection. An explicit `A` or
  `T` selection resolves intentional cases; it does not waive output checks.
- An explicitly declared `DSR` input skips both conversion stages.

Only after T-pose normalization call the existing T-to-DSR engine. Its leg
policy remains spread-only, preserving forward inclination and foot/toe roll.
Then run height alignment (Head by default; shoulder optional) and the targeted
native hand/finger fit.

Keep `reports/tpose.json` and `reports/pose.json` separate. A successful final
DSR pose alone is not evidence that the intermediate A-to-T step happened.
