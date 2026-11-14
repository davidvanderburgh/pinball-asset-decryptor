# Barrels of Fun emulator (PAD-257)

Run a Barrels of Fun title (Dune, Winchester Mystery House, Labyrinth) on a
PC, the way `tools/spike2_emu` runs a Stern Spike 2 game and `tools/jjp_emu`
runs a Jersey Jack one.

## Why this is the smallest emulator PAD has

A BoF `.fun` decrypts (GPG, per-title passphrase) to a tarball holding one
**native x86-64 Linux Godot 4 export** with its PCK embedded, plus the update
scripts (`updated_bash_profile`, `updated_updatecode`) and, on Dune, the worm
board's firmware (`worm_wrangler_main.bin`) and its flasher (`bossac`).

The binary needs only `libc` and `libm`, is **not stripped** (full symbols and
DWARF), carries no dongle, no licence check and no machine binding. Under WSL
it starts as is and draws through Vulkan (llvmpipe on a hidden Xvfb; the
host GPU through WSLg). With no hardware it stops at the game's own
"FAST HARDWARE NOT DETECTED" screen - that is the whole gap.

So there is no CPU to emulate, no GL/video bridge, no key. The work is the
hardware the game talks to over USB serial.

## The hardware, as the game's own scripts define it

The scripts are compiled GDScript (`.gdc`, Godot 4.5 bytecode) inside the PCK.
`pck_directory.read()` pulls them out; GDRE Tools (`--decompile`,
`--bytecode=4.5.0`) turns them back into readable source. Every protocol
reply in `bofhw.py` is shaped by the parser in these scripts, not by FAST's
documentation: the game's parser is the only reader that matters.

Engine side: a `SerialPort` Godot module wrapping the wjwwood `serial`
library. Its Linux port list globs `/dev/ttyACM*` (and ttyS/ttyUSB/...) and
reads each port's USB identity from sysfs:

| field | built from |
|---|---|
| `desc` | `<manufacturer> <product> <serial>` of the USB device |
| `hw_id` | `USB VID:PID=<idVendor>:<idProduct> SNR=<serial>` |

Game side (Dune, `autoloads/fast.gd` + `cooper/autoload_stems/fast_stem.gd`,
`autoloads/bics.gd`):

