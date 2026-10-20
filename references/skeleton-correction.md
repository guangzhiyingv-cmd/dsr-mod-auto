# Matched skeleton correction, enabled by default

Set `skeleton_correction: true` (default). Match the final prepared rig's bone
positions in SkeletonAsset and ANT defaults. Do not apply fixed Head-subtree
visual-offset or inverse-bind compensation. The user superseded that temporary
operation on 2026-10-19 after confirming the animation-channel removal experiment.

The optional animation repair (`--animation-fix`) is independent of matched
skeleton correction. Read [animation-fix.md](animation-fix.md). When enabled it
is merged into the body before skeleton processing, including when skeleton
correction is disabled or is a no-op.

## Delivery modes

Default `skeleton_package_mode: "merged"` produces one character FBMOD containing
the repaired body and matched skeleton references. `--no-skeleton-correction`
retains its established CLI meaning: select split delivery, leaving matching on.
Release `<name>_body.fbmod` with the animation repair already included and
`<name>_skeleton.fbmod` with matched EBX/ANT only. Do not also enable the internal
merged audit package. Explicit JSON `skeleton_correction:false` with merged mode
produces the repaired body without a skeleton override.

If all prepared anchors match native references, validate a no-op and release
the repaired body. Missing dependencies or failed matching must not silently
turn matching off. Fresh jobs are required for this workflow revision; preserve
historical jobs and releases.

## Required inputs

Use final `DSR_Rig` after pose conversion, scaling and fitting. Do not refit its
geometry. Native BLEND/XML, original raw SkeletonAsset EBX and original globals
bank must refer to the same game build. Required config fields are:

- `skeleton_cli`: CLI with skeleton translation import and actual FBMOD readback.
- `skeleton_globals_bank`: original `globals_shared.bin`.
- `skeleton_baseline_ebx`: original raw Player_Skeleton EBX.
- `skeleton_compiler`: C# compiler.

`init` defaults the CLI to the bundled `runtime/DsrCli.exe`, the compiler to the
Windows .NET Framework `csc.exe`, and the bank and baseline EBX to
`references/data/native/`. Matching preflight hashes them. The CLI and compiler
are also required for the optional animation merge when `--animation-fix` is
enabled, and for matching.

## Construction

`skeleton_correction.py` runs only after the repaired body is available:

1. Read the final character rig and unedited native rig in disposable Blender.
   Require identity pose and no constraints. Convert source heads using
   `inverse(native_world) * source_world`; preserve native world conversion.
2. Match native ModelPose positions to the model's named anchors. Unmapped
   helpers inherit the nearest mapped ancestor's displacement. Preserve native
   hierarchy and rotations; recompute matched local and inverse transforms.
3. Match Player_Rig ANT default translations to those positions with the audited
   hierarchy and native/ANT index mapping. Preserve unrelated bytes and motions.
4. Package that exact matched SkeletonAsset EBX with the matched globals payload.
   Do not call `prepare_head.py`, create `head_bind`, or use visual-offset mode.
5. Require actual skeleton readback to equal the matched source in LocalPose,
   ModelPose, InverseModelPose and raw EBX bytes. Require globals readback to equal
   the matched payload exactly.
6. Merge repaired body and matched skeleton with disjoint resource identities.
   Extract the final FBMOD and compare every raw payload to the exact union.

Historical Head-compensation helpers and case reports are retained for research;
they are not current construction stages. Do not reuse a previous character's
measurements or stack historical skeleton/animation probes over a new package.

## Validation and limits

Geometry/material/composition checks use the validated base package. The required
animation merge and final skeleton merge each prove the exact raw-payload union.
`verify` and `release` recheck all recorded artifact hashes. Reports record
`mode:"matched_references"` and `head_visual_offset:false`.

The user confirmed the earlier SuoMing matched-plus-Head combination effective
in a particular test. Vivian later exposed weapon-dependent Head output: a fixed
Head correction cannot represent both observed translation references. The user
confirmed the targeted translation-removal experiment effective and selected it
for future builds. This does not prove every animation, controller or character.

The animation repair covers inspected player-rig Eclipse clips in the Ishimura
main gameplay bank. Other banks, procedural writers, final renderer palette and
complete evaluation ordering remain outside that guarantee. Review the whole
skinned character, Contact Beam idle/aim, normal weapons, movement, melee/stomp,
feet, contacts and transitions. Record new game feedback against its exact hash.
