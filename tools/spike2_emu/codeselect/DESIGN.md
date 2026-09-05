# codeselect — a boot-time code selector for Spike 2 (item 90)

*Behaviour and file formats. The mechanism facts (wire protocol, GL recipe,
card geometry, validation) are folded in below as they are established; the
authoritative queue entry is item 90 in `plans/TODO.md`.*

## What David asked for

One SD card that carries several complete game images for one machine, and a
menu at power-up that lets the player pick which one boots — flippers move the
highlight, START or the lockdown-bar ACTION button confirms — so a machine can
run the stock Stern code or a
custom build (TMNT 1987 today; the Heisei Godzilla builds, normal and
orchestra, next) without swapping cards. The stock image has to keep passing
Stern's game validation and keep working with Insider Connected.

## Behaviour on the machine

1. Power on. u-boot, kernel and rootfs come up exactly as on a stock card
   (p1 and p2 are byte-for-byte Stern's). `boot_display` shows the Stern
   splash as usual.
2. `/etc/init.d/game` reaches its launch section, does its own
   `pkill boot_display`, and — the one added line — runs
   `/usr/local/codeselect/select.sh` if it exists.
3. `select.sh` runs `codeselect`, which owns the LCD until a choice is made:
   * A dark full-screen menu: title line, one card per image (name, version
     line, a short blurb), the highlighted card framed, and a footer with the
     controls and a countdown.
   * LEFT / RIGHT FLIPPER moves the highlight (wraps). Service **-** / **+**
     on the coin door do the same, as a fallback that needs no node bus.
   * START, the ACTION button on the lockdown bar (the one a thumb is
     already resting on), or Service Select confirms. When the countdown
     reaches zero the
     highlighted image boots by itself, so an unattended power-up still
     boots — the default highlight is the image that booted last time
     (`/data/codeselect.last`), falling back to the config's `default`.
   * `codeselect` exits with the chosen image's index; nothing else.
4. `select.sh` remounts `/games` from that image's partition (the primary
   image is already there from fstab, so index 0 is a no-op), records the
   choice in `/data/codeselect.last`, and returns.
5. Stern's own lines follow, untouched: `conagent_monitor`, `game_monitor`,
   `update`. The game finds its directory through `/games/game` exactly as it
   always has.

If anything in step 3 fails (program missing, exits non-zero, cannot open the
display or the bus), `select.sh` says so on the console and boots the primary
image — the card degrades to a stock card, never to a brick. The card log
(`/dump/log/codeselect.log`) is a development switch: only a card built with
`mkmulticard.py --debug-log` carries the `log=` line that turns it on, and
even then a boot starts the file afresh (the previous boot's kept as `.1`)
and writes at most 1 MiB, so no number of boots can fill the card.

## Behaviour in the emulator (the proof of concept)

`PAD_CARD=<multi-image .raw> watch.sh` — the same rootfs, the
same chroot, the same GL bridge window: the selector draws in the game window,
the keyboard flipper keys move the highlight, `1` (START) or Space (ACTION)
confirms, and the run continues into the chosen image's game exactly as a
plain card run does.
The validation oracle is the same one the rig already uses: the Tech Alerts /
attract screen past 90 s with no `GAME VALIDATION ERROR` line, read by the
screen oracle and by a screenshot.

`PAD_SELECT` NEED NOT BE SET (2026-09-02). It is a three-way switch: UNSET
asks the CARD — `parts.py --multiboot`, the one definition of a multi-boot
card (the rootfs holds `/usr/local/codeselect/codeselect` and its
`images.conf` names two or more images) — `1` forces the menu on whatever the
card looks like, and `0` forces it off. watch.sh decides once, at the top of
the run, says what it decided and why, and exports the resolved `1`/`0` to
run_game.sh so the two cannot disagree; the app's Boot selector tickbox shows
the same answer and is the override. David asked for it in those words: "if it
has multi-boot, i expect to see the multi-boot screen."

## Card layout

| part | type | content | from |
|---|---|---|---|
| p1 | FAT (0x0c) | zImage + dtb | primary image, verbatim |
| p2 | ext4 | rootfs + `/usr/local/codeselect/` (+ `media/`) + patched `/etc/init.d/game` | primary image, then patched |
| p3 | ext4 | games partition of image 0 (the primary) | verbatim (validator bypassed when asked) |
| p4 | extended | grown to the end of the card | — |
| p5 | ext4 | `/data` | primary image, verbatim |
| p6 | ext4 | `/dump` | primary image, verbatim |
| p7 | ext4 | `parts` layout: image 1's games partition verbatim. `multi` layout: one filesystem holding `img1/`, `img2/`, … each a complete games tree | see below |

p1/p2 keep u-boot's `root=/dev/mmcblk0p2` and the FAT load valid; p3/p5/p6
keep fstab valid; the extra images are only ever reached by `select.sh`.

**The card's kernel exposes p1..p7 only** (i.MX6 3.14, `CONFIG_MMC_BLOCK_MINORS=8`;
found in review), so there is room for exactly one extra *partition*. Two
layouts, chosen by `--layout auto`:

