# Verified Huohua case and historical branches

## Current optional default: SuoMing matched skeleton with Head compensation

The user confirmed package SHA256
`74a09a0024a6874065e8982b40685eb10a4dba11a7ee60a79245bba2ab0f4472`
effective and requested matched skeleton plus Head visual offset as a default-on
option. The user also requires one final FBMOD. Follow
[skeleton-correction.md](skeleton-correction.md); the historical no-skeleton
default and rejected probes below do not supersede that explicit selection.

The self-contained skill helpers regenerated the same raw SkeletonAsset and
globals payloads from SuoMing's prepared BLEND, exactly matching the confirmed
package. They merged those with the unchanged base into a single FBMOD and
read it back to verify the exact union of raw inputs. The offline test artifact
is `extracted/dsr_jobs/skeleton_skill_validation_v2/job/package/skeleton/combined/`;
its SHA256 is `fadc9cf137530dbab20f0fcfb4ab0043cd493c359099b575e05eb570c2d483a6`.
This new merged artifact was not installed or separately game-tested.

The combination is case-confirmed, not all-model/all-animation acceptance.
Keep the new optional default distinct from the historical experiments below.

This case is evidence for workflow decisions, not a universal model preset.
Original source and third-party/game assets are not bundled with the skill.
Source snapshot hashes and adapted module hashes are in `data/provenance.json`.

The current skill defaults to packaging Isaac Lv1 and Legacy together and to
placing job output beside the source model; the Lv1-only Huohua case below is
still the source of the material-pair and lighting lessons. See
`suoming-dual-suit-trial.md` for the first dual-suit package.

## Current user-confirmed package

`E:/mod/DeadSpace/extracted/huohua_no_inner_faces/package/release/huohua_lv1_v1.fbmod`

- SHA256: `edb001ad047a018a7850bf7b8ef5af44242bbefe62bfcdc8f724efaccec6ad7a`.
- Size: 15,192,903 bytes.
- Original build name: `huohua_lv1_no_inner_faces.fbmod`; the user renamed it.
- Corresponding BLEND:
  `extracted/huohua_no_inner_faces/huohua_no_inner_faces.blend`.
- User reported the skirt/collar blackening solved. Earlier localized-fitting
  improvement reports do not establish correct whole-character deformation;
  exhaustive animation/backside coverage was not confirmed.
- This release includes no SkeletonAsset or animation override.

Original project: `tests/huohua/huohua_mmd.blend`, SHA256
`87ae2b094439e0b072a54eb5f16e5df82464f4f6ba58db022219c90cf386bf9a`.
It was already pose-converted and user-aligned. Do not apply pose conversion
again when reproducing this case.

Measured preparation:

| Stage | Case-specific measurement |
| --- | --- |
| Original materials | 42 |
| Removed fully transparent alternate face | 2,608 triangles |
| Atlas | 8192 RGBA; SHA256 `637a76f8cf422ad6253671f79c10235a23fe33421fff562ae79d692521f30d3b` |
| Original / cleaned mod bones | 453 / 51 |
| Prepared visible triangles | 49,619 |
| Uniform shoulder scale | 1.06640781881691 |
| Arm extension at 15-degree minimum bend | Approximately 12.10% |
| Fitted Hand/finger bones | 32 total, plus four arm/forearm bones adjusted |
| Reversed inner triangles removed | 4,269 |
| Final triangles / parts | 45,350 / 11 |

Confirmed inner material pairs, only for this exact original material order:
`[[15,28],[19,30],[20,29],[21,32],[22,31],[23,33],[38,39]]`.
Removed counts: skirt 1667, waist lace 535, upper clothing 104, sleeve lace 422,
shoulder decoration 167, collar 1026, rear ribbon 348. Fourteen geometrically
reversed upper-clothing faces with different weights were retained, as were
glass and unrelated overlays.

Current part triangle counts:
`core=8680, spine=2948, head=18604, leftarm=1351, rightarm=1553,
leftforearm=3247, rightforearm=4289, leftupleg=562, rightupleg=958,
leftleg=1590, rightleg=1568`.

## What was superseded

- Full native-body fitting excessively stretched the model and was rejected.
- Copying Neck frames without mesh deformation was proposed, then canceled.
  The user requested shoulder scaling only; it remains a geometry checkpoint.
- Skeleton position overrides were tested separately. The user subsequently
  chose native-skeleton-driven geometry fitting; these experiments do not
  establish a general runtime displacement correction.
- The hand-only package intentionally used the old importer and white PACKED_1
  for an isolated experiment. It is historical, not a current combined baseline.
- `huohua_lv1_hand_ik_normal_fix.fbmod` combines hand fitting with correct normal
  maps and normalized frames, but predates the final inner-face cleanup.
- Reference-mod topology/atlas/composition observations were useful. Its white
  PACKED_1 values were wrong for this Lv1 material setup.

On 2026-10-18 the user clarified that apparent displacement can affect all
weighted mesh regions. Its cause remains unresolved. Current animation
extraction/parsing are not fully correct, so exported animation channels
must not be used as proof of runtime bone behavior or a displacement diagnosis.
Earlier localized explanations have been removed.

## Local detailed records

When investigating the historical case, consult only relevant records under
`E:/mod/DeadSpace/docs/`: `dsr-huohua-preparation-workflow.md`,
`dsr-huohua-shoulder-scale.md`, `dsr-huohua-hand-ik.md`,
`dsr-huohua-hand-normal-fix.md`, `dsr-huohua-no-inner-faces.md`,
`dsr-huohua-dark-garments.md`, and `dsr-huohua-shading-audit.md`.
They contain old implementation paths and historical instructions; the current
combined baseline and the bundled skill's defaults take precedence for new work.

## Skill forward-test on 2026-10-17

The new bundled pipeline was exercised from the original pose-converted Huohua
BLEND through atlas, rig, split, scale, hands, cleanup, eleven FBX exports,
FBMOD build, actual package readback, validation and release. It reproduced
the exact shoulder factor, 51-bone rig, 4269-face removal and 45350 final
triangles. Configuration used this case's inspected material pairs; those are
not the initializer defaults.

Generated test job: `E:/mod/DeadSpace/extracted/dsr_jobs/skill_validation/`.
Test package SHA256:
`8d1a081574d7fa5f21ffb47bd8dd2277517b0ba5f2f7f512cd5689354fcb1b26`.
This is an offline validation artifact; it was not installed or tested in game
and does not supersede the user-confirmed v1 release.

All readback geometry, UVs, weights and bind arrays matched the user-confirmed
baseline exactly. Thirty-four of thirty-five modified-resource payload hashes
were identical. The sole difference was the re-exported head mesh chunk's
tangent/binormal arrays, with maximum direction change below 0.000007 degrees.
Front, back and colored part previews were rendered and visually inspected.
Readback reported five zero tangent/binormal entries (two in head and three
in leftforearm). Their zero-vector masks match the user-confirmed baseline
exactly; the new automation did not introduce them. They remain recorded rather
than being hidden by a unit-vector-only validation summary.

Additional checks passed: five job/runtime contract tests, six pose conversion
regressions against the bundled engine (including preserved leg pitch and foot
orientation), and four arm-solver regressions against the bundled engine. The
repository standalone suite had twelve passes and eight Blender-only skips.
Skill frontmatter/scaffold validation and Python compilation also passed.
The source project and successful package were checksum-verified unchanged.
