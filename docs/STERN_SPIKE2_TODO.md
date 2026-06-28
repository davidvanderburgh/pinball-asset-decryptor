# Stern Spike 2 — open work / TODO

## Open work (priority order)

### 1. Re-encode tail bug (~5 ms at the end of every sound) — ★RESOLVED

**Root cause (register-level, mono+stereo, validated TMNT + generic LZ builds):**
the codec emits in 200-sample blocks driven from a cursor that starts at 200, and
within the block at cursor `C` it emits sample `i` **only while `C + i < length`**.
So a sound's true decoded output is exactly **`length - 200`** samples (the first
block is a cursor lead-in); any block past that emits nothing. Two consequences,
both now fixed:

* **Extract:** `decode()` returned `floor(length/200)*200` samples — up to ~200
  trailing **padding zeros** past `length-200`. Inaudible on a one-shot SFX but a
  click at the loop point when a looping-music WAV is played on a loop.
* **Re-encode:** the engine fit the user's replacement to the raw `length`
  (`_encode_mono`/`_encode_stereo` → `_fit(..., length)`); `encode_sound`'s
  per-block clamp then silently **dropped the last ~200 samples** of the user's
  audio, so a replaced loop landed ~200 samples early → the loop misaligned.

The original hypothesis ("`recover_block` returns short for the last block →
`body[lo+m:]` stays zero → garbage") was a *misdiagnosis*: those tail body words
are **dead** (never emitted by the firmware), so leaving them zero is correct, and
`encode_sound` was already bit-exact on every emitted sample.

**Fix (committed):** one canonical emitted length everywhere —
`emulator.emitted_length(length) = max(0, length-200)`.
* `Spike2Emu._decode_with_entry` trims its output to `emitted_length` (clean
  extract; capped `max_secs` runs keep all they decoded).
* `_encode_mono`/`_encode_stereo` fit the target to `emitted_length` (the whole
  replacement is encoded; nothing dropped).
The re-encoded body bytes are **byte-identical** for the unmodified round-trip
(the dropped samples were padding either way), so the hardware-verified Write
(v0.24.0) and the TMNT bit-exact round-trip are preserved.

**Guarded by** [tests/test_stern_audio_tail.py](../tests/test_stern_audio_tail.py):
fast unit tests for the `emitted_length` contract + encoder wiring (always run),
and a `@pytest.mark.slow`, image-gated round-trip that boots the firmware and
proves a forced-loud final partial block round-trips bit-exact on **turtles**
(validated) **and led_zeppelin** (generic — the build the bug was reported on).


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
  cached) and can't itself be shortened. **Done (v0.29.2):** the file-output
  `write_image` now copies the unpatched card to the output in a background
  *thread* that runs concurrently with the whole patch computation, joining
  before any patch byte is written. The compute yields the GIL enough (the
  assert's emulator fires a per-instruction Python hook; the re-encode blocks on
  its worker pool) that the copy fully overlaps — measured: a 7.9 GB card copy
  hides under the ~120 s assert (3.6 s on NVMe; more on slower disks, where the
  win is bigger). A *subprocess* was considered and found unnecessary (the thread
  overlaps). Direct-SD `write_device` is unchanged: it has no big copy, and its
  device write must follow the assert (a card write can't be un-done).
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
