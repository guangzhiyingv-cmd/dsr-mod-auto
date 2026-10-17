# Atlas and verified Lv1 material inputs

## One base-color atlas

The tested atlas uses Material Combiner 2.1.3.0 with Blender 5.2.2. Preserve the
current visible appearance, including visible translucency. Only fully
transparent shader layers are eligible for removal under the configured policy.

Tested settings are PO2, MAX_RECTS, 8192 square RGBA, 16-pixel gap (eight per
side), no crop, no extra maps, and `smc_pixel_art=True` to disable this add-on's
UV inset. Gutters repeat the opposite image edge. The resulting atlas
coordinates go into `UVChannel0`; the final mesh's second channel `UVChannel1`
is that UV scaled to zero. Retain the canonical PNG and pack it in BLEND.

The bundled preparation core supplies session-only adapters for Blender 5.2's
material API, alpha without RGB gamma conversion, and repeat-wrapped gutters.
It does not edit installed add-on files. RGB comes from the base texture/color;
MMD toon/sphere lighting is not baked into the atlas. Opacity and the base-color
image are read from MMD nodes named `mmd_shader`/`mmd_base_tex` when present, or
from the connected Principled node and its image otherwise. Extra source UV
layers are dropped during atlas preparation and recorded in
`reports/01_atlas.json`; every final mesh keeps exactly `UVChannel0` (atlas UVs)
and `UVChannel1` (all coordinates zero).

Do not change already-correct atlas UVs merely to fix lighting. Validate decoded
game texture RGB/alpha against the source atlas, including the problem region.
Alpha-zero RGB is allowed to differ after BC7 compression and is not evidence
that visible opaque cloth was blackened by compression.

## Suit texture contract

Every family of every target suit uses the same three replacement images:

| Slot | Source | Format | Tested size / mips |
| --- | --- | --- | --- |
| PACKED_0 | Base-color RGBA atlas | BC7_SRGB | 8192 / 14 |
| PACKED_1 | Flat RGBA `(128,128,255,0)` | BC7_UNORM | 512 / 10 |
| PACKED_2 | Constant RGBA `(255,0,255,255)` | BC7_UNORM | 2048 / 12 |

Lv1 writes this to TopBody and LowerBody; Legacy writes it to UpperBody,
LowerBody, Backpack, and Helmet. All families share one atlas PNG, so their
replacement payloads are identical.

The importer inherits native format and metadata, generates mipmaps, replaces
the original chunk identity, and links the texture RES. It deduplicates input
image conversion by path and format. Do not substitute a PNG filename or a
shader parameter for the actual texture resource replacement.

PACKED_1 readback `(128,128,254,0)` is expected BC7 rounding; 255 is also accepted.
Keep alpha zero. The exact shader interpretation of that alpha is unproven.
The earlier reference-style `(255,255,255,0)` is not a flat tangent normal and
caused incorrect lighting with the Lv1 materials. The same flat normal is used
for Legacy, but Legacy's packed-channel meaning is not independently verified;
PACKED_2's full channel semantics are also unproven. Preserve these constants
unless testing a specific material change, and confirm any change in game.

## Stored tangent frames

The correct normal image must be paired with normalized transformed Normal,
Tangent and Binormal vectors before the importer stores Half4 attributes.
The required source change is bundled as `data/frosty_unit_frame.patch`.
The successful frozen runtime manifest identifies the patched binary.

The Lv1 sections store Normals, Tangents and Binormals. Legacy sections store
only Normals and Binormals: the game's own original Legacy mesh exports with no
Tangent array, so the readback check requires exactly the suit's stored frame
set (`frames` in the suit contract) rather than all three everywhere.

On readback, check finite nonzero normals and near-unit N/T/B vectors, allowing
Half4 quantization. Flag zero tangents/binormals and inspect degenerate UVs;
the helper reports those counts and rejects non-unit nonzero vectors. Unit
length alone does not establish a correct tangent direction or mirrored-UV
handedness. Compare to the expected geometry/frame baseline when diagnosing
a new seam. Do not replace the normalized runtime with the old isolated hand
experiment runtime.

## Black clothing diagnosis

Separate texture values, stored frames, geometric orientation, overlapping
layers and original material behavior. In the verified case, opaque skirt
readback median was approximately `(227,225,228,255)`, atlas RGB error was small,
and stored frames were valid. Coincident reversed inner clothing layers remained.
Removing only matched reversed inner triangles solved the user-observed black
skirt/collar. This is a controlled-case result, not proof that every black
material has duplicate faces or that a specific depth/shadow pass is responsible.
