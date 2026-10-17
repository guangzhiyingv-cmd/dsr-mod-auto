# Lossi base-PMX forward test

Recorded on 2026-10-17. This trial starts from an original PMX, with none of
Huohua's manual Blender preparation. It validates the new raw-input branch
offline; no game installation or runtime test was performed.

## Source and outputs

- Input: `E:/mod/DeadSpace/Mods/Lossi/Lossi.pmx`.
- Input SHA256: `2ddc88f62ea9c801910904aadbb773833c82d0dd0afad6f614c670235de91e46`.
- Job config: `E:/mod/DeadSpace/extracted/dsr_jobs/lossi_raw.json`.
- Generated root: `E:/mod/DeadSpace/extracted/dsr_jobs/lossi_raw/`.
- Framed review project: `review/lossi_dsr_lv1.blend`.
- Test FBMOD: `package/release/lossi_raw.fbmod` (Isaac Lv1, character only).
- Package SHA256: `9c67bc4f0c1bc7cf60cf7234f7ff48533cb939fa232c2e84df448016476a9b7b`.
- Package size: 18,037,608 bytes.

Keep the original model and textures untouched. `raw_trial_manifest.json`
records the completed stage sequence, source/config paths, script hashes, and
locations of the detailed reports.

## Missing front-end work now automated

The PMX contains 70,533 vertices, 81,532 triangles, 514 bones, expressions and
28 constrained pose bones. Import retained morphs for inspection but excluded
physics simulation. Blender L/R renaming was required for the installed MMD
semantic preset. Original Japanese PMX names are recorded per bone.

Static freezing baked the visible neutral expression and evaluated controllers
on a copy before removing copied constraints, drivers and shape keys. Maximum
world-space rest error was approximately `2.07e-6` in the imported model's units.
All eight base textures were present. Missing shared toon bitmaps were unused
by the base-color-only atlas and were not replaced with invented textures.

AUTO measured depressed upper arms at approximately -39.63 degrees on both
sides, identifying A-pose. The saved T-pose intermediate had measured upper-arm
and forearm direction errors of zero within Blender's angular precision.
Only then did the existing T-to-DSR engine run, retaining spread-only leg
conversion and the source foot/toe orientation policy.

Saved intermediates are `stages/import.blend`, `static.blend`, `tpose.blend`,
`pose.blend`, `atlas.blend`, `rig.blend`, `split.blend`, `scale.blend`,
`hands.blend`, and `cleanup.blend`. The review project frames the final model
without changing the hashed packaging inputs.

## Remaining preparation and validation

The 8K atlas and current-visible policy removed 1,864 fully transparent
expression-layer triangles, leaving 79,668. Rig cleanup retained 51 DSR bones
and merged 463 extras. Position checks use recorded scale-relative float
tolerances because this raw import is much larger numerically than the earlier
prepared Huohua scene before alignment.

The shoulder factor was `0.012766657946521952`, including the imported/native
scene-unit difference. Both arm segments extended approximately 20.44% to reach
native wrists while retaining a fifteen-degree elbow bend. The final eleven
parts exported and the FBMOD passed actual readback validation:

- Eleven active meshes and six texture replacements, with expected Lv1
  identities and the five exact composition removals.
- Maximum position error approximately `6.11e-9` in native comparison units.
- Maximum UV component error approximately `0.0004881`, within Half2 precision.
- Maximum skin-weight component error approximately `0.00423`.
- Correct flat PACKED_1 maps and normalized nonzero stored frame vectors.

The head readback has one zero tangent/binormal entry, recorded in
`reports/zero_tangent_audit.json`. Its incident triangle has nonzero geometric
area and UV determinant; the exact cause was not established and no speculative
geometry/normal repair was applied. Front/back/part previews were inspected;
they do not substitute for an in-game shading or animation test.

The coincident-reversed-layer audit found zero matching position/weight pairs.
No Huohua material-pair indices or 4269-face cleanup were applied to this model.
The original native SkeletonAsset and animations remain the game drivers.

Six Blender regression tests cover A-to-T rotation, unchanged lower body/source,
T-pose passthrough, ambiguous/incorrect pose rejection, the T-to-DSR sequence,
and nonzero visible morph/controller freezing. Seven configuration/runtime
contract tests cover raw-stage ordering and prevent re-converting DSR input.
