# JJP multi-boot in the emulator (item 117)

The JJP twin of `tools/spike2_emu/codeselect/DESIGN.md`: how a multi-boot
install ISO (`mkjjpmulti.py`, item 116) boots in this rig, which script does
what, and what has been proven. The plan is `plans/jjp_multiboot_plan.md`
(gitignored, on David's machine); the menu is `jjpselect` (item 114) and the
hook `padselect.sh` (item 115), both in `tools/spike2_emu/codeselect/`.

## What a multi-boot install is, in one paragraph

Image 0's root goes into JJP's root A with the menu staged into it; image 1's
root goes into root B byte for byte; the stick's own installer, copied to
`/jjp/pad_install.sh` and patched on two lines, restores root B from the
second image's pieces. grub never changes and the machine always boots A, so
perm A (settings, audits, scores) is one set for both. On every boot root A's
`rungame.sh` runs `padselect.sh` after `runonce.sh`: fewer than two images,
nothing; otherwise JJP's updater is masked (it would write root B and boot
it), `jjpselect` draws the menu on the X server the machine already started
and reads the cabinet buttons off `/dev/jjpio100`, and for image 1 the hook
mounts root B at `/jjpe/multi/b` (by the UUID in the card's own
`fs_uuids.sh`), bind-mounts `/jjpe/multi/b/jjpe/gen1/<Game>` over
`/jjpe/gen1/<Game>`, re-does what `runonce.sh` did on the tree the game now
sees (the `vf` link into perm, chown, +x) and returns. Any failure unwinds to
image 0. The game then starts exactly as it always did.

## How the rig boots it

Every path is `padpath.sh`'s; `JJP_ISO=<multi.iso>` picks the base
`/var/tmp/jjp_<slug>/` like any other title.

