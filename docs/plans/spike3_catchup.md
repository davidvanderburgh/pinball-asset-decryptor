# Spike 3 catch-up: Mod Pack, Move Your Mods, Partitions, Test card (PAD-1586)

David, 2026-11-25 (idea 9 of ten checked against main): these exist on Spike 2 and not on
Spike 3 - mod pack, mod transfer and one-click port, the Partitions explorer, the Test
card. Bring them to Spike 3, in that order of worth (PAD-1585, PAD's own game update,
needs the transfer to carry an owner's work to a new Spike 3 build). Not this ticket:
jukebox, sounds in turn, attract flipper sounds, co-op characters (spike3_music.LEFT_OUT,
coop_play.A64_LEFT_OUT).

## Why the first three were small

A Spike 3 project is laid out exactly as a Spike 2 one (spike3_extract.py runs Spike 2's
extractors over the decrypted games partition): `.staged_changes.json`,
`text/strings.tsv`, `audio/idxNNNN.wav`, `music_catNN_NNNN.wav`, the `.checksums.md5`
baseline. `core/modpack.py` and `core/mod_transfer.py` are folder-to-folder, and the
port chain (`app._run_port_chain`, `core/mod_port.py`) extracts and writes with the
era's own pipelines (`make_extract_pipeline` / `make_write_pipeline` pick
Spike3ExtractPipeline / Spike3WritePipeline). All three were hidden only because
`_SPIKE3_CAPS` never set `modpack`, `mod_transfer`, `partition_explorer`.

## What changed (run 1)

