# Geometry, pose, and skinning

## Deformation evidence limits

The user clarified on 2026-10-18 that apparent displacement is observed across
all weighted mesh regions in the tested case. Do not frame it as a defect confined to selected joints
or assume the rest of the body is unaffected. Current animation extraction
and parsing are not fully correct; exported channel tables and transforms
cannot establish runtime displacement causes. Keep geometric fitting steps
as empirical preparation operations, not a proven general correction or an
animation-based diagnosis. Review the entire skinned character in game.

## Pose conversion

Raw A-pose inputs first pass through `_tpose_core.py`. Detect pose from actual
upper-arm/forearm joint directions in a character frame, not from a filename
or an assumed fixed forty-five-degree angle. A clear A-pose rotates each upper
arm and forearm about its own joint to form straight lateral T-pose arms. The
mesh follows and the intermediate is baked to rest. Finger local articulation
and hand roll follow their ancestors; torso, legs and feet are not targeted.
A measured T-pose requires no A-to-T rotations. An ambiguous asymmetric or
deeply posed source needs inspection. Store before/after angular measurements.

Then run the T-to-DSR engine below. Do not bypass this sequence for raw A-pose
models, and perform height alignment only after the DSR pose is established.

The bundled `_pose_core.py` and `data/dead_space_pose.json` derive directions
from the original Player_Skeleton semantic reference. They work independently
of the installed Modding-Toolkit UI. A compatible source mapping can still be
read from that add-on's preset directory.

Use character-local segment directions for upper body and arms. Keep the
pelvis anchored and model bone lengths/proportions. For thighs/shins, change
sideways spread only, using the upright native reference and a frame derived
from the armature's up axis and projected shoulder span. Preserve original
forward/backward leg pitch. Restore full foot/toe orientation after ancestors
move the ankle; their location can follow the adjusted leg.

This avoids the observed forward leg/foot tilt introduced by copying the
leaning game torso's frame into lower-body rotations. Non-uniform rig object
scale is rejected. The converter creates copies and bakes the result to rest.
It is not an MMD animation-controller or physics conversion.

## Atlas provenance and skin mapping

Before changing materials, record per-face `source_face_id` and
`source_material_index`, plus per-vertex `source_vertex_id`. Retain these through
splitting/filtering. Keep material identity even after all faces share an atlas.

The retained set comes from source semantic mapping plus the bundled DSR
mapping. Preserve retained bind matrices while renaming. Reparent to the nearest
retained original DSR ancestor, with disconnected joints. Preserve mesh world
transforms and check evaluated rest positions before/after cleanup.
Float checks must account for model scale: raw MMD imports and the tiny native
comparison scene can differ by roughly two orders of magnitude before alignment.
The helper records absolute errors and scale-relative position tolerances;
do not apply the old Huohua absolute threshold blindly to a meter-scale import.

For MMD ordinary and D deform leg chains, resolve aliases by anatomical role
before walking parents. Transfer ordinary knee/ankle/toe weights to their D-chain
counterparts where available. A literal ancestor walk can otherwise send toe
weights to Hips. Never drop unknown weighted groups silently.

Sum weights for every retained destination and normalize per vertex. Metadata
groups such as `mmd_edge_scale` and `mmd_vertex_order` are not skin influences.
The default static branch merges eyes and eye descendants into Head, and hair,
skirt, IK/control/physics helpers into retained ancestors. This loses their
independent animation/physics intentionally; change the policy if requested.
Constraints, unsupported modifiers, shape keys and unknown weighted roots must
be resolved on a copy before destructive cleanup. Do not silently discard them.

## Part allocation

Assign complete existing triangles by summed vertex weights per anatomical
region, using deterministic ties. Hands/fingers belong to forearms; feet/toes
to lower legs. Hips/Spine belong to core, higher spine/Neck to spine, Head to
head. Duplicated boundary vertices are expected; duplicated source faces are not.