| step | script | what changed for multi-boot |
|---|---|---|
| restore | `mount.sh` | restores EVERY `sdaN.ext4-ptcl-img` set the ISO carries, not a fixed list: `sda3.raw` (root A with the menu) and `sda5.raw` (root B) both land in the base; root B is loop-mounted read-only at `$JJP_ROOTB` (`<base>/rootb`). Prints `multiboot=` and `rootb=`. |
| jail | `jail.sh` | when `$JJP_ROOTB` is mounted, lays an overlay of it (tmpfs upper `$JJP_OVLB`, because root B is rw on the machine and the hook chowns and links inside it) at `$JJP_JAIL/jjpe/multi/b`, the path the hook looks at FIRST. So the hook takes its "already there" branch and never touches `/dev/disk/by-uuid`: one script serves the machine and the rig. |
| run | `run_game.sh` | the RUN executes in a mount namespace of its own (`unshare -m --propagation private`), and runs `$JJPEDIR/scripts/padselect.sh` at the point the machine's `rungame.sh` does (display up, before `./game`) when root A carries it. The hook's binds and the updater mask die with the run. `JJP_SELECT` is the three-way switch: unset = ask the image, `1` = insist (exit 9 when the image has no hook), `0` = skip the menu. The hook runs BEFORE the `cd $GAMEDIR`: a shell already inside the directory would keep the old one under the bind. Right before `./game` the run logs `[rig] game tree: <findmnt SOURCE,OPTIONS of $GAMEDIR>`. The launch watch counts a live `jjpselect` as up, because a run sits in the menu for up to the conf's timeout before a game process exists. |
| facts | `status.sh` | `multiboot=` (root A carries hook + conf), `rootb_mounted=`, `selector_procs=`, `choice=` (the integer the menu wrote), `bound=` / `bound_lower=` (asked INSIDE the run's namespace with `nsenter -t <leader> -m findmnt`; `bound_lower` ending in `/rootb` is image 1, empty is image 0 or no run). |
| alive | `alive.sh` | counts `jjpselect` with the game: a rig in the menu is live. `killgame.sh` kills it with the game (a client of the nested Xephyr, so no ghost). |
| teardown | `unjail.sh` | takes root B's overlay and its tmpfs down before the jail. The hook's own binds need nothing: the namespace died with the run. |

Two overlays read alike. Both roots are overlays in the rig, so a bind of
either shows `overlay[/jjpe/gen1/GunsNRoses]` as its SOURCE; the mount
OPTIONS (`lowerdir=…/rootb` vs `…/root`) are what tell them apart, which is
why the log line and `status.sh` carry them. On the machine the source reads
`/dev/sda5[/jjpe/gen1/GunsNRoses]` and there is no ambiguity.

## Running it

```
wsl -u root -- env JJP_ISO=/var/tmp/jjp116/GunsNRoses-v03.03.multi.iso bash tools/jjp_emu/watch.sh
```

is the whole thing (mount, jail, dongle, audio, boards, display, game, the
matrix): the menu appears on the Xephyr window, LEFT / RIGHT move, START
confirms, the timeout boots the highlighted image.

**The menu's buttons are the switch matrix's keys**, the same ones a game
uses: with the matrix window OR the game window focused, Left / Right (or
a / ') for the flippers and 1 for Start. The game window takes them because
the matrix runs `jjpkeys.py`, which grabs those keys on the nested display
the game and the menu draw into and reports each press back to the matrix. The matrix therefore opens BEFORE the game step on a
multi-boot image (`jjpsw_launch.sh --menu`), not after it: it used to need a
running game, so the menu came and went with nothing to press (David,
2026-09-13). It opens from this title's saved device tables, which are right
for both images because a multi-boot install's two images run the same game
binary; on a first run with none saved it opens with the five cabinet
switches alone (LEFT byte 1 bit 0, RIGHT byte 1 bit 2, START byte 3 bit 0,
and the Volume+ / Volume- pair on byte 1 bits 5 and 6, keys Up / Down),
and a detached `jjpsw_launch.sh --await-game` reopens it onto the game's own
tables once the game is up. Stop ends the waiter with the matrix.

**Volume.** The Emulate JJP tab's Volume / Mute is the other Emulate tabs'
knob and file (`audio_ctl.json`). The tab hands the file to `watch.sh` as
`PAD_AUDIO_CTL`; `audio.sh` starts `jjpvol.py`, which holds every PulseAudio
stream the game and the menu open at that level (pactl run inside the jail),
live, until the jail goes or `stop.sh` ends it. A muted rig (`PAD_AUDIO=0`) or
a PulseAudio that does not answer has no stream to hold and starts none. `JJP_SELECT=0` in the
environment skips the menu (image 0), `JJP_SELECT=1` insists on it. To drive
the menu from a script, poke the cabinet bytes in the shared block the CUSE
boards serve (RIGHT = byte 1 bit 2, LEFT = byte 1 bit 0, START = byte 3 bit 0,
active low; `jjpshm.h`).

Scripted runs wait for the MENU, not for a process: `JJP_SELECT_LOG=1` makes
the hook hand the selector `--log /jjpe/temp/jjpselect.log` (the same
`PADSELECT_SELECT_LOG` knob the hook's tests use), and a driver polls that
file for its `menu:` line before it pokes a button. A poke that lands while
the selector is still starting is simply lost: the first run of 2026-09-13
recorded no choice for exactly that reason, and the rerun with the wait
recorded every key.

Two more things a driver has to know. **The menu remembers.** `jjpselect`
writes its last choice to `perm/padselect.last` and starts highlighted on it,
so a second run in the same jail starts on whatever the first one chose:
"RIGHT, RIGHT wraps back to 0" is only true from a fresh perm, and the with-key
proof's second attempt chose Chaka twice that way. Either read the `menu:`
line's `highlight N` before poking, or remove `$JJP_JAIL/jjpe/perm/padselect.last`
and press START alone for the conf's default. **And GNR's game log has no
`Loaded N files (bytes)` line.** The plan named it as an oracle; the log is
NetworkManager and sensor noise, nothing about assets. What does tell the two
images apart while the game runs: `status.sh`'s `bound_lower`, the hook log,
the `[rig] game tree:` line, `nsenter -t <leader> -m du -sb
$JJP_JAIL/jjpe/gen1/GunsNRoses/edata` (4,450,623,016 stock, 5,157,432,132
Chaka), and `grab.sh` of attract.

## Proof (2026-09-13, the GNR multi-boot ISO of item 116, no Sentinel key attached)

| step | oracle | result |
|---|---|---|
| restore | `mount.sh` on the 12.97 GB ISO | sda3, sda2, sda4 and sda5 restored in 2 min 28 s; `multiboot=1`, `rootb=<base>/rootb` |
| root A | its tree | `padselect/{jjpselect,font.ttf,images.conf,build.json,media.json,media/}`, `scripts/padselect.sh`, the hook line at `rungame.sh` 32-33 |
| root B | its tree | Chaka's `GunsNRoses` with `edata` 5,157,432,132 B (root A's stock one: 4,450,623,016 B) |
| jail | `jail.sh` | `root B  : /var/tmp/jjp_run/jjpe/multi/b (overlay of <base>/rootb)`, the game dir visible there |
| choose 1 | RIGHT, START | selector log `chose 1 CHAKA'S LOTLJ`; hook log `image 1: rootB - /jjpe/multi/b/jjpe/gen1/GunsNRoses bound over /jjpe/gen1/GunsNRoses (root B was already at /jjpe/multi/b)`; game log `[rig] game tree: overlay[/jjpe/gen1/GunsNRoses] rw,relatime,lowerdir=<base>/rootb,upperdir=/var/tmp/jjp_ovlb/up,…`; `status.sh` `choice=1` |
| choose 0 | RIGHT, RIGHT (wraps), START | `chose 0 GUNS N' ROSES 3.03`; hook `image 0 chosen: the primary, already in place`; game log `[rig] game tree: /jjpe/gen1/GunsNRoses (no bind: image 0)`; `choice=0` |
| `JJP_SELECT=0` | no menu | `selector_procs=0`, no hook log, `no bind: image 0` |
| `JJP_SELECT=1` | the menu must run | it ran; START alone chose the default 0 |
| updater | every menu run | hook log `updater masked (2 images, jjp_update=refuse)` |
| the game | `./game` after the hook | `Sentinel key not found (H0007)` in every run: no key was attached (`usbipd list` showed none connected), so the game exited at its first envelope call, right after the bind was made |
| teardown | `unjail.sh`, `stop.sh --all`, `alive.sh --total` | 0 jail mounts, `game=0 matrix=0 xephyr=0 cuse=0`, alive 0 |

## Proof (2026-09-13, WITH David's GNR key over usbipd - plan row R3)

The same command, `watch.sh` with `JJP_ISO` on the multi ISO, muted
(`PAD_AUDIO=0`), the menu driven by pokes, the game left to boot the chosen
image and settle into attract. `usbipd attach --wsl --hardware-id 0529:0001`
put the key on the bus; `dongle.sh` found it (`key: kernel=1-1
node=/dev/bus/usb/001/002`, `hasplmd ready after 1s`, `dongle_present=1`).

| step | oracle | result |
|---|---|---|
| choose 1 | RIGHT, START | selector `chose 1 CHAKA'S LOTLJ`; hook `image 1: rootB - /jjpe/multi/b/jjpe/gen1/GunsNRoses bound over /jjpe/gen1/GunsNRoses`; game log `[rig] game tree: overlay[/jjpe/gen1/GunsNRoses] rw,relatime,lowerdir=<base>/rootb,upperdir=/var/tmp/jjp_ovlb/up,…`; `status.sh` `choice=1 bound=overlay[/jjpe/gen1/GunsNRoses] bound_lower=<base>/rootb`, `game_procs=3`, 168 s up when read |
| Chaka runs | the game itself | no `H0007`; one `exit 68 - restarting (1)` (every GNR run here does that once) and then attract: `grab.sh` shows Chaka's poster wall behind a COMA MULTIBALL high-score card, 99.9 % non-black |
| choose 0 | START alone, after `perm/padselect.last` was removed (menu line: `highlight 0 (GUNS N' ROSES 3.03) from conf default`) | `chose 0 GUNS N' ROSES 3.03`; hook `image 0 chosen: the primary, already in place`; game log `[rig] game tree: /jjpe/gen1/GunsNRoses (no bind: image 0)`; `choice=0`, `bound=` and `bound_lower=` empty, `game_procs=3`, 535 s up when read |
| stock runs | the game itself | `du -sb` of `edata` from inside the run's namespace = 4,450,623,016 (stock; Chaka's is 5,157,432,132); attract is the stock playfield render, 99.4 % non-black |
| both | the overlay both attracts carry | `COIN DOOR IS OPEN`: the rig's cabinet frame reads the door open (the shim's idle frame), the same as every GNR run in this rig and nothing to do with multi-boot |
| teardown | `killgame.sh`, `stop.sh --all`, `alive.sh --total` | `killed 3; still running: 0`, 0 jail mounts, `game=0 matrix=0 xephyr=0 cuse=0`, alive 0 |

