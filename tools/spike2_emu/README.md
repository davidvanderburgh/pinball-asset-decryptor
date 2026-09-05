# spike2_emu — running the Stern Spike 2 game on a PC

A real Stern Spike 2 armhf game binary, running under `qemu-user` in a chroot
of the card's own rootfs, with every piece of hardware replaced by `LD_PRELOAD`
shims. It boots to attract mode by itself in about 15 seconds, at 1360x768 /
60 fps on the GPU, with working audio, video and switch input.

## Any title

The rootfs is the OS partition and carries no title of its own; each game is a
directory under `games/`. `PAD_GAME` picks one:

```bash
PAD_GAME=<title> watch.sh          # the directory's name under games/
```

## Straight off the card, with nothing extracted

```bash
PAD_CARD=/path/to/<card>.sdcard.raw watch.sh
```

`cardmount.sh` puts the card's games partition on a **read-only FUSE mount** and
`run_game.sh` bind-mounts the title into the chroot. No copy, no root, about a
second, and the image cannot be modified. `mount -o loop,offset=` would need
real root; fuse2fs does not, and `apt-get download` + `dpkg-deb -x` into a
private prefix gets fuse2fs without a package manager or a password. Extraction
still works and is still the faster option for a title you run constantly.

## With your own edits on top, and no card rebuilt

```bash
PAD_OVERRIDE_DIR=/mnt/c/.../emulator-overrides \
PAD_CARD=images/Stern/spike2/turtles_pro-1_59_0.Release.8G.sdcard.raw watch.sh
```

An **override set** is the card files an edit touches, already patched, laid
out as they sit on the games partition — for a replaced callout that is
`<title>/image.bin` plus `spk/index/<title>.sidx`, and nothing else. PAD builds
one from the Emulate tab's "Apply my replaced assets on top" box
(`stern.engine.write_overrides`, the Write tab's own patch computation without
the copy of the card); `overrides.sh` stages it on the Linux disk and
`run_game.sh` bind-mounts each file over the read-only card mount — the same
trick that masks `boot_display_cmd` for item 45.

**Why it exists** (PAD-103): trying one edited sound on the PC used to cost two
full-size copies — the build's copy of the 7.3 GB card, then this rig's copy of
that new card into `~/cardcache`, because the cache is keyed on size+mtime and
a fresh build invalidates it. The set for that same edit is 1.4 GB written in
**9 seconds** (measured, jurassic_park_le 1.16.0), and the stock card's cache
stays valid because the stock card was never touched.

**And a second edit costs neither.** PAD builds each set by patching the one
before it — the card's own bytes back over what the last build wrote, then this
build's writes on top — and writes down what that changed in `overrides.delta`
beside the manifest: a `generation`, the `parent` it was patched out of, and
either a byte range or `whole` per file. `overrides.sh` keeps the generation it
staged in `$PAD_HOME/override.gen`; when that is the parent of the set it is
handed, it `dd`s those ranges onto the stage instead of copying the set again.
Change one callout and press Start and nothing copies a 1.4 GB `image.bin`:
not the app, and not this rig across 9p.

Everything about the delta path is fail-to-the-copy. No delta, a stage of some
other generation, a file the delta names that the stage has not got, a `dd`
that fails, a staged file that ends up the wrong size — each of them falls back
to staging the set whole, because a stage that is part one build and part
another is a run that plays a sound the user has already taken back.

The set names the card it was built from. A file in it that the booted card
does not have **fails the run** rather than being skipped: it means the set was
built against a different card, and half of one build over half of another is
not a card anybody should be listening to.

## Boot selector (item 90)

```bash
PAD_CARD=/path/to/<multi-image card>.raw watch.sh
```

**The card decides, not a flag.** A **multi-image card** (`mkmulticard.py`:
Stern's p1/p2, the primary's games partition as p3, each extra image's games
partition appended as p7, p8...) boots into a menu on the machine, and it
boots into the same menu here without being asked to. `PAD_SELECT` is a
**three-way switch** and `padpath.sh`'s `pad_select_wanted` is the only thing
that reads it:

| `PAD_SELECT` | what happens |
| --- | --- |
| unset (the default) | **ask the card** - `parts.py --multiboot <card>`, the one definition of "this card boots into a menu": the rootfs holds `/usr/local/codeselect/codeselect` **and** its `images.conf` names two or more images. `yes` = exit 0, `no` = 1, `unknown` (not a card, no debugfs) = 2 and is treated as no, out loud. No `PAD_CARD` at all = no menu and no probe. |
| `1` | show the menu whatever the card looks like |
| `0` (also `no`/`off`/`false`) | do not, whatever the card looks like |

`watch.sh` asks once, at the top of the run, prints what was decided and why,
and exports the resolved `1`/`0` to `run_game.sh` - so the menu that comes up
and the menu that was decided on can never be two different answers.

**A card can never make the emulator refuse to start.** The provenance travels
with the answer (`PAD_SELECT_AUTO=1` when the *card* decided), and every gate
that used to be fatal now reads it: an unbuilt selector, a missing games
partition, a partition that will not mount, or fewer than two games trees once
`parts.py --list-games` has resolved them all say so and **boot the primary
image without a menu**. An explicit `PAD_SELECT=1` still refuses loudly - it
asked for something it did not get.

What a menu run does: `run_game.sh` mounts every games partition
(`cardmount.sh --part N`, one `~/card/<label>.pN` per extra, sharing the
primary's cache copy), writes the menu to `$ROOT/dump/codeselect.conf` (the
card's own `/usr/local/codeselect/images.conf` names, `default=`, `timeout=`
and sound keys when it carries them - read the way `conf.c` reads them, so
`image = /dev/...` with spaces counts), and chroots
`/usr/local/codeselect/codeselect` - the ARM selector, drawing in the game
window through the GL bridge, no shim - before the game. Arrow keys are the
flippers and move the highlight, `1` (START) or Space (ACTION) confirms, and
the countdown boots the highlighted image by itself. The choice lands in
`$ROOT/dump/select.choice`, the selector's log in `$ROOT/dump/codeselect.log`,
the remembered highlight in `$ROOT/data/codeselect.last`; a non-primary choice
is a second bind over `games/<title>`, and the game then execs exactly as on
a plain card run. `[select]` lines reach the event pane; `dump/selecting` is
the flag that keeps `watch.sh` (and autoattract) from reading the menu phase
as a dead game.

Knobs: `PAD_SELECT` as above; `PAD_SELECT_TIMEOUT` is the countdown in seconds
and **overrides the card's own `timeout=`** (which is what is used when the
variable is unset; 30 when neither says, `0` waits for ever);
`PAD_CARD_CACHE=0` runs a WSL-local image without the 14 GB cache copy.
`buildselect.sh` builds the selector into `$ROOT` (`ensurebuild.sh`'s
`pad_ensure_select` does it on a menu start; it refuses the run only when the
menu was *asked* for); `alive.sh` counts it as `selector (codeselect)`. In the
app, the Emulate tab's **Boot selector** box shows what the card answered and
is an override: leave it alone and the rig asks the card again at Start, move
it and the tab says `PAD_SELECT=1`/`0` out loud. A launch from a save slot
always sends `0` - the save already chose its image.

### N images: the two card layouts

The card's own kernel exposes `/dev/mmcblk0p1..p7` only, so one extra games
partition is all a card can carry as a partition. `mkmulticard.py --layout`
(default `auto`) chooses:

- **`parts`** (one extra): the extra's games partition is p7 verbatim; the
  selector's device is `/dev/mmcblk0p7`, the rig's token `p7`.