`_prepare_core.extract_faces` preserves positions, material provenance, UVs,
weights, smooth flags, and per-corner custom normals. Blender may re-encode
normal vectors slightly; compare directions/tolerances rather than bitwise
normal bytes. Never recompute all normals merely because cloth boundaries open.

## Height scaling and targeted hand fitting

Select `height_alignment: "head"` (default) or `"shoulder"`. Head mode measures
the native and mod `Head` bone origins, not bone tails, mesh tops or headwear.
Shoulder mode measures the mean `LeftShoulder`/`RightShoulder` bone-origin
height. Measure both rigs in a common world frame. Scale the
whole mod rig and its parented meshes uniformly around the common pivot:
`factor = target_height / source_height`. Keep mesh-local coordinates, weights,
UVs and rest-bone local data unchanged. The tested case uses world origin and Z
up. Different scene origins require an explicit coordinate correction.
Record the selected mode and measured bone names in `reports/scale.json`.
Do not repeat scaling for a prepared model that already completed it.

Then use `_hands_core`:

1. Keep each upper-arm root fixed. Derive the original elbow pole from the
   source arm plane and transport it by the shortest root-to-wrist-axis rotation.
2. Solve the elbow with the law of cosines to reach the native wrist. If needed,
   extend both segments by the same ratio to retain the configured bend angle.
3. Fit Hand plus the thirty retained deform finger bones to native heads,
   tails and normalized world rest orientations. Use native joint-4 positions
   as terminal geometry targets for joint-3 finger segments.
4. Bake mesh deformation through anatomical frames: segment endpoints define
   length and index-to-pinky palm span defines transverse orientation. Preserve
   transverse arm/finger thickness, with explicit palm width fitting.
5. Transform custom normals by the inverse transpose of each blended local
   linear map. Reject folded/singular transforms. Then update rest-bone frames.

A raw native-rest-matrix delta can twist the model about ninety degrees because
MMD and native bone axes differ. Names alone do not establish axis equivalence.
Keep torso, Neck, head, lower body, upper-arm roots and unaffected vertices
unchanged in this localized stage. Validate native reference snapshots and
evaluated rest mesh to catch double deformation.

## Reversed inner-layer cleanup

Only confirmed material pairs are eligible. Group triangles by coincident
world positions (tested quantization `1e-8`), require opposite geometric normals
with dot product below `-0.99`, and compare position-associated skin weights
(tested rounding: seven decimal places). Remove the designated inner triangle
only when the match is unique. Retain same-winding duplicates, different-weight
faces, glass and unrelated overlays.

Validate surviving face IDs, UVs, positions, weights, custom normals and all
rig data. Inspect exterior and backside visibility; one-sided cloth can expose
holes when seen from inside. Thickness/two-sided shader work is separate from
this proven duplicate-removal fix. The exact renderer stage causing the black
result was not isolated.

## Coincident same-winding layers

Some source models draw one surface twice with the same winding: a skin layer
under a garment, or an exact duplicate triangle. These are not reversed inner
layers and the opposite-normal rule cannot remove them.

- `coincident_hidden_pairs: [[hidden, cover], ...]` removes a hidden triangle
  only when its three quantized world positions match a cover triangle, the
  geometric normals agree (dot above `0.99`), the skin weights match, and the
  cover samples fully opaque atlas texels at its centroid and at points twenty
  percent inward from each corner.
- `coincident_duplicate_materials: [material, ...]` collapses exact duplicates
  within a listed material (same positions, winding and weights) to one retained
  triangle.

The opacity test is mandatory. A transparent cutout (lace, stocking tops) needs
the skin underneath; removing it would open a visible hole. Both rules record
every removed face as `inner_face_id` in `reports/cleanup.json`, so the export
partition check continues to pass. Confirm material indices from the atlas
report or an inspection of the prepared scene; never copy another model's
indices.
