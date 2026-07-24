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

---

## Round 2 — 10 more ideas, each run down (2026-07-23)

After the mid-body scrap was closed (idea 10) and the start pop localized to
the machine, here are 10 further ideas with the verdict from actually chasing
each on the LZ 1.22 rig / firmware (scripts `clickdiag/inv1..inv3`).

**11. Firmware ELF patch — ramp the voice-start / un-mute step (the real fix
for the START pop).** Run down: the pop is in the *digital* domain — master
volume is applied via ALSA (`snd_mixer_selem_set_playback_volume_all`), a
hardware-codec gain *downstream* of the FIQ mix, so a digital pop scales with
the knob (matches Chris's v0.47-era report). That makes it software-addressable
in principle. BUT the FIQ callout output path is **unsymboled** in LZ's
game_real (only ALSA/SoLoud *imports* are named), so locating the exact
gain-step needs a full RE like cabal's 1987-game work, then a SIDX re-sign and
on-machine validation. **Verdict: the only true fix, but a dedicated
high-effort / high-risk firmware project — not shippable blind, can't validate
without hardware. Deferred.**

**12. Patch a per-sound attack/fade field in the codec obj.** Run down: dumped
the full 0x80-byte obj for four sounds (`inv1`). Every live field sits in
+0x00..+0x1e (body_off, band0, length, seed_a, pred16, stride, chan, flag,
scale); everything past +0x1e is zero. There is no attack/fade/ramp field to
set. **Verdict: DEAD — no such field exists.**

**13. Trim leading silence from voiced callouts so the voice masks the pop.**
Run down: his files already start at ~1.8 ms (Kashmir) / ~9 ms (Ramble On)
versus stock ~20 ms — already tighter than stock. And the video shows the pop
*precedes* the voice (coil → pop → voice), so a voice onset cannot mask a
transient that fires before our stream is even read. **Verdict: won't help —
onsets already tight, pop is temporally before the voice.**

**14. Anti-pop tick at sample 0 (emit the inverse of the pop to cancel it).**
Run down: needs the pop's exact shape, polarity, and timing, which are
machine-side and likely un-mute-latency dependent and variable; and the machine
appears to un-mute before it streams our samples. High risk of adding a click
instead of cancelling one. **Verdict: not reliable — speculative-negative.**

**15. A silent "priming" sound before the callout to absorb the un-mute pop.**
Run down: the track-change → callout playback order is driven by the game's own
logic, not by the card. We cannot insert a primer into the machine's trigger
sequence. **Verdict: not controllable from the card.**

**16. Pin whether the pop scales with master volume (mechanism-locating).** Run
down: RESOLVED from firmware — master volume lives in ALSA, a codec gain
downstream of the digital mix, so a digital/FIQ-domain pop scales with the knob
while a pure analog-amp pop would not. Chris's earlier "click tracks the master
knob" therefore places the pop in the *digital* domain, i.e. addressable by
firmware (idea 11). **Verdict: mechanism confirmed digital-domain; the Sound
Test volume A/B remains the clean hardware confirmation.**

**17. Forward-sweep whole-catalog re-encode (let params float so the consumed
words can be silenced).** The insight: the constraint isn't "params == stock,"
it's "each sound decodes to its target under whatever params the chain yields" —
so silence the target, then re-encode every downstream sound's *original* audio
to its new (shifted) params. Run down: the building block **fails** (`inv3`) —
re-encoding idx232's original audio to its shifted params decoded back with
maxerr 20648 (not a clean round-trip), so the core mechanic doesn't hold without
further deep RE. On top of that it would need a serial re-encode of the whole
downstream catalog per build (minutes–hours) at high risk. **Verdict: dead in
practice.**

**18. Firmware patch so the master-directory chain doesn't consume from the
audible range.** Run down: same class as idea 11 — unsymboled internal path,
deep RE, SIDX re-sign, and it would shift every sound's params (needing a
matched re-encode of all of them). **Verdict: deferred, high risk, not worth it
for a masked artifact.**

**19. Fill "silent" slots with low-level masking noise instead of pure
silence.** Run down: the consumed positions always play the *original* callout
regardless of our target (they are reverted to stock), so user content can
never change the scrap; only the non-consumed remainder could carry masking
noise, which turns "silence" into "quiet noise" the user didn't ask for.
**Verdict: low value — changes the user's intent, marginal perceptual gain.**

