# Packaging and verification contract

Two inspected target suits can share one package. Each is fixed by the game's own
resource, section, texture-family, and composition layout; do not interpolate
paths or reuse one suit's names for the other.

| Target | Mesh resource root | Texture root | Families | Composition |
| --- | --- | --- | --- | --- |
| `isaac_lv1` | `Game/Assets/Characters/Bodies/IsaacSuitLvl1/Parts/Cha_Body_IsaacSuit_Lvl1_` | `.../IsaacSuitLvl1/Textures/T_Cha_Body_IsaacLvl1_` | TopBody, LowerBody | `Game/Gameplay/Items/Suit_Level1_VisualItem` |
| `isaac_legacy` | `Game/Assets/Characters/Bodies/IsaacLegacy/Parts/Cha_Body_IsaacSuitLegacy_` | `.../IsaacLegacy/Textures/T_Cha_IsaacSuitLegacy_` | UpperBody, LowerBody, Backpack, Helmet | `Game/Gameplay/Items/Suit_Legacy_VisualItem` |

## Mesh resources and FBX structure

Each part FBX has exactly one mesh and the cleaned deform rig. The mesh object is
renamed to the suit's active section node `<Section>:lod.000` before export. The
FBX importer maps the node name to that section of the target MeshSet, so a wrong
section name fails the import rather than silently landing elsewhere.

| Part | Lv1 node | Legacy node |
| --- | --- | --- |
| core | `LowerBody:lod.000` | `Backpack:lod.000` |
| spine | `TopBody:lod.000` | `Backpack:lod.000` |
| head | `TopBody:lod.000` | `UpperBody:lod.000` |
| leftarm / rightarm | `TopBody:lod.000` | `UpperBody:lod.000` |
| leftforearm / rightforearm | `TopBody:lod.000` | `UpperBody:lod.000` |
| leftupleg / rightupleg | `LowerBody:lod.000` | `LowerBody:lod.000` |
| leftleg / rightleg | `LowerBody:lod.000` | `LowerBody:lod.000` |

Each FBX selects exactly one mesh and its cleaned deform rig. During export,
the rig is named `Reference`, the mesh is unparented with world transform
retained, and the mesh has the exact section node. Export mesh/armature only,
selection only, tangent space, triangles, no leaf bones, no animation, no
modifier evaluation. Restore names and parenting afterward. Exported FBX
rest/bind transforms do not replace the game's SkeletonAsset.

## Plan and composition

`character_plan.tsv` has exactly three tab-delimited columns per non-comment
line: operation, original asset identity, and input path or explicit item names.
For `T` targets it has `11*T` mesh rows, `3*sum(families)` texture rows, and `T`
suit-composition rows. No skeleton/animation EBX rows belong to this workflow.

Texture identity is `<suit texture_root>{Family}_PACKED_{0|1|2}`, using each
suit's own families from the table above.

Remove exactly these original items per suit, preserving remaining item order and
every other field:

- Lv1 (`24 -> 19`): `SAPP_Cha_Body_IsaacSuit_Lvl1_LeftHand`,
  `SAPP_Cha_Body_IsaacSuit_Lvl1_RightHand`, `SAPP_Cha_Body_IsaacSuit_Lvl1_LeftFoot`,
  `SAPP_Cha_Body_IsaacSuit_Lvl1_RightFoot`, `SAPP_Cha_Body_IsaacSuit_LvlX_Collar`.
- Legacy (`27 -> 23`): `SAPP_Cha_Body_IsaacSuitLegacy_LeftHand`,
  `SAPP_Cha_Body_IsaacSuitLegacy_RightHand`, `SAPP_Cha_Body_IsaacSuitLegacy_LeftFoot`,
  `SAPP_Cha_Body_IsaacSuitLegacy_RightFoot`.

New targets/compositions need explicit inspected adaptation rather than broad
name matching.

## Build and actual readback

Use `dsr_job.py build`, which runs these commands sequentially in the configured
runtime directory and records logs, argv, input hashes and package SHA256:

```text
DsrCli.exe --game <game> export-xml <composition> <composition_baseline_<target>.xml>   # per target
DsrCli.exe --game <game> package-character <plan.tsv> --out <character-dir> --mod-name <name>
DsrCli.exe --game <game> export-mod-assets <fbmod> --out <readback-dir> --skeleton Game/Anim/Rigging/Player/Player_Skeleton
DsrCli.exe --game <game> inspect-mod-assets <fbmod> --out <inspection-dir>
```

Do not run concurrent DsrCli processes using one runtime; they share `sdk.log`.
The CLI reads installed game assets for packaging; it does not apply the mod.

`verify` checks the actual FBMOD resource inventory (`T` EBX,
`11*T + 3*sum(families)` RES and the same number of chunks), exact expected
RES/EBX identities, `11*T` active meshes, source/readback triangle counts and
symmetric positions, two named UV channels (`UVChannel0` plus a zeroed
`UVChannel1`), corner-associated skin weights within byte
quantization tolerance, finite near-unit frames, decoded textures, and
composition-only changes. FBMOD internal empty embedded records are not extra
modified game assets. Treat reported zero tangents and visual seams as specific
follow-up concerns rather than blindly accepting a pass flag.

`package-character` writes fixed `composition_before/after.xml` names that the
last suit overwrites, so `build` captures each suit's baseline with `export-xml`
instead; `verify` diffs every baseline against the modified EBX the mod exports.
Both writers emit the same `BadRef` reference form, so members are matched by
their trailing file GUID.

The current readback checker allows position error below `0.000015` Blender
world units, UV component error below `0.0005` for Half2 storage, and skin-weight
component error below `0.02` for byte normalization. It records measured maxima;
these are storage-aware check bounds, not exact-equivalence claims. Legacy
sections store vertex positions at lower precision than Lv1: measured Legacy
error is approximately `1e-5` against `1e-9` for Lv1, both within the bound.
Diagnose unexpected errors near those bounds instead of increasing them without
evidence.

For an isolated geometry or texture repair, compare resource hashes to the
previous package and constrain changes to intended identities. For unchanged
parts, reusing hash-verified prior FBXs avoids unrelated tangent recalculation.
Mesh import chunk snapshots accumulate modifications; do not identify a part's
own chunk by choosing the first file. Follow plan mesh order and compare
successive snapshots or resolve the mesh resource's actual chunk ID.

`release` copies only after successful validation of that exact FBMOD hash.
Keep a separate game-test feedback record with reporter, date, issue, result,
package path and SHA256. Preserve build-time `runtime_tested:false` history.
Never infer animation/backside coverage from a single screenshot or user report.

## Default skeleton correction and one-package delivery

The inventory counts above describe the validated base input. By default,
`skeleton_correction` adds one SkeletonAsset EBX and one globals ANT RES, with
no extra chunks. The final merged inventory is therefore `T+1` EBX,
`11*T + 3*sum(families) + 1` RES and the original chunk count. Verify the base
geometry/composition first, the skeleton separately, and every merged raw
payload against the exact disjoint union. Deliver only the merged FBMOD.
With correction disabled, the base counts and original skeleton apply.
Read [skeleton-correction.md](skeleton-correction.md) for construction and limits.

## Application is a separate task

Dead Space's Frosty fork physically applies compiled data to the installed
game's Data tree, using its backup/restore system. It is not merely a runtime
`-dataPath` redirection. Do not install as a side effect of building a skill or
package. When installation is requested, use the repository's loading notes and
the configured manager's backup-aware process; do not manually overwrite CAS
files as a shortcut. Starting the game remains a separate explicit action.
