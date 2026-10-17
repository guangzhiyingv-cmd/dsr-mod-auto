# SuoMing Lv1 + Legacy dual-suit trial

Recorded on 2026-10-17. This is the first job that packages two suits into one
FBMOD and the first that starts from a prepared multi-mesh BLEND rather than a
PMX or a single-mesh BLEND. It was validated offline only; no installation or
in-game test was performed.

## Source and outputs

- Input: `E:/mod/DeadSpace/Mods/SuoMing/SuoMing0.blend`.
- Input SHA256: `72ff368fb746b66510b7dd9dc48c8f8d9a774232c43bb0a329d40c10449990fa`.
  It imports as one armature `suoming_arm` (640 bones, 82 constraints, identity
  rest pose = raw MMD A-pose) and two meshes `body` (32,992 vertices) and `head`
  (32,085 vertices), both with 5 UV layers and custom normals.
- Job config: `E:/mod/DeadSpace/Mods/SuoMing/suoming.json`.
- Generated job: `E:/mod/DeadSpace/Mods/SuoMing/suoming_job/`.
- Released package: `E:/mod/DeadSpace/Mods/SuoMing/suoming.fbmod`, 27,392,697
  bytes, SHA256
  `9f528a631089de4b41a8ed550450b41c4dc0a5c765a51231dfdc014688e1f91c`.
- Targets: `isaac_lv1` and `isaac_legacy` in one package.

Generated output now lives beside the source model: intermediates under
`<model_dir>/<name>_job/` and the release under `<model_dir>/`. The job config
records `release_dir`.

## Prepared BLEND front end

The source is a raw-MMD-rig BLEND, so the job used `--source-pose AUTO` (a
non-raw default of `DSR` would wrongly skip the pose stages), `--rig
suoming_arm`, `--mesh body head`, and `--source-mesh-parts head:head`.

- Multi-mesh inputs are supported by joining them at the atlas stage (materials,
  UVs, weights, custom normals and source IDs preserved). A later per-face
  `source_mesh_id` and the recorded mesh names let `split_parts` restore the
  hand-made head/body boundary instead of recomputing it by weight.
- `source_mesh_parts head:head` maps the whole `head` mesh to the DSR `head`
  part; the other ten parts are allocated by weight inside `body`. The head part
  is exactly the source head mesh (43,342 triangles), not a weight-derived
  boundary (a weight-only split had produced 43,124).
- The prepared-BLEND material adapter reads opacity and the base-color image from
  an MMD shader when present, else from the connected Principled node and its
  image. Extra source UV layers are dropped during atlas preparation; the final
  mesh keeps exactly `UVChannel0` (atlas UVs) and a zeroed `UVChannel1`.

## Preparation and measurements

- Pose routing: `AUTO` measured depressed upper arms at about -35.77 degrees on
  both sides, classifying A-pose; the saved intermediate converted A -> T -> DSR
  with zero measured arm-direction error. Legs used spread-only conversion.
- Static freeze baked the neutral shape-key mix (no non-default morphs) on a
  copy, removed copied constraints, and kept topology and custom normals.
- Atlas: 8192 RGBA, no fully transparent layer removed, SHA256
  `9966a229f07cabe5adbc2e7dc38543f56bf7fc8e495e3df19f14d03bb61e6b84`.
- Rig cleanup retained 51 DSR bones and merged 589 extras.
- Shoulder-height factor `0.014142418500741551`, bridging the raw import units
  and the native comparison scene; it is not a body-proportion decision.
- Hand/finger fit extended both arm segments by about 15.6% to reach native
  wrists at a 15-degree minimum bend; palm width scale about 1.35.
- Part triangles: core=1012, spine=24590, head=43342, leftarm=1890,
  rightarm=1891, leftforearm=3405, rightforearm=3405, leftupleg=785,
  rightupleg=785, leftleg=2422, rightleg=2422.
- No confirmed inner/outer material pairs, so the duplicate-layer cleanup
  removed zero faces.

## Suit contract differences learned

Both suits use part suffixes `core..rightleg`; only the roots, families,
section nodes, composition and removals differ. See `packaging.md` for the full
table. Points confirmed on this job:

- The CLI `package-character` is plan-driven and suit-agnostic, so a target only
  needs correct asset identities, FBX section node names and composition rows.
- Legacy FBX section nodes are `Backpack` (core/spine), `UpperBody`
  (head/arms/forearms) and `LowerBody` (legs); Lv1 uses `LowerBody`/`TopBody`.
  A wrong node name fails the import rather than silently landing elsewhere.
- Legacy texture families are UpperBody, LowerBody, Backpack, Helmet (12
  textures); Lv1 has TopBody, LowerBody (6). Both use the same atlas PNG.
- Legacy's composition removes four hand/foot items (27 -> 23); Lv1 removes
  those plus the LvlX collar (24 -> 19).
- `package-character` writes fixed `composition_before/after.xml` and
  `removed_items.txt` names, so the last suit overwrites the first. `build`
  captures each suit's baseline with the standalone `export-xml` command
  instead, and `verify` diffs every baseline against the modified EBX that the mod
  exports. Both writers emit the same `BadRef` reference form, so members are
  matched by trailing file GUID.

## Readback validation

`passed=True`; no skeleton or animation override. Modified-resource inventory:
2 EBX, 40 RES, 40 chunks (22 meshes + 18 textures). Both compositions changed by
exactly their removal sets with every other field identical and order preserved.
Measured maxima: position `/1.09e-5`, UV `/4.88e-4`, skin weight `/4.94e-3`.

Two storage properties were verified against the game's own original resources,
not treated as defects:

- Legacy sections store no Tangent array (only Normals and Binormals), whereas
  Lv1 stores all three. The game's original Legacy mesh exports the same way, so
  the frame check requires each suit's stored frame set.
- Legacy stores vertex positions at lower precision than Lv1: about `1e-5`
  against `e-9`. Both are within the storage-aware bound.

Legacy PACKED_1 uses the flat `(128,128,255,0)` normal for consistency with the
verified Lv1 lighting; Legacy's packed-channel meaning is not independently
verified and needs an in-game check. Offline validation does not imply an
in-game test.