* `parts` (one extra image): p7 = that image's games partition copied verbatim
  (byte-verified). Two 8G images need ≈14.7 GB, a 16 GB card.
* `multi` (two or more extras): p7 = one ext4 filesystem built with `mke2fs -d`
  from `debugfs rdump`s of each extra's games partition, `img1/ … imgK/`, each
  a complete tree (`spk/`, `<title>/`, the `game`/`conagent`/`data` symlinks,
  ownership restored). Sized to the used bytes + 10 % + 256 MiB. Device tokens
  are `/dev/mmcblk0p7:imgN`; `select.sh` mounts p7 under `/mnt/multi` and
  bind-mounts the chosen subdirectory over `/games` (no rw remount). Three 8G
  images ≈17.2 GB, a 32 GB card.

## Validation on the machine (David's first flash, 2026-09-01)

The card booted and selected perfectly on the TMNT Pro, but a GAME VALIDATION
ERROR showed on both images. `mkmulticard.py bypass --dry-run` on that card
read the stock image as ARMED and the 1987 image as already bypassed: the game
grades itself per build stamp into the board NVRAM, and the two 1.59.0 images
share that state, so the armed stock image tainted both. Every image on a
multi card therefore gets the same treatment the Insider-clean 1987 card has:
`valpatch.find_validation_exec` (a signature match, no fixed address) and a
4-byte `bx lr` at the validator's entry, with the game's `.sidx` record
refreshed so `spk` still accepts the file at update time. `build
--bypass-validation` does it for every games tree (opt-in since item 98: a bypassed image never
re-grades, so a stock image is left alone to clear a latched error; `update --restore-validation`
puts the stock game back), `bypass --card` retrofits a
built card in seconds, and `verify` reports the state per tree. The July 2026
hardware test of that patch is what makes this Insider-safe.

## Files on the card

```
/usr/local/codeselect/codeselect      the ARM program (EGL/GLES2 menu + input + sound)
/usr/local/codeselect/select.sh       the hook: run the menu, remount /games
/usr/local/codeselect/images.conf     one line per image (below)
/usr/local/codeselect/font.ttf        DejaVu Sans Bold (Bitstream Vera licence)
/usr/local/codeselect/media/          art PNGs, animated GIFs, WAVs (flat, <= 96 MB)
/etc/init.d/game                      stock script + one guarded hook line
/usr/local/codeselect/media/          art<N>.png, anim<N>.gif, music<N>.wav, confirm<N>.wav, move.wav, confirm.wav (optional, <= 96 MB)
```

`images.conf` v2 — plain text, `#` comments,
`image=<device>|<title>|<subtitle>|<art>|<anim>|<music>|<confirm>` one per
image (index = order, 0-based; fields 4-7 optional media file names in the
media directory, 3-field and 6-field lines stay valid; up to 16 images),
plus `default=`, `timeout=` (0 = wait for START/ACTION), an optional
`font=`, `media=` (default
`/usr/local/codeselect/media`), `sound_move=`, `sound_confirm=` (the confirm
sound for every image that names no `<confirm>` of its own), `volume=`
(0-100 software gain, default 50 - or `machine`: the machine's own MASTER
VOLUME SETTING, read off the card's `/data/nv/<title>/NVM` mirror by nvm.c,
with `machine_volume=<store>|<sha1 key>|<factory 0-63>` saying where and
what; `--volume` still wins) and the optional hardware-only
`mixer_volume=` (0-63, the game's codec curve on the ALSA `PCM` control;
untouched when absent). `<device>` is `/dev/mmcblk0p3`, `/dev/mmcblk0p7`
(the parts layout) or `/dev/mmcblk0p7:img2` (the multi layout: a partition
plus the subdirectory holding a complete games tree); `p3`, `p7`, `p7:img2`
in the emulator. Unknown keys are ignored.