**20. Per-slot scrap-severity warning.** Run down: already effectively shipped —
`_verify_final_patches` decodes the final card bytes and reports each replaced
sound's reverted-region dBFS, warning when a quiet replacement carries a loud
mid-body scrap. **Verdict: already in place; no new code needed.**

### Round-2 bottom line

The 10 ideas converge to one conclusion: **there is no new shippable code fix.**

- The START pop (Chris's actual complaint) is machine-side and digital-domain;
  the only true fix is a firmware ELF patch to ramp the voice-start gain step —
  a dedicated RE project (callout path unsymboled in LZ), high-risk, needs
  hardware validation. Do not ship blind.
- Two ideas are dead by inspection (no fade field; forward-sweep fails to
  round-trip), several are machine/hardware-bound (anti-pop tick, primer,
  volume A/B), and the mid-body-scrap avenues are all now closed.
- The best near-term path is unchanged and already shipped: the stock-head
  experiment mode plus the Sound Test isolation + master-volume A/B, which will
  confirm the mechanism and whether stock sounds pop too. If they do, it is
  intrinsic machine behavior and only a firmware patch can remove it.

---

## Firmware RE deep-dive (2026-07-23) — "how does Stern stay clean?"

Pushed on the firmware path to answer why stock callouts don't pop but our
rebuilds do. Result: the pop is decisively **machine-side, in the output
stage**, and every data-side explanation is now ruled out on the rig
(`clickdiag/fw1..fw4`, `inv1..inv3`).

**Findings that locate the pop:**

1. **The cat-0 callout codec is memoryless.** `decode_word` is a per-sample
   rotate + xor-keystream + companding multiply — no predictor, no state across
   samples (the 12-tap predictor belongs to the separate loud/music codec). So
   a silent body provably outputs digital silence sample-for-sample, and the
   pop is 100% downstream of the decode: in the FIQ mixer → saturate → DSP
   filter → amp_write / ALSA hardware stage, which the emulator does not model.
   That is why every round-trip on the rig looks clean.

2. **Stock does NOT avoid digital silence** (kills the noise-floor idea). Stock
   callouts contain hundreds of exact-zero samples (idx231: 864, idx258: 1667)
   and even fully-silent ~25 ms stretches (idx150). Adding a dither floor would
   not be "replicating Stern."

3. **The paradox.** Stock idx231 and idx258 — Chris's exact slots — decode with
   head `[0,0,0,0,0,0,0,0]`, an exact-zero silent head identical to ours, yet
   stock is clean and our silent replacement pops. Same slot, same silent head
   → the head is not the differentiator. This matches the EHOH machine-side
   voice-start artifact: the pop is present at voice-start and stock's arriving
   content masks it, while our silence/quiet head leaves it naked.

4. **Onset-energy masking is dead too.** Our `_fit` output reaches audible level
   *earlier* than stock (0.5%%-full at 3.7 ms even with the 40 ms fade; stock
   idx231/258 take 14–20 ms). So we are already hotter-earlier than stock —
   shortening or removing the fade cannot help, and would not explain why stock
   (slower onset) stays clean.

5. **No per-sound ramp field** in the codec obj to patch (all zero past +0x1e).

**Firmware structure.** game_real's `.dynsym` names only ALSA/SoLoud *imports*:
`snd_mixer_selem_set_playback_switch_all` (hardware mute), `_volume_all`
(hardware codec volume, downstream of the digital mix — so a digital pop scales
with the master knob, matching Chris's earlier report). The internal FIQ
callout output path is **unsymboled** and reached through PLT veneers, so
pinpointing the exact voice-start gain-step needs porting cabal's 1987-game
symbol map onto the LZ binary.

**The wall (why I did not ship a patch).** (a) The emulator is a codec oracle —
it cannot reproduce a mixer/amp pop, so I cannot see the defect here. (b) There
is no hardware in this environment to validate a firmware patch, and a wrong
audio patch can brick the machine's sound. A blind patch would be irresponsible.

**What unblocks the firmware fix.** A clean hardware capture: a line-out (not
phone-mic) recording from the Sound Test menu, music off, of (i) a stock callout
in isolation and (ii) our silent/replacement in the same slot, triggered several
times each. That definitively settles whether stock pops too (masking vs
genuinely clean) and characterizes the exact transient (DC step vs filter ring
vs un-mute) so a targeted, testable ELF patch to ramp the voice-start step can
be written — the same class of work as the TMNT validation patch, but for the
audio output path.