- `_SPIKE3_CAPS`: `modpack`, `mod_transfer`, `partition_explorer` on.
- `explorer.CardImage._scan_spike3`: a Spike 3 card's table (p1 signed FAT boot, p2
  system, p3 data, p4 extended, p5 connectivity, p6 games; p2..p6 LUKS2) is listed in
  the class's 0-based slots, each LUKS partition unlocked with the card's key
  (`Spike3KeySource.discover`: `$PAD_SPIKE3_KEYFILE`, a padkeys.json beside the card,
  else the user's own `~/.pad/spike3_padkeys.json`) and browsed through
  `spike3.open_partition_ext4`'s decrypted reader. No key: listed "(locked)" with the
  reason on `spike3_locked`, which the tab shows. Byte patches on an encrypted
  partition are refused (`_refuse_encrypted`); the tab's Replace says so in words.
  `info.card_version_probe` and `mode_project.probe_card_title` read through it, so a
  Spike 3 card's version and title now come from its own `/spk/index`.
- `SternManufacturer.mode_news` (What's new) answers a Spike 3 card from its Spike 3
  port (`profile_for_card(..., arch="a64")`).
- `App._port_other_generation`: Port + build / What's new refuse a card of the other
  generation up front (a Spike 2 card in a Spike 3 session or the reverse).

## Proven (run 1, real cards)

- Fallout LE 0.81.0 and 0.82.0 extracted (0.81: 1047 videos, 308 images, 4550 scene
  files, 3034 sounds; 0.82: 1073 / 308 / 4551 / 3061).
- 0.81 project edits: GameLogo.png (magenta corner), idx0100.wav (tone), a clip
  (ATTRACT_LOOP3_BW.mov, 2 s testsrc), the scene line "UFO CRASH SITE" -> "PAD 1586".
- The app's own Port + build (Mod Pack tab, web UI harness, Spike 3 session) onto the
  real 0.82 card: What's new "0.82.0 adds 26 videos, 27 sounds, 9 pictures and 3 text
  lines"; transfer "1 audio, 1 video, 1 image, 1 text" with the sound followed by
  content to its new index (idx0100 -> idx2187); the card built. Read back through its
  own encryption: logo pixel (255,0,255) vs stock (68,68,68), the line
  "   PAD 1586   " vs "UFO CRASH SITE", the image.bin body and the clip asset
  (448840 vs 1897367 bytes) changed.
- Mod pack: exported from the 0.81 project (4 files) and imported into the 0.82
  project through the Mod Pack tab; the logo is byte-identical and the text edit landed.
- Partitions: the real 0.82 card opens, all four encrypted partitions browse, the
  version reads 0.82.0 exactly.

## Test card (run 2 - the design)

The Spike 3 menu (`s3select`, codeselect `make PLATFORM=s3`) already compiles the test
card screens: `settings.c`, `testpics.c`, `video.c` (testcard=on: "nothing boots: the
test card menu until power-off"). It plays no sound on Spike 3 (the cabinet amplifier is
started by the game over I2C), so SOUNDS items are left off a Spike 3 test card with a
sentence.

A Spike 3 card cannot be made small the Spike 2 way (fresh p3/p5/p6 around p1+p2): every
partition past p1 is LUKS2 under the board's OTP key. So a Spike 3 test card is the
multi-boot card with no other image: `mks3multi.py testcard --primary CARD --out OUT
--selector-dir D [--media-dir M]`: image 0's card copied, its games tree moved to
`pad/img0` (the boot splash, conagent and data links still resolve through TOP_LINKS),
`images.conf` with `testcard=on`, the test items and `test_dir=/games/pad/testcard`,
the test files in `pad/testcard/`. The card is the size of the card it is made from
(64 GB). If the menu ever exits, padselect boots img0 (the stock game) rather than a
black screen.

Steps:
1. `bof.render_conf` (shared by mks3multi) carries no `tests=` / `testcard=` /
   `test_dir=`: add them as mkmulticard's `render_images_conf` writes them (same keys,
   conf.c reads one format), or have mks3multi use mkmulticard's renderer.
2. `mks3multi.py testcard` (+ verify), tests in tests/test_multiboot_s3.py style.
3. App: `testcard_core.available` (era != spike3 gate), the tab's "Made from: Pick a
   Spike 2 card image" words, `multiboot_core.testcard_commands` -> the s3 builder as
   root through WSL with `--keyfile` (webui/spike3_key.find_keyfile) and the s3select
   dir (ensures3select.sh), the size line, the Network options (Spike 2 only: hide),
   SOUNDS left off on Spike 3.
4. Proof: build a Spike 3 test card from Fallout LE 0.82 with a picture and a clip
   ticked, boot it in the Spike 3 emulator (s3launch.sh, hidden, muted, `--keyfile`),
   frames of the TEST CARD menu and the IMAGES screen (s3press.py NEXT/SELECT).
5. Shots: before/after testcard.png (the shot script already captures it).

## Test card (run 2 - what was built and proven)

- `mks3multi.py testcard --primary CARD --out OUT --selector-dir D [--media-dir M]
  [--color ...] [--keyfile K]`: the design above. images.conf is mks3multi's own
  (`image=img0|TEST CARD|...`, `timeout=0`) plus the lines mkmulticard writes for a
  Spike 2 test card (`color_profile=0|...`, `test_dir=/games/pad/testcard`, the
  `test_<kind>=` lines, `testcard=on`). Test sounds are refused in words.
- A card built for a Windows `--out` is put together in the first Linux folder with
  room for the card (`WORKDIRS`: /var/tmp/pad_s3multi, then the card store's disk
  /mnt/wsl/cards/pad_s3multi). This PC's distro has 38 GB free, so the multi-boot
  build was refused here too; it shares the fallback.
- The app: the Test card tab is offered on Spike 3 (`testcard_core.available`); a
  Spike 3 source card (`is_spike3_source`) takes `multiboot_core._s3_testcard_commands`:
  the Spike 3 menu program (ensures3select.sh), `selectmedia prepare --screen
  1920x1080` (test pictures and clips fitted to the Spike 3 screen, not Spike 2's
  1360x768 LCD), then the builder as root with the user's key. Sounds and the
  Spike 2-only network options are left off with a sentence; the page's words follow
  the source card (coin-door buttons on Spike 3).
- The emulator walk found two faults in the shared menu (codeselect settings.c) on a
  coin-door build: BACK was ignored in the test screens (a list could never be left),
  and the footers named the flippers, START and ACTION. Now, on SEL_COIN_DOOR builds,
  BACK backs out of a test card's screens and the footers say PREVIOUS / NEXT,
  SELECT, BACK; a Spike 2 build's strings are byte for byte what they were.

Proven: the app's Test card tab (web UI harness, Spike 3 session) built a test card
from the real Fallout LE 0.82 card with a picture, a clip and a sound (the sound left
off with its sentence), in 13-16 min. In the Spike 3 emulator (hidden, muted): the
TEST CARD menu (IMAGES 1 picture, VIDEOS 1 video, SCENES / SOUNDS none, COLOR
CORRECTION); SELECT opened DEFAULT PAD TEST CARD, BACK came back, NEXT + SELECT opened
IMAGES and showed the picture full screen, BACK BACK, NEXT + SELECT opened VIDEOS and
played the clip (60 frames at 30 fps).
