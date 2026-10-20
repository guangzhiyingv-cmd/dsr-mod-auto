# Standalone animation repair requirement

The skill produces **character content only**: the geometry/material package and
the matched skeleton correction. It does not build, merge or copy the animation
translation repair.

`--animation-fix` records that the character requires the standalone repair. It
adds this block to the preflight, build and verification reports and to
`<name>.release.json`:

```json
{
  "enabled": true,
  "required": true,
  "separate_package": true,
  "merged": false,
  "package_name": "dsr_animation_fix.fbmod",
  "note": "Load the standalone dsr_animation_fix.fbmod together with this character package. The repair is not merged into character builds."
}
```

`release` also prints the reminder. There is no bundled repair asset in the
skill any more, and the legacy `--animation-fix-mod`,
`--animation-fix-archive` and `--animation-fix-manifest` options were removed.
Old configuration files that still contain those keys have them dropped on load.

## Why the repair is separate

The repair is independent of the character body and covers several shared
animation banks that must stay consistent with each other:

- the Ishimura root bank,
- the shared human CQC/execution bank,
- the neutral story performance banks,
- all sub-level (`dsub_*`) banks.

Merging it into each character package duplicated the same payloads, made the
character mod grow by hundreds of megabytes, and tied the bank coverage to one
character release. Keeping it standalone also keeps the removal of the unsafe
channel-removal method in one place; see
`docs/dsr-animation-fix-cross-bank-failure.md`.

## Validated package (2026-10-20)

- `Mods/Shared/dsr_animation_fix_standalone/package_full/dsr_animation_fix.fbmod`
- SHA-256 `357651cc41ac6f698e8a03b3f6615721737ad3af96603045d682a375b341b446`
- 863,799,742 bytes, 105 unique payloads under 390 resource names
- Contains the Ishimura, all 34 corpse/CQC aliases, 19 story, 74 sub-level and
  296 creature/NPC/gameplay corrections (including the shared
  `creature_character_bundlegen_win32_antstate` CQC bank)

The earlier 95-payload package (`2e6de06d...`) is superseded; it did not cover
the creature banks that provide the player half of execution animations.

Character counterpart built without merging the repair:

- `Mods/Shared/dsr_animation_fix_standalone/character/suoming_v2_character.fbmod`
- SHA-256 `3155358bbb031db2a184991f0d1df4c1a139ebaf80d60d0689e7256f1fb5354a`

Enable both packages in the mod manager. The character package alone will show
joint offsets wherever the matched skeleton's local translations differ from the
native rig.
