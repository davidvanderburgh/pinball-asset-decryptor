# Pinball Brothers I/O-board emulator rig (Alien, ABBA, Queen)

Runs Pinball Brothers' own-electronics titles on this PC - the hardware PB
inherited from Heighway: a PC motherboard running Buildroot Linux and four
custom I/O boards on one USB link - on an emulated I/O board that speaks
the real protocol (`pbioboard.py`), the way `tools/spooky_emu` runs the
Warden games.  Predator is a different machine (FAST hardware) with its own
rig, `tools/pb_emu` (PAD-271); the two rigs share nothing but the program
names `pinprog` / `vidprog`, so this one finds its processes by `PBIO_MARK`
in their environment, never by name.

| title | files | status (2026-09-30) |
|---|---|---|
| Alien | `clonezilla-live-alien40.iso` (4.0, the whole machine); `pbap412.upd` over it (4.1.2) | attract, played (PAD-272) |
| ABBA | `pbap141.upd` + `pbap145.upd` (1.45), over Alien's ISO | attract, played - but a **black screen**: its factory media are not on D: (below) |
| Queen | `clonezilla-live-queen20d.iso` (2.0D, the whole machine, 10 GB); `pbq0210G.upd` over it (2.1G) | attract, played (PAD-326), both versions |

"Played" = coins, Start, the ball served by the game's own trough coil to
the shooter lane, launched by its own launch coil when Launch is pressed,
switches hit and scored (skill shot, ramp combo, top lanes, drops,
targets), a drain answered by BALL SAVED and a new ball - all hidden, on
both LCDs.

## Why it is only medium-sized

The machine is an ordinary x86-64 PC.  Its game is two native programs
under `/game/<title>`:

* **pinprog** - the game: a FreeWPC-derived C program (Alien 4.11's
  pinprog carries symbols: `cpu/native`, `platform/hp`, `platform/pb`).
  Rules, sound (SDL 1.2 + SDL_mixer over ALSA), NVRAM, and the I/O boards
  over USB serial.
* **vidprog** - the displays: SDL2 + GStreamer, the 1366x768 main LCD and
  the 800x480 "Airlock" LCD to its right on one 2166x768 X screen
  (`vidprog -2`).  It connects to pinprog on TCP port 5555.

Neither checks a licence or the hardware beyond the I/O boards, and both
run on the machine's own libraries.  So the rig restores the machine's root
partition from PB's Clonezilla restore ISO once, and runs the two programs
in a chroot of it:

| the machine | the rig |
|---|---|
| the root partition (sda2, ext4) | `$PBIO_CACHE/os-<iso>/root.img`, loop-mounted read-only, the lowest overlay layer |
| an update laid over `/game/<title>` | `$PBIO_CACHE/upd-<upd>/tree`, an overlay layer above it |
| writes | a per-run upper layer (`$PBIO_RIG/upper`) |
| `/game/<title>/nvram` (settings, audits, scores) | `$PBIO_NV/<title>`, kept between runs (`PBIO_FRESH=1` starts over from the image's) |
| `/mnt/log` (sda3: pinprog.log) | `$PBIO_RIG` |
| the I/O boards on `/dev/ttyACM0` + `/dev/ttyUSB0` | `pbioboard.py`'s two ptys, bind-mounted there |
| X on the two LCDs | a hidden 2166x768 Xvfb (`:200 + slot`), or WSLg with `--visible`: windows with title bars that move and resize (`pbioshim.so`, below) |
| the LCDs' GPU | none: SDL's own software renderer (`SDL_RENDER_DRIVER=software`; `PBIO_RENDER` overrides) |
| TCP 5555 between the two programs | the slot's own network namespace (loopback only), so slots do not collide; its Xvfb runs inside it |
| `date -s`, `hwclock -w`, reboot, init scripts, `firmware-update.sh` | logging no-ops (`$PBIO_RIG/shell.log`); the game also runs without CAP_SYS_TIME / SYS_BOOT, so a service-menu clock change cannot touch WSL's |
| sound (SDL 1.2 + SDL_mixer over ALSA, a softvol `Master` on the board's card) | with `--audio`: the chroot's `/etc/asound.conf` writes 48 kHz stereo into `$PBIO_RIG/audio.fifo` and `pbioaudio.py` plays it through WSLg's PulseAudio at the app's Volume / Mute; else `SDL_AUDIODRIVER=dummy` |
| fonts the factory image installed and no update carries | the same file from another title in the OS image, else a stand-in (`prepare.sh`, listed in `<build>/fonts`) |

Per title (`pbiotitles.py`): the firmware version the board reports, the
X screen and vidprog's arguments, the switch table, trough, coils.  Alien:
firmware 0.72, `-2` on 2166x768.  ABBA: firmware 1.03 (it and Queen refuse
anything below 1.00 - "Invalid FW version": the newer boards), one
1920x1080 screen, no `-2`.  Queen: firmware 1.03 (its 103.uf2, and the
factory log's "IO HW 0.04 FW 1.03"), one 1920x1080 screen.

## The I/O board (pbioboard.py)

Reverse-engineered from Alien 4.0's pinprog (stripped, but its debug
strings name every call) and confirmed against the factory machine's own
log (`/mnt/log/pinprog.log` on the ISO's sda3: "IO HW 0.04 FW 0.71").  The
protocol is in `pbioboard.py`'s docstring; in short:

* 115200 raw serial; pinprog opens **both** `/dev/ttyACM0` and
  `/dev/ttyUSB0` (either missing = no connection) and sends everything on
  the first.
* Host frame `0xA0|len, op, args`; board frame `0x50|len, type, data`
  (lengths count the whole frame).  Every host frame is answered by exactly
  one board frame - ACK `52 00`, or the reply to a request - and the host
  stops sending when too many are unanswered.
* Switch changes: `54 31 <sw> <1|0>` (1 = made); 96 switches.  At
  start-up the host reads every switch (`a3 53 <sw>` -> `53 xx <state>`).
* Versions: firmware `00 48` = **0.72** (the shipped `fw_alien_072.uf2`;
  the boot screen shows "FW. 0.72"), hardware 0.04.  Firmware 0.70+ puts
  the tongue motor in "programmed mode".  No firmware check forces a
  reflash: updating is a service-menu item that copies a `.uf2` to the
  boards' USB bootloader drive, and the rig no-ops it.
* Coils: `4E <coil> <pull %> <pull ms> <hold %> <hold ms le16> <mode>`
  (mode 0 configure, 5 pulse, 7 on until `4B <coil>`).  LEDs: `34 <n le16>
  <r> <g> <b>`, ~2000 frames a second in attract.  GPIO on/off `61` /
  `62`, servo `81` (Alien's jaw), motor pulse count `64`.

What it models, from the title's profile (`pbiotitles.py`):

* the trough (Alien: six balls, TROUGH 1-6 = switches 42-47, jam 41,
  eject coil 1 to the shooter lane 36, launch coil 0; ABBA: 31-36, jam 30,
  eject coil 0 to lane 37, launch coil 1), the ball in the lane half a
  second after the eject, the launch coil emptying it; kickers that empty their switch (LEFT
  EJECT 18/14, AIRLOCK scoop 23/70, CHAMBER LOCK 20/56-58);
* flipper buttons closing their end-of-stroke switches;
* **Alien's xenomorph tongue** - the one thing attract waits for ("amode
  waiting on xeno").  Its motor runs while GPIO 6 is on, forward while
  GPIO 7 is on; the game counts pulses itself (~250 a second) and
  calibrates against TONGUE MICRO (switch 0), a cam made at home and at
  full reach.  The board moves a virtual tongue at that rate and makes the
  switch at both ends (home <= 12 pulses, reach >= 215, travel 240), which
  the game's calibration accepts: "0 errors. System initialized."
* `PBIO_NAMES=1` answers the first switch poll with every switch made, so
  the game prints every switch's name (how the profiles were made).

Everything the board sees is counted (`state`: frames, opcodes, coils
fired/held, GPIO, servos, the tongue's position) and logged to
`$PBIO_RIG/board.log`; `leds` lists every lit LED.

## Use

All in PAD-Runtime as root; `PAD_SLOT=N` picks a slot (take a riglock slot
first; displays `:200+N`).

```
T=/mnt/c/.../tools/pbio_emu
P="/mnt/d/Pinball/images/Pinball Brothers"
PAD_VISIBLE=0 bash $T/watch.sh "$P/clonezilla-live-alien40.iso"   # Alien 4.0
PAD_VISIBLE=0 bash $T/watch.sh "$P/pbap411.upd" "$P/pbap412.upd"  # Alien 4.12, over the cached OS
PAD_VISIBLE=0 bash $T/watch.sh "$P/pbap145.upd"   # one file: pbap141.upd under it (pbiofiles.py)
python3 $T/sw.py coin; python3 $T/sw.py start     # sw.py --list, --state
python3 $T/sw.py plunge                           # the Launch button
python3 $T/sw.py "left orbit"; python3 $T/sw.py drain
bash $T/shot.sh /mnt/c/tmp/alien.png [main|airlock]
bash $T/status.sh; bash $T/stop.sh
bash $T/bootcheck.sh build-clonezilla-live-alien40  # VERDICT ... pass|fail
```

`prepare.sh` (files -> a cached build, printing `build=`) and
`run_game.sh` (a build -> attract) are the two halves of `watch.sh`.  An
update alone takes its OS from `$PBIO_OS`, else the OS already prepared,
else a `clonezilla-live-*.iso` beside it; an update's own files other than
`game/` (init scripts, its installer) are left out.  The first ISO restore takes a
few minutes and 3.5 GB; after that a start is ~13 s.  Logs:
`$PBIO_RIG/pinprog.log` (the game's own, as on the machine),
`vidprog.log`, `board.log`, `shell.log`, `inner.log` (the namespace).

Coins: Alien is set to 6 units a coin, 20 a credit - four coins make a
credit.  Presses closer than ~1 s apart are debounced away by the game.

## What is open

* **ABBA needs its factory media.**  `pbap141.upd` is called full but
  carries only what changed since the factory image: no attract videos
  (`media/Animations/amode`), no fonts, no sprite sheets (`*.sprites`),
  54 MB of audio.  So pinprog boots to attract, takes coins and Start,
  serves, launches and scores (proven from its log and the board), while
  vidprog - a different, newer build than Alien's - runs on a black
  screen ("video open error ... GStreamer not inited" for every missing
  video).  It needs an ABBA restore ISO (or the first full install), which
  is not on D:.  Five of its six fonts come from Alien's image under the
  same names; `BoringSansBold.ttf` exists nowhere here and is a DejaVu Sans
  Bold stand-in - without a font vidprog aborts.
* **Queen (PAD-326)** runs from its restore ISO,
  `clonezilla-live-queen20d.iso` (10 GB, PB's public Google Drive): its
  root partition is a raw `dd` image of 22 GB, restored sparse (9.5 GB on
  disk, about 5 minutes), with the whole 8.5 GB of media.  `pbq0210G.upd`
  (2.1G) is a delta over it; picking it alone finds the ISO beside it.
  Its profile came from a `PBIO_NAMES=1` boot (96 switches: trough
  57/58/60-63, jam 56, shooter lane 59) and from what the game fired:
  coil 1 TROUGH RELEASE on every "TROUGH: kicking now", coil 0 AUTO LAUNCH,
  coil 19 LEFT VUK (sw 27), coil 5 RIGHT VUK (sw 10).  **Queen has no
  Launch button**: the flippers launch ("FLIPPER PLUNGER"), and every
  ball starts on a song select that both flippers confirm - so the
  profile has `plunge: [77, 78]` (both flipper buttons) and no `launch`
  button, and the playfield window's Space key is not taken from the
  left flipper.  Played: coins, Start, song select, both flippers ->
  "SHOOTER LETS ROCK" and the song running, shots scored (1,100,220 on
  ball 1), a drain answered by bonus and ball 2, or by the ball save's
  auto-launch.  The CENTER SAUCER's kicker is not modelled (a tap scores
  it; a held switch stays made).
* **In the app since PAD-315**: the Emulate PB tab runs this rig when the
  picked file is Alien's, ABBA's or (PAD-326) Queen's (`emulate_pb_core.kind_of`), and
  Predator's rig otherwise.  One file is enough: `watch.sh` with one file
  stacks what it builds on (`pbiofiles.py chain`: the newest full update
  of that title at or below it, else its restore ISO).  The playfield
  window is Predator's (`tools/pb_emu/pbpf.py --rig pbio`) on
  `pbioswitches.py`'s table; the Cache window lists `cache.sh --list`
  (the restored OS images and unpacked updates) beside Predator's.
* **Sound, window, pace (PAD-322).**  SDL 1.2 in the image speaks ALSA
  only and has no PulseAudio client, so with `--audio` (the app always
  passes it) the chroot's ALSA default is `plug` -> `file` (raw, into
  `/mnt/log/audio.fifo`) -> `null`, and `pbioaudio.py` reads the FIFO on
  the host and plays it with libpulse-simple, scaling the samples to the
  app's control file (Mute = silence from the first sample).  The FIFO is
  the game's clock: the relay drains it at the speakers' pace, and at the
  real-time rate if PulseAudio is gone, so the game never stalls.
  `pbioaudio.log` logs the level and, every 10 s, the peak of what came
  in - proof sound flows on a muted run.  The game's own volume (the
  service menu's, through `amixer` on the board's card) is not modelled.
  The window: `pbioshim.so` (built by `build.sh` for the image's glibc
  2.30) gives vidprog's borderless LCD slabs title bars and RESIZABLE,
  scales the cabinet's whole screen into 1600x900 with one factor (Alien's
  two windows side by side), and draws each LCD into a texture that every
  present scales into the window - so any window size shows the whole
  picture.  The pace: vidprog drew through the image's Mesa `swrast`
  (softpipe, no LLVM) at ~9 frames a second on a whole core; SDL's
  software renderer draws the same at the game's 30 a window for a fifth
  of one.  `fps.log` (the shim) has the frames each window presented a
  second, every 5 s.
* **No physics** beyond the trough, the shooter lane and the kickers:
  ramps, orbits, locks and the tongue's ball-grab are switches you press.
  The magnets, posts and drop-bank reset fire into nothing.
* Alien 4.0 (the ISO) was played; 4.1.2 (`pbap412.upd` over it) booted
  to attract; the full 4.11 (`pbap411.upd`, 2.3 GB) was not unpacked -
  PAD-Runtime's disk had 1.8 GB free.  The xeno calibration is proven on the rig's model, not measured
  against a real tongue's travel.