- **`--layout multi`** (two or more): p7 is ONE ext4 partition (label
  `multi`) holding `img1/`, `img2/`, ... `imgK/`, each the complete file tree
  of that extra's games partition (`spk/`, the title dir, the
  `game`/`conagent`/`data` symlinks) - built with `debugfs rdump` from the
  read-only source into a scratch tree, `mke2fs -d` with the stock p3's
  feature set, sized to the sum of the extras' used bytes + 10% + 256 MiB.
  The devices are `/dev/mmcblk0p7:img1`, `/dev/mmcblk0p7:img2` ...
  (`select.sh` mounts p7 at `/mnt/multi` and binds the subdirectory over
  `/games`); the rig's tokens are `p7:img1`, `p7:img2` ... `parts.py
  --list-games` prints one line per TREE with the subdirectory as a fifth
  field (`7 15353856 7861174272 <title> img1`), `cardmount.sh --part 7`
  answers `<mount>/img1` for the partition (one component, so the teardown
  still finds the mount), and `run_game.sh` binds `<mount>/imgN/<title>` over
  `games/<title>` for the chosen tree.

### Media: art, animations, sounds

`mkmulticard.py build ... --media-dir DIR` reads `DIR/media.json` (written
by `selectmedia.py prepare`: per image an art PNG, an animated GIF and a
music WAV, any of them null, plus `sound_move`, `sound_confirm`, `volume`)
and stages only the referenced files into the card's
`/usr/local/codeselect/media` (flat, `^[A-Za-z0-9._-]+$`, PNG <= 1360x768,
GIF <= 1.5 MB / 512x288 / 30 frames, WAV pcm_s16le 44100 Hz 1-2 ch, the set
<= 20 MB - a wrong file refuses the build before a byte is copied). The
`images.conf` it writes carries the six-field image lines
(`image=<device>|<title>|<subtitle>|<art>|<anim>|<music>`) and the
`sound_move=` / `sound_confirm=` / `volume=` (a number, or `machine` plus a
`machine_volume=` line with `--machine-volume`: the menu then follows the
machine's own MASTER VOLUME SETTING) / `mixer_volume=` keys; `inject`
without `--media-dir` carries an existing media directory and those fields
through, with it the media directory is replaced.

In the rig, `run_game.sh` pulls the card's media out of its rootfs with
`parts.py --rootfs-dir /usr/local/codeselect/media` (debugfs, no mount) into
`$ROOT/dump/media` before the selector runs, forwards the card's
`sound_move`/`sound_confirm`/`volume`/`machine_volume`/`mixer_volume` keys into
`dump/codeselect.conf`, and passes `--media /dump/media`.
**`PAD_SELECT_MEDIA=<host dir>`** hands the selector a directory of your own
instead (art and sounds without rebuilding a card). Every media failure
inside the selector is non-fatal: the menu still draws, the card still boots.

**Hearing the selector in the rig: `PAD_AUDIO=1`.** David's default runs
are muted (`PAD_AUDIO=0`, no player, `PAD_AUDIO_PLAY` unset - the selector
logs `audio: none`); with `PAD_AUDIO=1` the selector inherits
`PAD_AUDIO_PLAY`/`PAD_AUDIO_FMT` from `watch.sh`, writes `44100 2` to the
format file, streams into the FIFO and closes it before the game starts, so
`~/padaudio.log` shows `guest reports 44100 Hz x 2 ch` before `[select]
chose`. To run such an E2E with SILENT speakers, mute the Windows player
rather than the run: `padplay.py` re-reads the JSON named by
`PAD_AUDIO_CTL` every 250 ms (`{"gain": 0.0-1.0, "muted": true|false}` -
the app's Emulate-tab knob writes it as
`%APPDATA%\pinball_decryptor\audio_ctl.json`, `_write_audio_ctl` in
`pinball_decryptor/gui/emulate_tab.py`), so
`PAD_AUDIO=1 PAD_AUDIO_CTL=/mnt/c/Users/<you>/AppData/Roaming/pinball_decryptor/audio_ctl.json`
with `{"gain": 1.0, "muted": true}` in that file plays everything into the
FIFO chain and nothing out of the speakers (the `[padplay] fed/played`
counters and the `[select]`/`audio:` lines are the oracle); flip `muted` to
`false` in the file to hear it, no restart needed.

### Same game code version on every image

**Use the same game code version for every image on the card.** `plan`,
`build`, `verify` and `inspect` all print a VERSION table - one line per image:
index, device, title directory, game code version, where that answer came from,
node board firmware - and `build` **refuses** a card whose images are not the
same game code. The refusal *is* the warning; it explains the cost and ends
with the flag that overrides it.

```
== game code versions
idx device                 title                    version   read from              node firmware
0   /dev/mmcblk0p3         turtles_pro              1.59.0    spk index + game ELF   1.33.0 (17 hex)
1   /dev/mmcblk0p7         turtles_pro              1.58.0    spk index + game ELF   1.19.0 (15 hex)
```

What each case costs:

- **Same title, same version — nothing.** This is the normal card: David's own
  is stock TMNT 1.59 plus a 1987 re-skin of that same 1.59, two game ELFs four
  bytes apart. Nothing is reported and nothing is lost.
- **Same title, different version — three specific things.** Operator settings,
  audits and scores are *not* on the card: they live in the node board's NVRAM
  keyed by the **SHA1 of each setting's menu caption**, not by its number, so a
  caption both builds spell the same way carries over untouched (11 of 11
  measured across a TMNT 1.59 → 1.58 → 1.59 round trip, with 202 of the 228
  shared captions renumbered in between). What *does* break: a setting only one
  build has falls back to that build's compiled default whenever you boot the
  other (43 settings of 1.59 and 13 of 1.58 on that pair); a setting Stern
  **renamed** reverts, because the new caption hashes to a slot never written
  (3 on that pair); and the store keeps only **three** generations, so two boots
  of the other build erase a build-exclusive value for good.
- **Different node board firmware — a service call.** Each image ships its own
  `*-<M_mm_p>.hex` node firmware set (`-1_33_0.hex` on TMNT 1.59, `-1_19_0.hex`
  on 1.58) and the machine records the running build's node firmware version at
  every boot, so a card whose images disagree can **reflash the node boards on
  every swap**. This is checked on its own line: two images can share a game
  code version and still differ here, and that alone is refused.
- **Different titles — everything.** Settings, audits and high scores are stored
  per title; nothing carries at all, and each title wants its own node boards,
  coils and switch table. Reported as its own, larger warning.

```bash
mkmulticard.py build ... --allow-version-mismatch
```

is the one override, and it covers all three (version, node firmware, title):
they are the same question - *these images are not the same code, build anyway?*
`plan` never refuses (it writes nothing); it prints the same table and then
exactly what `build` would have said. `verify` and `inspect` report a mismatch
and never fail on it: a card built with the flag is a card its owner chose.

**Where the version comes from** - read off each image, never guessed from a
file name, cross-checked between:

| source | what it is | notes |
| --- | --- | --- |
| `/spk/index/<pkg>-<M_mm_p>.sidx` | Stern's own package name (`turtles_pro-1_59_0.sidx`) | the authority: all three components, and what the code updater speaks. A bare `<pkg>.sidx` symlink sits beside it on some cards; it names no version and is skipped |
| the game ELF's build-identity record | a run of pointers to the game code, the model name(s), the release date and (on most builds) the title directory, followed by the version as a **uint16** — high byte major, low byte minor | the cross-check. MAJOR.MINOR only: `turtles_le` 1.58.**1** and `turtles_pro` 1.58.**0** both hold `0x013a`. Located on all 46 cards in the library and agreeing with the package name on 45 — `dungeons_and_dragons_le` 1.00.0's record says `0.01`, which is reported as a disagreement rather than resolved |
| the title directory's `*-<M_mm_p>.hex` | the node board firmware version | a **different** number from the game code version, so it gets its own column and is never used as one |
| `/data`'s `nv/<title>/NVM` | the machine's own record | `/data` is empty on all 49 cards in the library (it is written on the machine, not by the factory), so nothing here depends on it |

`build.json` records each image's `title_dir`, `version` and `node_fw_version`
too, so a card loaded back says what it was built from; `inspect` re-reads the
live truth off the card and flags any disagreement with that record.

### Loading a finished card back

**Straight off the SD card (item 99).**  The tab's "From SD card…" reads only the menu's
part of the card in the reader - the partition table, the boot and rootfs partitions,
every EBR sector and the identity bytes of the games partitions (`core.rawdevice.
read_device_menu_to_image`, elevated like a flash) - into a sparse image under
`%TEMP%\\pinball_spike2_multiboot\\cards\\<card>.menu.raw`, and loads that: titles, pictures,
sounds, settings and the images' sources come back; the games' versions do not (the trees
are not read).  Apply rewrites the menu in that image and then writes the menu partition
onto the card with the app's menu-only write, which first proves the card is that card
(the same ranges the read took).  A list change is a fresh build from the sources.

A card carries what it takes to re-open its own menu in an editor. Beside
`images.conf` - **never** inside `media/`, never in the media budget, never
opened by the selector - `build` and `inject` stage two small JSON files into
`/usr/local/codeselect/`:

- **`build.json`** `{"tool", "version", "written", "layout", "images":
  [{"device", "source", "title", "subtitle", "art", "anim", "music",
  "title_dir", "version", "node_fw_version"}], "timeout", "default", "volume",
  "machine_volume", "mixer_volume", "sound_move", "sound_confirm"}`. `source` is the absolute path of the `.raw` that image was
  built from - the one thing `images.conf` cannot hold and a rebuild needs. An
  `inject` given no `--primary`/`--extra` reads the card's own `build.json`
  first and carries the old sources through, **by device**: an inject must
  never lose provenance. (`inject --primary P --extra E` RECORDS those paths
  and reads nothing from them.)
- **`media.json`** - the manifest `selectmedia.py prepare` wrote for the staged
  set, **verbatim**, so the art/animation *spec strings* (`auto@20:2:8`,
  `/x/clip.mov@21`) survive on the card. `inject` with `--media-dir` restages it
  from that directory; without it the card's own is carried through byte for
  byte. A card with no media carries no `media.json`.

```bash
mkmulticard.py inspect --card CARD [--json] [--media-out DIR]
```

reads it all back with no mounts and no writes: the table, the menu, the
provenance, the media list and every games tree's `title_dir` and validator
state. The default is a human table; `--json` prints ONE object on stdout
(`card`, `size`, `layout`, `partitions`, `images[]` with `art_source` /
`anim_source` / `source` / `source_exists` / `title_dir` / `bypass` /
`version` / `version_source` / `sidx` / `sidx_version` / `elf_version` /
`node_fw` / `node_fw_version` / `built_version`, the globals, `media[]`,
`has_build_json`, `has_media_json`, `selector`, the ready-made
`version_mismatch` / `node_fw_mismatch` / `title_mismatch` /
`unknown_version` sentences (null when the images agree), and `warnings`),
and `--media-out DIR` extracts the card's media directory +
`media.json` into `DIR` - the flat shape `--media-dir` reads back, so a loaded
menu can be previewed and re-injected without a rebuild. A card written before
the sidecars existed still loads: the unknown fields degrade to `null` with a
warning. Exit 0 with the report; exit 2 only when the file is not a Spike 2
card or carries no selector.

That is the loop the app's Multi-boot tab runs on: `inspect --json --media-out`
fills the fields, then `inject` (seconds) writes back anything the menu owns -
titles, subtitles, art/animation/music, sounds, volume, countdown, default.
Adding, removing, reordering or replacing an image is a partition change and
still needs a full `build`.

### The validator bypass

A modified image trips Stern's game self/asset validator (`GAME VALIDATION
ERROR / UPDATE SD CARD`). `mkmulticard.py build ... --bypass-validation`
neuters it in EVERY games tree on the output card the way the app's Write
does (`plugins/stern/valpatch.py`: `validation_exec` found by signature,
`bx lr` at its entry, that tree's `.sidx` record of the game file refreshed)
and prints `validator: bypassed` / `validator: none on this build` per tree;
`mkmulticard.py bypass --card OUT` applies the same to an existing card in
place (`--dry-run` only reports) - which is what fixes a card that already
shows the error, no rebuild. Every partition written into gets an
`OUT.pN.md5` sidecar and `verify` holds it to that instead of the source,
and reports `bypass_status: armed|bypassed|absent|unlocated` per tree.
Measured on a two-image card carrying a stock image and a modified build of
the same version: the stock tree was ARMED and took 40 bytes (4 + the two
digests), the modified tree was already bypassed; the `.sidx` HMAC and MD5
matched the patched ELF afterwards and `verify` PASSed. The tamper *state*
lives on the machine's board NVRAM, not on the card: a machine that already
booted an unpatched image may keep its flag until a settings/factory reset.

**THE BYPASS ALSO SWITCHES OFF THE GRADE RESTORE (item 98).**  The validator
persists its three track grades in the board's NVRAM; the module's START
function restores that blob over its globals at every boot and initialises
the grades to P only when the restore fails, and only the state machine tick
ever re-grades.  A `bx lr` on the tick alone therefore froze whatever grade
was last written down: a GAME VALIDATION ERROR an earlier card left in the
machine stayed latched for ever on David's TMNT, on both images.  The bypass
now also turns the restore call (`bl` after `mov r0,#0x50; mov r1,#0x214; mov
r2,rN; mov r3,#0x80`, the same shape on every build measured) into
`mov r0, #0` - "the restore failed" - so a bypassed image starts every boot at
P/P/P and boots clean (`valpatch.find_grade_restore`).  A card patched before
this reads `validator: HALF bypassed` and any bypass run finishes it.  The
app's tick is ON by default (David: "make both images clear the validation
errors always"); `update --restore-validation` (the tick off) puts the
source's own game and `.sidx` back on every tree the card holds bypassed.

