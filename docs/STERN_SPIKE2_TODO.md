# Stern Spike 2 — open work / TODO

## Open work (priority order)

### 1. Re-encode tail bug (~5 ms lost at the end of every replaced sound)

`GenRecover.encode_sound` / `StereoRecover.encode_sound`
([codec.py](../pinball_decryptor/plugins/stern/spike2/codec.py)) leave the
**final output block** un-encoded: the per-block keystream recovery for the last
block uses cursor `200*(k+1)`, which reads body frames past the sound's end, so
`recover_block` returns fewer samples (`m`) than the segment and the tail
`body[lo+m:]` stays `np.zeros` → decodes to silence/garbage for the last ≤200
samples. Confirmed on LZ for mono (idx-dependent) and stereo (every short slot
tested). Cosmetic for one-shot SFX; **audible as a click at the loop point of
looping music** (the crown-jewel use case now that audio plays on hardware).

**This is the top remaining engineering item, but it's delicate** — the codec
calibration is easy to destabilize and the bit-exact round-trip (the thing that
makes audio boot+play on a real machine, hardware-verified in v0.24.0) MUST be
preserved. Plan:
1. First add a **full-length self-round-trip test** (encode → decode → assert
   bit-exact over the WHOLE sound, including the tail) against a bundled card
   image under [images/Stern/spike2/](../images/Stern/spike2/). This both
   characterizes the failure and guards the fix.
2. Then recover the last block's keystream without reading past the body end
   (e.g. extend the probe margin / clamp the cursor), and verify the new test
   passes for mono + stereo with no regression elsewhere (`pytest`, TMNT
   sha1-identical round-trip).


### 2. Build-time perf — keystream-recovery speedup (codec)

The long-song re-encode that took monkeybug **~2 h** in v0.23.0
(https://pastebin.com/Ty8XZsHB) was substantially addressed in **v0.24.1**
(capstone disasm cache 3.7× + longest-first/chunksize-1 scheduling + parallel
fan-out across cores).

**Further codec-side speedup (2026-06-26, offline bit-exact, in `codec.py`).**
Profiling the re-encode (`c:\tmp\spike2_perf\`) showed the cost is **not** the
ARM emulation itself (~28%) but the **per-output-sample capture hook** that drives
the firmware codec to recover the keystream — it fires once per sample per probe
(hundreds of thousands of times for a long song) and the unicorn `mu.reg_read`
Python wrapper was ~30% of the whole job. Two changes, both validated
byte-identical (mono + stereo, all 32 TMNT scales + a generic build, fast path ==
fallback path, 0 mismatches):
- **Fast capture hook** — read the companding register straight through unicorn's
  C API (reused ctypes buffer, hook registered directly) instead of the slow
  per-call wrapper. Safe fallback (`emulator.fast_reg_read` → `None`) keeps the
  portable path if a future unicorn moves the internals. **~1.3× mono, ~1.4×
  stereo.**
- **Stereo 3→2 probes** — the per-block keystream recovery drove the codec three
  times (probe bodies `(0,0)`,`(1,0)`,`(0,1)`); the third only recovers the `u1`
  rotate `bR`, which is **≡0** (verified across all 32 scales and 18 k positions
  spanning the eight longest songs). `recover_block` now self-validates per scale:
  the first block does the full 3-probe check and, only if `bR` is all-zero, later
  blocks (and later sounds of that scale) drop the third probe. A build that ever
  shows `bR`≠0 keeps the full recovery — no assumption baked in, and
  `_recovery_valid` still guards every sound. **~1.5× stereo** (songs are stereo).

Combined: **~2× on stereo re-encode** (e.g. a ~5-min stereo song's recovery
≈ halved) on top of v0.24.1, output byte-for-byte identical. **Re-confirm on
monkeybug's next build.**

**After-encode derive passes (cat-0 restore — DONE 2026-06-26).** A cat-0 audio
Write paid TWO full ~2-min param re-derives after encode:
`_restore_masterdir_consumed` (capture the masterdir-consumed body bytes to
restore) + `_assert_param_integrity` (re-derive the patched image to confirm no
codec param shifted). Measured: derive = 120 s (88% in the sequential, NON-
parallelizable per-record band-build chain), so restore + assert = ~240 s FIXED
per Write regardless of how few sounds changed. **Fix:** the consumed offsets are
deterministic for a card, so capture them (free — a read-only hook, ~0 added time)
during the Extract derive and cache them (`_consumed_cache_path`); the Write's
restore then replays them with NO re-derive. Validated byte-identical to the old
derive-based restore (low/mid/high idx) and the assert still passes. **Restore
118 s → 0.01 s; cat-0 Write fixed cost ~240 s → ~120 s.** The integrity assert is
deliberately left UNCHANGED as the hardware backstop, so a stale/incomplete cache
can only abort a Write, never ship a bad card.

**Remaining levers (not yet done):**
- **The integrity assert (~120 s).** Now the dominant post-encode fixed cost on a
  cat-0 Write. It re-derives the *patched* image (edit-specific, can't be cached).
  Safe option not yet taken: run it concurrently with the image copy / SD write
  (CPU-bound assert ∥ I/O-bound copy), joining + aborting on failure.
- **Music-bank derive passes.** Each edited bank still derives 3× (`_derive_cat`
  for encode + `_restore_bank_consumed` + `_assert_bank_integrity`), but a bank
  holds only 1–2 songs so each derive is seconds, not minutes — minor vs the
  (now-2×-faster) long-song encode. Could fold the restore-capture into the
  encode derive like cat-0, but low value.
- **Analytic keystream (moonshot).** If the per-sample keystream `K` could be
  computed directly instead of recovered by emulation, the per-block emulation
  disappears entirely (100×+). Probed offline: `K` is *not* a trivial slice of the
  VF2 keystream table (0/200 match), so this needs real RE of the keystream
  generator — a research project, not a quick win.
- **Within-song parallelism.** A single very long song is an irreducible serial
  tail (one worker); its blocks are independent and could fan across workers.
  Marginal when there are already more songs than cores; helps the last-song tail.
