# Stern Spike 2 — open work / TODO

Forward-looking backlog for the Stern Spike 2 plugin. Tester feedback comes from
**monkeybug** (real machines: Led Zeppelin, etc.).

---

## ⬤ v0.23.0 tester round (monkeybug, 2026-06-25) — raw feedback digest

Verbatim findings from updating a real Led Zeppelin machine to v0.23.0. Each item
links to the section that tracks the actual work.

**Image build**
- Writing a new image took **just over 2 hours** — log: https://pastebin.com/Ty8XZsHB .
  Confirms *"Build time: long-song re-encode dominates"* below; not network I/O.
- **Balena Etcher errors the instant it starts writing** ("card may have been
  disconnected"). Also seen the previous round. Etcher is stable on other images;
  unclear if it's specific to app-built images. → new section
  *"Balena Etcher 'card disconnected' on write"*.

**Game test — audio still broken (matches prior round)**
- Boots, looks good. Setup menu has **no audio** when moving the highlighted
  selection. Opening the **Audio** settings tab **locks up / freezes**.
- 2nd run (changed nothing, saved defaults): attract mode runs; the coin-door
  **volume button jumps straight to 63 (max)** on the first press and then does
  nothing; the **48 V-disabled warning** overlay gets **stuck** on top of a still-
  running attract mode and is unclickable.
- Follow-up: the warning eventually self-cleared; opening/closing the coin door now
  shows+clears it normally; changed to **free-play (still no sound)**; pressed
  **Start → froze, then rebooted**.
- This confirms the **audio-lockup is unfixed in v0.23.0**. Root cause is now known
  (masterdir forward-chain desync → garbage PCM → firmware codec reboot — see
  `[[project_spike2_realmachine_audio_failure]]` and the SD-validation "Remaining"
  notes). The size-neutral re-encode is byte-correct *per slot* but desyncs the
  forward-chained band-build.
- **FIX IMPLEMENTED (2026-06-25, pending hardware verify):** `engine._restore_masterdir_consumed`
  restores each re-encoded body's masterdir-consumed bytes to stock after encode, and
  `engine._assert_param_integrity` re-derives all sounds on the patched image and aborts the
  Write if any sound's codec params still shifted. Offline-validated end-to-end: a real
  flipped-audio mod → 0/2053 param shifts (unfixed = 2052/2053). cat-0 (image.bin) only so far;
  music banks (`image-scNN.bin`) still need the same restore. Needs an on-machine confirm
  (TMNT/LZ audio mod → Write → flash → boots + plays).

**App / GUI bugs + asks** — see *"GUI / UX backlog (v0.23.0 round)"* at the bottom.

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
each changed file's record — `HMAC-SHA1(K, file)` + `MD5(file)` — with the global
validation key `K` (recovered by RE, verified to reproduce real stored digests
incl. `image.bin`). Size fields stay valid (size-neutral). Covers **everything a
Write can change**: `image.bin` (cat-0 audio), `image-scNN.bin` music banks,
full-replacement video/image/texture, **and in-place `scene.radium` edits
(display text + embedded images)** — the radium writers return per-inode
file-relative overlays (`{i_block: (node, {file_off: bytes})}`) that
`_compute_sidx_writes` streams through `_overlay_digests` to recompute the patched
radium's digest. Best-effort (a missing/odd manifest only warns). End-to-end
validated; `tests/test_stern_sidx.py` + `tests/test_stern_radium.py` (incl. a real
TMNT-card check that the streamed digest of an unmodified radium == its stored
record, on files up to 70 MB / multi-extent).

**Two record formats (both supported as of 2026-06-25):**
- `FI64` (80-byte payload): HMAC-SHA1 @37, MD5 @57; header word `@0x34` =
  `0xffffffff` (disabled). Led Zeppelin, Godzilla, Metallica, Batman, Elvira, …
- `FINF` (60-byte payload): HMAC-SHA1 @**21**, MD5 @**41**; header word `@0x34` is
  a **non-disabled** value (e.g. turtles `0xcf14559a`). TMNT, Deadpool, King Kong,
  Munsters, Avengers, Jurassic Park, Iron Maiden, James Bond, Sword of Rage,
  Uncanny X-Men. **Same keyed scheme, different offsets** — the global key covers
  both. (The earlier "FINF is a custom unsolved 32-byte digest needing unicorn
  capture" was a misread: offset 20 is a constant `0x00` separator.) `sidx.py`
  `_FORMATS` + `parse_records` (now returns `fmt`) + `record_field_writes(…, fmt)`.
  Verified 300/300 on a real TMNT card; regenerated==stored on both formats.
- **Blast radius scanned across all 28 bundled cards: FINF = 11 titles, FI64 = 17
  (NOT chronological — per-title build choice).**

**▶ Remaining:**
- **Hardware verify (both formats):** small cat-0 audio swap → Write → boot →
  confirm sound + no "Game validation error" (log shows `Refreshed N <FI64|FINF>
  manifest record(s)`). monkeybug for FI64 (LZ); a FINF title (e.g. TMNT) too.
- **FINF header word `@0x34` — RESOLVED as a non-issue (2026-06-25 firmware RE).**
  Disassembled both on-card `.sidx` parsers (`/usr/local/bin/spk`, `spike_menu/game`)
  and the game firmware: **none read offset 0x34**, and a hardware test that forced
  `@0x34 -> 0xffffffff` on a TMNT card **still failed**. So `@0x34` is not an
  enforced integrity word — leaving it as-is is correct. (The "two u16 checksums"
  structure was real but the runtime ignores it.) See
  `[[project_spike2_realmachine_audio_failure]]` and `c:\tmp\sidx_re\`.
- **The real audio-lockup cause is SOLVED** (and was never the manifest — the
  per-file HMAC-SHA1+MD5 regen is provably correct on-card and the firmware never
  reads the `.sidx`). Root cause = the firmware's `MASTERDIR_DECODE` forward-chain
  (each sound's body bytes set every later sound's codec params); fixed by restoring
  the masterdir-consumed bytes after re-encode (see the top section + `engine._restore_masterdir_consumed`).
  Hardware-verified on a real TMNT machine.
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

## "Write image to SD card" feature (monkeybug request) — BUILT (pending hardware verify)

We can *build* an image or write changes in-place, and now also flash a pre-built
`.img`/`.raw` onto a card (a dd-style whole-image write), so users no longer need
a separate imaging tool.

**Shipped in code:**
- New `capabilities.flash_image` + `make_flash_pipeline`; Stern sets it on (Spike 2
  era only — hidden for the capture-only Whitestar era).
- Engine in `plugins/stern/rawdevice.py`: `flash_image_to_device` (sector-aligned
  bulk copy via `RawDeviceFile.copy_image_onto`; whole-sector fast path, RMW only
  for the final partial sector), `flash_preflight` / `device_size` / `format_size`.
- **Size guard:** refuses (`FlashError`) when the image is larger than the card —
  probed read-only **before** any write (the too-big case that crashed monkeybug's
  external tool). Unknown card size proceeds with a logged warning.
- **Windows whole-disk write:** `_disk_offline_for_write` takes the disk offline
  (`Set-Disk -IsOffline`/clear-readonly) for the duration and back online after —
  required because a flash overwrites the **mounted FAT boot partition** too
  (unlike the ext-only Direct-SD asset write). Best-effort + logged. POSIX logs a
  "unmount first" hint.
- **Pipeline:** `SternFlashImagePipeline` (phases Check card / Write image / Flush),
  progress + cancel (a mid-flash cancel raises `FlashCancelled` and the card is
  reported incomplete).
- **GUI:** a "Flash Image to SD Card" frame + button on the Write tab (gated on
  `flash_image`) opens `gui/flash_dialog.py` — image picker + SD-card-biased drive
  picker (`direct_target_kind="sd_card"`) + live "image X → card Y ✓ fits" readout
  + admin gate + red safety banner + erase-confirm. On confirm it runs the flash
  through the normal status area (`App._start_flash_image`).
- **Tests:** `tests/test_stern_flash.py` (18) — byte-equivalence vs a file copy at
  512/4096 sectors, tail-preservation, size guard, unknown-size warn, cancel,
  helpers, offline-wrapper no-op-for-files, pipeline wiring; `tests/test_gui_smoke.py`
  flash-frame gating. Non-GUI pytest 603; GUI smoke 11.

**▶ Remaining (hardware verify — can't be tested offline):** run the dev GUI as
Administrator → Flash a known-good image onto a spare card → confirm the disk goes
offline, the bytes land (re-extract / boots in a machine), the size guard refuses a
too-big image, and the card comes back online. Keep a backup first.

## Built image "too big for the card"

monkeybug's built image was rejected by external imaging tools as too big for his
original card; a 16 GB card worked. Likely just SD-size variance, but **verify
`build_image` output size == source image size exactly** (a padded-larger output
would be a real bug). Then surface card-size guidance in the Build/Write UI and
in the writer's size guard above.

## Build time: long-song re-encode dominates (perf)

22 long songs → **2h17m** total, of which the **re-encode phase was 2h08m**; the
image copy was only ~6 min — **network I/O is NOT the bottleneck.** monkeybug's
v0.23.0 build reproduced this ("just over two hours", log
https://pastebin.com/Ty8XZsHB ). Cost is the
unicorn per-block keystream recovery, which scales with track length; full 5–8
min songs are the worst case (already fanned across processes). Optimization
lever is a faster keystream recovery (less unicorn per block), on the codec side.

## Balena Etcher "card disconnected" on write (monkeybug)

Balena Etcher **errors the instant it starts writing** monkeybug's app-built
image, claiming the card may have been disconnected. Seen across two rounds
(v0.22 + v0.23.0). Etcher is stable for him on other (non-app) images, so it may
be specific to our `build_image` output. Things to check:
- **Output geometry/size:** does `build_image` produce a `.img`/`.raw` whose size
  is *exactly* the source image's, with no padding or truncation? (Cross-refs the
  *"Built image 'too big for the card'"* note — a few odd bytes can make Etcher
  abort early.) Verify byte-count and that the partition table / final sector are
  intact.
- **Now that we ship our own *"Flash Image to SD Card"* feature** (BUILT, pending
  HW verify), steer testers to use it instead of Etcher — it has the read-only
  size pre-flight and the Windows offline-disk handling. If our flasher writes the
  same image cleanly where Etcher fails, that localizes the problem to Etcher's
  handling of our image rather than the bytes.
- Ask monkeybug for the exact Etcher error text / version.

## GUI / UX backlog (v0.23.0 round)

1. **Edited audio changes don't reload after an app restart (bug).** On relaunch
   everything shows defaults; the **Audio** tab lists **no** changes for the audio
   files, but switching to the **Write** tab slowly populates *all* the staged
   changes — and returning to the Audio tab *still* shows none. So the staged
   edits persist (Write finds them) but the Audio tab doesn't rehydrate from them
   on load. Likely relates to the new `core/staged_changes.py`; the Audio tab needs
   to read staged changes at startup and mark/relist the modified entries.
2. **Write-tab scan restarts from scratch on every tab switch (perf/UX).** Opening
   the Write tab kicks off a slow file scan that populates gradually; leaving and
   returning **re-runs the whole scan** instead of reusing the prior result. Cache
   the scan (invalidate only when staged changes actually change) so re-entering
   the tab is instant.
3. **Right-click context menu on the log (request).** Add **Copy / Save As… /
   Clear** to the log pane's right-click menu.
