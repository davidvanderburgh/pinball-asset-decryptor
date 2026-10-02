# Spooky Pinball PC emulator rig (the Warden games, Halloween and Ultraman)

Runs Spooky's **Warden-era** games on this PC from their update files, the
way `tools/bof_emu` runs a Barrels of Fun game and `tools/ap_emu` an
American Pinball one, on an emulated **Warden** - Spooky's playfield
controller board - that answers the real protocol, so switches, coils, LEDs,
servos and the stepper behave. **Halloween** and **Ultraman** run the
same way on an emulated **Pinotaur**, the board before the Warden
(`spkpinotaur.py`, PAD-268, PAD-316; below).

| title | update | engine | status (2026-09-30) |
|---|---|---|---|
| Beetlejuice | `v2026.09.15.11.beetlejuice` (GPG-signed tar.gz) | Unity 2022.3 | attract, played (PAD-266) |
| Scooby-Doo | `v2025.12.01.09.scooby` (tar.gz) | Unity 2022.3 | attract, played (PAD-267) |
| Texas Chainsaw Massacre | `tcm-1_00.pkg` (tar.gz) | Unity 2019 | attract, played (PAD-267) |
| Evil Dead | `2026.07.15.ed` (tar.gz) | Unity 2022.3 | attract, played (PAD-267) |
| Looney Tunes | `2025.10.08.looney` (plain tar) | Godot 4.1 | attract, played (PAD-267) |
| Halloween | `code_H78.pkg` v1.18.1 (GPG-symmetric tar.gz) | Unity 2022.3 | attract, played (PAD-268) - Pinotaur board |
| Ultraman | `code_UM.pkg` v1.18 (GPG-symmetric tar.gz) | Unity 2022.3 | attract, played (PAD-316, 2026-10-02) - Pinotaur board |

"Played" = coins, Start, the ball served by the game's own trough-eject
coil into the shooter lane, launched by its own launch coil, switches hit
and scoring, all hidden on a private display. All seven were run from
`D:\Pinball\images\Spooky`. `bootcheck.sh` passes each; Spooky's restore
images are not needed.

Refused by `prepare.sh` with the reason (exit 4): Rick and Morty, Alice
Cooper and Total Nuclear Annihilation are P-ROC games: `proc/` runs the
first two on tools/proc_emu's board (PAD-269, its README).

**In the app** (PAD-266): Spooky Pinball has an **Emulate** tab
(`webui/tabs/emulate_spooky.py`) built on the American Pinball tab, the
template every maker's Emulate tab follows: the update file with
**Cache...**, Start / Cancel / Stop, **Switches window**, the live **Volume**
/ Mute, AP's status grid, a **Supported games** card. When the game reaches
attract, the **virtual playfield** opens: AP's window (`tools/ap_emu/appf.py`,
the Stern page) pointed at this rig by `spkpf.py`, fed `switches.json`
(`spkswitches.py`, apswitches.py's format, from the running title's
profile) - the same keys, service buttons, BALLS (Plunge, Drain, Reset
balls), Pause and VOL bar. Since PAD-316 the tab takes every title in the
table above, told apart by the update file's name
(`emulate_spooky_core.SUPPORTED`, held to `spktitles.TITLES` by a test).

**The board keeps up** (PAD-266, second pass): Beetlejuice gives each serial
write 20 ms and after ten late ones resets its board link and ignores
switches. The board reads 64 KB at a time, replies from a writer thread,
runs at real-time priority, and `spkshim.so` makes a write that would get
EAGAIN wait for room instead of failing.

## Why this is small

Every one of these is a native x86-64 Linux program (Unity with the Mono
backend, or Godot with its pack inside `main.x86_64`) with no licence,
hardware-ID or activation check, so the update alone runs on PAD-Runtime's
Ubuntu 24.04. The cabinets run sway or i3; the players are just as happy on
X, so the rig uses WSLg's desktop (or a hidden Xvfb) and OpenGL (Unity:
OpenGL core, `-force-glcore`; Godot: the compatibility renderer, because the
project asks for Vulkan), drawn on the Windows GPU by Mesa's d3d12 driver
where WSL offers one, else by llvmpipe on the CPU (below).