The captures and both drivers' output are kept outside the repo at
`C:\tmp\jjp117\` (`attract_chaka.png`, `attract_stock.png`, `rig117key*.out`).
That is the acceptance: the machine's own scripts, unchanged, boot whichever
image the cabinet buttons pick, with the key answering for both. What is left
for the hardware is item 119.

## The menu's sound (item 120)

A JJP machine keeps its amplifier chain at full while the menu plays (root
A's `asound.state` holds 0 dB, `scripts/audio/mute.pl` sets 100%) and the
game turns only its OWN stream down to the operator volume, so the menu's
software gain is the level the speakers get. On the first GNR the menu at
`volume=50` was very loud, and its move sound came a moment late: the ALSA
buffer was the Stern card's 500 ms, which `audio_pump()` keeps full.

- **The JJP build** asks for a 60 ms buffer and logs the one granted
  (`audio: alsa buffer N frames (M ms), period ...`); its number is 0-100
  as on Stern, starting at 50 (`DEF_VOLUME`), but 100 plays at 10% of the
  samples (`VOLUME_FULL_PCT`, PAD-219: the scale was 0-40 with 20 the
  default, and 20 was already high on the GNR and 8 "at max" on cooltoy's
  Sonic). Nothing takes it past 100 (`VOLUME_CEILING`): not `volume=`, not
  `--volume`, not the remembered level. `volume_max=` in the conf can only
  lower it; `mkjjpmulti.py` always writes `volume=` and `volume_max=100`
  and refuses a volume above 100.
- **The machine's front Volume+ / Volume- buttons** (byte 1 bits 5 and 6,
  active low: `dswitch_plus` "Up / Volume+ Button" and `dswitch_minus` "Down /
  Volume- Button" in GNR's device table; `key_plus=` / `key_minus=` move them)
  step the menu's level by 10 within the cap, play the move sound at the new
  level, restart the countdown, and put "VOLUME n / cap" and a bar over the
  middle of the menu for 2 s ("VOLUME OFF" at 0). When the indicator goes the
  level is written to `/jjpe/perm/padselect.volume`, beside
  `padselect.last`, and the next boot starts there - but only while the card's
  `volume=` is the one the level was set under (the file's `conf N` line,
  PAD-216). JJP's installer keeps perm on a same-game reinstall, so before
  that a card rebuilt with a lower volume still played at the old card's
  remembered level; now a new `volume=` wins. They change the MENU's
  level only; the game's operator volume is JJP's own and is not read. In the
  rig they are the switch matrix's Up / = and Down / - keys, from either
  window. The menu also opens with "VOLUME n / 100" up for its first 3 s on
  its own (PAD-219: cooltoy's Sonic was "at max" at volume=20, 8 and 10
  alike, with the PAD-216 fix on the card, and no machine log to read; the
  number on the glass says which level the menu holds, and a Down press
  that leaves the sound as loud says it is not the menu's). A start
  indicator writes nothing to perm; only a press does.
- **The media** the JJP media step writes is peak-levelled: every menu sound
  and music bed to -3 dBFS (`selectmedia.py prepare --peak-dbfs -3`; -12 until
  2026-09-14, when the GNR's 40 ms click at -26 dBFS read as no sound at all), so no
  source file arrives louder than planned.
- **When the menu has no sink it says so on the glass**: `SOUND OFF: <why>`
  along the top edge (only when a sink was asked for: `--audio none`, a
  snapshot and the rig's fifo show nothing), and a device that refuses the
  60 ms buffer is retried at 120, 250 and 500 ms before the menu gives up on
  sound. The selector's own log goes on the machine with `mkjjpmulti.py build
  --machine-log` (`log=/jjpe/temp/jjpselect.log`, bounded; it was on by
  default only while the GNR's silence was being chased, and off again since
  2026-09-15 on David's ask): JJP's own `dumplogs.sh` copies
  `/jjpe/temp/*.log*` onto a stick, so the Utilities log dump carries it.
  Proven silent on the rig (2026-09-14, scratchpad `pulseprobe120.sh`): the
  GNR root's own PulseAudio 15 with a null sink inside the jail, its monitor
  recorded, the selector at 60 ms and at 500 ms - every click and the confirm
  chime reached the sink with the mix's own peaks, 0 dropped, 0 recovers.
- **The menu is asked ONCE per install, not twice (David, 2026-09-14 evening).**
  After a fresh install the game exits 68 or 69 - JJP's own `rungame.sh`
  calls both "maintenance reboot" - and reboots the machine, and the menu
  asked again on the way back. The builder's second patch of rungame.sh
  (`mark_maintenance_reboots`, anchored on JJP's case comment) runs
  `padselect.sh --maintenance-reboot` right before those reboots: a timed
  mark in `/jjpe/perm/padselect.maint`. The next boot consumes the mark and
  boots the last chosen image without the menu (`maintenance reboot Ns ago:
  image N again, no menu` in the log), once, and only while the mark is
  under an hour old and a last choice exists; a rungame.sh without such
  cases is left alone and the menu shows again after such a reboot.
- **THE CAUSE of the GNR's silent menu: the wrong sink (2026-09-14, late
  evening).** A GNR with JJP's headphone kit has TWO PulseAudio sinks: the
  kit's USB codec (`alsa_output.usb-C-Media_Electronics_Inc._USB_Audio_Device-00.analog-stereo`)
  and the onboard codec that drives the speakers
  (`alsa_output.pci-0000_00_1f.3.analog-stereo`), and PulseAudio ranks usb
  above pci, so the server's DEFAULT sink is the kit. JJP's own
  `scripts/audio/setup.pl`, run once the GAME is up, finds the pci analog
  sink, makes it the default (`pactl set-default-sink`) and moves the game's
  stream there (`pactl move-sink-input`); `setoutputdevice.pl` moves it to
  usb / pci / bluez per the operator's output setting. The menu runs BEFORE
  setup.pl and played into the default sink, i.e. the kit: silent speakers
  through five sticks - the level, the buffer, the pump thread, the reopens
  and libpulse-simple were all real fixes to a path that was never the
  problem, and every rig proof heard them because the rig has ONE sink. The
  one loud boot (item 119) was a boot after the game had run: setup.pl's
  default is persisted by module-default-device-restore in /var/lib/pulse,
  and every reinstall since wiped it. The fix is in the hook: `padselect.sh`
  names the pci analog sink for the selector's stream (`PULSE_SINK`, the
  match setup.pl uses - "pci" in the name, "analog" on the line - via
  `pactl list short sinks`; `PADSELECT_PACTL` for the test) and logs `menu
  sound to <sink>`; the pulse sink logs `sink <name>` in its `pulse ok`
  line. No pci sink (the rig) = the default, as before. Rig instrument: the
  GNR root's pulse in the jail with two null sinks named as the machine's,
  the usb one the default, both monitors recorded, the HOOK launching the
  menu (scratchpad `pulseprobe120b.sh`): the stick's hook lands the clicks on
  the usb sink, the fixed hook on the pci sink. Machine confirmation: GNR
  check 5.
- **The JJP build plays through PulseAudio ITSELF** (`audio_pulse.c`,
  libpulse-simple, the library the game's own audio uses): `--audio auto` on a
  JJP build tries the server first and falls back to ALSA when none answers.
  GNR check 3 (2026-09-14): a fourth stick through ALSA's `default` - the
  pulse PLUGIN - with the pump thread and the reopens was STILL silent while
  the rocker stepped the indicator; the plugin's stream is what fails on the
  machine and only partly reproduces here. libpulse-simple is a blocking
  stream on the server's terms: an underrun is silence the server inserts
  and the stream carries on, nothing reconnects. The sink paces itself
  60 ms ahead of the wall clock (`PULSE_LEAD_MS`) into an 80 ms server
  buffer (`PULSE_TLENGTH_MS`), drops the backlog after a stall instead of
  playing it late, and logs `audio: pulse ok (... latency N ms)`, errors,
  reconnects and resyncs. Rig-proven on the GNR root's own PulseAudio 15
  (2026-09-14 evening, `pulseprobe120.sh`): plain, the render loop sleeping
  100 ms a pass, and the process stopped 80 ms of every 200 - every click and
  the chime reached the sink in all three, 0 errors, 0 reconnects; a single
  resync at 1.2 s in the quiet runs is the rig's null sink taking ~1.1 s to
  start pulling (the write blocks once, the backlog is dropped).
- **The first theory of the silence - underruns (2026-09-14, evening; the
  cause turned out to be the sink, above).** The
  machine's loop is vsync-paced and hiccups; a 60 ms buffer underruns on any
  hiccup over ~45 ms, and after the recover a stream through the pulse plugin
  never restarted: alsa-lib's start threshold is a whole buffer, which the
  reconnected stream never quite reaches. Rig-reproduced with the selector
  stopped 80 ms of every 200 (`STALL=1` in `pulseprobe120.sh`): 7 recovers,
  then 33,729 frames for the rest of a 16 s run and a 10 s hang on close,
  while 500 ms under the same stalls played everything. The fixes: the pump
  runs on its own thread every 5 ms (`audio.c`, both builds), so the render
  loop's stalls never starve the sink (`PADSELECT_STALL_MS` sleeps the loop
  each pass: 0 recovers at 100 ms a pass); and on the JJP build an underrun
  REOPENS the PCM (`ALSA_REOPEN_ON_XRUN=1`) instead of `snd_pcm_recover`,
  because after a recover the pulse plugin's own bookkeeping leaves the
  stream stalled whatever the start threshold (a one-period threshold,
  `ALSA_START_PERIODS=1`, is set too, so a fresh stream starts on its first
  period), and a WATCHDOG: nothing accepted by the device for 3 s while it
  is open counts as stuck, whatever the cause, and reopens it too. Three
  seconds because a fresh stream through the pulse plugin takes ~1.1 s after
  its first fill before the server pulls more (`audio: alsa took N ms after
  the first fill to take more` in the log), and every recover or reopen pays
  that pause again - which is how frequent underruns became silence: the
  pump thread is the cure, the reopen the net. The Stern card's sink keeps
  `recover`, untouched.
- **The headphone kit's rocker** (an LE/CE option: a plate with a 3.5 mm jack,
  a Bluetooth button and a VOLUME rocker on its own little board) is not in
  the game's switch table; on David's GNR the glass named it byte 3 bits 6
  (+) and 5 (-), and `mkjjpmulti.py build --key-plus 3.6 --key-minus 3.5`
  writes `key_plus=` / `key_minus=` into images.conf (all five `--key-*`
  flags exist; an inject carries them; `inspect` shows `keys=`). The coin
  door's Up / Down are REPLACED by a `key_plus=` / `key_minus=` (the ISO of
  GNR check 4 left them unmapped, printing the learn line). A comma and a
  second position is the same button in a second place, so the GNR build
  names both pairs, `--key-plus 1.5,3.6 --key-minus 1.6,3.5`, and
  `--key-start 3.0,3.4` makes the lockdown-bar Action button (byte 3 bit 4,
  read off the log) a second START (David, 2026-09-14 evening).
- **The machine's buttons are READ, not guessed**: with `learn=1` in
  images.conf (`mkjjpmulti.py build --learn`, which implies the log; off by
  default since 2026-09-15) the hook runs the selector with `--learn`, so a frame bit that changes and is not one of the five
  mapped buttons is written to the log (`INPUT byte N bit M pressed (not a
  menu button)`; it was on the glass for 3 s as well until David asked for
  that line to go, 2026-09-14 evening) and the changed frame goes to the
  log as hex (two
  lines of 32 bytes, at most 4 a second and 300 a run). David's GNR has an
  outside volume toggle that moved no mapped bit (2026-09-14); a press of it
  in the menu now names its byte and bit, which `key_plus=` / `key_minus=`
  in images.conf then take. The five mapped buttons: LEFT 1.0 and RIGHT 1.2
  and START 3.0 (JJP's own jjpcrt reads them there), Up/Volume+ 1.5 and
  Down/Volume- 1.6 (the game's switch table: frame bit = table index - 1,
  which puts the three jjpcrt buttons exactly where jjpcrt reads them).
- **Proof runs**: `JJP_SELECT_DUMP=1` makes `run_game.sh` hand the menu
  `--audio-dump /jjpe/temp/jjpselect.mix.raw` (s16le, 44100 Hz, stereo), which
  is how a MUTED rig hears the clicks follow the buttons.
- **Videos**: a JJP image's picture is a video file (the Edit image dialog's
  "A video file"; there is no "attract video" choice on JJP - a JJP root has
  no attract clip in the clear). `.webm` and `.flv` are videos, because that is
  what PAD extracts from a JJP game (629 of GNR's 648 clips are VP9 `.webm`).

### Proof (2026-09-14, muted, no Sentinel key plugged in)

The menu needs no key (the hook runs before `./game`), so the launch was
`watch.sh`'s own steps with the dongle step left out; the game after the menu
died with H0007, which is the key's business. Every ISO was built the tab's
way: `ensurejjpselect.sh`, `mkjjpmulti.py media`, `mkjjpmulti.py build`.

| step | oracle | result |
|---|---|---|
| media | `selectmedia.wav_stats` | move.wav -6.0 -> -12.00 dBFS, confirm.wav -6.9 -> -12.00 dBFS; `media.json` volume 20 (the mark is -3 dBFS since 2026-09-14) |
| buffer | the selector's log | `alsa buffer 2646 frames (60 ms), period 661 frames (14 ms); asked 60 ms`, `lead 60 ms`, 0 recovers |
| buttons | Up, Up, Down typed into the game's display | `key: plus/plus/minus`, `volume: 20 -> 25 -> 30 -> 25 (of 40)`, `indicator off at 25`, `25 remembered in /jjpe/perm/padselect.volume`, the perm file holds 25 |
| level follows | the mix dump (`JJP_SELECT_DUMP=1`) | the clicks peak 2058 / 2444 / 2058 against 2057 / 2443 / 2057 expected (move.wav's 8231 x the gains of 25 / 30 / 25); the confirm chime 2058 |
| remembered | a second launch | `volume: 25 of 40 (remembered in /jjpe/perm/padselect.volume)` |
| indicator | `JJP_DISPLAY=:1 grab.sh` | "VOLUME 25 / 40" and 5 of 8 segments over the menu, then the plain menu 3 s later (`C:\tmp\jjp120\osd_up.png`, `osd_gone.png`) |
| animations | a GNR clip on each image (`Attract_Montage_1.webm`, `Attract_Back_BulletsRoses_loop.webm`) | `anim: image 0 120 frames 512x288, a 5.0 s loop`, `image 1 96 frames ... 4.0 s`, every frame cached, `played 528 drawn 528` each; grabs 400 ms apart differ in 87-92 % of the highlighted panel; the loop at 326-334 passes/s, longest 71 ms at start and 5 ms after |
| teardown | `stop.sh`, `alive.sh --total` | `game=0 matrix=0 xephyr=0 cuse=0`, alive 0 |

The last run was on the family with main merged in (`item/120-merge`), after
the Stern check: Stern's selector built from main and from the merge ran
`make check` and 133 of 138 frames matched byte for byte; the other five
differ between two runs of main too, or print a clock-seeded random group roll.

## From the app (item 118)

The Multi-boot tab builds this ISO too. Pick Jersey Jack and the tab switches
to its JJP backend (`gui/multiboot_backend.py`): the path box says
"Multi-boot install ISO", the list takes two install ISOs (root A, root B; no
random groups), the size strip says which USB stick they need, and the green
button is "Build / make stick…". Its run is the selector step
(`tools/jjp_emu/ensurejjpselect.sh` builds `jjpselect` and installs it under
`/var/tmp/jjpselect` in the card's layout),
the media (`mkjjpmulti.py media`: 'auto' art is each image's own JJP logo,
'auto' sounds are the built-in click and chime), `plan`, `build` and `verify`,
all `mkjjpmulti.py`, the writing steps as root. The dialog's stick tick hands
the ISO to the plugin's own FAT32 stick maker; 'Run in emulator' hands it to
the Emulate JJP tab, whose rig shows the menu by itself.

**Loading an ISO touches only its menu.** The load reads `/jjp/padselect` off
the ISO (the conf, the media, the menu program) and restores nothing.
`jjpselect` links against nine of a JJP root's libraries and what those need,
so `ensurejjpselect.sh` copies them once into `/var/tmp/jjpselect_sysroot`
from a root already on the PC (a mounted one, or a restored
`/var/tmp/jjp_<slug>/sda3.raw`), and every rebuild after that takes seconds
with nothing mounted. With no root on the PC, the preview (`--preview`) draws
with the ISO's own `jjpselect`; only a writing run restores anything, and then
only the first ISO's root partition (`mount.sh --root-only`). Until
2026-09-15 a loaded multi-boot ISO went to `mount.sh` whole: all four
partitions, 13 GB, with the progress thrown away.

**The tab's tools run in the app's own distro, PAD-Runtime**, not the default
one: its `/var/tmp` holds its own restores (`jjp_<slug>`), its own
`/var/tmp/jjpselect`, its own scratch (`/var/tmp/pad_jjpmulti_work`), and it
has no squashfs-tools, so the builder reads JJP's installer out of the live
squashfs with a loop mount there. Proven 2026-09-13 through the real tab code
on the GNR pair: selector 17 s, build 585 s (12.97 GB to `D:\Pinball\multi`),
verify 33/33, "Card built and verified". The stick and the emulator launch
from the tab wait on a USB stick and a tab-driven run with the GNR key.

## Straight onto the SSD (item 123)

`mkjjpmulti.py install --iso X.iso --disk /dev/sdX [--yes]` writes an install ISO onto a
disk the way JJP's installer writes it on the machine, with no stick, no live boot and
no security key (the key gates the game, not the disk).  THE STEPS ARE THE ISO'S OWN
INSTALLER'S, READ OUT OF IT: `jjp_install.sh` (this tool's `pad_install.sh` on a
multi-boot ISO) names the partition numbers, the filesystem UUIDs grub.cfg, fstab and
the perm mount generator expect, the sgdisk templates by disk size (`/jjp/lib/
backup.sgdisk1/2/3` in the live squashfs: 30/60/120 GB), the size gate
(`version_info.txt` Disksize, 111 GiB), which image goes into which slot in what order,
and how the temp partition is made - each line anchored exactly, like the installer
patch, and an installer that does not parse is refused.  So a stock ISO installs as
JJP's does (root B = a copy of root A) and a multi-boot ISO as `pad_install.sh` does
(root B = image 1).  The disk is then read back: the table sector for sector against
the template, every slot's UUID, the menu in root A (`padselect` + the hook once),
the game in both roots, `curgrub` = a with root A's UUID in grub.cfg, a loader on the
EFI partition, mountable perms, an empty temp.

What the ISO carries and NEITHER installer reads: partimag's `parts`, `sda-pt.sf`,
`sda-gpt-*`, `dev-fs.list` - Clonezilla's record of a 4.6 GB golden disk.  The app's
old Restore-to-SSD path used them (a wrong table, one root, no UUIDs, no temp); it now
runs this command.

In the app: the Multi-boot tab's green button opens the stick dialog, whose "Onto:"
row offers the game's SSD in a dock as the second place (Windows and Linux).  The
disk is taken offline, handed to WSL whole (`wsl --mount --bare`: Administrator, the
Direct-SSD gate), installed by this command, verified, and handed back.  Nothing new in
the runtime image: the partition table is written from the template by the tool itself
(gdisk ends every write with the global sync() that hangs under WSL2), partclone,
e2fsprogs and util-linux do the rest.

Proof: the self-test installs the synthetic multi ISO onto a 120 GB sparse file on a
loop device and checks it (plus the in-use and too-small refusals); the rig proof of
2026-09-15 wrote the GNR multi-boot ISO onto a 120 GB sparse disk on D: the same way
and booted it under qemu with UEFI firmware (see plans/TODO.md item 123).

### Only the menu, or only one image (item 124)

Two partial writes onto a disk that ALREADY holds this ISO's install, both leaving the
settings partition (scores, settings, audits) and everything else alone. The disk is
checked first: the installer's seven slots on its GPT and every slot's filesystem UUID
the installer's, else refused (a full install writes it whole).

- `install --iso MULTI.iso --disk /dev/sdX --menu-only`: the ISO's menu into root A -
  the same staging `build` and `inject` do (`stage_into_root`, on the partition itself:
  selector, font, images.conf, media, build.json, the hook, rungame.sh hooked). For a
  new title, clip or conf, `inject` the ISO first, then this. Refused when root A on the
  disk is not the ISO's image 0 (build.json's game sha; `--allow-version-mismatch`
  overrides). Two minutes.
- `install --iso MULTI.iso --disk /dev/sdX --image N --from GAME.iso`: image N's root
  (0 = root A, the menu re-staged on top; 1 = root B) restored from GAME.iso's own
  sda3 pieces with the installer's tail (resize2fs, the slot's UUID), and root A's
  build.json updated to say where image N came from and what code it is. GAME.iso is
  the game's own install ISO (a multi-boot ISO is refused). THE SAME-VERSION GATE
  holds against the OTHER root on the disk: GAME.iso's Name/Version against
  build.json's record of the other image, then GAME.iso's root (restored into the
  rig's cache for its identity) against that root's GAMENAME, game and fl.dat shas -
  both roots share one settings partition. A new custom code in slot B is six minutes.

In the app, the disk target's "Write:" choice offers everything, only the boot menu,
or only image 0/1 (named by the tab's titles) with a From ISO box. Both partial
writes read the disk back with the same checks as a full install, plus: every staged
menu file in root A is the ISO's, root A's build.json records the replaced image, and
that slot's game binary is the new ISO's.

Proof: the self-test's legs on the loop disk (a "score" planted on perm A survives
the menu write, image 1 from fake0, and image 0 from fake1 with the menu re-staged;
a 03.04 image and a multi-boot ISO as `--from`, and a blank disk, are refused); the
rig proof of 2026-09-15 on the item 123 disk: a copy of the GNR multi ISO injected
with new titles, `--menu-only`, then `--image 1 --from` the LOTLJ ISO, then the VM
boot showing the new titles (plans/TODO.md item 124).

