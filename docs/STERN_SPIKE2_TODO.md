# Stern Spike 2 — open work / TODO

Forward-looking backlog for the Stern Spike 2 plugin. Tester feedback comes from
**monkeybug** (real machines: Led Zeppelin, etc.).

---

## SD validation manifest regeneration — BUILT (pending hardware verify)

**Background.** A real-machine test of an audio mod (monkeybug, Led Zeppelin)
produced **no sound + a lockup/reboot** — even though our written image is
provably correct (re-encode is bit-exact mid-stream, size-neutral by
construction, and `_apply_writes` touches only the replaced slots, so every
unreplaced sound stays byte-identical). The failure is **game-side**: the card's
`/spk/index/<title>.sidx` manifest indexes every moddable file (`FI64` records,
88 bytes each) with the file's size, a **keyed HMAC-SHA1**, and a plain **MD5**.
A size-neutral mod keeps the size valid but makes the HMAC + MD5 **stale**, and
Stern's validator rejects it. Asset mods that *do* work on real machines work
precisely because the manifest is recomputed for the changed files.

**Fix (shipped in code, `plugins/stern/sidx.py` + `engine._compute_sidx_writes`/
`_overlay_digests`, default-on in `_compute_patches`):** after a Write, recompute
each changed file's `FI64` record — `[37:57] = HMAC-SHA1(K, file)`,
`[57:73] = MD5(file)` — with the global validation key `K` (recovered by RE,
verified to reproduce real stored digests incl. `image.bin`). Size fields stay
valid (size-neutral); header CRC `@0x34` is `0xffffffff` (disabled) on the modern
FI64 cards. Covers `image.bin` (cat-0 audio), `image-scNN.bin` music banks, and
full-replacement video/image/texture. Best-effort (a missing/odd manifest only
warns). Offline-validated end-to-end; `tests/test_stern_sidx.py`.

**▶ Remaining:**
- **Hardware verify:** small cat-0 audio swap → Write → boot a machine → confirm
  sound + no "Game validation error" (the log shows `Refreshed N … manifest
  record(s)`). monkeybug to test.
- **Radium display-text / radium-image edits are not yet manifest-updated** (the
  Write warns). Add: after applying their in-place writes, recompute the affected
  `scene.radium` inode digests into the manifest.
- Resolve the `_changed_music_banks` (engine.py "Write can't re-encode banks
  yet") vs `_compute_music_patches` comment contradiction.

## Re-encode tail bug (~5 ms lost at the end of every replaced sound)

`GenRecover.encode_sound` / `StereoRecover.encode_sound` (codec.py) leave the
**final output block** un-encoded: the per-block keystream recovery for the last
block uses cursor `200*(k+1)`, which reads body frames past the sound's end, so
`recover_block` returns fewer samples than the segment and the tail stays
`np.zeros` → decodes to silence/garbage for the last ≤200 samples. Confirmed on
LZ for mono (idx-dependent) and stereo (every short slot tested). Cosmetic for
one-shot SFX; audible as a click at the loop point of looping music. Fix is
delicate (the codec calibration is easy to destabilize — the bit-exact
round-trip must be preserved), so add a full-length self-round-trip test first.

## "Write image to SD card" feature (monkeybug request)

We can *build* an image or write changes in-place, but not flash a pre-built
`.img`/`.raw` to a card. Add a dd-style writer: pick an image, pick the target
card, raw-copy with progress.

- Reuse `plugins/stern/rawdevice.py` (`RawDeviceFile` over `\\.\PHYSICALDRIVEn`)
  + the Direct-SD admin gating already in place.
- Use the SD-card-biased drive picker (`direct_target_kind="sd_card"`) so the
  target defaults safely.
- **Size guard:** refuse / warn clearly when the image is larger than the target
  card (a too-big image crashed external imaging tools for monkeybug). Show image
  size vs card size up front.
- Confirmation + the existing red safety banner before any write.

## Built image "too big for the card"

monkeybug's built image was rejected by external imaging tools as too big for his
original card; a 16 GB card worked. Likely just SD-size variance, but **verify
`build_image` output size == source image size exactly** (a padded-larger output
would be a real bug). Then surface card-size guidance in the Build/Write UI and
in the writer's size guard above.

## Build time: long-song re-encode dominates (perf)

22 long songs → **2h17m** total, of which the **re-encode phase was 2h08m**; the
image copy was only ~6 min — **network I/O is NOT the bottleneck.** Cost is the
unicorn per-block keystream recovery, which scales with track length; full 5–8
min songs are the worst case (already fanned across processes). Optimization
lever is a faster keystream recovery (less unicorn per block), on the codec side.