```
image=/dev/mmcblk0p3|STERN 1.59.0|Original Stern code|art0.png||
image=/dev/mmcblk0p7|TMNT 1987|1987 cartoon upscale (1.59.0)|art1.png|anim1.gif|music1.wav|confirm1.wav
sound_move=move.wav
sound_confirm=confirm.wav
volume=50
default=0
timeout=15
font=/usr/local/codeselect/font.ttf
```

The builder writes this file (and `media/`, from `selectmedia.py`'s
`media.json`); David can edit the names.

## The selector program

Built and tested in `tools/spike2_emu/codeselect/` (README.md there has the
full CLI, the log lines and the test list). What it is:

* C (the rootfs libstdc++ is GLIBCXX_3.4.20, gcc 13's C++ cannot link),
  cross-compiled with the rootfs used as the sysroot by hand (recipe D:
  `-nostdinc -isystem $ROOT/usr/include`, rootfs crt objects, `-nostdlib`,
  `-l:libc.so.6 libc_nonshared.a -l:libm.so.6 -l:libgcc_s.so.1`), so the
  binary demands at most GLIBC_2.17 and NEEDs only `libEGL.so.1
  libGLESv2.so.2 libc.so.6 libm.so.6 libgcc_s.so.1` - the rig's bridge shims
  in the emulator, Vivante's blobs on the machine, same exported names. The
  Makefile's `check` target enforces that ceiling with readelf.
* Files: `codeselect.c` (loop, CLI, layout, menu state, countdown, sounds,
  the confirm wait, choice/last files), `gfx.c` (software RGBA canvas,
  rounded frames, stb_truetype text with a glyph cache, RGBA blits,
  dirty-rect tracking + a packed sub-rect, 180-degree rotation, P6 PPM),
  `egl_stern.c` (Stern's EGL bring-up, sub-rect uploads), `art.c` (PNG +
  animated GIF through the vendored stb_image, box-downscaled into the art
  panel; a GIF is decoded ON DEMAND in the pinned/snapshot modes - one frame
  per tick - and ONCE, onto a RAM cache filled by a thread at nice 10, in
  the live menu (2.8: 13 ms a frame on the machine, more than half the CPU
  for two clips when it ran on the menu's thread; the hardware input scan is
  its own thread at nice -5 for the same reason), frame 0 kept as
  the still, the count and delays from a walk of the block stream - so a
  150-frame loop costs two panels of RAM and the menu is up after one
  frame), `audio.c` (WAV loader, 4-voice mixer) +
  `audio_fifo.c` (the rig's FIFO) + `audio_alsa.c` (the card's libasound,
  hand prototypes), `input.c` + `input_hw.c` + `input_padsw.c` (buttons),
  `conf.c` (images.conf v2), `log.c`; `select.sh`, `images.conf.example`,
  `fakebus.py`, `test/` (with `mkmedia.py`, the PIL-free test media).
* Draws into a software canvas sized from `fbGetDisplayGeometry` (1360x768
  on the bridge and the TMNT LCD) and presents it as ONE full-screen RGBA8
  textured quad: boot_display's exact EGL order and attribute lists,
  `#version 300 es` sprite shaders, VAO + VBO only, `glTexImage2D` once and
  `glTexSubImage2D` of only the DIRTY rectangle (tightly packed, w*4-byte
  rows) when something changed - an animation tick costs one panel, ~370 KB,
  not the 4.18 MB canvas - LINEAR/CLAMP set
  explicitly, never `glPixelStorei`, a swap every frame, the bring-up
  retried 6 x 500 ms (boot_display may still hold the LCD), teardown that
  leaves default GL state then `eglMakeCurrent(dpy,0,0,0)` / `eglTerminate` /
  `eglReleaseThread`. Proven against the bridge libs on a private ring
  (attach, TEXIMAGE 1360x768, per-change TEXSUBIMAGE, 124 acked swaps at
  ~61 fps, exit 0); not yet run on Vivante.
* The menu: `SELECT GAME CODE`, one card per image with an `IMAGE n` label,
  the title (shrunk to fit, wrapped to two lines when it must) and the
  subtitle (wrapped to four), the highlighted card framed amber on a lighter
  fill, a footer `LEFT / RIGHT FLIPPER: choose   START or ACTION: boot` and
  `booting <title> in N s` (or `press START or ACTION to boot <title>` with
  timeout 0) — both drop the ACTION half wherever no Action button resolved,
  and the log line quotes whichever was drawn. Every line shrinks to fit and
  is then ellipsised: `gfx_fit_px()` floors at its minimum size and returns
  it whether or not the text fits, so a 199-character title (the conf's
  limit) used to run off both edges of the glass. 2-4
  images sit in a row (width scaled); 5-16 become a carousel of three cards
  with the highlighted one in the middle, its neighbours beside it
  (wrap-around), the neighbours-but-one peeking in from the edges and a
  `<  n / N  >` line under the cards. When any image has art or an
  animation every card gets a picture panel across its top - the widest
  16:9 the card allows, capped so the text block fits, the text centred
  in what is left (the picture
  aspect-fitted and centred, never upscaled) above the label, and the text
  packs below; with no media the picture is the v1 layout byte for byte.
  EVERY card's GIF plays on the file's own frame delays, all the time
  (David: "all boot selections should play video at the same time"); a
  card without one shows its still. A full redraw happens only on a
  state change; an animation tick repaints the panels that moved, and only the dirty
  rectangle is uploaded. A key press restarts the countdown. On confirm one
  `LOADING <title>...` frame (with the card's picture) stays up while the
  confirm sound plays to completion (cap 8 s), the sound device is drained
  and closed, and only then the choice is written and the program exits.
* Sound: `sound_move` on every LEFT/RIGHT/-/+ edge, the highlighted card's
  `music` looping (hard switch on a highlight change), and on START/Select
  the CHOSEN CARD'S own `<confirm>` when it named one that loaded, else the
  menu-wide `sound_confirm` (David, 2026-09-02: "the 'confirm sound' we
  should be able to customize for each entry if we want to"). Each card's
  clip is loaded at startup beside its music, by the same WAV rules and
  through the same by-name cache, so a file two cards share is decoded once;
  one that is missing or refused is logged and that card falls back to
  `sound_confirm`. The log names which sound played and how long the exit
  waited for it. One single-threaded s16 44100 Hz stereo mixer (4 voices,
  saturating, `volume=` gain) pumped from the main loop into ONE sink:
  `--audio auto` = ALSA when `snd_pcm_open` succeeds on `default` (the
  machine's asound.conf: dmix on both the backbox and the cabinet card),
  `cabinet_and_backbox`, `sysdefault:CARD=sgtl5000main` or `plughw:0,0`, in
  that order (`snd_pcm_set_params` S16_LE / interleaved / 2 ch / 44100 /
  500 ms, non-blocking `writei` in 1764-frame chunks, `snd_pcm_recover` on
  -EPIPE, drain + close before the choice file; **once the device is
  configured, both SGTL5000s get the game's own 50-register power-up over
  `/dev/i2c-1` (codec.c: line-out, VAG, DAC powered, analog mutes cleared -
  the kernel routes only the headphone jack and never powers LINE_OUT,
  which is what the amplifiers hang off; the reason a perfectly streamed
  menu was silent on the machine) and are put back at close**; the kernel's
  `Line Out Mute` switch on ctl `backbox` + `cabinet` is set ON as well and
  back OFF at close where it was OFF; the volume untouched unless `mixer_volume=` (or
  `volume=machine`, the machine's own number) asks for the game's codec
  curve on `backbox` + `cabinet`), else the rig's FIFO when `PAD_AUDIO_PLAY` is set
  (`44100 2` into the fmt file first, `O_WRONLY|O_NONBLOCK` with ENXIO
  retries, 200 ms lead, silence while idle, EAGAIN dropped and counted,
  EPIPE reopened through the same retries with the fmt file re-asserted
  whenever it has been removed and a 3 s gap logged once, SIGPIPE
  ignored), else none. Every failure is logged and the menu runs silent.
* Input backends (`--input`), a shared two-sample debouncer, press edges
  only, Service Back ignored (autoattract.sh presses it in the rig):
  * `hw` (default): the game's own tty setup on `/dev/ttymxc1` (460800 8N2,
    ASYNC_LOW_LATENCY, VMIN 0/VTIME 3, RTS pulse), the unaddressed bring-up
    + enumeration + `fe` identity reads (`--preamble min`; `full` also
    replays the byte-exact write-only frames captured before the game's
    first 0x11), then `88 02 11 65 0c` / `81 02 11 6c 0c` every 25 ms with
    per-node back-off when a board is silent; the node-0 cabinet word over
    `/dev/spidev1.0` (100 kHz mode 3, 8 bytes every 10 ms) for Service
    Select/Plus/Minus. The node-1 reply carries two buttons: START at bit 11
    (byte 1 bit 3) and the lockdown-bar ACTION button at bit 2 (byte 0 bit 2),
    so ACTION costs no extra bus traffic. Every ioctl failure is tolerated and
    the first 40 exchanges are hex-logged. Tested against `fakebus.py` on a
    pty (which can now press `action` as well as `left`/`right`/`start`).
  * `padsw`: the rig's keyboard file (`PAD_SW_SHM`, 4096 bytes, `held[]` at
    8 / `scr_held[]` at 280) re-read every 20 ms, ids from
    `/dump/tables/$PAD_GAME/switch_list.txt` by wire position — the same
    resolution padglhost's `cab_wire` table does, and for the same reason: an
    id is a table index that drifts per generation and the names drift too
    (17 of the 31 title lists on this disk say `LOCKDOWN BUTTON`, two of
    those with an `(OPTIONAL)` suffix; 12 say `Action Button`; metallica_spike
    names nothing at all). ACTION also has a whole-name fallback for a list that
    puts it off (1,2) — whole-name because `START BUTTON` as a substring
    would also match the `TOURNAMENT START BUTTON` that 26 of those lists
    carry. Platform ids (36 START / 25-28 service) stand before a title has a
    table; a parsed list that knows neither the wire nor a name leaves ACTION
    unset rather than aiming an id at some other switch (on beatles, the one
    list with no lockdown row, id 34 IS the START button).

    ACTION has NO platform id, deliberately. Across the 31 cached lists id 34
    is `COIN DOOR INTERLOCK` (node 0 bit 23) on seven — aerosmith_le,
    avengers_infinity_le, foo_fighters_le, guardians_le, iron_maiden_le,
    mando_le, rush_le — and a shut coin door holds that switch made, so a
    table-less menu read it as an ACTION press and confirmed itself untouched.
    The window is emulator-only: the `hw` backend reads the wire and never
    sees an id. The other platform ids were swept too: none of them lands on a
    switch anything holds made except 36 on batman, which is the same
    interlock. 36 is kept deliberately (2026-09-02) — keeping it risks one
    wrong boot on one title in an emulator-only window, a restart; dropping it
    takes the only confirm key a table-less menu has away from the other 30,
    since the flippers are unresolved there by definition. The window is
    shrunk instead: with no table the list is re-checked every 250 ms, and
    every title David runs carries a cached table. A resolved list is
    re-read whenever its mtime moves, the way padglhost re-resolves its own
    binds, because mktables repairs a partly-derived list a minute into a run.
    Tested with a scripted padsw file, the phantom case with a positive
    control on id 36, five synthetic tables and a list that changes on disk.
  * `none`: countdown only (tests).
* `images.conf` v2: lines of
  `image=<device>|<title>|<subtitle>|<art>|<anim>|<music>|<confirm>`
  (index = order; fields 4-7 optional, field 7 = that card's own confirm
  sound; up to 16), `default=`, `timeout=` (0 = wait), `font=`, `media=`,
  `sound_move=`, `sound_confirm=`,
  `volume=`, `mixer_volume=`; `--media DIR` overrides `media=`; `--out` gets
  `<index>\n`, `--last` (`/data/codeselect.last`) is read for the initial
  highlight and written on confirm. Exit 0 = a choice was written, 2 =
  anything else. Media: PNG art (pre-scaled by the tools), animated GIF
  <= 512x288 / <= 150 frames (5 s at 30 fps; ANIM_MAX_FRAMES, which must
  agree with selectmedia.py's GIF_MAX_FRAMES) / <= 10 MB (delays from the
  file, 100 ms where it says 0, clamped 20 ms-10 s), WAV RIFF PCM 16-bit
  44100 Hz 1-2 ch; a missing or
  unusable file is logged (`art: cannot load ...`, `audio: ...: unsupported
  (...)`) and skipped. Log lines: `media: N art, M anim (F frames), K
  music, C card confirm, move=y|n confirm=y|n`, `confirm: image N sound
  <file> | menu sound <file> | no sound, <ms> ms under the LOADING frame`,
  `audio: alsa <dev> ok` | `audio: fifo <path> open` |
  `audio: none (<reason>)`, and at exit `audio: <frames>
  frames written, <dropped> dropped`. `--headless` renders pin every
  animation with `--anim-frame N`; `--audio-dump FILE` captures the mix.
* Honors `-invert` in `/games/data/boot_display_cmd` (parsed exactly as
  boot_display parses it) by rotating the presented pixels 180 degrees;
  `--invert`/`--no-invert` force it.
* `--headless FILE.ppm` renders without EGL and writes the last menu frame
  (plus `FILE.loading.ppm`): the offline test, and the screenshots.
* `--snapshot FILE.ppm [--highlight N] [--anim-frame N]` renders ONE menu
  frame the way the machine shows it the moment the menu appears - the card
  asked for (else the conf default; the last-choice file is never read)
  highlighted, its GIF at frame N, the other cards their still or frame 0,
  the countdown at its full value, no rotation - as a P6 PPM and exits 0
  with nothing else started: no display, input, audio, choice or last
  file. The Multi-boot tab's preview runs it under `qemu-arm-static -L`
  against the rootfs copy to play the highlighted card's animation; stdout
  says `frame F of N`. Under qemu an absolute
  font/media path is looked up in the `-L` sysroot first, then on the host
  (README.md, "Paths under qemu").
* `--frames K` writes a WHOLE RUN of K frames - `--anim-frame`, then the
  next, wrapping - out of that one load, because the preview otherwise pays a
  process start and a re-decode of every PNG, GIF and font per frame to move
  one panel: 16 frames measured 1313-1346 ms as 16 runs against 228-243 ms as
  one, same bytes out. K > 1 makes the `--snapshot` value a printf pattern
  taking exactly one bare `%d`, the frame number, so the caller keeps its own
  file naming; anything else is refused before a byte is written. K = 1 (the
  default) is the single-frame path untouched. A K past the animation's
  length, or any K on a card with no animation, is trimmed rather than
  writing the same file twice, and the trim is logged.
* `select.sh` is the hardware hook: after `/etc/init.d/game`'s own
  `pkill boot_display ` it waits up to 3 s for boot_display to be gone, runs
  the selector, reads the index and looks the device up in images.conf
  (busybox awk: split on `|`, then the device on `:`). Index 0 touches
  nothing (the primary is fstab's mount). Otherwise `umount /games`, then
  `<dev>` = `mount -t ext4 -o ro,relatime,exec <dev> /games`, and
  `<dev>:<sub>` = `mkdir -p /mnt/multi` (falling back to
  `/var/volatile/multi` on the read-only rootfs) + `mount -t ext4 -o
  ro,relatime,exec <dev> /mnt/multi` + `mount --bind /mnt/multi/<sub>
  /games`; the new `/games` must have `game`. Any failure undoes the mounts
  and puts `/dev/mmcblk0p3` back on `/games`: the primary boots. It never
  touches `/mnt/boot`; it passes `--log` (and writes its own lines) only when
  images.conf has a `log=` line (`--debug-log`), else the card gets no log at
  all; the `CODESELECT_*` variables let `test/select_sh_test.sh` run the whole
  hook against a fake selector and fake mount/umount (`CODESELECT_LOG` forces
  the log on or, empty, off).

## Card builder

`mkmulticard.py` (run under WSL): takes the primary image and N extra images,
writes the layout above onto a sparse output file, injects the selector into
p2 with `debugfs -w`, verifies every copied range by digest and every ext4
by `e2fsck -fn`, and prints the `images.conf` it wrote. `--verify` re-checks
an existing output.

## Updating a card in place (item 93)

The card records what is on every games tree - `trees.json` on p2 beside `build.json`
(format 1: per image the device, the subdirectory, the source's stamp, every file's
sha256/size/mode/owner, every symlink and directory, the bypass's own digests for the game
and the .sidx; the primary's identity for the update gate; which partitions were written
in place; a DIRTY list while an update runs) - and `mkmulticard.py update` changes only
what changed: stamps against the record, a diff per tree, a loop mount per touched
partition (root; `--direct-io=on`), tmp + rename writes with adds before removals, the
bypass through the mount, the record written last.  The engine is
`tools/spike2_emu/treesync.py` (pure Python, tested on Windows); the mount, the lock, the
p2 primitive and the CLI are mkmulticard's.  A partition written in place is held by
`verify` to the record, never to a range md5: a rw mount alone stamps the superblock.
Metadata is never identity - two cards were found with files equal in path, size and
mtime and different in content.  The multi layout's p7 grows on demand up to the Stern
size class.  Full detail in `tools/spike2_emu/README.md`, "Updating a card in place".

## The compact layout (item 95) - opt-in, default off

A third layout, `store`, chosen only by `--layout store` (the app's tick, off by default):
the primary's own p3 grown with `resize2fs` on the loop device, the extras inside it as
`img1/`, `img2/` ... beside the primary's tree, and one `.blobs/<sha256>.<mode>.<uid>.<gid>`
store every regular file of every tree is a hardlink into - one inode per unique (content,
mode, owner).  The primary is adopted by linking (its inode numbers stay the source's; zero
bytes rewritten); each extra writes only the blobs the store lacks.  p5/p6 are re-laid after
p3; no p7.  Device form `/dev/mmcblk0p3:img1`: `select.sh`'s `<dev>:<sub>` branch handles it
unchanged (umount /games, mount p3 at /mnt/multi, bind the subtree).  David's three TMNT
images: 18 GB -> about 8 GB.  `update` converges the store (a held blob is linked, never
written; orphans collected); `verify` holds the store to its invariants (names, attrs, link
counts = 1 + references, every file a link, no orphan/tmp, full: every blob hashes to its
name).  The bypass runs through the mount and the patched game is adopted under its own key.
Never USB-update a store card (a Stern update writes through shared blobs); `bypass` refuses
one.  Hardware-only proofs, until which the tick says experimental: Stern's update/spk layer
tolerating `.blobs/` and `img1/` at `/games`' root, and the same-device remount.  Detail in
`tools/spike2_emu/README.md`, "The compact layout".

## What is deliberately NOT in the proof of concept

* Per-image NVRAM snapshots (settings/scores kept apart per image). Both
  TMNT images are 1.59.0, so the board NVRAM is shared cleanly; two different
  versions of one title may re-initialise on swap (the Beatles multi-boot
  finding). Designed for, not built.
* USB code updates while a non-primary image is selected write into that
  image's partition (the `update` script uses `/games`), which is the
  behaviour one would want; the primary's p3 is only updated when it is the
  one selected.

## Proven in the emulator (2026-09-01)

Card: `mkmulticard.py build` of `turtles_pro-1_59_0.Release` (primary) +
`TMNT 1987/turtles_pro-1_59_0.1987-upscaled` (extra) — 14,723,055,616 B,
p7 at LBA 15353856, `verify` PASS (every copied range md5-equal to its
source, every ext4 fsck-clean, p2 differs from stock by exactly the five hook
lines and `/usr/local/codeselect/`). Runs: `PAD_CARD=<that .raw>
PAD_CARD_CACHE=0 PAD_SELECT=1 PAD_AUDIO=0 watch.sh`, four times:

| run | keys (swpoke ids 64/65/36 = RIGHT/LEFT/START) | chose | result |
|---|---|---|---|
| 1 | right, left, start | 0 STERN 1.59.0 (p3, primary in place) | attract mode ~200 s after hand-off; NVRAM grades GE/CE/ZK = **P/P/P** in both slots (`nvgrades.py`); no validation banner |
| 2 | right, start | 1 TMNT 1987 (`bound over /games/turtles_pro` from p7) | attract; P/P/P; but the host video player still served the primary's clips (fixed: `dump/vidroot`) |
| 3 | right, start | 0 — the highlight had been remembered at 1, RIGHT wrapped to 0 | attract (the last-choice memory works) |
| 4 | right, start | 1 TMNT 1987 | `[padvid] clip root overridden by dump/vidroot: .../tmnt_multi.p7/turtles_pro`; attract shows the 1987 cartoon art |
| 5 (after the review fixes) | right, 95 s dwell, left, start | 1 TMNT 1987 | watch.sh no longer drops the selecting flag on a wall-clock bound (no `giving up` / `the game exited`); the 1987 splash `Back in 1987` was on the glass 1 s after START; attract at 259 s; clean teardown |
| 6 (v2: three images, media, bypass) | right, left, start | 1 TMNT 1987 from `p7:img1` (multi layout) | three cards with the cards' own logos, the 1987 animation on the highlighted card, move/confirm sounds through the rig's audio FIFO (`guest reports 44100 Hz x 2 ch`, padplay fed/played growing), confirm played 1.7 s under the LOADING frame, videos from `tmnt_multi3.p7/img1`, attract, grades P/P/P; one emulator-only gap: the FIFO reader dropped at 31 s and the menu's later sounds were lost - root-caused 2026-09-02 (reproduced standalone) to the rig's Windows padplay.py dying on its first `print()` after the wsl.exe session that launched the run exited, with playaudio.sh's restart loop blind to it (the interop stub never returns), so no reader ever came back for the game either; the selector had been retrying correctly and now names the gap and re-asserts the fmt file; the rig-side fix (a print-proof player, a restart loop that trusts the relay's "player went away" rather than the stub) is proposed, not applied |

| 7 (item 95: the STORE layout, three images inside p3) | start / right, start / right, right, start (one run per image, `PAD_CARD_CACHE=0 PAD_SELECT=1 PAD_AUDIO=0`, keys within the menu's 15 s) | 0 STERN 1.59.0 (p3, primary in place); 1 TMNT 1987 PRO (`p3:img1`, bound over /games/turtles_pro, `clip root overridden by dump/vidroot: .../sdcard.p3/img1/turtles_pro`); 2 TMNT 1987 LE (`p3:img2`, bound over /games/turtles_pro) | card `turtles-1_59_0.store-stock+1987pro+1987le.16G.sdcard.raw` (15.49 GB apparent = the 16G class exactly; 3.35 / 1.65 / 1.59 GB unique, 5.40 GB shared and stored once, 7.6 GB free; `verify` PASS in full: 1827 blobs, every tree file a link into the store, link counts exact, 6.58 GB of blobs hash to their names); the menu listed all three with the right trees, every choice landed (`[select] chose N`), the game drew its attract with each image's OWN art (image 0 the modern art, images 1 and 2 the 1987 cartoon - the framebuffer read back with `glshot.sh`), START fed a ball every time (`[ball] trough 5/6 after the feed`) and the glass showed PLAYER 1 / BALL 1 (Raphael on image 0, Donatello on image 1; the LE, on a fresh per-title NVRAM, first showed Stern's GUIDED SETUP - stepped to Save & Exit with SERVICE PLUS/SELECT (ids 26/25, 300 ms presses), a coin (39), then START - PLAYER 1 over the 1987 rooftop intro, a ball fed); no validation line; clean teardown, `alive.sh --total` 0 after each. `cardmount.sh`'s title rule had to learn that `img1/game` is a symlink (it would have run image 1 as the primary). |

The selector attached to the live GL bridge after padglhost was already up,
drew at ~60 fps, mapped the flipper ids from the title's switch table, and
exited 0 within 30 ms of START; watch.sh rode the `dump/selecting` flag
across the hand-off and `alive.sh` read 0 after every run.

## Testing on the machine (David)

1. Flash `D:/Pinball/TMNT 1987/multi/turtles_pro-1_59_0.multi-stock+1987patched.16G.sdcard.raw`
   (stock 1.59.0 + the Insider-clean patched 1987 build) to a 16 GB card with
   the app's *Build / flash SD card…* (any card ≥ 14,723,055,616 B) or
   `dd bs=4M conv=fsync`.
2. Power up. Expect the Stern logo, then within ~2 s of where the game would
   normally start: the SELECT GAME CODE menu. Flippers move, START or the
   lockdown-bar ACTION button boots;
   15 s countdown boots the remembered image. Service **−/+/Select** on the
   coin door do the same without the node bus.
3. If the menu never appears the card boots the primary (stock) by itself —
   nothing else changes. Read the serial console, or build the card with
   `--debug-log` and pull `/dump/log/codeselect.log` (the card's p6, or
   through a root shell): look for `egl: up after N attempt(s)`,
   `nb: node 8 switches 00 ff 1f fb 40 00 00 00` (the first 0x11 answer) and
   `spi: rx ff 0f 0f …`. `short reply (timed out)` on every frame means the
   node board wanted more of the game's bring-up: rebuild the card with
   `--preamble full` in `select.sh`'s codeselect line (opt-in replay of the
   byte-exact captured frames) and send the log back.
4. Insider Connected: log in from the stock image first (it grades and
   persists P/P/P), then from the 1987 image.