What each game needs around it is in `spktitles.py`, one profile per title
(switch names, trough, coils, layout, how attract shows), and
`run_game.sh` provides it:

| the machine | the rig |
|---|---|
| `/game` (settings, audits, high scores: each game keeps them in folders of its own choosing - `code/config`, `audits`, `game_settings`) | `$SPK_ROOT/nv<slot>/<title>/game`, kept between runs (`SPK_FRESH=1` starts over) |
| `/game/code/uptest/` (the game) | the cached build (Texas Chainsaw, Evil Dead: its `uptest/`), hard-linked into `$SPK_RIG/game`, bound there in a private mount namespace |
| `/game/code/assets/` (Texas Chainsaw, Evil Dead media) | the build's `assets/` |
| `/game/logs`, `/game/tmp`, `/game/media` (USB), `/game/backup`, `/game/update` | `$SPK_RIG/<name>`, per run |
| hostname `haunted-mansion...` | `pad-rig-<slot>` in its own UTS namespace (Beetlejuice's virtual mode) |
| the Warden board on USB (`/dev/WARDEN`, 115200) | `spkwarden.py` on a pty; `spkshim.so` maps `/dev/WARDEN` onto it and lists it among the serial ports (Looney) |
| `sudo`, `unlock-root`, `reboot`, `avrdude`, `timedatectl`, `swaymsg`, `wpctl`... | logging no-ops first on the game's `PATH` (`$SPK_RIG/shell.log`) |
| speaker / topper / light-kit boards (`/dev/spookynano`, `/dev/spookypico`) | none - every game carries on without them |
| Vosk speech sidecar (TCP 12346) | none - speech is off |
| the cabinet LCD | a hidden 1920x1080 Xvfb per slot (`:160 + slot`), or WSLg |

Per title:

* **Beetlejuice** has a built-in desktop mode: `Constants.IsVirtual` is true
  unless the hostname contains `haunted-mansion`, and then `Settings.Bash`
  skips every shell call not marked safe for a VM. A settings folder without
  `beetlejuice_factory_defaults.json` stops attract behind "FACTORY DEFAULT
  SETTINGS HAVE NOT BEEN SAVED"; the rig writes an empty one (= the build's
  own defaults).
* **Scooby-Doo** has no such mode. It picks its PC model from `uname -r`: an
  unknown kernel means "a developer's PC" and lightshows from
  `/home/dj/...`, so the game's `uname` says the GK3 cabinet's
  `6.1.0-21-amd64`. At boot it compares `~/.profile`, udev and sway configs
  with its own and reboots to install them; the rig seeds the profile and
  the rest are no-ops. It wants all 7 balls home.
* **Texas Chainsaw Massacre** keeps its orbit diverter down at rest (switch
  43 made); without that it ball-searches forever. 7 balls. Its archive
  carries no execute bits (`prepare.sh` sets them).
* **Evil Dead** has two shooter lanes fed through a servo diverter (servo 33:
  90 = left, 145 = right), a lower playfield that keeps its own ball on
  `lower_pf_drain`, GROOVY drop targets that read made while standing, and a
  stepper-driven hand that homes at boot. Its Start is "verified" by asking
  the board 40 ms later, so a press must outlast that round trip (sw.py
  presses for 500 ms).
* **Looney Tunes** (Godot 4.1) finds the board by listing serial ports - a
  glob of `/dev/ttyUSB*` and friends, which the shim answers with
  `/dev/WARDEN` - and pings it with hardware-info every 2 s. Godot 4.1 will
  not start without a `libXinerama`, which PAD-Runtime lacks: `lib/` has a
  stub (`xinerama_stub.c`) that says "no Xinerama", used only when the
  distro has none. A release build prints nothing, so attract is read off
  the board: its hardware start is the only thing that turns 48 V on.

## The board (spkwarden.py)