The hardware side is the same program installed in p2 and hooked into
`/etc/init.d/game` by `select.sh`, reading the flippers over the node bus and
remounting `/games` from the chosen partition - `codeselect/DESIGN.md` has the
card layout, the file formats and the degrade-to-stock rules.

### Updating a card in place (item 93)

A finished card is not rebuilt for a small change.  `build` records what is on every
games tree (`/usr/local/codeselect/trees.json` on p2, beside `build.json`: every file's
sha256, size, mode and owner, every symlink and directory, and the stamp - size, mtime,
partition UUID - of the source each tree came from), and

```
mkmulticard.py update --card OUT [--primary P --extra X ...] [menu flags as build] [--dry-run]
```

writes ONLY what changed since.  Every source's stamp is compared with the record; an
unchanged source is skipped without a byte read; a changed one is hashed (about 16 s per
4 GB, cached under `%TEMP%\pinball_spike2_multiboot` so it is never hashed twice); the
diff per tree is applied through a loop mount of that partition alone - every write a
temporary file then a rename, adds before removals, whole trees moved in two phases when a
multi card's images are reordered - then the validator bypass runs through the mount for a
tree whose game changed, the record is written last, and `verify --touched` re-hashes what
moved.  A one-file change is about a minute; the work is proportional to the change, not
the card.  A multi card's p7 grows on demand (resize2fs on the loop device) up to the
Stern size class when an added image needs the room.

**Root.**  `update` and `build` run under `wsl -u root` (the app passes the desktop user's
HOME so `~/spike2root` is still theirs): the loop mount is what makes writing into a
`.raw` on a Windows drive fast (~150 MB/s with `--direct-io=on`; debugfs manages 13).
`plan`, `update --dry-run`, `verify` and `inspect` stay ordinary-user runs - they read the
card through the pure-Python ext4 reader and debugfs and never mount.

