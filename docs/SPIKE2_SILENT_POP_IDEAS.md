# Spike 2 "silent replacement still pops" — 20 ideas, ranked

Context: monkeybug (Led Zeppelin LE 1.22.0) put silence into two song-name
callout slots (idx0231 Ramble On, idx0258 Kashmir) and still hears artifacts.
David's challenge: if *silence* isn't silent, our encode/decode pipeline is
suspect. This ranks 20 ways the app could be at fault (or could help prove it
isn't), with what shipped, what's deferred, and why.

Two distinct artifacts are now separated:

- **START pop** (~0 ms, right at voice trigger, after the flipper coil): the
  final card bytes decode to pure silence at the head (−120 dBFS) even after
  the whole pipeline runs. Not in our data. Machine-side.
- **MID-BODY scrap** (~190–710 ms in): the card really does play a −12 to
  −15 dBFS chunk of the *original* callout. This IS our pipeline — the
  master-directory restore (below). David's instinct was correct.

Ranking is by (impact on the reported problem) × (confidence it's real) ×
(cheapness to try on hardware).

---

## Tier 1 — shipped this round, directly test on the machine

**1. Honest post-restore verification + preview (`_verify_final_patches`).**
The per-sound `_verify_encoded` runs *before* `_restore_masterdir_consumed`
reverts ~1 KB of scattered body words to stock. Those decode to the original
callout mid-body. This new pass decodes the FINAL card bytes, warns when a
quiet replacement carries a loud scrap, and writes the real machine-render
preview. This is the single most important change: it makes "silent isn't
silent" visible instead of hidden, and corrects previews that understated
reality. **Rig-verified.**

**2. Stock-head mode (`PAD_STERN_HEAD_MODE=stock`).** Keep block 0 byte-
identical to the stock card (triple-gated: delta=0, target head silent, stock
head silent). If the START pop is a playback start-state sensitivity to
re-encoded head words, this kills it while changing nothing audible. The
highest-value *start-pop* experiment. **Rig-verified** (head byte-identical,
verify passes).

**3. Per-slot experiment scope (`PAD_STERN_EXPERIMENT_IDXS`).** Apply head/
tail experiment modes to only chosen idx numbers, so one card carries treated
slots and untouched controls. Turns every hardware test into a within-card
A/B, removing "was it this build or that build" ambiguity. **Shipped.**

**4. Patch-map audit (`_audit_audio_patches`).** Every build now proves each
audio patch lands inside exactly one sound's write window, with only the
documented shared-boundary overlap. Cheap standing guard against the whole
"did we scribble on a neighbor" class. **Shipped.**

**5. Tail-block mode (`PAD_STERN_LEADOUT=stock`).** A/B the v0.71.1 silence
tail against the older stock-scrap tail on the real machine, per slot. Rules
the tail in or out as a contributor without a code change between builds.
**Shipped.**

## Tier 2 — shipped earlier this session, supporting

**6. Machine-render preview export.** Hear what the decoder produces before
flashing. Now fed by the honest post-restore render (idea 1). Kills the "is my
audio mangled?" question for everything except a machine-added artifact (which
no preview can show — stated plainly in the UI).

**7. Fade / cap / roll-off overrides (`PAD_STERN_FADE_MS`, `_HEADROOM`,
`_LOWPASS_HZ`).** Vary one shaping lever at a time from the GUI. Lets the next
HW test change exactly one variable instead of rebuilding the app.

**8. Stock-vs-replacement profiler (`audio_profile_report`).** Characterize
every sound (lead-in, fade, peak/RMS, DC, centroid, HF %) and flag
replacements that deviate from the game's callout house style. Turns "his
files are hotter/brighter" from an impression into a per-slot number and a CSV.

**9. Build-log fingerprinting of every override.** A card built during an
experiment is identifiable from its log forever (the RAW-toggle lesson: a
stale A/B setting silently shaped later cards). The Advanced button also stars
when anything is off-default.

## Tier 3 — deferred, real RE required

**10. Silence the master-directory-consumed words (the actual mid-body fix).**
**RE DONE 2026-07-23 — NEGATIVE, CLOSED.** Investigated on the LZ 1.22 rig
(scripts `clickdiag/re1..re4`). Findings:
- Silencing idx231 with no revert shifts **317 of 549** downstream sounds'
  `scale`/`pred16`, cascading from the very next sound — the band-build folds
  each sound's body into forward-chain state (`re1`).
- Replay of the band-build is bit-faithful, but it *analyzes decoded body
  content*: a silent body makes it produce no obj at all, and driving it with
  perturbed bodies access-violates the emulator (`re2`). So there is no simple
  checksum to preserve — the obj depends on the actual audio.
- The obj arithmetic lives in dense, heavily-optimized C++ (shared_ptr atomic
  refcounting, `unordered_map`, nested `bl` calls); analytic RE of the exact
  `scale`/`pred16`/`seed_a` formula is not tractable in reasonable effort
  (`re3`).
- **Decisive:** reverting only *half* the consumed words (first, second, or
  alternate) preserves the chain no better than reverting *none* — all three
  give the same 317/317 downstream shift; only reverting **all 512** words
  gives zero (`re4`). Every consumed word is load-bearing, jointly. There is no
  subset freedom and no equivalence class to exploit.

Conclusion: the mid-body scrap on a **silent/quiet** replacement is
**irremovable by re-encode** — the firmware makes every sound's codec params
depend on the raw bytes of earlier sounds' consumed regions, so those bytes
must be exactly stock (which is the original audio) or the machine reboots.
The only remaining path is a **firmware ELF patch** so the forward chain
doesn't consume from the audible range (deep RE, same class as the TMNT
validation patch) — not worth it for a mid-body, mostly-masked, non-pop
artifact. What ships instead: the honest detection/preview/warning (idea 1).
Full write-up: memory `reference_spike2_masterdir_accumulator_re`.