Warden's protocol, from the hosts' own code (Beetlejuice's and Scooby-Doo's
`Warden.cs`, Texas Chainsaw's and Evil Dead's `warden.cs`, Looney Tunes'
`warden.gd` - one firmware): the host sends `'>' <opcode> <args>`, a fixed
argument count per opcode (`ARGS`: coils, LEDs in every colour form, switch
config, servos, the stepper, flippers, auto-actions); the board sends
`'<' 1|0 <sw>` for a switch going active/inactive and answers requests. The
board reports *logical* states - the host tells the firmware which switches
are inverted (opto troughs).

The board frames every message by its count (a `>` inside arguments never
starts one; an unknown opcode is logged and skipped to the next `>`) and
keeps what it says:

* **Replies**: `get_switch_state` (152) the switch; `get_coil_config` (168)
  the configuration the host sent (143) - the Unity games' watchdog asks for
  coil 6, and a fresh board's zeros make them send the whole configuration
  again, as after a real board reset; hardware info (151) `WARDEN\0` - Evil
  Dead and Texas Chainsaw read exactly those 7 bytes; firmware info (150)
  `PAD rig Warden`; stepper state (212).
* **Coils**: pulses counted, holds (held until released, or timed by 191),
  PWM outputs (GI, flashers), configurations; 48 V and PWM enable; the
  start/launch button lamps (188).
* **LEDs**: 8-bit `RRGGGBBB`, 12-bit, 24-bit and palette colours, one or
  `n` at a time or all, solid / blink / breathe / chirp / rainbow /
  crossfade, and the overlay layer drawn over the base.
* **Servos** (angle per servo) and the **stepper** (home, move, enable,
  disable: it reports homing / moving until the move ends, then idle).

Behaviour, from the title's profile:

* the trough starts full; an eject coil moves a ball to the shooter lane
  (Evil Dead: the lane its diverter points at) half a second later; a launch
  coil empties its lane; `drain` puts a ball back.
* a flipper button the host configured (144) fires its coil and closes its
  end-of-stroke switch while held; a switch the host tied to a coil (146:
  slings, pops) fires it.
