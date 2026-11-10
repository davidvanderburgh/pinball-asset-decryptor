# Spike 3 SPK builder — mod-only incremental packages (PAD-1125)

Let a PAD user turn modded Spike 3 assets into a **small single-file SPK** they
can hand to someone, instead of redistributing a whole modded SD image
(gigabytes, and full of Stern's copyrighted OS). The receiver installs the one
file over USB; the machine itself unlocks it with its own on-board key, so **no
key changes hands and the installing user never needs the OTP key**.

This mirrors what PAD already does in reverse: `spike3_spk.py` *reads* a Spike 3
`.spk` (LUKS2 -> ext4 -> nested **SPKS** archive) and pulls the asset tree out.
The builder *writes* that chain back.

## The layers (outer to inner)

A Spike 3 `.spk` is:

1. **LUKS2** container (AES-XTS), unlocked by the fleet update key
   (`spk_keyfile`, aka "screen_timing") via its keyslot — PAD already does this
   (`spike3.read_luks_header`, `DecryptingSegmentReader`, `_luks_otp.verify`).
2. an **ext4** filesystem, whose root holds one nested `*.spk` file.
3. that nested file is an **SPKS** archive — every shipped file stored verbatim
   and by name (`spks.SpksArchive` reads it).

### Keys involved (none shipped; all user-supplied — PAD policy, PAD-1072)

| key | what it does | where in PAD |
|---|---|---|
| `spk_keyfile` (fleet update key) | unlocks the `.spk` LUKS2 keyslot | `spike3_keys.Spike3KeySource` |
| factory HMAC key (16 bytes) | signs each SPKS file (HMAC-SHA1) | **new**, optional, user-supplied |
| per-volume master key | alt unlock path | `spike3_keys` |

The **factory HMAC key** is a third key, distinct from both the OTP SD key and
the `spk_keyfile`. JayFoxRox's point: the signature is pointless as a barrier —
it is symmetric and every machine already holds the key — and `pack-spk` makes
signing optional (unsigned => 20 bytes of `0xAA` placeholder). We default to
**unsigned** and accept a user-supplied factory key when they have one. Whether
the installer actually verifies the HMAC is unknown; recorded as a gate decision.

## Build strategy: edit-in-place, not build-from-scratch

We do **not** synthesise a LUKS2+ext4 image from nothing. The user already has
the title's real `.spk` (the public update download). We:

1. unlock + open it (existing read path),
2. rebuild the nested **SPKS** with the user's modded files swapped in
   (new code: `spks_pack.py`),
3. splice the new SPKS back into the ext4 and **re-seal the LUKS2** under the
   same master key (new code — the inverse of `DecryptingSegmentReader`; ext4
   file replace via `debugfs`/`mke2fs` under WSL, or a minimal writer).

This reuses almost all the existing read code and sidesteps writing a full ext4
/ LUKS2 from scratch.

### Incremental vs full

Stern's `.spk` carries a full SPKS. A **mod** keeps every original file and
substitutes only the changed ones, so the output is a complete, valid package
(not a sparse overlay) — the reliable shape until the installer's overlay/merge
semantics are confirmed on hardware.

## Not-official marking (mandatory — JayFoxRox ske-spk-tools#pack-spk)

A PAD-built SPK must never be mistakable for an official Stern package. The
builder refuses to write without a mark, applying **all** of:

- a visible marker file in the package root
  (`NOT_AN_OFFICIAL_STERN_PACKAGE.txt`),
- a package **version** bump / name suffix the caller sets,

per JayFoxRox's note ("change the package name or version, or add a header
stating the file isn't official").

## Provability (honest, per repo rules)

- **SPKS writer: fully provable here.** Round-trip: pack -> read back with
  `spks.SpksArchive` -> assert identical paths/sizes/modes/bytes; unsigned
  placeholder HMAC; mark present. The format is already verified against real
  packages (our reader) and against Stern's own extractor (JayFoxRox).
- **Asset swap in the emulator: provable.** The Spike 3 emulator reads assets
  from the card; a repacked SPKS with a changed asset can be shown to change
  what the emulated game renders.
- **USB install on a real machine: NOT emulator-provable.** The rig never runs a
  card's init/updater chain (boot-script hooks aren't emulator-provable), and
  JayFoxRox never tested installing a crafted SPK. This stays **hardware-pending**
  and is stated as such; we do not claim it works until a Spike 3 machine
  confirms it.

## Status / increments

- [x] Phase 1 — `spks_pack.py`: SPKS writer + repack + mandatory mark; round-trip
  test. Fully provable, mergeable on its own.
- [ ] Phase 2 — LUKS2 re-seal + ext4 splice: produce the USB-installable `.spk`.
  Needs the user's `spk_keyfile` to exercise end-to-end; install stays
  hardware-pending.