**11. Move a slot's audio away from its consumed region.** If the firmware's
consumed offsets are a function of position/length, a size-neutral internal
re-layout could put the ~1 KB it reads onto low-energy audio. Speculative;
depends on the consumed-offset model. **Deferred.**

**12. Firmware playback trace for the START pop.** Ghidra-trace the FIQ sound
engine's per-sound start: does it apply an instant attenuation step or read an
uninitialized state at voice-start (no ramps anywhere — already known from the
2026-07-09 RE)? If the pop is a firmware gain step, an ELF patch (soft-start /
ramp the attenuation write) removes it — same class as the TMNT validation
patch. **Deferred, high effort, but the only true START-pop fix if machine-
side.**

**13. Model the machine's block-0 codec-state seeding.** The extract side
needed the quiet-intro slot-trap fix for exactly this ambiguity. If the real
decoder seeds slot state differently than our emulator at sound start, encode
to match it. Would let us verify start behavior faithfully instead of
inferring. **Deferred.**

## Tier 4 — investigated and ruled out (kept for the record)

**14. History-dependent keystream.** Tested: block-0 K/rb for idx231/258 are
identical between a fresh-boot emulator and one warmed by deriving params +
recovering other sounds. Encode is order-independent. **Refuted.**

**15. Slot-resolution nondeterminism at the tail.** The old "static burst"
theory; the emulator was audited against Stern's own bytes at maxerr 0, and
silence gives zero non-zero samples pre-restore. **Refuted for these slots.**

**16. Edge step / DC at sample 0.** The 40 ms raised-cosine fade lands the
head at zero; the final bytes decode to −120 dBFS at the head. Not the START
pop. **Refuted.**

**17. Loudness / bandwidth of his files.** Shaping normalizes to a 0.80 cap
and 5 kHz roll-off; silence has neither loudness nor treble yet still shows the
artifacts. Cannot be the cause of the silent-slot behavior. **Refuted for the
silent case** (still worth profiling for hot replacements — idea 8).

**18. Duration rounding (his files a few ms off).** The encoder refits every
replacement to the slot's exact emitted sample count before encoding; source
length never reaches the machine. **Refuted.**

## Tier 5 — cheap diagnostics, not fixes

**19. Sound Test isolation + master-volume tracking.** Trigger the silent
slots from the Sound Test menu (no flippers, no gameplay coils) and vary master
volume. Separates machine-audio-path (scales with volume) from mechanical
(doesn't) from gameplay-coincident (absent in isolation). No code; the decisive
HW experiment for the START pop.

**20. Re-run the pop detector on the old stock-round-trip A/B video.** If the
"OriginalReplacements" (stock re-imported through our pipeline) card also pops
on track changes, the START pop predates any content change and is intrinsic to
the machine. Needs the video re-sent. No code.

---

### Bottom line

- The **mid-body scrap** is ours (master-directory restore) and is now honestly
  surfaced; the accumulator RE is **done and negative** (idea 10) — it is
  irremovable by re-encode, so honest detection is the shipped answer.
- The **START pop** is, on all current evidence, machine-side; the shipped
  stock-head mode (idea 2) is the cleanest way to prove that on hardware, and a
  firmware ELF patch (idea 12) is the only true fix if it is.
- Everything in Tier 1–2 is committed and built to be tested on monkeybug's
  actual machine, with per-slot A/B so one card settles multiple questions.
