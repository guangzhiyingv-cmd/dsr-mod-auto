---
name: dsr-mod-auto
description: Build Dead Space (2023) Isaac character replacement FBMODs from raw PMX/PMD or Blender models, including A-to-T-to-DSR pose conversion, atlas packing, skin mapping, part export, and package readback validation. Use for DSR character mod creation or fixes; the automated default replaces the Isaac Lv1 and Legacy suits with one package.
---

# DSR Mod Auto

Produce a reviewable Blender project, suit-specific FBX parts, one base-color
atlas per family, and a validated character FBMOD using the original game
skeleton. The bundled automation implements the locally verified Isaac Lv1 and
Legacy contracts and packages both suits into one FBMOD by default. Each suit's
resource/section/material contract was inspected from the game and must not be
interpolated from another suit. Adding a further suit needs its own inspected
contract first.

## Start from the actual request

- Inspect the supplied model and existing progress; resume from the most recent
  compatible stage. Do not repeat pose conversion, scaling, or fitting already
  applied to the input.
- PMX/PMD inputs start directly with the bundled MMD import and static-state
  preparation. Read [raw-input.md](references/raw-input.md) for that branch.
  FBX, GLTF, VRM, or OBJ sources still need a compatible importer and a working
  BLEND. Resolve missing base textures and multiple-character ambiguity first.
- Preserve original assets and earlier successful releases. Generate jobs beside
  the source model: intermediate files under `<model_dir>/<name>_job/` and the
  released FBMOD under `<model_dir>/`. A changed configuration needs a fresh
  output directory rather than mixing stages.
- If the user asks to inspect the model first, stop at that review milestone.
  Otherwise continue through offline packaging and validation when authorized.
  Building a package does not authorize installing it or changing the game Data.
- Ask about unresolved choices that alter visible appearance or body proportions.
  Use the established choices when continuing this model; do not ask again.

Read [workflow.md](references/workflow.md) to set up and run a job. Paths there
describe the current workstation; configuration permits other installations.

## Choose the preparation path

For a raw MMD model: import, freeze the current visible static state on a copy,
identify the pose, convert A-pose to T-pose if necessary, then convert T-pose to
DSR pose. Save and validate each intermediate pose. Only then perform atlas,
rig cleanup, splitting, shoulder-height alignment, targeted hands, duplicate-layer
cleanup, and export. Read [geometry.md](references/geometry.md) before adjusting
pose, proportions, bone mapping, or weights.

The required order is **A -> T -> DSR -> shoulder-height alignment**. A source
already in T-pose skips the A-to-T rotations. A source already in DSR pose skips
both pose conversions; never normalize that prepared pose back to T automatically.

For an already prepared model, select only the remaining stages and configure
its actual rig/mesh names. Export-only inputs still require DSR-named bones,
eleven `dsr_part` tags, two UV channels (`UVChannel0` with the usable UV and a
zeroed `UVChannel1`), source-face IDs, and a canonical atlas. The helper
deliberately rejects incompatible inputs rather than guessing.

The default geometry method preserves most of the model's proportions:

1. Match mean native `LeftShoulder`/`RightShoulder` height with a uniform scale.
2. Keep upper-arm roots fixed and solve the arms to native wrists, extending
   both arm segments proportionally only as needed within the configured limit.
3. Fit Hand and deform fingers to original native frames while baking mesh
   deformation through anatomical segment frames.

Do not apply Huohua's measured scale, stretch, material indices, triangle counts,
or exact retained-bone count to another character. Do not automatically fit the
entire body to every original joint; that approach excessively stretched the
tested model. A new model's appearance still requires visual review.

## Keep these technical invariants

- Use the unedited native skeleton for the wrist/finger target. A user-aligned
  game rig is a different reference. Preserve native world conversion and units.
- DSR mesh import does not write FBX bind transforms into `Player_Skeleton`.
  Mesh fitting and a SkeletonAsset override are separate operations. This
  pipeline emits no skeleton or animation override.
- Legs change spread only during pose conversion; preserve forward pitch and
  foot/toe orientation. Do not introduce the earlier forward leg tilt.
- Sum helper weights into an appropriate retained deform ancestor. Resolve
  equivalent ordinary/D leg chains anatomically before ancestor merging so toe
  weights cannot collapse to Hips. Unknown weighted groups require resolution.
- Preserve original custom corner normals, UVs, skin weights, and surviving face
  identities when splitting or filtering. Use inverse-transpose normal changes
  when baking non-rigid anatomical fitting.
- Delete garment inner faces only for inspected outer/inner material pairs with
  coincident positions, opposite winding, and matching skin weights. A `+`
  material suffix alone is insufficient evidence. Review back-side coverage.

Read [materials.md](references/materials.md) for atlas, normals, and black-cloth
diagnosis. Every family of every target suit uses PACKED_1 source RGBA
`(128,128,255,0)` in BC7_UNORM; the reference mod's white normal constant is
incorrect. Preserve normalized transformed N/T/B in the importer. Lv1 sections
store Normals/Tangents/Binormals; Legacy sections store only Normals/Binormals.

Read [packaging.md](references/packaging.md) before export/build/readback. Use a
verified normalized-importer runtime, serialize DsrCli calls, and inspect the
actual FBMOD rather than treating FBX export as proof of a valid mod.

## Automation and delivery

`scripts/dsr_job.py` implements `init`, `preflight`, `inspect`, `run`, `plan`,
`build`, `verify`, and `release`. Blender stages run in separate background
processes through `scripts/blender_pipeline.py`. Private core modules preserve
the tested algorithms and load no source code from historical Huohua scripts.
External Blender add-ons, Frosty binaries, keys, game assets, and the native
reference BLEND/XML remain explicit environment dependencies.

Keep commands, input/tool hashes, stage reports, an inspectable BLEND, package
hashes, and final validation under the job directory. Render or inspect front,
back, hands, collar, skirt, and split boundaries before delivery. Stop a failed
stage, inspect its log, and correct that issue; do not continue a partial build
or loop on tool failures. A changed job configuration needs a fresh output
directory, preserving existing outputs.

Deliver clickable paths to the final BLEND and validated FBMOD, the target suit,
what changed, and the actual validation performed. Record game-test feedback
separately against the tested package SHA256. Offline validation does not imply
an in-game test. If the user renamed a matching package, preserve that rename.

For regressions, read [verified-case.md](references/verified-case.md), which
separates user-confirmed game behavior from measured offline checks and labels
older experimental branches. Do not inherit those branches as current defaults.
The [Lossi raw-input trial](references/lossi-raw-trial.md) verifies the complete
base-PMX front end, including the separate A-to-T intermediate. The
[SuoMing dual-suit trial](references/suoming-dual-suit-trial.md) records the
first Lv1+Legacy package and the multi-mesh BLEND front end.
