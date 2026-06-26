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


### 2. Codec slot-resolution NONDETERMINISM (generic builds) — CONFIRMED, fix deferred

`Spike2Emu._resolve_entry` ([spike2/emulator.py](../pinball_decryptor/plugins/stern/spike2/emulator.py))
caches the audio codec slot **per `(scale, chan)`, seeded by whichever sound
first hits that key**.  A loud sound seeds via pass-1 (0.6 s, specflat<0.45); a
quiet-intro sound seeds via pass-2 (3.5 s, noise-reject + lowest specflat).  When
the two passes would pick **different** slots for a key, the result depends on
decode ORDER — so the parallel extract (per-worker `_slot_cache`,
`imap_unordered`) and the single-emu revert/Write disagree, and even two extracts
can disagree.

**Reproduced on the bundled `led_zeppelin_le-1_20_0` image** (`c:\tmp\sidx_re\repro_revert_mismatch.py`):
extract-decode vs single-emu re-decode differ for **13 of 535** cat-0 sounds
(all stock-sounding, non-silent) — including **idx0439, idx0459, idx0231, idx0220,
idx0343, idx0352, idx0408, idx0422, idx0436, idx0443, idx0448, idx0503, idx0512**.
The first three are **exactly** the files monkeybug saw stuck as "Modified" in the
Write preview after a Revert (his card = this title).  Root cause of his report:
Revert re-decodes (no `.orig` snapshot for pre-v0.25.0 edits) and the re-decode
picks a different-but-valid-sounding slot than the extract baseline → byte-diff →
"Modified".

**Why this is delicate, not a quick fix:** ENCODE also goes through this path —
`codec.py` `GenRecover`/`StereoRecover` call `emu.recover_entry(p)` which returns
`_resolve_entry(p)` for generic builds.  So a determinism change touches the
bit-exact, hardware-verified re-encode round-trip.  For the ~13 ambiguous LZ
sounds our chosen slot may not even match the **firmware's** actual slot, which
would mean editing one of those sounds could ship bad hardware audio — so the fix
must be validated offline bit-exact across titles AND ideally hardware-verified.

**Mitigation already in place:** going-forward edits get a byte-exact `.orig`
snapshot, so Revert restores them exactly (no re-decode, no false "Modified").
The nondeterminism only bites the legacy pre-snapshot re-decode fallback and
re-extraction.

**Proposed fix (deferred):** resolve the full `(scale,chan)→slot` map **once,
deterministically** during the params derive (pick a stable representative per
key — e.g. the longest-bodied sound — instead of "first to seed"), persist it in
the per-card params cache (`%TEMP%/pinball_spike2_params`), and load it into
**every** decode path (parallel workers, revert, AND encode) so all agree.  Then:
(a) re-run the repro → expect 0/535 differ; (b) re-confirm offline bit-exact
encode on aero/bat/godzilla/TMNT + LZ; (c) hardware-verify a replaced LZ sound
before shipping.


### 3. Build-time perf — remaining levers (the big wins already shipped)

The long-song re-encode (2 h in v0.23.0) was brought down by v0.24.1
(capstone-cache + scheduling + parallel) and the v0.26.0 codec speedups (fast
capture hook + stereo 3→2 probes + cached masterdir-consumed restore), all
byte-identical.  What's left is optional and lower-value:

- **The integrity assert (~120 s).** The dominant post-encode fixed cost on a
  cat-0 Write — it re-derives the *patched* image (edit-specific, can't be
  cached). Safe option not yet taken: run it concurrently with the image copy /
  SD write (CPU-bound assert ∥ I/O-bound copy), joining + aborting on failure.
- **Music-bank derive passes.** Each edited bank still derives 3× but a bank
  holds only 1–2 songs (seconds each) — minor. Could fold the restore-capture
  into the encode derive like cat-0, but low value.
- **Analytic keystream (moonshot).** Computing the per-sample keystream `K`
  directly would remove per-block emulation entirely (100×+). Probed offline:
  `K` is *not* a trivial slice of the VF2 keystream table (0/200 match), so this
  needs real RE of the keystream generator — a research project.
- **Within-song parallelism.** A single very long song is a serial tail (one
  worker); its independent blocks could fan across workers. Marginal when there
  are already more songs than cores.
