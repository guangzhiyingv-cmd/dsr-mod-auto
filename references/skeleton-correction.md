# Optional skeleton correction, enabled by default

Set `skeleton_correction: true` (default). Disable it with initializer flag
`--no-skeleton-correction` or explicit JSON `"skeleton_correction": false`.
Do not ask again whether to enable the established default. A disabled job
keeps the original SkeletonAsset and ANT resources. Missing dependencies or a
failed correction are errors, not permission to silently omit the default.
If all prepared anchors already match the native reference, record a validated
no-op and release the body package without fabricating a skeleton override.

Deliver ONE FBMOD containing body geometry, textures, suit composition,
matched SkeletonAsset and matched ANT defaults with Head visual compensation.
Do not ask the user to enable separate body/skeleton packages. Internal build
FBMODs are intermediates; only the merged hash-validated character is released.

## Required inputs

Use the final prepared `DSR_Rig` in the exported working BLEND, after pose
conversion, scaling and hand fitting. Do not fit geometry to native proportions
again. The native BLEND/XML, original raw EBX and original globals bank must
refer to the same game build. Preserve original assets.

New job configuration records:

- `skeleton_cli`: CLI supporting import-skeleton-translations, extract-mod and
  the validated Frosty package writer. Separate from the normalized mesh CLI.
- `skeleton_globals_bank`: original `globals_shared.bin`.
- `skeleton_baseline_ebx`: original raw Player_Skeleton EBX.
- `skeleton_compiler`: VS2022 Roslyn csc.exe, used for packaged C# helpers.

Initializer overrides are `--skeleton-cli`, `--skeleton-globals-bank`,
`--skeleton-baseline-ebx`, and `--skeleton-compiler`. The example defaults resolve
the first three under the configured workspace and the compiler under
`D:/VisualStudio/MSBuild/Current/Bin/Roslyn/csc.exe`. Preflight checks and hashes
them when enabled. The original mesh runtime normalization check still applies.
Existing configurations without the boolean now select the enabled default;
preserve old jobs and use fresh output for the changed build behavior.

## Construction

`dsr_job.py build` runs the bundled `skeleton_correction.py` after base packaging.
It invokes helpers under `scripts/skeleton/`; no historical case script is loaded.

1. Read the final prepared rig and unedited native rig in disposable Blender.
   Require identity pose/no constraints and preserve their world/unit conversion.
   Convert source heads with `inverse(native_world) * source_world`.
2. Match native ModelPose positions to this model's DSR-named anchors; unmapped
   helpers inherit their nearest mapped ancestor's displacement. Preserve
   native rotations and hierarchy. Recompute matched local/inverse transforms.
3. Match Player_Rig ANT default translations to the same positions, using
   parent rotation/scale and the audited native/ANT index mapping. Do not decode
   or rewrite animation clips. Preserve the ANT extra joint/index relationship.
4. Compute the remaining conditional Head residual: evaluate original Head.t
   under the matched reference parent, holding other matched locals fixed.
   The visible compensation is the NEGATIVE of observed-minus-target Head
   model-space position. Do not use a world-axis average from arbitrary frames.
5. Over the MATCHED EBX, apply the existing visual-offset convention only to
   Head and its descendants: subtract the requested visible delta from their
   ModelPose translations and recompute inverse binds. Preserve MATCHED
   LocalPose and every non-Head bind exactly. Preserve matched ANT bytes exactly.
   If Head.t needs no correction, skip that compensation, retaining matched.
6. Merge body and skeleton inputs into one final package with disjoint resource
   identities. Extract the actual final FBMOD and require its raw payloads to
   equal the exact union of the validated inputs. Reject overlaps or extra edits.

Never reuse SuoMing's 339 descendant count, 51 retained-bone count, or its delta
`(1.1685968e-7, -0.043791414, -0.027454737)` for another model. Compute each
profile afresh. Reversing the visible/bind signs repeats the old wrong-direction
failure. Applying the compensation over the original EBX would discard matched
body corrections. Do not layer old skeleton or animation probes over the result.

## Verification and release

Base geometry/material/composition checks still run against the validated base
readback. The merged package's exact raw-payload union proves those same body
resources are carried forward; the independent skeleton validation checks:

- Expected SkeletonAsset EBX plus globals RES, no skeleton chunks.
- Native names, hierarchy and rotations retained.
- Matched LocalPose unchanged during Head compensation.
- Non-Head bind data unchanged relative to matched.
- Model/inverse consistency and correctly signed Head compensation.
- Matched globals payload byte-identical after compensation.
- Final merged identities and raw payload hashes match both input inventories.

`build_manifest.json` selects the merged package. `verify` and `release` recheck
its hash and skeleton/readback artifacts. Release copies only that one FBMOD.
Reports remain under `package/skeleton/`; intermediate packages are not user
deliverables. Record input/source/tool hashes and preserve originals.

## Evidence and limits

The user confirmed SuoMing's matched-plus-Head package effective, SHA256
`74a09a0024a6874065e8982b40685eb10a4dba11a7ee60a79245bba2ab0f4472`.
They then requested this default optional workflow and a single final FBMOD.
That establishes this tested combination; it does not verify every character
or animation state. Keep user feedback separate from build-time runtime flags.

Visual offset compensates mesh binding; it does not move evaluated joint
centers, IK targets or weapon sockets. Head rotation and later deformation can
affect the result. Inspect the whole skinned character, head turns, weapon
contact, feet and transitions for each new model. The complete animation parser
and final renderer palette remain unverified. Do not restore the old claim
that apparent displacement universally affects only hands/neck.