* `rest` switches are made at rest; a coil in `holds` opens its switch while
  held (Texas Chainsaw's diverter); a coil in `resets` makes its drop bank's
  switches again (Evil Dead).

Everything is logged to `$SPK_RIG/warden.log`; `state` reports it, `leds`
lists every lit LED.

## Halloween's board (spkpinotaur.py)

Halloween (`code_H78.pkg`, v1.18.1) is a Unity 2022.3 Mono game laid out
like Texas Chainsaw (`uptest/`, `assets/`, `config/` under `/game/code`),
encrypted with a GPG passphrase that `prepare.sh` reads from the app's own
Spooky plugin (`spktitles.py passphrase`). It is told apart from Ultraman
(same `VideoServer` product) by the update name its code carries.

**Ultraman** (`code_UM.pkg`, v1.18, PAD-316) is the same code base
(`H78UM`): its `SwitchConfig.cs`, `CoilConfig.cs` and `VirtualCoil.cs` wire
the trough, the cabinet, the drop bank and every coil the profile names
exactly as Halloween's do, so its profile is Halloween's with one
difference - the board's game-name row (8064) says `0 1`, Ultraman
(`firmware.cs` GameSetting; the game reads it but goes on whatever it says). It has no
licence check; its board is the **Pinotaur** (USB `cafe:4001`, udev's
`/dev/pinheck`, Mono's SerialPort with a 1 ms read timeout), which
`spkshim.so` maps onto the rig's pty as it does `/dev/WARDEN`.
`spkwarden.py` starts `spkpinotaur.Pinotaur` for it - a `Board` with the
Pinotaur's wire format, so the control socket, trough, flippers, logs
(`warden.log`) and every client (sw.py, the virtual playfield) are the
Warden's.

* **Wire**: the host sends `'<' <op> <0x81 + 2n> <n args>` - the third byte
  frames every message; the board answers `'>' <op> <payload>`. Boot asks
  the system name (it must say `Pinotaur`), firmware and API versions, the
  boot fault flag, the game-name row (8064: `0 0` = Halloween), and every
  switch twice (`88`); the replies for switch 95 are the board's "machine
  ready", two of the three the game waits for. Then switch changes are
  pushed as `'>' 89 <0x80|sw>` (active) / `<sw>` (inactive). The game reads
  one message per frame and reports RAW inputs (it inverts its reversed
  optos itself).
* **Kept**: coil pulses (23), patter, 48 V (96) and flippers (97) enable,
  flipper buttons (30) with their end-of-stroke switches (94),
  auto-actions (91: slings), GI strings, start/launch lamps, servos, LEDs
  (48-55) and the light shows' frames (62, drawn over the rest).
* **Attract** is read off the board: the first "coils enabled" is
  `machine_state_3`. Unity's own log is switched off on Linux and the
  game's text log (`/game/logs`) keeps exceptions only.
* **At rest** (the game's own `VirtualCoil.cs` / `InitialiseVirtualStates`):
  7 balls; the pumpkin drop bank's switches read made while standing (the
  game reverses them twice - without it the game fires the bank reset five
  times and flags a hardware issue); `sets` in the profile say what the
  bank reset, drop target knockdown/reset and mid-playfield scoop coils do
  to their switches. Its cabinet is wired differently from the Warden's
  (Launch 84, Tilt 85, coins 56/59, service 60-63; the profile's
  `aliases`), and the switch table and `sw.py` follow.
* **A first start**: a machine leaves the factory with
  `/game/highscores.config`. Without it the game writes one from its
  defaults and then dies syncing it through the board object it has not
  created yet (a black screen, nothing logged); the file it leaves has
  "null" vanity awards that kill every later start too. `run_game.sh` seeds
  it from the update's `config/default_highscores.config` (the profile's
  `seed`) and replaces a "null" one.
* Its update helper (`config/test`) and firmware reflash
  (`config/firmware_*.bin`, from the service menu) are not run.

## Use

The app runs `watch.sh <update>` as root (`PAD_VISIBLE=1` draws on the
desktop at 1280x720, `PAD_AUDIO=1` plays sound, `PAD_AUDIO_CTL=<the app's
audio_ctl.json>` makes the level follow its Volume / Mute live through
`spkvol.py` - AP's apvol.py, on the game's own libpulse since PAD-Runtime has
no pactl), polls `status.sh` (key=value, AP's keys) and stops with `stop.sh`;
`cache.sh --list | --drop` is the Cache window. The virtual playfield talks
to the board through `ctl.sh --stream`, one JSON reply per request - the
requests AP's game answers: `state`, `sw <n> <0|1>`, `tap <n> [ms]`,
`rip <n> <0|1>`, `plunge` (presses Launch: the game fires the ball in),
`drain`, `reset`, `pause <0|1>` (SIGSTOP/SIGCONT the game), plus `leds`.
Plunge presses Launch also with the lane empty - Scooby-Doo's character
select and Evil Dead's movie select are confirmed with it - and on a Warden
game never lets the ball go by itself (PAD-321, below). A
press is held at least 120 ms: the games believe a Start / menu edge only
after asking the board again. By hand, all in PAD-Runtime as root;
`PAD_SLOT=N` picks a slot (default 0) - take a riglock slot first:

```
T=/mnt/c/.../tools/spooky_emu
bash $T/build.sh                                  # once, if spkshim.so is missing
PAD_VISIBLE=0 bash $T/watch.sh /mnt/d/Pinball/images/Spooky/v2025.12.01.09.scooby
python3 $T/sw.py coin; python3 $T/sw.py start     # sw.py --list, sw.py --state
python3 $T/sw.py plunge                           # the Launch button
python3 $T/sw.py "left sling"; python3 $T/sw.py drain
bash $T/shot.sh /mnt/c/tmp/scooby.png
bash $T/status.sh
bash $T/stop.sh
bash $T/bootcheck.sh scooby_v2025.12.01.09        # VERDICT <build> pass|fail ...
```

`prepare.sh` and `run_game.sh` are the two halves of `watch.sh`; a build is
named `<title>_<version.txt>` (`bj_`, `scooby_`, `tcm_`, `ed_`, `looney_`,
`h78_v118` - Halloween's version is its `uptest/version_118.txt` name).
The game's log is `$SPK_RIG/player.log` (Unity's log, or Godot's stdout),
the board's `$SPK_RIG/warden.log`, the no-op'd shell calls
`$SPK_RIG/shell.log`, the volume keeper's `$SPK_RIG/spkvol.log`.

## What is open

* **The P-ROC games are not in the app.** Rick and Morty and Alice Cooper
  run by hand on `proc/`; the Emulate Spooky tab does not offer them yet.
* **Halloween's plunger**: sw.py `plunge` presses its Launch button (84);
  the game fires its launch coil for ball saves and multiballs, and
  otherwise the rig lets the ball go after 1.5 s as a manual shooter would
  (`manual_plunger` in the profile; Ultraman the same). The Warden games
  have no shooter rod, so there the ball waits for the game's launch coil:
  the rig used to let it go after 1.5 s on every title, and Evil Dead,
  whose first Launch after Start picks the movie, then had a ball it never
  launched - after its drain it served no other (PAD-321).
  Its subway, scoops, crossover and lock mechanisms are switches you press
  yourself.
* **It draws on the GPU.** Mesa's d3d12 driver renders the games' OpenGL
  on the Windows GPU (WSL's /dev/dxg + libd3d12), on the desktop and on a
  hidden Xvfb alike (`run_game.sh` picks it whenever WSL offers it). Beetlejuice's
  attract measured 52-65 fps hidden at 1920x1080 and 66-80 fps in the
  1280x720 desktop window, ~170% CPU (2026-09-30, an AMD Radeon iGPU);
  Mesa's llvmpipe (the old default, and the fallback where WSL has no GPU;
  `SPK_GL=llvmpipe` forces it) managed 5.5-7.8 fps on ~500% CPU. All seven
  on d3d12, hidden at 1920x1080 (PAD-321, 2026-10-02): Beetlejuice 55-60
  fps in play, Scooby-Doo 105-120, Looney Tunes 240+ (127% CPU); Texas
  Chainsaw, Evil Dead, Halloween and Ultraman hold themselves at 30 fps
  (their own frame cap: 13-25% of one core). `status.sh` reports `gl=` and
  `fps=` (Mesa's HUD, sampled once a second into `$SPK_RIG/hud/fps`, drawn
  nowhere). ~3 GB of memory; on llvmpipe `LP_NUM_THREADS` is capped at 4
  (`SPK_LP_THREADS`).
* No physics beyond the trough, the shooter lanes and the mechanisms above:
  scoops, VUKs, locks and ramps are switches you press yourself (the game
  fires their coils into nothing). Evil Dead's lower-playfield launcher and
  cabin, Texas Chainsaw's hook locks and grinder, Looney Tunes' Taz toy are
  not modelled.
* One build of each title was run. Looney Tunes' 2025.03.01 stable build and
  Beetlejuice's v2026.06.11.13 were not.
* Sound: all seven play through PulseAudio and follow the app's Volume /
  Mute (PAD-321: each stream moved to a null sink with PAD-Runtime's
  speakers muted; 30% gives 0.3x the level, Mute silence). Rig runs stay
  muted.
* **The window** on the desktop moves by its title bar and resizes from its
  edges, and the game scales its picture to the size (PAD-321, a mouse
  drag on Beetlejuice). The Unity titles' hints say min size = max size (a
  cabinet build), but WSLg's window manager does not hold a window to
  them; a window manager that did would need them cleared.
* No lights in the virtual playfield: the board decodes every LED write
  (`leds`), but the Spooky games ship no map from LED numbers to insert
  positions, so the window's light grid stays empty.
* The game's own window keeps its built-in keys (Beetlejuice: Enter, Space,
  arrows); the playfield window's keys are AP's and work there only.