* **FAST Neuron, NET port** - first `/dev/ttyACM*` whose desc contains
  `FAST Pinball`, 921600 baud, `\r`-terminated ASCII.
  `ID:` -> `ID:NET <board>  <fw>` (the game reads `split(" ")[3]` and demands
  fw >= 2.26 or it starts flashing firmware), `CH:2000,01` -> `CH:P`,
  `CN:` -> one `NN:` line per node board (matched by substring against
  `0024-`, `3208-`, `1616-`, `3208-`; `split(" ")[5]` is the firmware),
  `SA:` -> `SA:<n>,<hex>` (switch n = bit n%8 of byte n/8, **physical** level:
  the game applies each switch's `reversed` flag itself), `SL:`/`DL:`/`TL:`
  switch config, driver config, driver action, `WD:` watchdog.
  Switch events: `-L:xx` active, `/L:xx` inactive (logical, no reversal).
* **FAST expansion bus** - the second FAST port. `ID@<board>:` for boards
  `48` (Neuron's own), `b4`, `84`, `86` -> `ID:EXP <name>  <fw>` (>= 0.44).
  Then `ER@`/`RF@`/`LM@` config and **binary** LED frames with no terminator:
  `RD@<board>:` + count + count x (index, r, g, b), `RL@` the same with a
  fade byte.
* **BICS** ("Barrels Interactive Control", Dune's worm wrangler) - the port
  whose hw_id contains `PID=2341:` (an Arduino), else `/dev/bof_worm`.
  `\r\n`-terminated replies. `ID:` -> `ID:WORM WRANGLER,..,<board>,v1.0.0`,
  then a homing handshake (`HOME:STEPPER ALL` -> `,ACK`, `HOME:EDGES?` ->
  `HOME:EDGES ACK`), magnet/flasher/profile `SET:`s, `MOVE:STEPPER`,
  `POSITION:STEPPER?` and `SET:OFFSETS?` (positions compare as STRINGS
  against the offsets, so named moves report the offset string exactly).
  Its four switches arrive with the prefixes REVERSED (`/L` = active) and map
  to game switches 49..52.

## How the emulator presents the ports

* `bofhw.py` makes one pty per port, links them as `<rig>/dev/ttyACM0..2`
  (+ `bof_worm`) and writes a fake sysfs tree under `<rig>/sys` with the USB
  identities above (FAST = 2e8a:1074 "FAST Pinball Neuron", BICS = 2341:003d
  "Arduino LLC Arduino Due").
* `bofhwshim.so` (LD_PRELOAD) rewrites only paths: `/dev/ttyACM*` to the rig
  dir (real ones are hidden), `/sys/class/tty/ttyACM*` to the fake sysfs, and
  `glob("/dev/ttyACM*")` lists the rig's ports under their `/dev` names. It
  also makes `TIOCMBIS`/`TIOCMBIC` succeed on a tty: a pty refuses them and
  wjwwood **throws** on that failure (`set_dtr`), which would abort the game.
* A control socket (`<rig>/ctl.sock`) sets switches: `sw <n> <0|1>`,
  `tap <n> [ms]`, `state`, `leds`.

## The host must be protected from the game

The game shells out through `OS.execute("sudo", ...)`: `mount -o remount,ro /`
and `remount,rw /` around every settings save, `sync`, `systemctl`, `iwctl`,
`bluetoothctl`, `dhcpcd`, `cp` over `/home/pinball/.bash_profile`. Run as
root in a WSL distro, the first of those remounts the distro read-only. The
rig therefore:

* runs the game as an ordinary user, never root;
* puts a logging no-op `sudo` (and `systemctl`, `iwctl`, ... `reboot`) first
  on `PATH` - seen in the first boot: 16 `sync`s, both remounts, two `cp`s;
* gives it its own `HOME`, so `user://` (settings, audits, high scores) lives
  in the rig dir.

## Per title (tools/bof_emu/profiles)

Everything that differs between titles is data, generated by
`gen_profile.py <decompiled tree> profiles/src/<title>.json profiles/<title>.json`
from the title's own `autoloads/switches.gd`, `coils.gd`, `game.gd` plus a
hand-written overrides file for the protocol facts:

| | Dune | Winchester | Labyrinth |
|---|---|---|---|
| binary | GDHarvest_202600513 (Godot 4.5.2, v3 PCK, encrypted dir) | GDHarvest_not_harvest_20260429 (4.5, v3, plaintext dir) | GDCraze_linux_20260130 (4.4.1, v2) |
| FAST driver | port = desc contains "FAST Pinball" | same as Dune | OLDER: every ttyACM except desc "Audio Controller" |
| Neuron fw | >= 2.26 (float) | >= 2.26 | == "02.25" (string!) |
| node boards | 0024, 3208 A/B, 1616 | 0024, 3208 A/B, 0804 | 0024, 0804, 3208, 1616 |
| expansion | 48, b4, 84, 86 (0.44) | 48, b4, 84 (0.48), 86 | 48, b4 + toppers ac, b5 (absent: never answer) |
| BICS | worm wrangler, v1.0.0 | "Barrel_of_Interactive_Control_Systems_" Haunt Handler, v0.6.1; switch 3 flips its prefix | none; a FAST audio board instead |
| balls | 6 | 6 | **5 in 6 trough slots** |

The ball count matters: `trough.is_full()` wants EXACTLY `num_balls_total`
active trough switches, so a Labyrinth trough reading 6 is "too many" and
Start is refused.

The decompile has to keep the res:// tree (GDRE `--decompile` with
`--output` per directory): flattened, same-named scripts overwrite each
other (Labyrinth's modes/attract.gd vs its lampshow attract.gd).

## The app

`webui/tabs/emulate_bof.py` + `static/js/tabs/emulate_bof.js`, gated by the
`emulate_bof` capability. Input: a `.fun` (the machine's, or one Write
built). Start runs `watch.sh` as root in PAD-Runtime (the app's own Linux:
gpg, Xvfb, Mesa, 90 GB free) - decrypt into a size+mtime keyed cache
(`prepare.sh`, two builds kept), boards, game in a window on the desktop.
The playfield switches are ON THE TAB (quick buttons, Plunge / Drain, coin
door, service buttons, every switch lit while active), sent down one
`ctl.sh --stream` pipe. Rendering: Godot's OpenGL compatibility renderer,
identical on these titles, and it needs no Vulkan in the runtime.

## Plugins and Visual Pinball (PAD-1305)

bofhw.py loads observer plugins (`--plugin`, `BOFHW_PLUGINS`, or any `.py`
in `$BOF_ROOT/plugins/`, which run_game.sh passes): each sees every switch
change, DL:/TL: line, LED frame (LM@ aliases expanded onto their members,
alias boards 840/860 filed under 84/86), BICS command and other bus line,
can set switches and turn PAD's ball model off. PAD's own `bofvpx.py` is
always loaded: the kit's PAD.Controller files (tools/spike2_emu/vpx/
bofbridge.py) with a rule plane, and a line stream on TCP
127.0.0.1:7470+slot for other links. The names a link reads (every LED,
servo, BICS magnet / coil / flasher) are in each profile, from the title's
own leds.gd / servos.gd / coils.gd (`gen_profile.py --names`).

## Proven (emulator-proven)

1. All three titles: no hardware -> the game's own "FAST HARDWARE NOT
   DETECTED"; emulated hardware -> full handshake -> **attract**; Start ->
   trough eject -> ball in the shooter lane -> **Ball 1**. Plunge/Drain move
   balls; after a drain the game re-serves the ball (no playfield switch was
   hit, so the ball never counted as played).
2. The repo rig in PAD-Runtime as the unprivileged `pad` user: Dune finds its
   boards in 9 s; the no-op sudo caught both `mount -o remount` calls;
   `stop.sh` leaves nothing running.
3. The game outlives the `wsl.exe` that launched it (it did not, at first:
   runuser passed the hang-up on - fixed with `setsid -f runuser`).
4. The tab against a live rig: Running, Neuron + 4 expansion + BICS, balls,
   LEDs, drivers; its own Start button began Ball 1
   (`scripts/shot_pad257.py`).

## Open / owed

* The visible window on the WSLg desktop and sound through WSLg's
  PulseAudio are wired but not yet watched: both disturb the desktop, so
  they wait for David to look.
* Ball physics beyond counting (the playfield switches are pressed by hand).
* LED/lamp display on the tab (the boards already record every LED colour:
  `ctl.sh leds`).
* The game's own debug keyboard map (InputMap `switch?XX` actions in
  project.binary) is not decoded; the tab's keys cover play instead.