**What it refuses, before writing anything:** a card that is not a regular file; a card
something else holds (a fuse2fs mount of it - the emulator with its cache off - or the card
cache's copier); another update of the same card (a flock on `<card>.lock`); a loop of the
same file mounted anywhere but under this tool's own `/var/tmp/mkmulticard_mnt_*`; a
`parts`-layout list change (that layout holds its extra as a whole partition - build a
fresh card); a primary that is another build (p1 must be the card's bytes and p2, minus the
boot menu's own files, the same tree - never a range md5, which a rw mount stamps); a
partition without room for the update's PEAK (a replacement's new bytes coexist with the
old until the rename); `--expect-bytes N` when a source moved since a dialog measured it.

**Crash safety.**  Before the first write the rootfs is copied to `<card>.p2.bak` (the one
partition an interrupted write could leave unbootable - `dd` it back), and the record is
written with the touched partitions flagged DIRTY; the small p2 writes go through one
debugfs script straight into the card (never the 352 MB extract/write-back).  A killed
update leaves old files in place, temporary files, a loop device and the dirty flag; the
next `update` detaches the stale loop (held by nobody, under this tool's prefix), runs
`e2fsck -fy` on the dirty partitions, sweeps the leftovers and converges; `verify` fails a
dirty card loudly, and `inject` refuses it.  A card built before item 93 carries no record:
the first `update` hashes its trees once (cached under the card's own stamp) and records
them.  `verify` holds a partition written in place to the record rather than to a range
md5 (a rw mount alone moves the superblock); `plan` prints `image-size free N`, the room
the games partitions keep for updates, and every image row is its tree's used bytes.

`mkmulticard.py selftest DIR` part 4 proves the record with any user; part 5 (root) proves
update: nothing changed writes nothing, one changed file writes one file, the primary's
tree syncs in place, list changes on a parts card refuse, another build refuses at the
gate, an unrecorded card is hashed once, a multi card reorders/removes/adds without
copying what stayed, p7 grows, a held lock refuses, a writer SIGKILLed mid-file is
repaired by the next update, and a foreign mount of the card refuses by name.

### The compact layout (item 95) - opt-in, experimental

Three TMNT 1.59 images (stock pro, 1987 pro, 1987 LE) are 18 GB on a card while their
unique content, by sha256, is 6.6 GB: the 1987 pro and LE share 2.4 GB at DIFFERENT paths
(`turtles_pro/` vs `turtles_le/`), the stock and the 1987 pro 2.4 GB more.  `build --layout
store` (root, like `update`) keeps one copy of every file the images have in common:

```
mkmulticard.py build --primary P --extra X --extra Y --out OUT --layout store [--size 16G|32G|content] ...
```

The primary's own p3 - Stern's filesystem, copied verbatim - is grown with `resize2fs` on the
loop device to the smallest Stern image size that holds the union of the images' unique
content (`--size` picks another; `content` = just what it needs), p5 and p6 are re-laid after
it (the card names them by device, never by LBA), and there is no p7.  Inside p3:

```
/spk/ /<title>/ game conagent data   the primary's tree at the root, byte for byte Stern's (image 0)
/img1/ ... /imgK/                    the extras: complete trees of the same shape (images 1..K)
/.blobs/<sha256>.<mode>.<uid>.<gid>  one inode per unique (content, mode, owner); every regular
                                     file of every tree is a HARDLINK to its blob
```

The primary's files are ADOPTED (linked into `.blobs/` - zero bytes rewritten, its inode
numbers stay the source's); each extra is synced into its `imgK/` writing only the blobs the
store does not hold yet.  The three TMNT images come to about 8 GB on a 16G card.  The menu's
device for an extra is `/dev/mmcblk0p3:img1`, which `select.sh` already handles the way it
handles `p7:img1` (umount /games, mount the device, bind the subtree).  `plan --layout store`
hashes the sources (cached) and prints each image's UNIQUE bytes as its row plus
`image-size shared N`, the bytes stored once.  `update` works on a store card as on any other
- a file the store already holds is linked, not written (the dry-run's byte counts say so),
blobs nothing links any more are collected - and `verify` adds the store's own invariants:
every blob's name parses and matches its inode's mode/owner, every file of every tree is a
link into the store, every blob's link count is 1 + its references, no orphan, no half-written
blob, and (full) every blob hashes to its name.  The validator bypass goes through the mount
(a raw write behind a shared blob would patch every tree at once) and the patched game is
adopted into the store under its own key, so two images with the same stock game share one
patched game too.  `parts.py --list-games` lists the store's trees under p3 (`3 ... <title>
img1`), which the emulator's `run_game.sh` binds as it binds a p7 subtree.

**Rules.**  Never USB-update a store card: a Stern update writes through hardlinked blobs
into every tree sharing them - rebuild with this tool.  `bypass` refuses a store card (use
`build --bypass-validation` / `update`).  The tick in the app ("Compact build", beside the size
strip; the bar hatches what it saves) is OFF by default and the layouts the app has always
made are untouched without it.  Ticking it hashes every image the first time (20-30 s for two;
the cache answers after), and the strip shows it thinking meanwhile - the head reads "…", a
hatched band sweeps the bar until `plan`'s meter (`[card] progress … measuring <image>`) says
how far it has got, and the detail line names what is being measured.  Two things only hardware can prove: that Stern's update/spk
layer tolerates `.blobs/` and `img1/` at the primary's `/games` root, and the same-device
remount of p3's subtree; the tick says experimental until both have.

**Proven in the emulator (2026-09-05):** the store card of David's three TMNT images (stock
pro, 1987 pro, 1987 LE; `verify` PASS in full) booted each image through the menu -
`[select] chose 0/1/2`, the extras bound from `p3:img1` / `p3:img2` with their own clip root -
reached its attract with that image's own art, and took START into PLAYER 1 / BALL 1 with a
ball fed every time (DESIGN.md's proof table, run 7).

`selftest` part 6 (root) builds a store card from three sources sharing files by content at
different paths (and one with another mode), checks the shared inode has link count 4, the
other-mode twin its own blob, the primary's inode numbers unchanged, verify PASS (full), the
plan rows' invariant, inspect's `trees.store` block, `--list-games`, then update drills: a
new unique file writes once, a file the store holds writes nothing (linked), reorder = renames,
remove = its blobs collected, add back = only its own bytes, the primary's tree synced in place,
a raw bypass refused.

## Titles

**Per-title emulation status, one line per title, kept current by `/finish`**
(item 57, David's ask 2026-08-19: "we should be keeping a running list of
what each game has and doesn't have"). Four columns, each a plain fact about
ONE run, not a promise about every card version of that title:

- **switches** — does a real switch table exist (either the runtime's own
  live `[sw]` dump, or `swelf.py`'s static fallback) with plausible Stern
  numbering (flippers/slings/trough checked against the standard scheme)?
- **artwork** — does the virtual playfield draw the title's own CAD/service
  drawing, or fall back to the schematic dot layout?
- **positions** — do the artwork-relative device (LED/coil/switch) XY
  coordinates land INSIDE the artwork, so the picture and the wire agree?
- **2nd display** — does the title open a second window, and does it show
  real content or nothing? `n/a` = never targets one.

A title only reaches "clean" when all four say so. **This table is built
from real runs, not inference** — a title not yet re-checked keeps its last
known state with the date it was last run, not a guess.

★ **THE DEVICE-TABLE AUDIT IS NOW MEASURED RATHER THAN INFERRED, AND IT WAS
DONE OFF THE RIG** (2026-08-21, item 61). Every `.raw` in
`images/Stern/spike2` plus the running custom card — 40 images — was read with
the repo's OWN read-only ext4 reader (`plugins/stern/explorer.CardImage`), which
pulls `/<title>/game` straight out of the image. Nothing was mounted, no card
cache was copied, no lock was needed and a live run was untouched; the whole
sweep takes about two minutes. **`cardaudit.py` is that sweep** — run it with
no arguments for the whole library, or name images:

```
python tools/spike2_emu/cardaudit.py
python tools/spike2_emu/cardaudit.py "C:/.../My Custom Card.raw"
```

**Re-run the audit that way. A mount-and-run sweep is what poisoned the table
cache in the first place, and it cannot be done while anyone is playing.**

**THE DEVICE TABLE IS A PROPERTY OF THE BUILD, NOT OF THE TITLE, and that is the
finding that resolves most of the 2026-08-19 disagreements.** Stern adds the
graphical device test data in a specific release, so an older card for the same
title legitimately has none:

| title | older build | newer build |
|---|---|---|
| `godzilla_le` | 1.13.0 — no `Test` dir, 0 records | **1.14.0 — 593 records, art shipped** |
| `jaws_le` | 1.01.0 — 0 records | 1.02.0 — 439 records |
| `elvira3` | 1.11.0 — 0 records | 1.13.0 — 275 (topper only) |

So the 2026-08-19 sweep's `❌ none shipped` for `godzilla_le` was CORRECT about
the card it measured (`godzilla_le-1_13_0`), and wrong only as a claim about the
title. The card David actually runs is a custom image built on **V1.14.0**, and
that build ships both the drawing and a complete layout. A row here names a
build from now on.

**11 of the 40 images carry a device table** (10 of the 39 in
`images/Stern/spike2`, plus the running custom card):

| card image | build | device records | layout image | art on the card | draws on art |
|---|---|---|---|---|---|
| `deadpool_pro-1_16_0.Release.8G.sdcard.raw` | 1.16.0 | **459** (coil=14 led=376 switch=69), 160 on the layout | `playfield` | `deadpool_le_playfield.png` 330x710<br>`deadpool_pro_playfield.png` 329x710 | yes |
| `dungeons_and_dragons_le-1_00_0.Release.16G.sdcard.raw` | 1.00.0 | **255** (coil=16 led=169 switch=70), 229 on the layout | `TestMode/Rope_LE-Premium-X8-X9_TOP_rotated_edit_cropped` | none shipped | blank field |
| `elvira3-1_13_0.Release.16G.sdcard.raw` | 1.13.0 | **275** (led=275), 275 on the layout | `System/TestMode/universal_topper_scaled` | none shipped | blank field |
| `Heisei Custom Image Premium V1.raw` | custom (V1.14.0) | **593** (coil=14 led=513 switch=66), 177 on the layout | `playfield` | `scaled_godzilla_le_playfield.png` 313x710 | yes |
| `godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw` | 1.15.0 | **575** (coil=10 led=506 switch=59), 164 on the layout | `playfield` | `scaled_godzilla_le_playfield.png` 313x710<br>`scaled_godzilla_pro_playfield.png` 313x710 | yes |
| `james_bond_60th_le-1_10_0.Release.8G.sdcard.raw` | 1.10.0 | **513** (coil=16 led=426 switch=71), 138 on the layout | `Test/scaled_playfield` | `scaled_playfield.png` 202x443 | yes |
| `james_bond_le-1_06_0.Release.16G.sdcard.raw` | 1.06.0 | **526** (coil=17 led=429 switch=80), 185 on the layout | `playfield` | `bond_le_playfield.png` 459x998<br>`bond_pro_playfield.png` 459x998 | yes |
| `jaws_le-1_02_0.Release.16G.sdcard.raw` | 1.02.0 | **439** (coil=14 led=347 switch=78), 217 on the layout | `playfield` | `jaws_le_playfield_scaled.png` 312x710<br>`jaws_pro_playfield_scaled.png` 312x710 | yes |
| `john_wick_le-1_01_0.Release.16G.sdcard.raw` | 1.01.0 | **503** (coil=16 led=412 switch=75), 479 on the layout | `playfield` | `john_wick_le_playfield.png` 321x710<br>`john_wick_pro_playfield.png` 321x710 | yes |
| `king_kong_le-0_96_0.Release.16G.sdcard.raw` | 0.96.0 | **517** (coil=21 led=421 switch=75), 489 on the layout | `TestMode/Rodeo_LE_Service_Playfield_Wireframe_300dpi_cropped` | `Rodeo_LE_Service_Playfield_Wireframe_300dpi_cropped.png` 312x710<br>`Rodeo_PRO_Service_Playfield_Wireframe_300dpi_cropped.png` 313x710 | yes |
| `metallica_spike-1_03_0.Release.32G.sdcard.raw` | 1.03.0 | **664** (coil=22 led=569 switch=73), 502 on the layout | `TestMode/metallica_playfield_with_handle_cropped` | `metallica_playfield_with_handle_cropped.png` 312x710 | yes |

**★ CORRECTION, 2026-08-28 (item 80, led_zeppelin_le): "ship none" was
measured with a parser that could not SEE one whole variant of this table, so
the list below overstates itself and it is not yet known by how much.** A build
can ship the device table with the ARTWORK left out — the image field points at
the shared empty string and x/y/w/h, the connector and the part number are all
zero — while still carrying the class, the (group, index) and the NAME, which is
everything this rig joins on. `devicexy.seeds()` looks for a pointer to an image
NAME to find a table at all, and an artwork-less one contains none, so it was
never seeded and the title read as `0 records`. **`led_zeppelin_le 1.22.0` is in
the list below and ships 617 of them** (coil=23 led=499 switch=95). The parse
now handles the variant (`devicexy.BLANK_IMAGE`); what has NOT been redone is
the 40-image `cardaudit.py` sweep that produced this list, so **every
`ship none` here is unverified until it is re-run.** The three titles reachable
without a card mount were re-measured by hand and two of them changed:
`turtles_pro` 0 → 259 records, `dungeons_and_dragons_le` +41, and
`godzilla_pro` +17 with all 575 of its existing records byte-for-byte identical
— which is the control that says the change only adds tables the old seeder
could not reach and alters nothing it could.

The other 29 were measured as shipping none, on the builds we hold: `aerosmith_le 1.15.0`, `avengers_infinity_le 1.09.0`, `batman 1.13.0`, `deadpool_le 1.14.0`, `elvira3 1.11.0`, `foo_fighters_le 1.03.0`, `godzilla_le 1.13.0`, `guardians_le 1.14.0`, `iron_maiden_le 1.16.0`, `jaws_le 1.01.0`, `jurassic_park_le 1.15.0`, `led_zeppelin_le 1.20.0`, `led_zeppelin_le 1.21.0`, `led_zeppelin_le 1.22.0`, `led_zeppelin_pro 1.20.0`, `led_zeppelin_pro 1.22.0`, `mando_le 1.44.0`, `munsters_le 1.27.0`, `rush_le 1.18.0`, `star_wars_le 1.30.0`, `stranger_things_le 1.12.0`, `sword_of_rage_le 1.18.0`, `turtles_le 1.58.1`, `turtles_le 1.59.0`, `turtles_pro 1.58.0`, `turtles_pro 1.59.0`, `uncanny_xmen_le 0.97.0`, `venom_le 1.06.0`, `venom_le 1.07.0`.

**What the 2026-08-21 seeder fix changed across the whole catalogue: exactly one
image.** `godzilla_le` V1.14.0 went 477 → 593 records (coil 0 → 14, switch
18 → 66) and its layout image flipped from
`System/TestMode/spike_2_cabinet_front_cropped` to `playfield`. **The other 39
are byte-for-byte identical under the old and new seeder** — that is the control
that says the fix only adds the runs a merged string hid, and invents nothing.

**Known self-check noise, not regressions** (identical before and after the
fix): `LEFT POP BUMPER` sits right of centre on `deadpool_pro`, `james_bond_le`
and `metallica_spike` — the name is the left pop OF A CLUSTER, so the
left/right check counts it wrong; `elvira3` 1.13.0 positions 275 TOPPER lamps
and nothing else, so its records fall outside a playfield-sized box by design
(item 50's case); `dungeons_and_dragons_le` and `elvira3` position devices but
ship no matching art, so they draw on a blank field.

**Every `❌ none shipped` / `not re-measured` row in the table below is now
CONFIRMED by that sweep** — for the build named in the list above, and only for
it. What the sweep cannot answer is the other three columns: switches, second
display and whether a title actually boots are properties of a RUN, and those
still come from running it.

**`E2E play (item 80)` column, added 2026-08-24.** The other columns are all
DESK WORK or scripted-boot measurements (item 57's sweep and its successors).
This one is different: it is David actually playing each title, alphabetically,
in the app, and reporting what he sees — ball serve, video, audio, coils, the
whole machine, not just switches-boot-to-attract. `not yet` means this pass
has not reached that title. See item 80 in `plans/TODO.md` for the log and the
per-title follow-up items it spawns.

**`build` column, added 2026-08-28, and it is not decoration.** A row that names
only a TITLE cannot say which card was measured, and the device table is a
property of the BUILD — the same fact the card-image table above already
records. `jaws_le` is what forced the column: **1.01.0 ships no device table and
no service art at all, 1.02.0 ships 439 records and two playfield drawings**, so
a single `jaws_le | ✅ | ✅` row was true of one card in the library and false of
the other, and a run of 1.01.0 correctly drew the switch-list view while the row
promised artwork. Both builds now get their own row, the way `godzilla_le`
already did for 1.13.0 vs V1.14.0.

**How each build was established**, strongest evidence first: the `# binary: game
N bytes` line `devicexy.binary_id()` writes into the cached `device_xy.txt`,
matched against the ELF size `cardaudit.py` reads out of each library image —
that is what pins `elvira3` to 1.13.0 (8770432) and `turtles_pro` to 1.59.0
(6457552), the two titles here we hold two builds of and could otherwise only
guess at; and, where the library holds exactly ONE image for a title, the
filename. Three rows say **not recorded** rather than guessing: `venom_le`,
`turtles_le` and `led_zeppelin_le` were measured before `binary_id()` existed,
we hold more than one build of each, and nothing on disk says which one ran.

**And one row's binary matches NO image in the library**: `godzilla_pro`'s
cached table was built from a 7912180-byte ELF, while the stock
`godzilla_pro-1_15_0_spike2` image carries 7884188 bytes. The two produce the
IDENTICAL 575-record table (coil=10 led=506 switch=59), so the measurements in
that row stand — but the binary they were taken from is a modified 1.15.0, not
the stock card, which is worth knowing before anyone treats the baseline row as
a statement about a factory machine.

| title | build | switches | artwork | positions | 2nd display | E2E play (item 80) | last checked |
|---|---|---|---|---|---|---|---|
| godzilla_pro | 1.15.0, but a MODIFIED ELF — see below | ✅ live, 88 | ✅ | ✅ (baseline) | n/a | not yet | 2026-08-19 |
| jaws_le **1.02.0** | 1.02.0 | ✅ live, 109 | ✅ jaws_le_playfield_scaled.png 312x710 | ✅ 217/439 on the layout, 0 outside; 82/82 RGB stems aligned; 28/29 left-right, and the one flagged name is real geometry, not a misread — `LEFT RAMP ENTER` sits at x=159 against a 156 midline, 3 px the wrong side of centre and right beside `LEFT RAMP MADE OPTO` at x=153, so the ramp straddles the centreline | n/a | ✅ clean, 2026-08-28; green check re-confirmed 2026-09-01 (David) | 2026-09-01 |
| jaws_le 1.01.0 | 1.01.0 | ✅ live | — none shipped (the card has no `images/Test` **or** `TestMode` directory at all) | ❌ 0 records — this build ships no device table; the ELF contains no image-name string to seed one | n/a | ran, but superseded by 1.02.0 | 2026-08-28 |
| john_wick_le | 1.01.0 | ✅ live, 106 | ✅ | ✅ | n/a | ⚠️ plays, with one OPEN fault, 2026-09-01 (David): **the car mech screeches its tyres continuously from ball start.** No car exists to answer `Car Motor Home` / `Car Motor Away` (node 9 bits 3-4) or the three car optos (bits 0-2), so the game drives the mech, times out waiting for position, and retries for ever - the screech is its move sound on every retry. Same shape as the DnD dragon and the trough feeder: a mech wanting closed-loop feedback the rig does not yet answer. Nothing else wrong on this title | 2026-09-01 |
| james_bond_60th_le | 1.10.0 | ✅ live, 118 | ✅ | ✅ | n/a | not yet | 2026-08-19 |
| james_bond_le | 1.06.0 | ✅ live, 108 | ✅ bond_le_playfield.png | ✅ | n/a | ✅ clean, 2026-09-01 (David; three runs — the credits-scene attract SEGV fired on 2 of 3 boots and stays covered by the armed reporter, true backtrace on next fire; play itself clean) | 2026-09-01 |
| deadpool_pro | 1.16.0 | ✅ live, E2E-played, 103 | ✅ deadpool_pro_playfield.png | ✅ 41 placed | n/a | ✅ played, 2026-08-27 (David) | 2026-08-27 |
| king_kong_le | 0.96.0 | ✅ live, 105 | ✅ Rodeo…Wireframe.png (item 57 fix) | ✅ 489/517 inside, 0 outside (item 57 fix) | n/a | not yet | 2026-08-19 |
| dungeons_and_dragons_le | 1.00.0 | ✅ live, E2E-played to Player 1 Select a Character, 104 | ✅ `TestMode/Rope_LE-Premium-X8-X9_TOP_rotated_edit_cropped.png` (fixed 2026-08-28 — see note below) | ✅ 229/255 on the layout | n/a | ✅ played to Player 1 — Select a Character, 2026-08-28 (David; needs the Device Enables adjustment noted below) | 2026-08-28 |
| venom_le | 1.06.0 **or** 1.07.0 — not recorded | ✅ live, 107 | ❌ none shipped | not re-measured | n/a | not yet | 2026-08-19 |
| turtles_le | 1.58.1 **or** 1.59.0 — not recorded | ✅ live, 96 | ❌ none shipped | not re-measured | n/a | not yet | 2026-08-19 |
| uncanny_xmen_le | 0.97.0 | ✅ live, 110 | ❌ none shipped | not re-measured | n/a | not yet | 2026-08-19 |
| deadpool_le | 1.14.0 | ✅ live, E2E-played, 103 | ❌ none shipped | ❌ 0 device records (title ships no device table at all, not a parser gap — measured 2026-08-27) | n/a | ✅ played, 2026-08-27 (David) | 2026-08-27 |
| godzilla_le **V1.14.0** | custom (V1.14.0) | ✅ live, 98 | ✅ scaled_godzilla_le_playfield.png 313x710 | ✅ 177/593 inside, 0 outside; 30/30 left-right; 48 switches, 14 coils, 115 lamps placed | n/a | boots and holds attract, 3 min, 2026-09-01 (`Godzilla Premium 1.15 Heisei Custom V1.0.raw`, game ELF 7930828) — 98 switches, `picture: FIRST at frame 19`, no `[segv]`, clean teardown; not a played game, so not a green check. **A USER's card of this family DOES die at start** (PAD-102: a Godzilla Premium **1.16** Heisei custom, ELF 7962924, 32096 bytes larger): switches drawn, renderer up, then SEGV ~4 s in, twice identically, right after `[play] guest reports 44100 Hz x 2 ch`. **SOLVED 2026-09-02, and the cause was OURS** — every 1.16 reproduces it (stock and retheme); `sw_prime()` splatted hwshim's own .bss through `SW_NODEREC` under a shadow switch table, and the shim then tail-called the pointer it had just overwritten. Item 93. **His crash report was also part fiction** — the reporter's hard-coded blocks are godzilla_pro 1.15.0's and the gate matched any name starting "godzilla", so godzilla_le got Pro's loader gate, event table and mixer read against its own unrelated memory, and the pool walk then faulted a second time inside the handler and truncated the report. Fixed the same day (`gz_addrs_ok`, whole-name match), and the truncation reproduced before/after on demand | 2026-09-01 |
| godzilla_le 1.13.0 | 1.13.0 (game ELF 7453652) | ✅ live, 98 (first run of this build, 2026-09-01) | — no device test data in this build | — 0 records (measured off the card) | n/a | boots and holds attract, 3 min, 2026-09-01 — `picture: FIRST at frame 4`, video steady at 30 fps (61 frames / 2033 ms, late 0), no `[segv]`, clean teardown. Not a played game, so not a green check; run as the PAD-102 control and it did NOT reproduce that user's start crash | 2026-09-01 |
| godzilla_le **1.16.0** | 1.16.0 (game ELF 7962924; the Heisei V1.5 retheme carries the same size, 2162 bytes differing, none in code that matters here) | ✅ live, 98 — resolved by SHAPE, so this build runs on the shadow route (`entry[]=0x009a9990 raw[]=0x00000000`), which is what exposed item 93 | not re-measured | not re-measured | n/a | ❌ died ~4 s into every boot until 2026-09-02 (PAD-102, a user's card; reproduced here on BOTH the stock image and the Heisei V1.5 retheme, register-identical) → ✅ boots and holds a full 6-minute run after the item 93 fix: picture at frame 47, no `[segv]`, no `[swprime]`, `sw_rest_set` intact, clean teardown. Not a played game, so not a green check | 2026-09-02 |
| metallica_spike | 1.03.0 | ✅ live, 106 | ✅ metallica_playfield…png (item 57 fix) | ✅ 502/664 inside, 0 outside (item 57 fix) | n/a | not yet | 2026-08-19 |
| aerosmith_le | 1.15.0 | ✅ static (swelf.py), live-verified | — no device table shipped | — | n/a | ✅ clean, 2026-08-24 (David) | 2026-08-19 |
| avengers_infinity_le | 1.09.0 | ✅ static (swelf.py), live-verified | — | — | n/a | ✅ clean, 2026-08-24 (David; validation banner was item 62's stale NVRAM grade, fixed + relaunch-verified same day) | 2026-08-19 |
| batman | 1.13.0 | ✅ static (swelf.py), live-verified | — | — | ✅ VILLAIN VISION window — SOLVED & live-faithful: own `[villain vision]` window mirrors node 24's control stream exactly — clips PLAY by commanded id (lossless webp), block commands CYCLE clip-by-clip, brightness 0 BLANKS the screen and 255 reveals (the per-beat fade the game sends), verb 2 holds the last frame (play-once). `lcdring.py` reads the transcript live or from `padlcd.last`. **RE-verified architecture (10-agent pass) + GROUND TRUTH (video of the real machine, 2026-08-25):** ONE physical TV, bezel-printed "Villain Vision" (the old "three TVs" line was invented — deleted). The node bus is CONTROL-only (LPC1113, can't decode video); the real display is COMPOSITED by the game on a GPU "secondary display" render target (`fbGetDisplayByIndex(2)`) that batman's binary HARD-DISABLES (renderer-ctx +0xf0 = NULL, 0x1e79c8) — which is why the 4 villain gst channels die at 0 frames. **Proof from the machine:** the real attract shows game-RENDERED cards (a "Game Over" card, the BATMAN-on-green logo) that exist nowhere in the 3,069-clip store (3 independent scans) — so a bus mirror can never show those. Verified against the video and matching: ~5-7 s per item, a fully black frame between items, one full-screen motion clip. **The window shows the CARD'S OWN TV artwork** (`lcdframe.py` pulls the villain scene's wood-cased TV sprite — screen hole and all — off the card; the clip is composited into it keeping its aspect, falling back to a drawn cabinet when a title has no such texture) with a **filmstrip of the last four clips** under it, so the SEQUENCE is visible at a glance rather than one frame at a time. **Clips are NAMED**: `lcdnames.py` parses the title's scene.radium at run start into `<tables>/<game>/lcd/names.txt` (3,069/3,069 for batman, 0.15 s) and the window shows e.g. `asset 54 - once` / `S1E001 00:18:32` - which is also the first independent verification of the id-to-clip mapping (asset 2 is named `PhoneScenes...` and shows the Batphone). **THE BOARD IS AN ID→STILL LOOKUP (2026-08-26, two tripod videos of the real machine + the TV-settings "update the images" diagnostic tester-found in the service menu):** the display NEVER plays video - it holds one stored still per command id and fades (~0.3 s) between them. The attract cycle is 11 stills at ~5.3 s on a 62.7 s loop - one-for-one with the wire's 11-command rotation - and gameplay rests on the green logo card while the wire hammers asset 54, which anchors the whole mapping: 2=Game Over card, 54=logo, 720=Riddler, 591=Batmobile, 601=Gotham City sign, 1605=umbrella sign, 1736=Penguin, 2066=Penitentiary, 2359=Joker, 3004=fur-shop sign, 3026=Catwoman, 919-block=IN COLOR title card. `lcdstills.py` derives a CARD-ONLY still set - it extracts stills from the mounted card at runtime and ships NO asset (the board has its own image store, id-mapped independently of the clip store: wire 591=a frame of clip 27, wire 601=another frame of clip 27, so the set can't be derived by clip id). Five ids whose board image is a card store frame are mapped (logo scene texture + Batmobile/Gotham sign/Joker/Catwoman clip frames); the game-rendered cards and villain/sign stills exist in NO unpacked card store and are left unmapped (fall back to the clip still, never footage) until the UPDATE TV IMAGES service upload is captured - the one place the byte-exact board images and their ids both surface. The panel selects stills by id, fading only the SCREEN (the cabinet never dims), no clip playback. Event cards (BALL SAVE) are further unmapped ids; the board's byte-exact uploaded set is capturable by running the TV-settings diagnostic on this rig with the wire logged. Exact id↔clip correspondence at a given real-machine moment beyond those pins is still not claimed. The 0x90 poll is answered (present board) but its content is inert — nothing reads it (get_status is dead code) and it does NOT stop the game's own 250 ms double-command (items 82/83) | not yet | 2026-08-25 |
| foo_fighters_le | 1.03.0 | ✅ static (swelf.py), live-verified | — | — | n/a | ✅ clean, 2026-08-28 (David) | 2026-08-19 |
| guardians_le | 1.14.0 | ✅ static (swelf.py), live-verified | — | — | n/a | ✅ clean, 2026-08-28 (David) | 2026-08-19 |
| iron_maiden_le | 1.16.0 | ✅ static (swelf.py), live-verified | — | — | n/a | ✅ clean, 2026-08-28 (David) | 2026-08-19 |
| jurassic_park_le **1.16.0** | 1.16.0 | ✅ live, 108 | ✅ `test_menu/jp_le_playfield.png` 312x710 (found 2026-09-01 — the folder is spelled `test_menu` on this build, a name neither `find_playfield_art()` nor `cardaudit` looked in; both read the folder list off the card now) | ✅ **221 records** (coil=17 led=113 switch=91), 178 on the layout, 0 outside; 58 switches placed. 5 of 65 left/right names sit on the wrong side (LEFT POP BUMPER, LEFT RAMP SIGN 1/2) — not re-checked against the glass | n/a | ✅ clean, 2026-09-01 (David's green check, after the two fixes this pass: the `test_menu` artwork discovery and the stale-switch-list guard — its first run showed the wrong key mapping, a 48 V warning on a closed door and dead flippers, all from a switch list cached off 1.15.0) | 2026-09-01 |
| jurassic_park_le 1.15.0 | 1.15.0 | ✅ static (swelf.py), live-verified | ❌ none shipped — this build's `assets/nuk/images` holds only `Connectivity`, no drawing of any kind, so the schematic playfield is the right answer for it | ❌ 0 records — ships no device table | n/a | ran 2026-09-01, superseded by 1.16.0 (which ships both) | 2026-09-01 |
| mando_le | 1.44.0 | ✅ static (swelf.py), live-verified | — | — | ✅ real (topper accessory, David-confirmed) | not yet | 2026-08-19 |
| rush_le | 1.18.0 | ✅ static (swelf.py), live-verified | — | — | n/a | not yet | 2026-08-19 |
| star_wars_le | 1.30.0 | ✅ live, 104 | ❌ none found | not re-measured | ✅ real (mini display above the targets, David-confirmed) | not yet | 2026-08-19 |
| turtles_pro | 1.59.0 | ✅ live, 94 | ❌ none found | not re-measured | n/a | not yet | 2026-08-19 |
| elvira3 | 1.13.0 | ✅ live, 110 | ❌ none found | not re-measured | n/a | not yet | 2026-08-19 |
| led_zeppelin_le | **1.22.0** (ELF 69473804 bytes, the mounted card) | ✅ live, 96 — 95 named, 1 `?` (node 9 bit 30, a wire bit the device table does not carry) | ❌ none shipped | ❌ **0 positions, but 617 device records** — this build ships the table with the DRAWING left out: names, class and (group, index) for coil=23 led=499 switch=95, and no coordinates at all | n/a | ✅ clean, 2026-08-28 (David) — after the artwork-less device-table fix below; ❌ 2026-09-01 every game START died `SIGBUS` (an unaligned `LDRD` in the sound preloader that the real kernel fixes up and qemu-user does not — `hwshim.c` now does the kernel's fixup, `[align]` on the pane) → ✅ CLEAN, David's green check, 2026-09-01 (after the same-day fix) | 2026-09-01 |
| stranger_things_le | 1.12.0 | ✅ static (swelf.py, item 52) | ❌ none found | not re-measured | ✅ real (projector, item 44) | not yet | 2026-08-19 |
| sword_of_rage_le | 1.18.0 | ✅ static (swelf.py, ROOTS_NONUM), live-verified, 98 | ❌ none shipped | ❌ no device table | n/a | not yet | 2026-08-19 |
| munsters_le | 1.27.0 | ✅ static (swelf.py, ROOTS_NONUM), live-verified, 103 | ❌ none shipped | ❌ no device table | n/a | not yet | 2026-08-19 |
| beatles | 1.29.0 | ✅ live, 92 (item 80 sweep fix: all-`?` message-table title, names now filled from the device table) | ✅ Test/beatles_playfield.png 336x710 | ✅ 50 placed (item 80 sweep: `layout_image()` join fix, was hard-coded to the literal "playfield") | not re-measured | ✅ played, 2026-08-27 (David) | 2026-08-27 |

**dungeons_and_dragons_le, 2026-08-28 — Start was refused, and it was BALL
ACCOUNTING, not switches, wiring or NVRAM corruption.** Three real code
fixes landed on the way here and now ship for every title, not just this
one: `gameinfo.py` now falls back to a `TOP`-named art file when a card ships
no file with "playfield" in its name (this is why the artwork column above
flips from ❌ to ✅ — the card was never art-less, the finder just only knew
one naming convention); `nbobjs.py` (new) derives each title's node-board
array base from its own ELF indexing idiom instead of a hard-coded address,
and `coilmap.py`'s `group_node()` derives the coil-group → node map per
title from `node_ident.txt` instead of one constant tuned for godzilla_pro
(this DnD's TROUGH resolves to node 8 idx 1, which the old constant got
wrong); `ballfeed.py` now answers the auto-plunger AND drains the launched
ball home after `PAD_BALL_HOME_MS` (default 5000 ms) unless a keyboard event
claims it — titles that auto-plunge (DnD is the first one seen) were
declaring **Device Malfunction: Auto Plunger** and emptying their own trough
under the old always-refuse behavior.
**The actual Start-refusal root cause was DATA, not code, and does not ship
in this repo**: DnD LE's factory ball count is **8** — 6 in the trough plus
**2 captive in the dragon** — and the game disarms its own Start/Tournament
buttons while it believes balls are missing. Our rig models 6. **A fresh or
factory-reset DnD card needs its own operator adjustment, every time**,
before Start will do anything:
`Adjustments → Machine Settings → Device Enables` — set **Disable Dragon =
Yes**, **Disable Diverter = Yes**, **Number of Balls Installed = 6** (the
page's own help text says the same). This is exactly the setting a real
operator makes on a dragon-less machine; the emulator does not (yet) seed it
automatically, so the artwork/positions ✅ above is unconditional but the
"live, E2E-played" claim depends on that adjustment having been made on the
card's saved NVRAM.

**CORRECTION, same session, right after this table's first version shipped:**
the first pass checked the CONSOLE pane for the live switch dump
(`[event] [sw] id=...` lines), and got 6 false "no live dump" negatives —
`venom_le`, `turtles_le`, `uncanny_xmen_le`, `deadpool_le`, `godzilla_le`,
`metallica_spike` **all actually have a real, complete, correctly-numbered
switch table**; the console's `tail -F` on `gzwatch.log` simply had not
attached yet when the shim wrote its dump, so the lines existed in
`gzwatch.log` on disk but never reached console. `venom_le` was the catching
case: 107 real switches (LEFT/RIGHT FLIPPER BUTTON at 9/10, LEFT/RIGHT
SLINGSHOT at 7/8, TROUGH 1-6, the standard scheme) sitting in `gzwatch.log`
the whole time, zero of them ever forwarded. **Checking `gzwatch.log`
directly (never the console) is now the only trusted method** — the ★★★★
solved-titles bucket up top used the same static/live methods and is
unaffected, but every "❌ no live dump" verdict below this point had to be
individually re-run and re-checked; only `sword_of_rage_le` and
`munsters_le` survived the recheck as genuinely broken, each with its own
EXPLICIT `[swfind] no switch table yet` refusal line naming why (35 and 33
records of the right shape but "(node,bit) not distinct" — the same failure
class already diagnosed, see item 57's `full_solve_one2.sh`/`solve_verify2.py`
work). **`sword_of_rage_le` SOLVED AND SHIPPED same session**: its DEV
record is a THIRD struct variant (name pointer at the record's own start,
not +12 like the original or +12-with-48-byte-stride like the
james_bond_le-class titles) — `swelf.py`'s `ROOTS_NONUM` + `_rows_nonum()`
read it directly with no ENT table at all (none could be found for this
title despite extensive search; `num` ships as an explicit, documented
placeholder since `swtable.py` never actually reads it). Live-verified: 98
switches, clean shutdown, no crash.

**`munsters_le` SOLVED AND SHIPPED, same session, right after being written
down as the catalogue's last gap.** Shares the identical DEV struct as
`sword_of_rage_le` (same offsets, decodes just as cleanly), but its BRD
(slot→node) table needed a different search: the bare-address bijective
scan that found `sword_of_rage_le`'s turned up 16,713 candidates and 789
node-tuples, all zero-heavy noise. Reversing the search order found it —
first collect every address that has AT LEAST ONE literal reference
anywhere in `.data` (6,858 candidates, a much smaller and much cleaner
universe than "every 4-byte-aligned offset"), THEN check which of those
decode to valid, distinct nodes. Exactly one candidate survived, at a
genuine two-reference root (`0x5512e4` — the same "usually exactly 2"
pattern every other confirmed root in this file has). One slot (5, the
BUSIEST by far — 92 of the title's device records, almost certainly the
main lower-playfield board) still read as a nonsense value (1032): turned
out to be a byte-width mismatch, not a wrong address — `1032 = 0x0408`, a
valid node (8, unused by any other slot) in the LOW byte with an
unrelated nonzero flag sitting in the byte above it. Masking every slot's
read to `& 0xFF` (harmless for the other 15 slots, already under 256)
rebuilt the whole table clean: 103/103 rows named, all 18 ground-truth
keyword rows (LEFT/RIGHT FLIPPER BUTTON, LEFT/RIGHT SLINGSHOT, TROUGH 1-6)
landing on the correct node. Live-verified: 103 switches, clean shutdown,
no crash. Full test suite: 2782 passed, 1 unrelated pre-existing GUI-test
flake (`test_a_wsl_restart_re_probes_what_it_left_behind`, a Tk/WSL-panel
test with nothing to do with either changed file — passes clean in
isolation, 0 failures either way).

**Net: of 30 known card versions, ALL 30 have a confirmed-working switch
matrix.** The catalogue-wide "does every title load its switch/coil/LED
matrix and boot to attract" question this item opened with is closed.

**`king_kong_le`/`metallica_spike`'s "positions land outside the artwork"
gap SOLVED, same session, right after being written down as priority (2)
above.** Not a coordinate bug at all: `devicexy.py`'s raw x/y values were
correct the whole time (checked directly - x 7..512, y 1..654, well inside
a 312x710 image). The bug was in the SELF-CHECK, not the data: `checks()`/
`text()`/`main()` filtered "is this device on the playfield" by comparing
`image == "playfield"` literally - a hard-coded spelling one title family
uses, not a constant. `devicexy.py` already HAD the fix for exactly this
class of bug (`layout_image()`, built for item 50's `james_bond_60th_le`,
which spells it `Test/scaled_playfield`) and `playfield.py`'s actual
renderer was already using it correctly - only the diagnostic/reporting
functions were never wired to it, so the rendering was fine the whole
time and only the "N playfield records" COUNT `watch.sh` prints was wrong.
Fixed by routing `checks()`/`text()`/`main()` through `layout_image()`
instead of the literal. Live-verified: `king_kong_le` 489/517 records now
land inside with 0 outside (was 0/517); `metallica_spike` 502/664 (was
0/664). Full test suite clean before and after (2785→2783 passed, the
2 fewer are pre-existing Tk/Tcl display flakiness unrelated to this
change, not new failures - 0 failures either run).
**Both titles are now FULLY clean**: switches ✅, artwork ✅, positions ✅.

**Reading this table alongside item 57 in `plans/TODO.md`**: the earlier
"7 titles share a newly-found 48-byte device-record generation" static
finding is REAL as a structural fact (confirmed by byte-delta histogramming)
but turned out to be **irrelevant to whether a title actually works** —
`james_bond_le`, `king_kong_le`, `led_zeppelin_le`, `venom_le`, `turtles_le`,
`uncanny_xmen_le`, `metallica_spike` all carry that struct and every one of
them has a working LIVE switch table via the runtime's own hunt, independent
of the struct shape `swelf.py`'s static fallback would have needed. The
struct-shape research is preserved in item 57's own history as a real,
possibly-useful-later finding, but it was never the blocker for these
titles' actual live behaviour, and no further work should be spent
"fixing" it for titles that already work. The two ACTUALLY broken titles
(`sword_of_rage_le`, `munsters_le`) instead need whatever makes their entry
table's `(node,bit)` pairs not distinct — a live-shim-diagnosis question, not
a static-struct one.
The "positions land outside the artwork" failure on `king_kong_le` and
`metallica_spike` is a real, separate, NOT-yet-root-caused gap — the artwork
file is now found (item 57's `Test`/`TestMode` fix), the device XY
coordinates just don't land inside it. `dungeons_and_dragons_le`'s positions
DO land correctly (255 real records) despite having no artwork at all, which
rules out "the fix broke something universal" — it is specific to whatever
`king_kong_le` and `metallica_spike` share.

**Titles not yet run this pass** (existed before this table, no fresh data
to report against the 4 columns above): every other card version beyond the
one path each row above was tested against — `led_zeppelin_pro`,
`turtles_le-1_58_1` (the 1987-upscaled build), older `jaws_le`/`venom_le`
versions, etc. Re-running a DIFFERENT version of an already-clean title is
low priority; a title with no row above at all has simply not been reached
yet.

What the rig works out about a title by itself:

| | |
|---|---|
| the switch table | found in the heap at run time by SHAPE (`sw_find_table`), because the address differs per title and the layout does not |
| node firmware version | read off the `.hex` filenames the title ships beside its binary |
| device positions | scanned out of the binary by `devicexy.py`, seeded from the image-name strings rather than an address window |
| playfield artwork | the title's own `assets/nuk/images/Test/*_playfield.png` |

**Not every title has positions.** Godzilla Pro 1.15.0 ships a graphical device
test mode - a playfield drawing and an XY record per switch, coil and insert.
TMNT 1.59 ships neither: no `images/Test`, and "playfield" appears in its binary
only inside adjustment help text. So the playfield window draws artwork when a
title has it and a schematic switch list (`swtable.py`) when it does not. Both
are clickable and live; only one is a picture.

### Where those tables come from, and where they do not

`mktables.py` builds them, per title, into `$PAD_TABLES/<title>/` — under the
rootfs by default, so the WSL side that writes them and the Windows playfield
window that reads them name one directory. `watch.sh` runs it before opening
the window, and the window runs it itself if it finds nothing.

| | |
|---|---|
| `playfield.png` | copied out of the title's own assets |
| `device_xy.txt` | the device table in the game ELF |
| `led_io.txt` | derived from `device_xy`; the wire enumeration only ever *checked* it |
| `switch_list.txt` | the shim's `[sw]` dump, i.e. it needs a run |
| `switch_xy.txt` | the two joined on the device NAME |

**Three of the five need no run at all**, which is what lets a title show
artwork, inserts and coils the first time it boots. The switch half is the one
exception and cannot be made otherwise: the game builds its switch table on the
heap, so the id belonging to a name is not in the binary anywhere. It is cached
per title, so only the first run of a title waits for it.

**These were checked into git until 2026-08-06, and only Godzilla's existed** —
so every other title got a schematic and it read like a property of the title
rather than of the repository. The artwork was worse: it sat here ignored by
this directory's own `*.png` rule while `gameinfo.py` claimed it was committed.
Nothing under `games/` is generated into the checkout any more.

Anything the shim reads at a hard-coded address is a `TITLE_ADDR`: overridable
per title, checked before use, and switched off rather than fatal when it is not
mapped. That is not tidiness - the first attempt at a second title died 0.06 s
in, inside a printf, reading Godzilla's audio gate.

**`plans/spike2_pc_emulation_handoff.md` is the authoritative document.** It is
not in git (`plans/` is ignored); this README only covers what you need to run
the thing. Everything about *why* any of it is shaped this way — and the long
list of confident conclusions that turned out to be wrong — lives there.

## Layout

| | |
|---|---|
| Hardware shim (ARM, `LD_PRELOAD`) | `hwshim.c`, `alsastub.c`, `gststub.c`, `gstvid.c`, `padsw.h`, `padvid.h` |
| GL backend A, software raster | `glraster.c` |
| GL backend B, the bridge (default) | `glbridge.c` + `padglhost.c` (native x86-64), `padgl.h` |
| EGL, either backend | `eglshim.c` |
| Host decoders / players | `padvidhost.py` (video), `playaudio.sh` (audio) |
| Virtual playfield (Windows) | `playfield.py`, `coilact.py`, `plunge.py`, `swpoke.py` |
| Switch block layout | `padsw.h` (C), `padsw.py` (the scripts) — three regions, one writer each |
| Device maps and decoders | `devicexy.py`, `ledio.py`, `leddecode.py`, `coildecode.py`, `padled.h` |
| Where anything is | `padpath.py` / `padpath.sh` (paths), `gameinfo.py` (titles), `parts.py` (partitions) |
| Per-title tables | `mktables.py`, built from the card — see above |
| First-time setup | `rootfs.sh`, `getboot.sh`, `gethex.sh` |
| Build | `build.sh`, `buildgl.sh`, `buildbridge.sh` |
| Run | `watch.sh`, `runbridge.sh`, `nbrun.sh`, `verify2.sh`, `verify3.sh` |
| Safety | `alive.sh`, `killgame.sh`, `runlim.sh` |

Everything else is an instrument. They were written one at a time against a
specific wrong answer, and the handoff says which.

## Running it

All of these are `wsl -e bash <path>/<script>`, from this directory:

```bash
watch.sh          # WATCH IT: a real window on the Windows desktop, keyboard drives it
alive.sh          # what is still running. MUST print 0 after every run
killgame.sh       # emergency stop
build.sh          # the hardware shim      \ both built on demand; see below
buildbridge.sh    # the GL backend         /
```

**`watch.sh` and `runbridge.sh` build what they need.** `ensurebuild.sh` checks
the hardware shim and both halves of the GL bridge against a digest of their
sources: missing gets built and stops the run if it cannot be, stale gets
rebuilt and never blocks, and neither happens while a run is live. The builds
above are for building deliberately, not because a start needs them.

**A failed build is reported by its errors, not by its last eight lines.**
`gcc` compiles every source before it gives up, so the errors sit wherever the
broken file was on the command line and the tail belongs to whichever file came
last — the one arrangement a tail can never show is an error early with noise
after it, which is the common one. `_pad_build` republishes the matching error
lines first, keeps the tail only as the fallback when nothing matches, and
writes the full output to `$TMPDIR/pad-<script>.log`, which it names in the log.
Both builders pass `-Werror=implicit-function-declaration` so GCC 13 gives
GCC 14's answer here rather than on a user's newer distro.

`buildgl.sh` and `buildbridge.sh` **both write `libGLESv2.so.2`**, so whichever
ran last decides which backend is live. Re-run the one you want before measuring.

## Four rules that are not negotiable

- **Never wrap a run in `timeout`.** It signals only its direct child, which
  here is a `setsid` wrapper, so the guest survives it and spins at ~140% CPU
  forever. Use `watch.sh`'s own minute cap, or `runlim.sh`.
- **Run `alive.sh` after every run** and confirm it prints 0. An orphaned guest
  is invisible and expensive.
- **Anything a run starts goes in `alive.sh` the same day.** That list is the
  rig's only definition of "clean", and it has twice been out of date: once it
  reported `TOTAL STILL RUNNING : 0` over seven leaked Windows-interop stubs
  and three orphaned card mounts. `killgame.sh` and `status.sh` now ASK
  `alive.sh` (`--total` / `--procs`) instead of keeping their own copies, so
  there is one list and one place to add to.
- **Bracket `pkill` patterns** — `pkill -f padvidhost.py` from inside
  `wsl -e bash -c '...'` matches the shell's own command line and kills it.
  Write `pkill -f "padvidhost[.]py"`.

### When a window will not close

A window that WSLg is still painting after its X client has gone cannot be
closed by clicking its X (there is nothing left to receive the close) and
`msrdc` refuses `Stop-Process`. `wsl --shutdown` is the only cure found; the
app's **Restart WSL…** button on the Emulate tab does it for you. Note that
synthetic closes do NOT work as a test either: `WM_CLOSE` and `SC_CLOSE` posted
to a RAIL window from Windows are both ignored, the same UIPI class as the
`SendInput` and PrtScn blocks documented elsewhere.

### When the game window never appears

The playfield window opens, it says *emulator up*, the guest really is running,
and there is no game window. **The run says which of the two it is**, on its own
output, so read that line first:

- `[watch] game window opened 1445x827 on DISPLAY=:0` — the window EXISTS.
  Nothing inside Linux can see the Windows desktop, so if none is showing there,
  what is missing is WSLg's mirror of it and not the window: **Restart WSL…**.
- `[watch] THE RENDERER HAS NO WINDOW` — padglhost went headless and its own
  line says why. The run continues (the guest boots, the sound plays, the
  playfield answers) and shows no picture at all.

`DISPLAY` being SET is not the same as an X server being reachable: WSLg sets it
when the distro starts and never takes it back. `pad_display_state` (padpath.sh)
is the real question, and `masked` is the one worth knowing about — WSLg's socket
lives in its own tmpfs and WSL bind-mounts it to `/tmp/.X11-unix`, so anything
that mounts a fresh `/tmp` over that bind (systemd's `tmp.mount`) hides it from
libX11 while leaving it in `/mnt/wslg/.X11-unix`. watch.sh binds it back when it
is root, which the app's own launch is; by hand it is

```bash
sudo mount --bind /mnt/wslg/.X11-unix /tmp/.X11-unix
```

## The coin door interlock, which explains a whole class of "it does nothing"

The emulated machine keeps the real one's interlock and it is not optional:

- **Coin door CLOSED** (switch 33 held, the default) — 48V is live, so coils
  fire. The service buttons are locked out; pressing Enter does nothing.
- **Coin door OPEN** (switch 33 released) — the service menu works. 48V is off
  and the game says so on its own screen: *48V DISABLED / CLOSE COIN DOOR*.
  **No coil can fire in this state**, which makes a perfectly working playfield
  look broken. The playfield window says so in the status bar.

You can close the door *while in the menu* to get both at once, which is how the
coil frames were captured. To see coils fire without playing: close the door,
open the trough switches so the balls look missing, press Start — the game puts
up LOCATING PINBALLS and ball-searches on an 8.3 s cycle. `coildecode.py` reads
the result out of a `PAD_COIL_PROBE=1` capture.

## Requirements

**Linux, or Windows with WSL.** `qemu-user-static` (binfmt `qemu-arm`
registered with the **F** flag), `gcc-arm-linux-gnueabihf`, `gcc` +
`libc6-dev`, `e2fsprogs`, `fuse3`, `ffmpeg`, and `python3-tk` for the playfield
window. Then, once:

```bash
rootfs.sh <card.raw>    # the guest rootfs, from the card. No root needed.
```

**Two compilers, and they are not interchangeable.** The hardware shim and the
guest half of the GL bridge are ARM and want the cross compiler; `padglhost`,
the renderer that draws the picture, is a native x86-64 binary and wants plain
`gcc`. `libc6-dev` is named beside it because gcc only *recommends* the
headers, and `padglhost.c` opens with `#include <stdio.h>`. `setupcheck.sh`
reports that one as `nativecc` and probes it by compiling rather than by
looking on the PATH — a compiler with no headers is on the PATH and cannot
build anything.

**`ffmpeg` is the decoder for both the picture and the sound**, and it is the
one requirement here whose absence does not stop anything. The game cannot
decode its own H.264 (of the 175 plugins in its gstreamer-0.10, the only one
that does is the i.MX6 hardware element), so `padvidhost.py` decodes out here
and hands the guest raw frames; `playaudio.sh` uses ffmpeg's `pulse` muxer for
the same reason, this distro having no pulseaudio client tools. Without it the
emulator starts, builds, boots the guest and opens a window — and that window
is black and silent. `watch.sh` says so once at startup rather than letting it
arrive as a decode error per clip.

On **Ubuntu**, `qemu-user-static` is published in the `universe` component and
the others are in `main`. A distro with universe switched off therefore
answers `E: Package 'qemu-user-static' has no installation candidate` — apt
knows the name and has no version — and, because `apt-get install a b` is all
or nothing, installs none of the others either. `setupcheck.sh` reports that as
`nocand` and `universe=0` rather than only as "missing", and `setupfix.sh`
turns universe on before it installs anything.

That is the whole of it: the ARM hardware shim and the GL backend are compiled
by the first run that needs them. They used to be two more steps printed as
advice, which is how a user reached `env: './padglhost': No such file or
directory` at their first start.

`rootfs.sh` is the step that used to be missing: `run_game.sh` chroots into
`$PAD_ROOT` and nothing in the repository created it, so the recipe lived only
in a planning document that is not in git. It reads the partition table rather
than assuming one card's offsets (`parts.py`), extracts the OS partition with
`debugfs` — no loop mount, no sudo — and finishes with the boot partition,
which `rdump` of the OS partition never touches and whose absence is a `GAME
VALIDATION ERROR #3`. It refuses to extract to a `/mnt` path, because drvfs
cannot hold symlinks and `ld-linux.so.3` would silently vanish.

It does **not** extract a title. `PAD_CARD=<image> watch.sh` runs one straight
off the card in about a second; `rootfs.sh --game <title>` is there for a title
you run constantly.

Every run then checks that the guest can actually **start a program** — a user
namespace, a chroot, `/bin/sh`, about 25 ms — before it starts one. A rootfs
that exists is not a rootfs that runs, and all four ways it can fail (an
extraction that stopped part way, a missing ARM loader, no `qemu-arm`
registration, a registration without the **F** flag) produce the same single
line and no other clue:

```
chroot: failed to run command '/bin/sh': No such file or directory
```

The first two are rebuilt from the card you are already running; the last is
repaired by putting a copy of the interpreter inside the guest, which needs no
root. Only registering `qemu-arm` needs root, and that one is named with the
command for your machine — WSL loses the registration on every restart unless
the distro boots `systemd`.

### WSL and Linux are not two ports

This is a Linux program. `run_game.sh`, `cardmount.sh`, `padglhost.c` and
`padvidhost.py` contain nothing Windows-specific at all — the chroot, qemu-user,
the node bus, the card mount and the renderer are the same code either way.
What WSL needs on top are **workarounds, not features**, and there are exactly
two:

| | |
|---|---|
| the playfield runs as a **Windows** process | this WSL has no Tk of any kind, and installing one needs a sudo the rig does not have |
| audio bridges to a **Windows** player | the WSLg→Windows audio hop degrades music, while every instrument inside WSL reads clean |

On a Linux desktop both simply go away: the playfield is a local Tk window and
audio goes straight to PulseAudio. `padpath.sh`'s `pad_is_wsl` (and
`padpath.py`'s `is_wsl()`) is the **one** place that decides which of the two
applies — `playaudio.sh` used to carry its own copy of that test, which is the
duplication this rig's own rules forbid.

**`PAD_FORCE_NATIVE=1` makes a WSL session take the Linux branches**, which is
the only way to exercise them from a Windows machine. It is how the Linux path
was tested; what it cannot show is the playfield window itself, because the
distro that needs the workaround is by definition the one with no Tk.

### macOS: in a container, watched over VNC

`qemu-user` translates *Linux* syscalls, and `unshare`, user namespaces and
`chroot` into an ELF rootfs are Linux kernel features. So macOS is not a port
that could be written — running the rig there means running Linux there, and
`docker/` is that Linux.

```bash
docker/padbox.sh --build                 # once
PAD_CARD=~/cards/<card>.raw docker/padbox.sh watch.sh 30
open vnc://localhost:5900                # Screen Sharing; nothing to install
```

**The container runs its own X server** and exports only the finished
framebuffer. Forwarding X to XQuartz instead would push every frame across the
VM boundary as uncompressed protocol, ~4 MB a frame at 1360x768.

**Software rendering is not the bottleneck and never was.** Measured on a
headless Xvfb with `GALLIUM_DRIVER=llvmpipe`, which is what a container with no
GPU gets: guest **57.1 fps**, renderer **59.9 fps**. The 1 fps figure this
project remembers is `glraster.c` running *inside* the emulated ARM guest, which
the GL bridge replaced and which none of this uses.

Three container details are load-bearing, all in `padbox.sh`:

| | |
|---|---|
| `--security-opt seccomp=unconfined` | Docker's default profile blocks `unshare`, so the guest could never get its mount and PID namespaces |
| `--cap-add SYS_ADMIN --device /dev/fuse` | `cardmount.sh`'s read-only card mount |
| `-p 127.0.0.1:5900` | the VNC display is an unauthenticated view of the machine; loopback only |

**KNOWN, and see REMAINING item 30: a container run ends by itself after about
60 seconds.** Everything is healthy until it does — full frame rate, clean
teardown — and `watch.sh`'s three exit paths all stay silent, so it is taking a
signal from outside. It was seen on Docker Desktop for **Windows**, which is not
the target; macOS uses a different VM layer entirely, so the first question is
whether it happens there at all. Video also does not stream in the container,
unexplained.

## Paths

Nothing here carries a path to a particular machine any more. `padpath.sh`
(sourced by the scripts) and `padpath.py` (imported by the Python) are the only
two files that know:

| | | |
|---|---|---|
| `RIG` | this directory | from `BASH_SOURCE` / `__file__` |
| `ROOT` | the guest rootfs | `PAD_ROOT`, else `~/spike2root` |
| `TABLES` | derived per-title data | `PAD_TABLES`, else `$ROOT/dump/tables` |
| — | any of those as **Windows** sees it | asked of `wslpath`, never built by pasting strings |

That last row is the one that reads like a detail and is not.
`\\wsl.localhost\Ubuntu\...` was written out in four files: it names a distro
that need not exist, under a prefix older WSL spells `\\wsl$`. `wslpath -w`
knows the right answer for the running system, and `watch.sh` passes the
translated values across interop through `WSLENV`'s `/p` flag, so the playfield
window normally has them already and asks nothing.

**This used to be 187 files carrying `/home/david` and 51 carrying the
checkout's absolute path**, and this section used to say it was 44 files and one
`sed`. Both halves of that were wrong, which is roughly the point: a count
nobody re-derives goes stale, and a path nobody derives never works anywhere
else. If you move the rig now, nothing needs editing.

Two things to know if you add a script:

- **Source `padpath.sh` before using `$RIG` or `$ROOT`**, with
  `. "$(dirname "$0")/padpath.sh"`.
- **A quoted heredoc does not expand anything**, so `$ROOT` inside `<<'PY'`
  reaches Python as five literal characters. Pass it through the environment
  (`export PAD_ELF=...` then `os.environ["PAD_ELF"]`), which is what the
  forensic scripts here do. Same trap for `pkill -f '...'`: single quotes stop
  the pattern expanding and it silently matches nothing.
