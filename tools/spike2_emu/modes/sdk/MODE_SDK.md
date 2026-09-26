# Writing a game mode for a Stern Spike 2 machine

This folder is everything needed to write a game mode of your own in C and put it in
a Stern Spike 2 pinball game. A mode written here runs INSIDE the game and uses the
game's own scoring, sound, lights and display, so it plays like a mode the game shipped with.

If you are an AI agent asked to write a mode: read this file top to bottom, then
`pad_mode.h`, then `template_mode.c`. Copy the template, change it, build it and test it
with the loop below. Everything you need is in these files.

| File | What it is |
|---|---|
| `pad_mode.h` | The API. Every call a mode can make, documented. |
| `template_mode.c` | A complete mode (TARGET RUSH) that uses nearly every call. Start here. |
| `examples/powerline_blitz.c` | A second mode: each target pays once, completing ends it, a shield ends it early, and a test trigger feeds shots by name. An AI agent given only this folder wrote it, and it ran correctly in the emulator the first time. |
| `examples/README.md` | Five INTRICATE modes and their rules sheets (item 152): a boss battle with health, a hurry-up, a combo chain started by the skill shot event, a multi-phase wizard mode, and an ally that stacks with the game's own battle. They share `examples/intricate_kit.h` (a shot debounce, screen lines, lights, countdown, a pack ledger). `examples/desk_harness.c` plays any mode at the desk against a fake game. Each has its own clip, picture, music and calls cut from the films (`examples/film_recipes.json`). |
| `pad_mode_assets.h` | A code mode's OWN clip, screen, music and calls, as the build carried them (see "A code mode's own clip, screen, music and calls"). |
| `mode_file.c` | The mode that runs the Modes tab's mode files. It is an ordinary mode on this API. |
| `MODE_PARAMETERS.md` | Every key a mode file takes, every field the Modes tab saves, every call above, and what is measured about each. |
| `pad_mode_runtime.c` | The runtime, compiled into every mode. You do not edit it. |
| `ports/<game>-<version>.port` | One per game build: where the game's functions are, plus its shot names, scenes and callouts. |
| `build_mode.sh` | Compiles your modes and the runtime into one `mode.so`. |
| `port_words.py` | Fills in, or checks, a port's instruction words from the game's program. |
| `port_tool.py` | Drafts a port for another game or version from one that works. |
| `census_mode.c`, `shot_census.py` | Measure which shot each switch makes, and turn that into a port's `shot` lines. |
| `lamp_map.py`, `lamp_probe.c` | Read a game's playfield inserts into a port's `lamp` lines; hold and read inserts by hand in the emulator ("Lights: named inserts"). |

## The mode maker is a preview feature (in the app)

In the app the mode maker ships DARK: the Modes tab, its Examples and film cutter, Try it,
the Write tab's "Pending (Modes)" rows, a Write carrying a project's modes and code modes,
and the game's own modes' numbers (item 145) reaching a card all ride on one preview
switch, and it is off in every copy until a personal code turns it on (Settings, the gear,
> Preview features: paste the code, Unlock). A code names the person, the features and the
last day it works, and is signed with David's Ed25519 key (`tools/preview_code.py issue
--name "..." --days 90`; the app checks it in pure Python, `pinball_decryptor/core/preview.py`,
once at start-up). With the switch off, a Write of a project that holds modes builds
everything else exactly as a build without the mode editor does, leaves the modes and the
game's own modes' numbers off the card, and says so in one log line. What ships to everyone
is the emulator side: a card's own modes run in the Emulate tab either way. Nothing in this
folder needs the switch: a mode built here with `build_mode.sh` and tried with the loop below
runs in the emulator as it always did.

## What a mode is

A mode is a `struct pm_mode` with up to four callbacks. You register it with
`PM_REGISTER`:

```c
static const struct pm_mode my_mode = {
    .name = "RAMP FRENZY",
    .init = on_init,          /* once, on the game's first tick */
    .tick = on_tick,          /* 60 times a second */
    .shot = on_shot,          /* every shot the game dispatches */
    .ball_end = on_ball_end,  /* the ball drained */
};
PM_REGISTER(my_mode);
```

Several modes can go on one card, and they all build into one `mode.so`. One of them
runs at a time.

## The loop

```bash
# 1. build (needs arm-linux-gnueabihf-gcc; the app's PAD-Runtime WSL distro has it)
bash build_mode.sh -o mode.so my_mode.c

# 2. try it in the emulator. The emulator lives in tools/spike2_emu (one folder up from
#    this one); its README says how to set it up, and the rig is shared, so take its lock
#    first (tools/spike2_emu/README.md). The game's root filesystem is ~/spike2root on the
#    host: the game's /lib is ~/spike2root/lib, and its /dump is ~/spike2root/dump.
cp mode.so ~/spike2root/lib/my_mode.so
cp ports/godzilla_pro-1.15.port ~/spike2root/dump/game.port
cd ..    # tools/spike2_emu
PAD_AUDIO=0 PAD_MODE_SO=/lib/my_mode.so bash watch.sh 4 &
python3 plunge.py coin; python3 plunge.py game      # start a game
python3 swpoke.py 48 150                            # press a switch for 150 ms (48 = Maser Target)
echo 1 > ~/spike2root/dump/my_mode.start           # a test trigger your mode checks (below)

# 3. read what happened, then stop the game
cat ~/spike2root/dump/mode.log
bash killgame.sh
```

`build_mode.sh` refuses a misspelt `pm_` call, and a libc call a mode must not make (rule 2).
The C compiler catches most other mistakes, because every call is declared in `pad_mode.h`.

**Which switch makes which shot** (to test with `swpoke.py`) is measured per game. On
Godzilla Pro 1.15, one 150 ms press each:

| Switch | Shot |
|---|---|
| 73 | Left ramp |
| 81 | Right ramp |
| 77 | Building |
| 76 | Godzilla target |
| 48 | Maser target |
| 78 / 79 / 80 | Powerline left / center / right |
| 85 / 86 | Shield target left / right |
| 46 | Skill shot |
| 74 (exit), 82 (enter) | Big loop |

**Test triggers.** Name them after your mode, e.g. `pm_trigger("my_mode.start")`. It
returns 1 once when `/dump/my_mode.start` appears, and it deletes the file. Check triggers
twice a second, not every tick. A trigger that feeds a shot NAME to your own shot handler
(`pm_trigger_text("my_mode.shot", buf, cap)`, then `on_shot(pm_shot(buf))`) lets you test
shots no switch table covers.

On a machine, `mode.so` goes in `/usr/local/padmode/` on the card's root filesystem,
with the game's port as `/usr/local/padmode/game.port`. The app's Write step does this;
it is not something you copy by hand.

## The pinned object

A mode made in the tab's form needs no compiler. It is a mode FILE, and what reads
mode files is one object, the runtime plus `mode_file.c`. It is built once and committed as
`prebuilt/mode.so`; the app copies it into the emulator (Try it) and onto a card (Write).
`prebuilt/SOURCES.sha256` records the hashes of the files it was built from (`pad_mode.h`,
`pad_mode_runtime.c`, `mode_file.c`, `build_mode.sh`, CRs stripped first), the object's own
hash, and the compiler. The app finds both through
`pinball_decryptor/plugins/stern/mode_runtime.py` (`prebuilt_object()`,
`port_file(game_dir, version)`).

**After changing any of those four files, rebuild it** and commit both outputs:

```bash
wsl.exe -d PAD-Runtime -e bash tools/spike2_emu/modes/sdk/build_prebuilt.sh
```

`tests/test_stern_mode_runtime.py` fails, naming the builder, while the object is stale. The
build is reproducible: the same sources and compiler give the same bytes from any checkout.
A mode written in C (a code mode) is still built with `build_mode.sh`; to keep the tab's
mode files working beside it, build them into one object:
`build_mode.sh -o mode.so my_mode.c mode_file.c`.

The tab's **Try it** does the loop above for you: it builds the modes into an override set
with Write's own code (the card's own scenes, a mode's own sounds, the patched game
program), puts the object in the guest as
`/lib/pad_mode.so` with the port and mode files in `/dump` (`../tryit.sh`), and starts the
card in the Emulate tab. **New code mode…** copies `template_mode.c` into the project as
`modes/<name>/<name>.c`, and Try it builds every such file in with `mode_file.c`. A project
of code modes only needs no set: Try it compiles them, puts in the port of the card being
booted, and starts it. **Start mode now** and **End mode** reach only what the last Try it
put in the game that is up: a mode added or opened since is refused until the next Try it.
End mode also ends the code modes Try it built in, through each one's own
`/dump/<name>.stop` (a code mode never reads `mode.stop`). Try it runs on Windows and Linux;
on a Mac the emulator's container cannot see the modes yet, and the tab says so. Write on a
Mac leaves a project's modes out for now (the tools that put their files on the card run
only on Windows and Linux), and says so in the Write scan and when it is done.
Write carries a project's code modes too: it compiles them with `mode_file.c` into the card's
`mode.so` (the same compiler Try it uses) and carries each one's own clip, screen, music and
calls (see "A code mode's own clip, screen, music and calls").

## A card's own modes run in the emulator

On a machine, a card that carries modes loads them itself: the hook in its
`/etc/init.d/game_monitor` preloads `/usr/local/padmode/mode.so`, and the object reads
`game.port` and `mode.cfg`, `mode1.cfg`, `mode2.cfg` ... beside it (`../../mode_install.py` lays
them out on the card's rootfs partition). The emulator never runs a card's boot chain, it
starts `./game` directly. So `run_game.sh` asks the card before every boot (`../cardmodes.sh`):
it pulls `/usr/local/padmode` out of the card's rootfs with `parts.py --rootfs-dir` (debugfs,
no mount, no root, about 0.15 s on a stock card), puts the card's own object, port and mode
files in the guest through `../tryit.sh install`, and preloads the object. Emulating a card
then means what booting it means: pick the card in the Emulate tab and press Start, with no
project open and nothing ticked. The log says what was found:

```
[modes] this card carries 7 mode(s) of its own (ATOMIC BREATH, DESTOROYAH, ...): their runtime runs in this game, as on the machine
```

- **A runtime the launch brings wins.** When `PAD_MODE_SO` is already set (the Emulate tab's
  "apply my edits" set with modes in it, the Modes tab's Try it, a run scripted by hand), that
  runtime and its files run, nothing in the guest is touched, and one `[modes]` line says the
  card's own modes are left out.
- **`PAD_CARD_MODES=0` opts out.** The card is not asked at all.
- A card without `/usr/local/padmode` is the run it always was: no line, no file, no variable.
  What an earlier card's install left in the guest is taken out by the next run that installs
  nothing (a marker, `/dump/cardmodes.from`, says which files those are; `tryit.sh install`
  removes it with the files it replaces).
- A card whose `game_monitor` does not load the object is left as a machine leaves it, with a
  line saying so. A card that cannot be read, or a guest the account cannot write to, is a
  line in the log and an ordinary boot, never a refused run.
- A multi-boot card has ONE rootfs, the primary image's (`mkmulticard.py` carries only the
  games partitions of the other images), and the machine's hook preloads the same object
  whichever image the menu boots. The same files go in here; the runtime checks its port
  against the game it finds itself in and stays out of the way when they differ. This case is
  reasoned from the card layout, not yet run.

## The rules (break one and the game can crash or hang)

1. **Never block.** Every callback runs on one of the game's own threads, so return
   quickly. There is no sleeping and no waiting: count ticks instead (60 a second).
2. **No allocation, threads, sleeping, stdio or processes.** The object is built
   `-nostdlib`: use static variables, small stack buffers, `pm_snprintf`, `pm_commas`,
   `pm_read_file` and `pm_log`. `build_mode.sh` refuses `malloc`, `new`, `pthread_*`,
   `sleep`, `printf`, `fopen`, `system` and the like. Plain string and memory functions
   (`strlen`, `memcpy`) are fine: gcc emits some on its own, and they resolve from the
   game's libc.
3. **One mode at a time.** Call `pm_begin()` before starting. If it returns 0, another mode
   is running, so do not start. Call `pm_end()` when you stop.
4. **A 0 or NULL return means "not here".** Either this game's port lacks that capability
   (`pm_can(...)`), or the shot, scene, node or clip you asked for does not exist on this
   game. Log it and carry on without it.
5. **Test shot BITS.** A playfield switch often dispatches twice: first `0x1` ("a switch
   was hit"), then its own shot bit. Use `shot & pm_shot("Left ramp")`; never `==`.
6. **Find and hide your screen.** A screen the build adds is visible by default, and only
   your mode hides it. The scene it lives in can load after `init`, so try `pm_node` from
   your tick every half second until it returns the node, and hide it then.
7. **The game can move on under you.** Check `pm_in_game()` and `pm_player()` each tick,
   and end cleanly when either changes.
8. **Touch the game only from your callbacks.** Never from a C constructor of your own:
   at load time the game's `main()` has not run, and a call into it crashes the game at boot.

## Doing things

| To... | Call | Notes |
|---|---|---|
| know if a game is on, and whose turn | `pm_in_game()`, `pm_player()` | player is 1-4 |
| read a score | `pm_score(p)` | |
| add points | `pm_score_add(p, points)` | through the game's scoring; returns what was added |
| react to a shot | `.shot = fn(uint64_t shot)` and `pm_shot("name")` | port names are per game |
| list the game's shots | `pm_shot_count()`, `pm_shot_at(i, &mask)` | |
| time things | count `.tick` calls | 60 a second |
| speak | `pm_callout(pm_callout_id("ten_seconds"))` | roles: `countdown`, `ten_seconds`, `time_up` |
| count down | `pm_callout_nth(pm_callout_id("countdown"), n)` | n = seconds left - 1 |
| light the playfield | `pm_lights("blele ...")` | the game's light language; see "Lights" below |
| light YOUR inserts, over the game's | `pm_lamp_shot(shots, PM_RGB(r,g,b), PM_LAMP_BLINK, 0)`, `pm_lamp_set("MASER", ...)`, `pm_lamp_release_all()` | the game's own insert names; see "Lights: named inserts" |
| show your screen | `pm_node("hud", name)`, `pm_show(node, 1)` | see "Screens" below |
| write on your screen | `pm_text("hud", "Screen.Screen_Words")`, `pm_set_text` | |
| play a clip full screen | `pm_clip("name")` | a stock clip or one the build added; the runtime draws it until it ends |
| test from the emulator | `pm_trigger("my_mode.start")`, `pm_trigger_text(name, buf, cap)` | once when `/dump/<name>` appears; the file is deleted |
| read a file | `pm_read_file(path, buf, cap)` | whole file, up to `cap` bytes |
| log | `pm_log("...")` | goes to `/dump/mode.log`, prefixed with your mode's name |
| wait for the game's own battle or multiball | `pm_stock_mode_running(PM_STOCK_BATTLE \| PM_STOCK_MULTIBALL)` | the kind found (`pm_stock_mode_what` names it), 0 none, -1 this port cannot tell; see "The game's own modes" |
| react to what the game does | `.event = fn(unsigned id)` and `pm_event("ball_start")` | see "Events" below |
| keep the game's lesser displays off your clip and screen | `pm_display_priority(180)` (mode file: `priority 180`) | see "Display priority" at the end |

### Screens

A screen is a picture with a line of words under it. It is added to the game's `hud` scene
by the build, not by your code: the Modes tab adds one for each mode that wants it. For a
mode whose folder in the card project is `modes/<folder>/`, the build names them:

- the screen node: `PadMode_<folder>_Screen`
- its words: `PadMode_<folder>_Screen.PadMode_<folder>_Screen_Words`

For example, `modes/powerline_blitz/` gets `PadMode_powerline_blitz_Screen`. A mode must
work without its screen, because `pm_node` returns 0 when the build added none.

### Lights

`pm_lights` runs one command in the game's own light language, the same commands the
game's shows use. It returns 1 only when the command ran under a live show; without one
the game accepts the command and lights nothing. What is known:

- `blele --sweep 0 --lts <set> --red R --green G --blue B --freq 10 --use_alpha 1 --alpha 255`
  starts a colour sweep over light set `<set>`. The port's `light_lts` is the set its
  examples use (224 on Godzilla; which lamps that set covers is not decoded). Light sets
  and the owner a command runs as are each title's own, so a port without them (Jaws LE
  today) has no lights: `pm_can(PM_CAN_LIGHTS)` is 0 there. It keeps
  running until you send the off command.
- `blele --sweep 1 --lts <set> --fade 20 --rgb 0 --freq 10 --delay_start 15 --end 1` fades it
  out and ends it.

Copy a port's `example_lights_on` / `example_lights_off` and change the colour. The rest of
the language is the game's own and is not documented here yet.

### Lights: named inserts (item mode-leds)

`pm_lights` recolours one of the game's light shows. To say "THIS shot is lit for my mode", a
mode holds the playfield's inserts themselves, by the game's own names, in a colour and a
pattern, while everything it does not hold keeps doing what the game wants:

```c
static void start(void)
{
    pm_lamp_shot(pm_shot("Left ramp") | pm_shot("Right ramp"), PM_RGB(255, 96, 0), PM_LAMP_BLINK, 0);
    pm_lamp_set("MASER", PM_RGB(255, 255, 255), PM_LAMP_PULSE, 0);
    pm_lamp_set("HEAT RAY L1,HEAT RAY L2,HEAT RAY L3,HEAT RAY", PM_RGB(255, 200, 0), PM_LAMP_CHASE, 150);
}
static void shot(uint64_t s)
{
    if (s & pm_shot("Left ramp")) pm_lamp_release_shot(pm_shot("Left ramp"));   /* made: back to the game */
}
static void stop(void) { pm_lamp_release_all(); pm_end(); }
```

| To... | Call |
|---|---|
| hold one insert, or a list (`"TANK 2,ADV TRAIN"`) | `pm_lamp_set(names, PM_RGB(r, g, b), pattern, period_ms)` |
| hold every insert of some shots | `pm_lamp_shot(shots, rgb, pattern, period_ms)` |
| hand them back to the game, at once | `pm_lamp_release(names)`, `pm_lamp_release_shot(shots)`, `pm_lamp_release_all()` |
| sit under the game's shows instead of over them | `pm_lamp_priority(p)` (1-255; 255 when never called) |
| list the inserts | `pm_lamp_count()`, `pm_lamp_at(i, &shots)`, `pm_lamp_find(name)` |
| see the game's layers | `pm_lamp_layers(priorities, max)` |

Patterns: `PM_LAMP_SOLID`; `PM_LAMP_BLINK` (on half the period, off half; 500 ms); `PM_LAMP_PULSE`
(breathes between dim and full, never dark; 1600 ms); `PM_LAMP_CHASE` (one insert of the list
lit at a time, in the order given, stepping every period; 150 ms). A period of 0 takes the
pattern's own. A single-colour insert (`MASER`, `POWERLINE LEFT`) is lit at the colour's
brightest part; an RGB one shows the colour. Names are the game's, any case. A mode that holds
an insert another of ours holds takes it (`[pad] lamps: X takes LEFT RAMP from Y`); a mode
releases only what it holds; every held insert is handed back when the game leaves play.
`pm_can(PM_CAN_LAMPS)` is 0, and every call does nothing, on a port without `lamp` lines.

**How the game layers its lights, and the rule.** Read off Premium 1.16 and Pro 1.15 and
watched live: the game lights through LAYERS (lamp groups). Each layer has a priority, the
show that owns it (its event), and one slot per LIGHT (one colour channel of one LED). Every
frame the compositor gives each light the game's base value, then walks the layers from the
lowest priority to the highest, and each slot a layer HOLDS (its byte +3 set) overwrites the
light's level (+2) and fade time (+8); a slot not held lets the layers below show. The output
stage then sends each light whose level changed to its node board. The game's own shows sit at
priorities 1 to 145 in the runs measured (attract `1 1 128`, plain play `3 3 3 3 4 x14 5 x4
128 145`, more 144/145 layers coming and going with its effects). So:

- A mode's inserts sit in a layer of the runtime's, at priority **255 by default**: above every
  show the game ran, so while the mode holds an insert, the insert shows the mode's colour and
  pattern whatever the game's own mode, battle or multiball does with it, and every insert it
  does not hold is untouched. The layer is created with NO show attached, so no show of the
  game's ending ever frees it; the runtime checks twice a second that it is still in the game's
  list and makes a new one if not.
- **A lower priority lets the game win where it lights.** `pm_lamp_priority(p)` (a mode file:
  `light_priority p`) puts the mode's inserts in a layer at `p`: a game show at a HIGHER priority
  covers them while it lights them, a lower one does not. Two of our layers at one priority are
  one layer. The runtime rides the game's own mechanism: nothing of the game's is hooked or
  rewritten, and the game's shows run as they always do underneath.
- **Release hands the insert back at once:** the slot stops holding, and on the next frame the
  light is whatever the layers below say.
- A held light carries the game's own fade time (`value lamp_fade`, 3 on Godzilla: what its own
  in-play inserts carry, read live), so a held insert changes the way the game's own do.

**The map: every insert, by the game's own name.** A port's `lamp` lines (below) are read off
the game program by `lamp_map.py`, from four of the game's own tables: the LIGHT records (one per
colour channel; each names its DEVICE), the device table (the name, the picture it is drawn on,
its I/O board and channel, its x/y), the LAMP table (the fixtures, `blele --lt` ids: which lights
make one RGB insert), and the SHOT table (one `cshot` object per shot bit, whose +0x10 is the lamp
the game lights for that shot; built by a static initialiser, so it is read by running that
function in unicorn). Premium 1.16 has 592 lights, 267 lamps and **88 inserts on the playfield
picture** (Pro 1.15: 585, 260, 86); 24 lines carry a shot. The inserts of the shots:

| Shot | Its insert(s) | | Shot | Its insert(s) |
|---|---|---|---|---|
| Left ramp | LEFT RAMP (RGB) | | Shield target left / center / right | SHIELD LEFT / CENTER / RIGHT (RGB) |
| Right ramp | RIGHT RAMP (RGB) | | Skill shot | SKILL SHOT |
| Building | BUILDING (RGB) | | Big loop | BIG LOOP (RGB) |
| Maser target | MASER | | Godzilla target | MAGNA GRAB |
| Powerline left / center / right | POWERLINE LEFT / CENTER / RIGHT | | Pop bumper | POP BUMPER (RGB) |
| Left / right return lane | LEFT / RIGHT RETURN LANE | | the outlanes (0x8, 0x20) | LEFT / RIGHT OUTLANE |
| the left spinner (0x800000000) | LEFT SPINNER (RGB) | | the top spinner (0x800, 0x1000) | TOP SPINNER (RGB) |
| 0x2000000000 | SELECT CITY | | 0x4000000000 | MECHA LANE (RGB) |

The rest are named but tied to no shot by the game: the feature inserts in front of each ramp
(TANK 2, ADV TRAIN, MAGNA GRAB, TANK 3, ATTACK BRIDGE before the left ramp; TANK 5, HEAT RAY L1-L3,
HEAT RAY before the right; LITE DESTRUCTION JACKPOT, TANK 4, TESLA STRIKE, BUILDING FIRE LEFT/RIGHT
1-3 at the building; DESTRUCTION JACKPOT, TAIL WHIP inside the big loop), the scoop's SCOOP BB-BATTLE
/ -GODZILLA PWR UP / -SUMMON ALLY (the scoop dispatches only 0x1), the saucers and allies (TOP /
BOTTOM SAUCER, SAUCER, MOTHRA, RODAN, ANGUIRUS, ATTACK MECHA, TANK 6), the cities and wizard modes
(NY, LONDON, PARIS, TOKYO, PLANET X, KAIJU, BRIDGE, POWER, TANKS, the three WIZ), the fighters, lanes
and SHOOT AGAIN, and the GI strings and flashers (their lines carry one light each). The
port's lines say where each is (`# lamp N, I/O group G index I, at x,y` on the playfield picture).
On Pro 1.15 the game ties the shield bit its port calls "Shield target right" (0x100000000) to the
insert named SHIELD CENTER: that is the game's own table.

**Mode files** carry four keys (MODE_PARAMETERS.md has every detail):

    light          <shots> <colour> [pattern] [ms]      the inserts of these shot bits, while it runs
    light_insert   <colour> <pattern> <ms> <name>[,<name>...]
    light_shots    <colour> [pattern] [ms]              every shot that scores in this mode (automatic)
    light_priority <1-255>

`colour` is `rrggbb` or red, green, blue, yellow, orange, purple, cyan, white, pink. The inserts are
held from the mode's START and handed back at its END, whatever ends it. An older `mode.so` logs
each line as an unknown key and lights nothing.

**The port lines:**

```
data lamp_layers            0x007d408c   # the lamp group lists: free head, then the active head
data light_count            0x007d38f0   # how many lights the game counts (0 until its main() runs)
value lamp_slot_size        40
value lamp_slot_level       2
value lamp_slot_alpha       3            # non-zero = the layer holds this light
value lamp_slot_fade        8
value lamp_slot_used        36
value lamp_group_prio       4
value lamp_group_next       20
value lamp_fade             3
lamp 346,347,348  0x100000  LEFT RAMP     # lamp <R,G,B light ids | one id> <shot mask> <name>
lamp 298          0x8000000 MASER
lamp 365,366,0    0         BUILDING FIRE LEFT 1    # a 0: the fixture has no such colour
```

`lamp_group` (the game's group allocator) is the site `pm_lights` already needs. The lines go at
the END of a port, after the display-priority lines: a runtime before this one read only a port's
first 16 KB and skips a `lamp` line, so an older `mode.so` given a new port simply has no lamps
("How much a port holds", under Ports). `port_tool.py` carries `lamp`
lines to another build of the same title BY NAME, re-read from the target program with
`lamp_map.py` (the light ids move), and leaves them out for another title.

**What is proven (emulator-proven on Godzilla Premium 1.16, item mode-leds RUN 5: a copy of the stock
card launched as the Emulate tab launches it, muted, `mode_file.c` + `lamp_probe.c` built from this
branch).** The observable is the node bus itself: every frame the game sent to the insert boards
(nodes 8 and 9) under `PAD_NB_TRACE=1`, decoded with the repo's twin of the boards' grammar
(`leddecode.wide_decode`), each channel's last level kept, against the probe's commands on the same
millisecond clock:

| When | The held inserts' channels | The rest of nodes 8 and 9 |
|---|---|---|
| attract, `LEFT RAMP` red | R 255, G 0, B 0 for 100% of the 5.3 s | 91 other channels kept changing (the attract show) |
| attract, released | LEFT RAMP back in the attract show (0..255, 18 changes) | 109 moving |
| play, `LEFT RAMP` blue | R 0, G 0, B 255, 100% (the game had it white) | the game's powerline blink went on (24 changes) |
| play, `MASER` white blink 500 | 0/255, 17 changes in 4.3 s, 51/48% | |
| play, `BUILDING` blue pulse 1600 | B 40..245 smoothly, R and G 0 | |
| play, `HEAT RAY L1,L2,L3,HEAT RAY` chase 200 | each lit about a quarter of the time, in turn | |
| play, `release LEFT RAMP` | white again (the game's in-play layer holds it at 255,255,255) | |
| a mode FILE (`light_shots orange blink`, `light_insert cyan pulse TOP SPINNER,BIG LOOP`, `light 0x70000000 purple chase`) | the ramps orange (R 255, G 96), BIG LOOP G/B pulsing 40..255, the powerlines in turn; handed back at its END | |
| a BATTLE (the stock query said so): `LEFT RAMP` red, `RIGHT RAMP` green, `MASER,BIG LOOP` blue blink | exactly those channels; MASER 0/255, 29 changes in 7.3 s | 11 other channels kept changing (the battle's show) |
| the same, `prio 1` | MASER went to the game's steady 255: the game's own layer at priority 3 holds it and now covers ours. The ramps and BIG LOOP stayed ours (no layer of the game's lit them in the battle) | |
| the same, `prio 255` | MASER blinking again (25 changes in 6.3 s) | |
| battle, `release_all` | the ramps and BIG LOOP back to the battle's 0, MASER to its 255 | |

The runtime's own reads agree (`lamp_probe.c slots`): the compositor's output record for a held
light carries our level and our layer's fade, with the game's in-play layer (priority 3) still holding
the same light underneath. `lamp_probe.c wiremap` read the output stage's board lists live: every
playfield light goes out on the channel the device table says (LEFT RAMP-R/G/B = node 9 channels
48/49/50, MASER = node 8 channel 62). No crash in any run (segv 0).

**Not proven:** a real machine (nothing was flashed); Pro 1.15 (its map and layer values are read at
the desk only); a multiball; what a node board shows if the game also runs a board-side effect on a
held channel (none was seen in these runs: the game's strobes on the ramps go out on the level path,
under the layer). In RUN 5 about one node 9 frame in ten was of a form the decoder then refused (the
long bitmap body, `a2`/`aa`/`ba`); it is read now (below), and every node 8 and 9 frame of that game
closes exactly.

**The rig's LED view (the virtual playfield) shows the Godzilla inserts, the game's and a mode's.**
Godzilla's insert boards take their levels in the bitfield grammar the rig already had a decoder for
(`hwshim.c` `led_wide_walk`, `leddecode.wide_decode`; the builder behind Premium 1.16's `0x5b0468` /
`0x5adf20`). That decoder was switched off for godzilla by a per-TITLE vote (item 85): the vote was
drawn over every board, godzilla's strip boards (nodes 12, 14) do not speak the grammar, and a board
that sends the LONG bitmap body (a window of more than 8 groups, which the walk then refused) failed
too, so the title said no and the insert boards were read with the older shapes, which read this
build's frames wrong or not at all. Now each board votes for itself with its own multi-lamp frames
(`led_node_wide_publish`: 200 votes, 90% exact), and the long body is read. On Premium 1.16 nodes 1,
7, 8 and 9 say yes (200 of 200 each, about 70 s into a boot), 12 and 14 no; the same vote over Pro
1.15's attract trace (item 27) gives the same answer. A title whose own verdict is yes (batman) and a
board that says no are read exactly as before. RUN 6: the virtual playfield in a stock game's attract
(`run6a/pf_attract_*.png`) and during the lamp probe (`run6b/pf_held_*.png`: LEFT RAMP red, MASER
blinking, the HEAT RAY chase, the game's own show around them).

**The instrument** (`lamp_probe.c`, built beside `mode_file.c`): `/dump/lamp.do` takes `set`,
`shot`, `release`, `release_shot`, `release_all`, `prio`, `layers`, `list`, `watch <ms>` (the
layers whenever they change), and two raw porting reads, `slots <lists> <output array> <light>`
(every layer's slot for one light and the compositor's output record) and `wiremap <board table>
<board count>` (every light the output stage sends, and the board channel it goes out on).

### Lights on every title (item 164)

Only Godzilla, Jaws and King Kong carry the game's light language (`blele`), so `pm_lights`
cannot work on the rest. The named-insert layer above works on every framework measured, so a
mode's Lights go through it there: `pm_lamp_all(rgb, pattern, ms)` holds every insert the
port names (mode file: `light_all <colour> [pattern] [ms]`), and the tab writes
`light_all <colour> pulse` for a title whose profile says `light_route` "inserts".

Every port whose inserts `lamp_map.py` can read carries the block now. It takes four things
from the build's own program:

- **`data lamp_layers`**: the first global the lamp-group allocator loads. The allocator is
  the first call inside the port's `lamp_group`.
- **`data light_count`**: the light table accessor's bound. Both agree with every port that
  had them before.
- **The slot layout and fade**: Godzilla's values.
- **The `lamp` lines**: read on the title's own playfield picture (`lampmap.playfield_image`),
  since each title names its own. `lamp_map.py` also reads `-R` written as ` - R` (Venom),
  lamp kind 6 (Deadpool Pro, TMNT Pro: left without lights) and single-colour tables with no RGB
  lamp (Star Wars ELG).

**Emulator-proven (2026-09-25):** a mode file's `light_all ff00ff solid` on each of 20 builds (and 5 SWELF builds, below).
The shim's LED view (`dump/padled`, a board channel per light: node = the light's I/O group +
1 on most, + 2 on Godzilla, Munsters and TMNT Pro) was copied before the mode, twice while it
ran, and after it ended. The rule: while the mode ran, every addressed RGB insert (or, on a
title with none, every single-colour insert) read R >= 200, G <= 40, B >= 200; none did before
or after, beyond what the game's own show lit.

- The 20 builds: Beatles, both Deadpools, D&D, Elvira, Foo Fighters, both Bonds, Jaws, John
  Wick, JP LE, King Kong, both Led Zeppelins, Metallica, Munsters, both Star Wars, TMNT Pro
  1.59, X-Men and Venom.
- Deadpool LE held 23 of 30 (its arrows are addressed but stay dark: another output path).
- Star Wars LE held 29 of 38.
- On Jaws and King Kong the game's own shot table ties 26 inserts to shots, so "Light the
  shots that score" works there too.

**The SWELF generation** (Aerosmith, Avengers, Batman, Guardians, Iron Maiden, Mando, Rush,
Stranger Things and Sword of Rage) has no Godzilla-style light table. Its DEVICE table is found
through the light accessor instead: 24-byte records whose word 3 points at a {u32, name x5}
record, word 4 is the board node and channel, and word 5's low half is the class (4 = LED). A
light id is the device's index, and the game's light count is that table's length (313 on
Aerosmith, logged by the runtime). The `lamp` lines are every LED but the cabinet's, a
fixture's -R/-G/-B or -RED/-GRN/-BLU on one line, with the board address in the comment.

The shim reads only some of this generation's boards: it refuses the bank form, about half the
frames. So the proof is the boards it does read:

| Build | RGB inserts in our colour (before → during) | Single-colour inserts lit (before → during) |
|---|---|---|
| Aerosmith | 0 → 11 of 22, on exactly the channels the device table names | |
| Guardians | 5 → 42 of 76 | |
| Rush | 3 → 21 of 25 | |
| Mando | 0 → 4 of 15 | 6 → 26 of 80 |
| Batman | | 7 → 20 of 72 |

All five went back after the mode ended.

Later the same day, with the insert lines back in: Avengers (2 of 2 readable colour inserts held,
none before), Sword of Rage (8 of 24, none before) and Iron Maiden (5 of 21, 1 before) - the same
partial proof. TMNT LE: all 18 colour inserts once its game started.

Not yet: Stranger Things - its inserts are driven in the BANK form on bank 1 (`[nbcmd] 90`, `b0`,
`b2` with the prefix 0x24 / 0x34), which the shim refuses. Its port carries the lines; the tab
leaves Lights off until one is seen.

### Sounds of your own (item 150)

The game plays sounds by REQUEST id: a request names one or more sound ids, and each of
those names a record in the card's sound bank. A sound the card never had is added by the
BUILD, not by your code: it appends a record to the bank and re-points one stock request
(the "carrier") at it. Your mode then plays the carrier by id:

| To... | Call |
|---|---|
| play a request | `pm_sound(request)` - no city variant is swapped in, unlike `pm_callout` |
| know it is still playing | `pm_sound_active(request)` |
| stop it | `pm_sound_stop(request)` - every channel playing it; 1 if one was |

Each returns 0 on a port without `sound_play` / `sound_active` / `sound_stop` (there is no
`PM_CAN_` bit for them). A carrier must be a request the game itself never plays while
your mode might, or the game plays your sound at its own moment: the per-title list of
safe carriers is in item 150's entry in `plans/TODO.md`, measured by `sound_census.c`.

Mode files carry four keys for this, read by `mode_file.c`:

    sound_start <request> [ms]          played when the mode starts
    sound_shot  <request> [every] [ms]  played on every scored shot, or on every Nth
    sound_end   <request> [ms]          played when time runs out, instead of callout_end
    music       <request> [sid]         started with the mode, started again whenever no
                                        channel plays it, faded out at every end; with a sid,
                                        the mode's own bed (below)

**Lengths.** A record appended for a sound is never shorter than the carrier's stock record, so
a SHORTER sound is followed by silence. For music the build tiles the WAV in whole repeats past
the carrier (`mode_sounds.build_bank(music=)`), so the record loops it with no gap. For a call,
`[ms]` is the sound's own length: `mode_file.c` stops the carrier once `[ms]` + 1/8 + 120 ms have
passed, so the silence does not hold the speech bus (a 1 s start call on a 4.6 s carrier would
otherwise drop a shot call 2 s later). An older `mode.so` reads only the request.
`pm_sound` returns 1 when the game ACCEPTS the request, also when the bus then refuses it, so a
`mode.log` line saying a call "played" is not proof it was heard: the channel dump
(`sound_fire_mode.c`, `sound.dump`) or the capture decides (item 150 RUN 8).

**On a card (item 149).** Write puts a tab mode's start sound, shot sound and music into the
card's sound bank, each on its own carrier from `mode_sounds.TITLES` (Godzilla Pro 1.15 and
Premium/LE 1.16 so far), and writes these keys into its mode file; each mode's music goes on a
bed of its own (below). A sound it cannot carry (a title with no measured carriers, the carriers
or beds run out) is left out, and the log and the Write scan say so. The END sound stays on the
title's time-up request.
Try it's set is Write's, so a Try it run plays the same sounds.

**Buses and priority.** Music, speech and each kind of effect play on a BUS that holds one
sound at a time. A new request takes a bus from a playing one of lower priority, or of equal
priority when the playing one's steal flag is set, and is otherwise not played at all. The
game's music takes the music bus back from yours (both priority 1, flag set), and a call of
yours at the carriers' stock priority 2 is dropped while any other speech plays. So
`mode_file.c` sets its carriers at every start with

| To... | Call |
|---|---|
| change how a request competes | `pm_sound_priority(request, priority, flags)` - -1 leaves one as it is; returns the old `priority << 8 \| flags`, or -1 without `data sound_requests` / `sound_request_count` in the port |

start and end calls to priority 4, shot calls to priority 3, all three without the steal flag
since the item 150 follow-up (with it, an equal-priority sound cut them mid-sound), and the music
without the flag. So a call takes the bus from the game's lower-priority speech (after fading it,
see below) and is never cut by an equal one; a shot call waits under the game's priority-3 speech
(multiball intros, super jackpots, the ball-start lines); a start or end call cuts that too. Use
it only on a request the game never plays itself. MODE_API.md, "Sound BUSES and priority", has
the measurements.

#### A music bed of your own, and no clicks (item 150 follow-up)

Godzilla has ONE music carrier (request 125), yet every mode can have music of its own. The
play worker reads a request's list of sound ids (the pointer at +8 of its 20-byte record) at
EVERY play, so the build binds each mode's bed to a sound id that no request names (a BED,
`mode_sounds.TITLES[...].beds`, grown and re-pointed like any own sound) and the mode points the
carrier at its bed while it runs:

| To... | Call |
|---|---|
| make a request play ONE sound id | `pm_sound_sid(request, sid)`; `pm_sound_sid(request, 0)` puts the request's own list back. 1 = done; 0 without the port's request table |
| fade a request out, then stop it | `pm_sound_fade(request, ms)` - linear in dB (the codec's volume step, 1/3 dB each, on every voice of every channel playing it) down to -86 dB, then the stop, in silence. Without the port's `value sound_channel_*` / `sound_voice_volume` lines it stops at once. `pm_sound` on a request still fading ends that fade first |
| see what plays | `pm_sound_playing(requests, buses, max)` - the request and bus bits (0x01 music, 0x02 voice) of every channel playing; -1 without `data sound_channels` |

The mode file says it with a second number: `music 125 618` = carrier 125 playing bed sid 618.
An older `mode.so` reads `music 125` and plays the carrier's own (stock) record.

What makes the sounds click-free (David's run of the film pack, 2026-09-18: every one of the 39
clicks on our sounds in his capture was one of these, `plans/TODO.md` item 150):

- **The build.** The boot derive reads two 512-byte WINDOWS of every record, at a quarter and
  three quarters of its body, and they set the codec parameters of every record AFTER it (never
  its own). The build used to put the scaffold's bytes back in each appended record's windows,
  and the card played ~6 ms of the copied stock sound there - also in a call's silent tail. Now
  the appended records are encoded ALONG the chain (`engine._chain_encode_appended`): each with
  the parameters the chain gives it, its bytes put in, the chain carried on from them. Nothing is
  restored, and no firmware patch is needed. And a record's declared duration (the descriptor's,
  in 1/4000 s) now ends where its audio ends: the voice played ~10 samples past the codec's
  output, a burst at the end of every appended record and at every loop of a looping one.
  And the machine also plays the codec's LEAD-OUT block past `length - 200`: an appended
  record's bytes there were the scaffold's, an 11000-21000 count burst at every record end and
  loop seam. The encode now covers 400 samples of silence past the end
  (`engine._APPENDED_TAIL`), inside the room the appended body already has.
- **Music loops.** `mode_sounds.loop_wav` makes a bed a seamless loop a whole number of 441
  samples long (so its declared duration is exact), crossfading the audio that follows its end
  onto its head; the encode puts no edge fades on it and low-passes it as a circle. The loop is
  then repeated so the record OUTLASTS its mode (`mode_sounds.bed_min_frames`: the mode's
  seconds + 3, at most 150 s): the engine's own restart of a record at its end drops ~4 ms,
  in the game's own tunes too, so a mode's music never reaches it.
- **The runtime (`mode_file.c`).** Nothing is cut while it sounds. Calls no longer carry the
  steal flag (the game's equal-priority speech and the mode's own next call cut them); a call
  whose own sound is over is faded (40 ms) before it is stopped, never cut; a shot
  call whose previous call still sounds is skipped; a call that would cut the game's
  lower-priority speech fades it first (60 ms) and plays 70 ms later, and one the bus refuses
  waits (1.5 s for a start or end call, 0.8 s for a shot call) before it is dropped with a log
  line. The game's music is faded out (250 ms) before the mode's starts; any music of the
  game's (a request of priority 1) that plays during the mode is faded out too; at the end the
  mode's music FADES (400 ms) and the game's music that was playing at the start is played
  again - before, the end left nothing playing until the game's next music request.

`sound_census.c` (a porting instrument, built with `-p` and preloaded INSTEAD of a mode:
both hook the tick) logs every request the game makes and dumps its 8 sound channels twice
a second; `sound_census_read.py` turns that into per-phase counts and channel holds.
`sound_fire_mode.c` plays, polls and stops requests from `/dump/sound.fire`,
`sound.active` and `sound.stop`, beside `mode_file.c`; `sound.prio "<request> <priority>
<flags>"` calls `pm_sound_priority`, and `sound.dump "<ms>"` logs the channels playing
(request, priority, flags, bus, serial) whenever they change.

#### Every other title: the carrier's own key swapped in (item 163)

Godzilla's carriers are its Japanese variants and its music beds are sound ids no request names.
Neither travels: the newer titles PLAY most of the sound ids their request table leaves out
(D&D's character banter from u32 sid tables, Foo Fighters' variant structs, Venom and JP lines
reached from data no static scan finds), so re-pointing one would change a line the game says.
Every other title (`mode_sounds.TITLES[...].swap`) touches no stock sound id at all:

- **The build** grows each carrier's own record with the mode's sound and leaves every descriptor
  as the card had it (`engine._plan_descriptor_repoint(keep=...)`), so nothing the game plays
  names the appended record. The mode file (and a code mode's `.assets`) gets
  `swap <request> <stock key> <our key>`: the carrier's record key and the appended one's.
- **The mode** plays the carrier with `pm_sound_swap(request, stock, ours, priority, ms)` armed:
  the runtime's `sound_lookup` hook hands back OUR key for every lookup of the STOCK one (by key,
  so the worker thread's later lookup and a looping descriptor's every loop both get ours), and
  puts it back from its own tick once `ms` (and a second) have played: only the lookup at the start of the play needs it. A call is
  swapped for its play; the music for as long as the mode runs, then for its fade.
- **The carrier's descriptor still sets the bus, the loop and HOW LONG it plays.** So a call must
  be no longer than its carrier's own record (the build refuses a longer one, and the carriers
  are the title's longest unplayed calls), and the music carrier is a stock tune (minutes long).

**The end sound on a carrier (item 164).** On a title whose time-up callout is not known, there is
no request to re-point for the end sound, so it rides a carrier like the start and shot sounds:
the mode file says `sound_end <request> <ms>` with its `swap` line, and mode_file.c plays it when
time runs out. Each mode gets its own (a card no longer carries one end sound for the whole game
on those titles). `mode_project.end_sound_carried` says a title has the carriers for it. Heard in
the emulator at time-up, after the game's own countdown, on 16 builds (2026-09-25): Avengers, The
Beatles, Foo Fighters, Iron Maiden, John Wick, JP LE, JP The Pin, the Led Zeppelins, Mandalorian,
the Star Wars builds, Sword of Rage, the TMNTs and X-Men.

| To... | Call |
|---|---|
| play a request with another record for one play | `pm_sound_swap(request, stock_key, our_key, priority, ms)` (keys: 8 bytes), then `pm_sound(request)`. 1 = armed; 0 without the port's `sound_lookup` site - then do NOT play it, the carrier would say its own line |

### A code mode's own clip, screen, music and calls

A mode written in C gets its own sounds and pictures the same way a form mode does: the BUILD adds
them, and the mode plays them by name. The project keeps them beside the code, in
`modes/<folder>/assets.json` (`pinball_decryptor/plugins/stern/code_modes.py`):

```json
{
  "format": 1,
  "name": "KING GHIDORAH",
  "seconds": 90,
  "screen": true, "screen_art": "screen.png", "words_on_art": true,
  "clip": "clip.mp4",
  "music": "music.wav",
  "calls": {"sever": "sever.wav", "won": "won.wav", "spike": {"wav": "spike.wav", "priority": 3}}
}
```

`seconds` is the longest the mode can run (its music bed is repeated to outlast it, up to 150 s).
`words_on_art` puts the mode's words on the picture's bottom band (a darkened strip the examples'
pictures carry) instead of under it. Each CUE (`sever`, `won`, ...) is a word the mode's C uses; the
file maps it to a WAV. A call at priority 3 is one that repeats (it waits under the game's own
priority-3 speech and is skipped while its previous play still sounds); 4 is the default.

Write (and Try it, which is Write's code) then:

- adds the screen to the HUD scene and the clip to the video bank, named after the folder
  (`PadMode_<folder>_Screen`, `PadMode_<folder>_Clip`), in the same pass as the form modes';
- puts the music on a bed of its own and each call on a carrier of its own, from the same allocator
  as the form modes' sounds (`mode_write.choose_code_sounds`), and grows and encodes them the same way;
- compiles the project's code modes with `mode_file.c` into the card's `mode.so` (build_mode.sh in the
  app's Linux) instead of the pinned object;
- writes `<folder>.assets` beside it, naming what it carried:

```
name   KING GHIDORAH
screen PadMode_ghidorah_heads_Screen PadMode_ghidorah_heads_Screen.PadMode_ghidorah_heads_Screen_Words
clip   start PadMode_ghidorah_heads_Clip
music  125 576
call   sever 1186 1400 4
```

The mode reads it with `pad_mode_assets.h` (a header, nothing added to the runtime):

| To... | Call |
|---|---|
| read the file (once, at init) | `pa_load(&own)`, with `static struct pa_assets own = { .folder = "ghidorah_heads" };` |
| every tick, running or not | `pa_tick(&own)` (an end call outlives the mode; the game's music comes back after) |
| the mode starts | `pa_start(&own)`: the carriers' priorities, the music (the game's fades out 250 ms first), the start clip half a second later |
| an event | `pa_call(&own, "sever")`: 1 if the card carries that cue, else 0 (play the game's own call then) |
| the mode ends | `pa_end(&own)`: the music fades (400 ms), the carrier's list is put back, the game's music plays again |

It follows mode_file.c's rules (the section above): no steal flag on any carrier, the game's lower
speech faded before a call, a call the bus refuses waits (1.5 s, 0.8 s at priority 3), a call faded
(40 ms) once its own sound is over, never cut. Two more for a mode with many calls: a call of the
mode's own that still sounds is faded (30 ms) for the next one (the newest event speaks), and a
priority-4 call played again while its previous play still sounds starts over (the sound engine
does not restart a request that is still playing; without the fade the second event is silent).
It logs every play, and what holds the music bus
whenever that changes and a second after the end (`own sound: the music bus now holds: 125`).

On the card the files sit beside `mode.so` in `/usr/local/padmode` (`mode_install.py --asset`); a
card of code modes only carries no mode file at all. The emulator's card reader (`../cardmodes.sh`)
and Try it's installer (`../tryit.sh install`) put them in `/dump`. The Modes tab's Examples offer
the five intricate modes this way: each brings its code and a recipe of film times
(`examples/film_recipes.json`) that the tab cuts with the film cutter from the person's own films.
Emulator-proven on Godzilla Premium 1.16 (the showcase card, 2026-09-18).

### What is measured, and what is not

- **Countdown callouts:** variants n = 0..4 (5 down to 1) are proven. Others are not measured.
- **Scoring:** `pm_score_add` goes through the game's scoring, so the playfield multiplier
  applies. There is no call that bypasses it. The return value is what the game actually
  added, and it can be 0.
- **`.ball_end`:** the game's end-of-ball broadcast, the one every stock mode ends on. What
  it does on a multiball drain or a ball save is not measured.
- **`pm_in_game()`:** a player is up, and the game's mode mask shows none of the port's
  `mode_mask_busy` bits. Those bits are set at game over and in menus; they are not fully
  decoded.
- **Repeated shot bits:** on Godzilla a switch dispatches `0x1` and then its shot bit; on
  Jaws both come in one dispatch; TMNT Pro sends only the shot bit. Whether one shot
  can repeat its own bit (a loop, a spinner) is not measured for every shot. Spinners
  are known to send several different bits.
- **Threads:** the runtime logs which thread the tick, shot and ball-end callbacks run on,
  on every boot (`[pad] tick callbacks run on thread N`). On Godzilla Pro 1.15 the tick and
  shot callbacks were measured on the same thread, and on Jaws LE 1.02 all three were, so
  they cannot overlap there. On another game, read those lines before sharing state
  between callbacks.
- **Clips race the game's own.** There is one video surface. A clip you start on a shot
  that also starts one of the game's clips (a Maser Target hit on Godzilla does) can be
  replaced by the game's clip. A clip started from the tick, or a moment after the shot,
  keeps the surface. Measured again in item 141 on Godzilla Pro 1.15: a mode file's
  `clip_start` played inside the Maser trigger shot never reached the glass; played 500 ms
  later from the tick it did (at +1, +2, +3 s). `mode_file.c` now waits
  `CLIP_AFTER_SHOT_TICKS` (30) before a clip a shot starts; do the same in a mode in C.
  One clip waits at a time and the newest wins: a clip still waiting when another is
  asked for (one mode's end clip when the next mode starts inside that half second, a start
  clip whose mode ends first) is dropped with `clip "X" (...) dropped before it played: ...`
  and never plays over the newer one (item 141's host harness; in the rig, run 3: an end
  clip still waiting when the next mode started by file was dropped, and the new mode's
  clip was on the glass). Asking for the clip that is still playing does not start it again
  (item 141 run 3: the same clip at both ends of a mode stopped 3 s into its 4 s clip ran on
  to its end).

### How often a mode can start (mode files, item 139)

`mode_file.c` (the Modes tab's modes) can limit how often a mode starts. The tab writes
these lines from "How often it can start"; a mode written in C keeps its own counts.

| Line | Means |
|---|---|
| `starts once_per_game` | once a game |
| `starts once_per_ball` | once a ball |
| `starts 3` | up to 3 times a game (1 to 99) |
| `starts unlimited`, or no line | any number of times, as before item 139 |
| `cooldown 20` | not again until 20 s after it ends (0, or no line: no wait) |

- **Counted for each player, when the mode starts** (measured with two players: player 2's
  once-a-game mode starts after player 1's has run, player 1's cooldown does not hold
  player 2, and player 1's counts survive player 2's ball). A refused start says why:
  `ONCE GAME not started (trigger shot): already ran this game`, `... already ran this
  ball`, `... already ran 2 times this game`, `... cooling down, 19 s left`. A trigger shot
  hit while the mode is refused still counts toward its trigger, as it does while another
  mode runs.
- **A ball's counts clear at every end of ball** (`end of ball: this ball's start counts
  cleared`). A drain the ball saver gives back is not an end of ball: no end of ball
  reaches the modes, and a once-a-ball mode stays refused (measured on Godzilla Pro 1.15).
  A ball drained with no playfield switch hit since its launch was given back every time
  (three drains, each 45 s into the ball), so hit a switch before a drain that must end
  the ball.
- **The cooldown is wall-clock time from the mode's END** and runs on through an end of
  ball (measured: a 20 s cooldown said `cooling down, 7 s left` on the next ball).
- **A new game clears the game's counts and every cooldown** (`new game (<witness>):
  how-often counts cleared`).
- **What marks a new game** (measured on Godzilla Pro 1.15, item 139). `mode_file.c` logs
  every change of `pm_in_game()`, `pm_player()` and whether player 1's score is 0 as a
  `game:` line. At game over `pm_in_game()` falls (the mode mask goes `0x0005` -> `0x0098`
  -> `0x0010`) while the player byte stays 1 and every score stays on the display; nothing
  is reset. A new game clears the mask, raises `pm_in_game()` and zeroes player 1's score
  in the same tick:
  ```
  730879 [mode] game: in_game 1 -> 0, player 1 -> 1, player 1 score not 0 -> not 0
  810344 [mode] game: in_game 0 -> 1, player 1 -> 1, player 1 score not 0 -> 0
  810344 [mode] new game (player 1's score went back to 0): how-often counts cleared
  ```
  Holding Start for 3 s in the middle of a game (player 1's second ball of a two-player
  game) restarts it as a new one-player game, and there `pm_in_game()` never falls: the
  player count goes 2 -> 1 and player 1's score goes to 0 in one tick, with the ball left
  in play:
  ```
  233832 [mode] game: in_game 1 -> 1, player 1 -> 1, player 1 score not 0 -> 0
  233832 [mode] new game (player 1's score went back to 0): how-often counts cleared
  ```
  An end of ball sets mask bits `0x0004` and `0x0001`, which are not busy bits, so
  `pm_in_game()` never drops there either. So the witness is **player 1's score falling to
  0**, or **`pm_in_game()` rising while it is 0** (a fresh card's first game, or a game
  after one player 1 never scored in), recognised once, then not again until player 1
  scores or `pm_in_game()` falls. `pm_in_game()` rising alone would miss the held-Start
  restart. The last game's scores survive a reboot of the card (measured once), so the
  first game after that boot is also seen by the score falling to 0.
- **Trigger files bypass it.** `/dump/mode.start`, `/dump/modeK.start` are a test path: they
  start the mode whatever `starts` and `cooldown` say, and that run is neither counted nor
  starts a cooldown (`ONCE GAME: a trigger file starts it whatever starts/cooldown say, and
  this run is not counted`).
- **An older `mode.so`** logs `unknown key, skipped: starts once_per_game` and starts as
  often as it always did, so a new file is safe on an old object.
- **Not measured:** a multiball drain, a tilt, a game ended from the service menu, and a
  cooldown cleared by a new game while it still had time left (the clear is desk-tested
  only).

## The game's own modes (stacking)

A mode of yours runs beside whatever the game is doing, including its own battles and
multiballs: nothing stops both from scoring the same shots. A mode that should not stack
asks first:

```c
int kind = pm_stock_mode_running(PM_STOCK_BATTLE | PM_STOCK_MULTIBALL);
if (kind > 0) { pm_log("not started: %s is running", pm_stock_mode_what(kind)); return; }
```

A mode file does the same with `stack no` (the default, `stack yes`, is how every mode ran
before the key existed). A `stack no` mode that is refused logs
`<name> not started (<why>): a battle is running` and keeps its trigger count, so the first
start shot after the game's mode ends starts it. On a port that cannot tell (-1) it logs
that once and starts as `stack yes` would. The `starts`/`cooldown` check (item 139) comes
first; unlike it, a trigger file (`/dump/modeK.start`) does NOT bypass `stack no` (read from
`mode_file.c`; the runs below used trigger shots).

**What "running" means.** The game keeps its modes in one mode manager (`cmode_manager`,
27 modes on Godzilla), and already answers these questions for its own rules with compiled
queries. The runtime calls those, never a guess of its own:

- Each game mode has a kind: `0x1` multiball, `0x2` timed, `0x4` hurry-up, `0x8` battle.
  On Godzilla the battles are ids 12-17; the multiballs are ids 1-11; Megalon and Gigan
  multiball (id 6) is both.
- A mode is RUNNING when its flag for the player up is set (a timed mode: while its
  timer's event is live). It is ACTIVE when it is running, or its second timer event is
  live (a timed mode), or its own event is live (a multiball). The queries the port names
  ask for ACTIVE. Measured on Godzilla Pro 1.15 and Premium 1.16: a battle turned active
  about when its KAIJU BATTLE SELECT screen came up (the screenshot taken as the answer
  changed showed that screen, or the monitor it opens on), not at the scoop, and stayed
  active until its TOTAL screen, about 2 s after its timer ran out (only its second timer
  event live by then); a multiball stayed active until 3 to 3.5 s after the drain that
  ended it.
- `PM_STOCK_BATTLE`: an active mode whose kind has `0x8`. `PM_STOCK_MULTIBALL`: an active
  mode whose kind has `0x1` and not `0x20`. `PM_STOCK_ANY`: any active mode not flagged
  `0x20`.
- The queries are called only once the manager exists and a player is up; with no player
  up the answer is 0.

**The port lines.** Each is a virtual of the manager, called with the manager in r0:

```
site stock_any_running        0x000d1e20 ...   # manager virtual 10
site stock_battle_running     0x000d2040 ...   # manager virtual 15
site stock_multiball_running  0x000d2218 ...   # manager virtual 22
data stock_mode_manager       0x0079d954       # the manager singleton
```

`port_tool.py` places all four on Godzilla LE 1.16 by signature (the manager's code there is
Pro 1.15's instruction for instruction). On another title, find `cmode_manager` with
`rtti_tree.py` and compare its virtuals 10, 15 and 22 with Godzilla's; a title without a
`cmode_manager` (TMNT Pro's `crule_manager`) has no port lines, and the call returns -1.

**What is proven.** In the emulator on Godzilla Pro 1.15 and Premium 1.16 (`godzilla_le`),
with a mode file set to `stack no` beside one with no stack key: both started in plain
play; during a battle the game started itself (Titanosaurus on Pro, Ebirah on Premium:
both ramps twice, the scoop, the pick) and during a Godzilla multiball (started on demand)
the `stack no` mode logged `not started (trigger shot): a battle is running` / `a multiball
is running` while the other one started; and once each ended with the ball still in play,
the next start shot started the `stack no` mode.

**Not decoded yet.** Kind `0x10` (set on the double battles, the later multiballs and some
timed modes) and `0x20` (set by no constructor, so a runtime flag); other titles' managers;
a stock mode that starts while yours is already running (yours keeps running: the check is
made only when yours starts). The game's mode mask (`data mode_mask`) is NOT a witness: it
stayed 0 through a battle and a multiball (it is `0x10` in attract, `0x4` at the end of a
ball, `0x5` in the bonus). Only multiballs started on demand were measured: when a
multiball the player lights turns active, compared with its intro scenes, is not measured
(a battle turned active only at its select screen, so a `stack no` shot during a
multiball's intro may still start).

### The game's own modes on every cmode title (item 164)

Only Godzilla's port names the manager's own queries. Every other title whose rules are
`cmode` classes (the crule titles included: their `cmode` is abstract) takes a GENERIC route:
the runtime walks the game's mode TABLE itself.

```
data stock_mode_table       0x0086a020   # the array the get-mode-by-id accessor reads (Jaws LE 1.02)
value stock_mode_count      36
value stock_slot_active     18           # the cmode class's ACTIVE virtual
value stock_slot_start      12           # its START (read by pm_stock_start and the rig probe)
data typeinfo_cmode         0x006e2098
data typeinfo_cmode_mball   0x006fa754
data typeinfo_vmi           0x006dfe78   # any multiple-inheritance typeinfo: its vptr
```

- **The table.** Godzilla's get-mode-by-id is `cmp r1, #N ; movw/movt T ; ldr r0, [T, r1, lsl
  #2]`; its queries load `T - 4` from a literal and step by 4 up to `T + 4 * count`. The table
  both kinds of code read is the one. Star Wars LE 1.30 has no such accessor: there the table
  its queries walk most is taken, when every entry is an object pointer.
- **The class.** An entry counts when its vtable's typeinfo reaches `cmode` through its bases:
  a single-inheritance typeinfo's base is word 2; a multiple-inheritance one (John Wick's
  `cmode_the_staircase` is a `cmode_mball` and a `cwick_mode`; Led Zeppelin's song modes) is
  followed through its base at offset 0. Reaching `cmode_mball` makes it a multiball
  (`PM_STOCK_MULTIBALL`); any other `cmode` is `PM_STOCK_BATTLE`, logged as `one of the
  game's modes (<class>)`.
- **ACTIVE** has one shape on every build: `ldr r2, [r0]`, one vtable load (the RUNNING slot,
  the "is it overridden?" test), then `ldrb r0, [..] ; cmp r0, #0 ; popne`. Godzilla 14,
  Jaws 18, Avengers 17, Mando 44, Iron Maiden 15. **START** tests another slot, then
  RUNNING, through the vtable (Godzilla's 8: slot 7, then 12); Deadpool has no such slot, and
  its START (13) is the other short slot that tests RUNNING.
- **Base play.** Some titles run modes for the whole ball: Venom's `cmini_mode_01..03` are
  active from the plunge on, D&D's `ctraveling` and Foo Fighters' `csuper_skill_shot` at the
  ball's start. The runtime notes every entry running from a ball's start until 2 s after its
  first score and does not count it until it is seen stopped. A ball is the player up plus the
  `ball_start` events (or the ball ends) seen so far.

`stackport.py` (the item's scratch tool) derives all of these from the ELF.

**What is proven.** In the emulator, one scripted game per build: nothing running (the
`stack no` mode started), then the rig started one of the game's modes through its START
slot (the runtime named it; the mode was refused), then a multiball (named, `a multiball
(cmode_trex_multiball)` on JP LE). Proven on: Jaws LE 1.02, Jurassic Park LE 1.16, Deadpool
LE 1.14 and Pro 1.16, Avengers LE 1.09, TMNT Pro 1.59, Led Zeppelin LE 1.22, Munsters LE 1.28,
Venom LE 1.07, D&D LE 1.00, King Kong LE 0.97, Mandalorian LE 1.44, Iron Maiden LE 1.16, Sword
of Rage LE 1.18, Rush LE 1.18, Star Wars LE 1.30 and Foo Fighters LE 1.04 (a mode, and on most a multiball too); John
Wick LE 1.01 and Led Zeppelin Pro 1.22 on a multiball only (the mode the rig started there did not
stay on: Led Zeppelin runs one song mode at a time). The app offers `stack no` only on those
(`mode_project.STACK_PROVEN`).

### Multiballs on the titles with no cmode rules (item 164)

The plain-C titles (The Beatles, Bond, Metallica, Star Wars ELG, Stranger Things, X-Men,
Aerosmith, Batman, Guardians) and Elvira 3 (its own `Rule` classes) have no mode table the
runtime can walk. Every Spike 2 build does share the framework's ball code, and its count of
the balls in play is one function, found on all 34 latest builds by its code (The Beatles
1.29 `0x1fd194`, 17 to 20 of its first 20 instructions alike, the runner-up at 8 at most):

```
site balls_in_play         0x001fd194 0xe92d4010 0xe3084ab0
```

While a multiball is being served it answers the balls the multiball asked for (the
framework's ball manager, byte `+0xa`); otherwise the balls installed less those in the
trough and the other ball devices. Two or more is `PM_STOCK_MULTIBALL`. It says nothing of
the title's other modes, so on these titles `stack no` waits for the game's multiballs only,
and the Modes tab says so. A ball that is out of the trough and every ball device counts as in
play, so a ball stuck on the playfield (or, in the rig, one of a six-ball multiball the script
never drained home) makes the next ball read as a multiball until it comes home. The ball manager's byte alone is not a witness: it is set only
while the multiball's own serving process runs (it read 0 through a whole multiball on both
Bond builds).

**What is proven.** In the emulator, one scripted game per build: nothing running (the
`stack no` mode started), then a multiball (on The Beatles 1.29 its own, `0x39270`, the TAXMAN
multiball: all six balls went into play; on the others the framework's own "start a
multiball" asked for two), `a multiball` answered within 5 s and the mode refused, and
`nothing` again once the multiball was over. Proven on: The Beatles 1.29, Bond 60th LE 1.11,
Bond LE 1.06, Metallica 1.03, Star Wars ELG 1.10, Stranger Things LE 1.12, X-Men LE 0.98,
Batman 66 1.13, Guardians LE 1.14, Aerosmith LE 1.15 and Elvira 3 1.13 (`mode_project.STACK_BALLS_PROVEN`; the tab says the mode
waits for multiballs only). The rig cannot serve a SWELF-generation build's balls (its derived
device table has no coils), so on those the answer was asked 0.3 s after the
start, before the ball the game could not serve ended the multiball (Batman, Guardians and
Aerosmith).

TMNT LE 1.59 was proven the same way once its game started (`ctraining_level_two` held a stack
no mode back). In attract the LE keeps serving balls until its trough is empty and only then
takes a Start, so the scripted check presses Start for about two and a half minutes.

JP The Pin 1.05 takes the balls-in-play route (`site balls_in_play`, the framework's count),
proven the same way on 2026-09-25.

**The other modes, from their FLAGS (item 164).** The plain-C framework keeps a bitset of game
flags, saved per player (JP The Pin 1.05: set 0x152d60, clear 0x152d18, get 0x152df8; the bitmap
pointer at [0x594a40 + 4], its size in bits at [0x4beff8]), and a mode's START sets a flag of its
own that its stop clears (Stegosaurus 0x90860 sets 40; 0x90718 and 0x9090c clear it). The flag
functions have one shape on every plain-C build, so they are found by their code; each mode's
flag is read off its start function in the build's stock table, and kept only when a clear of its
own exists (a flag set by many starts, or never cleared, would hold a mode back for ever). The
port names them:

```
data game_flags             0x00594a40      # the holder; the bitmap pointer is at + game_flags_at
value game_flags_at         4
data game_flag_count        0x004beff8      # its size in bits
value mode_flag_1           39              # .. mode_flag_32: any of them set is one of the game's modes
```

and the runtime answers "one of the game's modes (flag N)" beside the multiball count. Proven in
the emulator (2026-09-25, a stack no mode held back while the mode its start was called for ran):
JP The Pin (Stegosaurus, 40), Star Wars ELG (Inner loop, 86), Stranger Things (Bust out, 78) and
Bond LE (Bust out, 102 - which cleared when it ended, and the next start went ahead);
`mode_project.STACK_FLAGS_PROVEN`, and the tab drops its "multiballs only" note there.

**Not yet.** Aerosmith's double scoring only pulses its flag (96). The Beatles' song modes, X-Men,
Guardians, Bond 60th, Metallica, Batman and Elvira keep no flag of their own that a start sets (X-Men
keeps its state in each mode's object), or their starts take arguments: multiballs only there.

## Ports: why your mode runs on any game

A mode calls the game's own compiled functions, and they sit at different addresses in
every game and every version. A **port** records them for one build, with everything
else about that game a mode needs:

```
game           godzilla_pro
version        1.15
site tick             0x004ec828 0xe92d4038 0xe3a00037   # function, address, first two instructions
data scores           0x007e4968                          # a global
value light_owner     538                                 # an offset, a flag, an id
shot 0x00100000       Left ramp                           # a named shot
callout ten_seconds   1291
scene hud             32e6ae280ddaec08e203a02289bb39a04968e7b0
text example_clip     Mothra_godzilla_attack20
```

**The safety gate.** At boot the runtime compares the first two instructions of every
function against the port. If the core functions (tick, shot dispatch, ball end, score)
do not match, the port is for another game or version: the runtime hooks nothing, calls
none of your code, and logs `NOT THIS GAME'S PORT`. Every other function that fails the
check switches off only its own capability (lights, screens, clips...). The gate reads the
process's mappings (`/proc/self/maps`) once and never reads an address outside the game's
own code: such a site is logged `site X 0x...: not in the game's code - not read` and
counts as not matching. The core sites are checked first, and when one of them fails no
other site is read at all. (Before this, `godzilla_le-1.16.port` on The Beatles 1.29 killed
the game at boot: its `resource_get` 0x538484 lies in Beatles' unmapped hole between its code
and its data, and the gate read it.)

**The core, and its alternatives.** A port names one of each; the runtime (`core_of_port`) and
the app (`mode_project.core_missing`) pick the same:

| Core part | The reference way | Or |
|---|---|---|
| the tick | `site tick` | |
| a shot source | `site shot_dispatch` | `site switch_hit` with `switch` lines (see "Shots from switches") |
| the end of a ball | `site ball_end` | `value ball_end_event <bus id>` with `site hook_dispatch`: the runtime hands the ball end to the modes from the bus dispatch, as the game's own handler of that id would run |
| the score | `site score_add` + `data scores`: 64-bit points in r2:r3, u64 scores | `site score_add32` + `data scores32`: 32-bit points in r1, u32 scores (The Beatles). The game multiplies the points by its playfield multiplier and adds them with no carry check, so `pm_score_add` cuts an award to the room left below 4,294,967,295, divided by the multiplier byte the optional `data score_mult` names (taken as 1 without it): a score stops at the top instead of wrapping. The boot log says `scores: 32-bit (score_add32 0x..., scores32 0x..., multiplier byte 0x...)`. The Modes tab also refuses an award above 16,843,009 (4,294,967,295 / 255) on such a title. The names carry the calling convention, so a runtime from before the 32-bit form finds no core `score_add` in such a port and hooks nothing |
| the player up | `data cur_player` | | The words are
never typed by hand: `port_words.py <game ELF> <port> --write` reads them from the game.
Two entries are weak checks: `string_new` and `dynamic_cast` are PLT stubs, and every PLT
stub starts with the same two instructions.

**How much a port holds.** The runtime reads a port a line at a time, in 4 KB pieces, up to
128 KB (`PORT_MAX`), and keeps each kind of line in a table of its own: 48 `site`, 48 `data`,
64 `value`, 64 `shot`, 32 `callout`, 32 `scene`, 32 `text`, 48 `event`, 192 `lamp` and 32
`switch` lines (each `switch` line's name also takes a `shot` place). A
line past a full table or past 128 KB is not read, and the boot log says so (`port: 2 line(s)
not read - a table is full (sites 48 of 48, ...)`); `tests/test_stern_mode_runtime.py` fails
for a committed port that outgrows a table. Godzilla Premium 1.16's port, with its display
lines and its 88 `lamp` lines, is 23.6 KB (43 sites, 26 data, 54 values). A runtime before
the lights and display priority were merged read a port in ONE read of at most 16 KB (32 KB on
the lights branch): given a newer port it reads what fits and skips the keys it does not know,
which is why the `lamp` lines go last.

**Games with ports today**, each proven in the emulator by running `template_mode.c` unchanged:

| Port | Notes |
|---|---|
| `godzilla_pro-1.15.port` | The reference. Every entry proven by items 125-134. |
| `godzilla_le-1.16.port` | Drafted by `port_tool.py`; every function and global moved. Its shots come from a census: LE has three shield targets where Pro has two. Callout ids and some offsets are copied, not yet proven; the file says which. |
| `jaws_le-1.02.port` | The first title with its own rules. `port_tool.py` placed 21 of 24 functions and all 13 globals; the shot dispatch and both callouts were placed by hand (see below). Shots from a census (27 bits), callout ids read from Jaws's own timed-mode code. No lights and no award screens yet: those need Jaws's own rule ids. Its first end of ball was a look-alike that ran at game start; the one its event hook calls ended the mode on a drain. |
| `turtles_pro-1.59.port` | An older framework (see below). 17 functions: the shot dispatch and end of ball were found with `call_probe.c`; lights, screens and clips are off (their functions were not found). 13 globals, 17 shots (32-bit mask in r1), no callout ids. |
| `turtles_pro-1.58.port` | Drafted by `port_tool.py` from 1.59: everything placed. |
| `deadpool_pro-1.16.port` | `cmode_manager` again (35 virtuals); the shot dispatch (virtual 11, mask in r2:r3) found with `call_probe.c`, the end of ball through its event hook. Lights, screens and clips off. 25 shots. |
| `deadpool_le-1.14.port` | Drafted from Deadpool Pro, every entry strict. Proven with a census and the template: its 25 shots, a start and an end on the clock and on a drain, and 8 bus events (its bus is two ids smaller than Godzilla's, so its tilt ids are too). Plus the two spinners and the top target. |
| `beatles-1.29.port` | The first title whose rules are plain C (no `cmode_manager`, no `crule_manager`) on Godzilla's framework. 32-bit scores (`score_add32` / `scores32`); 27 shots from its one shot function (one bit in r0, `shot_mask_at 0`, `shot_mask_bits 32`), plus 8 from switches (standups and lanes; emulator-proven with a census and a mode file). Every core entry, the 27-bit shot map and the 8 bus events were proven with a census and a scoring template (the file says which run proved what). No lights (no `light_run`), no clips (no `clip_play`), no HUD scene, no game mode queries. |
| the latest build of every other title | Worked out by `port_derive.py` and PROVEN by a full build check (`modes/gamecheck.sh play <game> full`, 2026-09-24): the runtime hooked the game, the shots came from their switches, a drain ended each ball, and each `event` line fired where its name says. Each file's header says how many shots the check saw. Shots derivation could not name carry the name of the switch that made them in the check. The event bus comes in three numberings: bound 207 (Godzilla's ids), 205/206 (the high ids shift down), and 191 (generation A: Aerosmith, Avengers, Batman, Guardians, Iron Maiden, Mando, Rush, Stranger Things, Sword of Rage, whose end of ball is 0x30). |

A mode that uses port roles (`pm_shot_at`, `pm_callout_id`, `pm_port_text`) instead of one
game's shot names runs on each unchanged. **The port format is settled** after these five
titles: the only additions they needed were `shot_mask_at` and `shot_mask_bits`, and both
default to the reference layout, so no existing port changes. The Beatles added three
alternatives to the core (the 32-bit scoring pair, `ball_end_event`, `switch_hit` with
`switch` lines), each optional: a port without them reads as before.

**What changes from one title to another** (learned on Jaws LE):

- **Shot bits, callout ids and example names are the title's.** So are three values:
  `light_owner` and `light_lts` (the rule and light set a light command runs as) and
  `award_screen_type`. `port_tool.py` leaves all of these out when `--game` is another title.
- **The shot dispatch can be a different function.** Godzilla's walks 27 modes; Jaws's walks 36
  and passes an extra argument. The shot mask is in the same place (r2:r3), so the same hook
  works. Jaws also sends `0x1` and the shot bit in one dispatch, where Godzilla sends two:
  test bits, never compare the whole mask.
- **A title may wrap a framework call.** Godzilla's callout remaps a sound id per player
  before the framework's sound request; Jaws calls the request directly. The port can
  point at the framework call on every title.
- **Scene ids are shared when the scene is.** The video bank (`60ed7e50`), the attract scene
  (`394c4a03`) and the score panel (`9d578751`) have the same ids on both titles. Godzilla's
  mode slide-out scene (`32e6ae28`) does not exist on Jaws.
- **An older framework runs rules differently** (learned on TMNT Pro). There is no
  `cmode_manager`: `crule_manager` runs 54 rules, and its shot dispatch carries a 32-bit mask
  in r1, not a 64-bit one in r2:r3. The port says where with two values, which default to
  Godzilla's layout:
  ```
  # the register holding the mask's low word (r2 if absent), and its width (64 if absent)
  value shot_mask_at          1
  value shot_mask_bits        32
  ```
  Its end-of-ball broadcast starts by loading a table address from a literal; the runtime
  moves such a load into its trampoline, so a hooked function may start with one.
- **The end of ball is an event hook, and a loose look-alike is a trap** (learned on Deadpool
  and Jaws). The game's rules subscribe to numbered hooks through one registrar,
  `registrar(slot, hook, handler, priority)`; the hook numbers are the same on every title.
  Godzilla's handlers for hooks `0x34` and `0xc6` both call its end of ball. Jaws and
  Deadpool send them to two functions, and hook `0x34`'s is the end of ball (Deadpool Pro:
  the drain that took the game from ball 1 to ball 2 ran it; `0xc6`'s never ran). A mode
  table has several loops of the same shape calling different virtuals, and Jaws's first
  port had taken one that runs at game start.

### Plain-C titles: The Beatles 1.29

Twelve of the latest Spike 2 builds run their rules as plain C, with no rule classes at all
(The Beatles, Aerosmith, Batman, Elvira 3, Guardians, both James Bonds, Jurassic Park The
Pin, Metallica, Star Wars ELG, Stranger Things, Uncanny X-Men). The Beatles runs them on
the same framework as Godzilla (its tick, event bus, switch drain, current player, lamp
allocator and end-of-ball sequence match Godzilla Pro 1.15 instruction for instruction), so
a port for it needs three things Godzilla's does not:

- **32-bit scores.** Its `score_add` is `(u8 player r0, u32 points r1) -> u32` and its scores
  are `u32[4]`: `site score_add32` and `data scores32` (see "The core, and its alternatives").
- **One bit in r0.** Every shot reaches one function with the shot's single bit in r0:
  `value shot_mask_at 0` and `value shot_mask_bits 32`. There is no `0x1` pre-dispatch.
- **Shots from switches** for what its rules never send as a shot (below).

What it does not have greys cleanly: no `light_run` (so no `pm_lights`; its named inserts
work through the `lamp` lines), no `clip_play` (its game code plays clips inline), no layered
display (display priority can arm on the display effects alone, see "Display priority", once
a port names them), and no mode manager to ask (`pm_stock_mode_running` returns -1, and a
`stack no` mode starts anyway). Its countdown callout 385 has no ten-seconds call beside it:
the Modes tab offers the 5..1 count with only `callout countdown`.

#### Shots from switches

A plain-C title's shot function carries only what its rules score as a shot: The Beatles'
four standups (switches 73-76) and its lanes (48-51) send no bit. The framework broadcasts
every switch whose descriptor flags ask for it, once per hit, from its switch drain, through
one small function per flag with r0 = the switch id (The Beatles: 0x96e68 for flag 0x2000,
0x96f08 for flag 0x1000; Godzilla Pro 1.16's is 0x1e1508). A port names each as a site whose
name starts `switch_hit`, and maps switch ids to shot bits of their own:

```
site switch_hit       0x00096e68 0xe2503000 0x012fff1e
site switch_hit2      0x00096f08 0xe92d4010 0xe2504000
switch 73          0x100000000     Target 1
switch 48          0x1000000000    Left outlane
```

Here `switch_hit` is the flag-0x2000 broadcast (the lanes) and `switch_hit2` the flag-0x1000 one
(the standups). A `switch` line is `switch <id> <shot mask> <name>`, and the name runs to the end
of the line, so put a comment on a line of its own above it, never after the name.

- Use bits the rules' dispatch never sends (above bit 31 on a 32-bit title). Each name is also
  a named shot (`pm_shot("Target 1")`), unless the port has a shot of that name already; two
  lines for one switch give both bits in one hit.
- A hit is counted where it happens, lock-free, and handed to every mode's `.shot` from the
  tick, like an event: within a tick of the hit, on the tick thread. `pm_can(PM_CAN_SWITCH_SHOTS)`
  is 1 once a `switch_hit` site matched. `value switch_hit_at` names the register holding the
  id when it is not r0.
- Only a switch the game's flags broadcast can be mapped: The Beatles' slingshots (60, 61) have
  no flag, so nothing broadcasts them. The drain skips a switch while the game's mode mask
  shares no bit with its flags (attract, the bonus), so a switch shot comes only in play.
- A port with `switch` lines and no `shot_dispatch` still has a shot source: `site switch_hit`
  is then core.
- The boot log says `switch shots: 8 switch line(s) hand their shots to the modes; 2 of 2
  switch_hit site(s) hooked (the id in r0)`, and at the first hit `switch hits run on thread N`.
- The Modes tab offers the switch shots beside the port's own, and says they are not proven
  until `mode_project.SWITCH_SHOTS_PROVEN` names the port. Emulator-proven on The Beatles 1.29:
  each of 73-76 and 48-51 gave exactly one shot in play and none in attract, and 60/61 gave none.

#### A ball end from the bus

Where no function runs only at the end of a ball, a port can name the bus id instead:
`value ball_end_event 0x34` with `site hook_dispatch` and no `site ball_end`. The runtime hooks
the dispatch (it does anyway for `event` lines) and calls every mode's `.ball_end` when that id
is dispatched, from inside the dispatch, where the game's own handlers of the id run; the boot
log says `ball end: the game's event 0x34, from its dispatch (the port has no ball_end site)`.
A port with `site ball_end` keeps it, and the value is not used. On The Beatles the `ball_end`
site is itself a handler of bus 0x34, called from inside that dispatch. Emulator-proven on The
Beatles 1.29 with the site taken out of the port: one ball end per drain, a tilted ball's included.

### Clips on the newer builds (clip v2, item 164)

The newer builds have no `clip_play`, `video_player` or `video_surface` function to name.
The lookup is inlined at every call site (Venom 1.07 has 22). So the runtime does what those
sites do:

1. It takes the video bank's scene (`scene video_bank`, 60ed7e50... on 28 of 30 latest
   builds) through `resource_get`, `dynamic_cast` and the root at `scene_player_scene`.
2. It finds the node "VideoSurface" with the typed find (`site surface_find`). That is
   `find_node` + 0x2f4 where the port has `find_node`. Otherwise it is the function the
   game's own "VideoSurface" lookups call. Every build has Godzilla LE's prologue there.
3. It calls `surface_set_video(surface, &name)`, which returns 0 when the bank has no such
   clip, then `surface_play(surface, 0, -1)`.

The game draws that surface, so there is no draw loop. `surface_state` reads 2 while the clip
plays. `surface_stop` stops it.

The port lines:

```
site surface_find       0x...    # the typed find
site surface_set_video  0x...    # } at fixed distances from surface_state: layout A (Godzilla
site surface_play       0x...    # } LE and 21 more: +0x4cac / +0x2ab8 / +0x2268) or layout B
site surface_stop       0x...    # } (Aerosmith and 8 more: +0x4ddc / +0x257c / +0x2080)
value surface_playing   2
value scene_player_scene 0x10
scene video_bank        60ed7e5036b8ce09d35a3e101ea6fc1380b37d97
```

With `site video_surface` (the game's own getter), the runtime asks that getter for the
surface on every call instead of looking up the scene. JP LE 1.16 keeps its bank in
`demand_loaded`, and so does Avengers 1.09, so the bank is not in the resource manager until
the getter loads it. Both are emulator-proven with an added clip on the glass in a game.
There `scene video_bank` is not needed. `mode_project.TITLE_SCENES` gives such a title
`bank_tree="demand_loaded"`, and the build adds the clip under that tree.

**A clip that plays is not a clip on the glass.** On some builds the bank's surface is not
part of what the game shows at that moment. Led Zeppelin shows the song video on the stage
screen. The Bonds keep their own video in front. There `pm_clip` returns 1, `surface_state`
reads 2, and nothing shows, so those ports carry no clip lines. The tab offers Clip only where
an added clip was SEEN on the screen in the emulator (`clip_proven` in `TITLE_SCENES`).

**The clip layer (Deadpool).** Deadpool shows a full-screen video by adding a video LAYER to
its display stack. The game's own "SinisterModeTotal" sequence does it this way. The runtime
does the same:

1. `layer_add(layer_stack, video_layer, clip_layer_priority)`.
2. `layer_video(video, &name, 0)` on the layer's video object, which sits at
   `layer_video_at` in the layer.
3. It watches `layer_playing(video)`. When the clip ends, it calls
   `layer_remove(layer_stack, video_layer)` and the HUD comes back.

```
site layer_add        0x...    # add(stack, layer, priority)
site layer_remove     0x...    # remove(stack, layer)
site layer_video      0x...    # request(video, &name, loop)
site layer_playing    0x...    # playing(video)
data layer_stack      0x...
data video_layer      0x...
value clip_layer_priority 5
value layer_video_at  0x14
```

When a port has both, the layer route wins over clip v2 (and `clip_play` wins over both).
Emulator-proven on Deadpool LE 1.14 2026-09-25, in attract and in a game.

**Where a clip is on the glass today (2026-09-25).** In each of these, a mode's added title
card was seen in a game in the emulator:

- Through clip v2: Aerosmith, Avengers, Beatles, D&D, Foo Fighters, Guardians, JP LE, King
  Kong, Mando, Stranger Things, Sword of Rage, TMNT Pro 1.59, Venom and X-Men.
- Through `clip_play`: Godzilla (Pro 1.15, 1.16, Premium/LE) and Jaws.
- Through the layer: both Deadpools.

**More banks (item 164, 2026-09-25, each seen on the glass in a game):**

- A Video's SECOND list (`video_bank._marked`): clips with frame markers - a name and an id, and on
  the id's first occurrence an f32 fps and [u64 n] (u32 frame, marker name). Empty on Godzilla,
  whose bank walked by accident; Munsters ("EndOfBallBonus": Pause, Explosion), the Star Wars builds
  ("SW5_SCENE_001": MUSIC_START) and John Wick carry some. All 33 banks parse now.
- The bank the game DRAWS is not always 60ed7e50: the Led Zeppelins, Metallica and Rush draw a
  background bank, 914f6bd9 (their song and concert videos), over it; Bond LE's real bank is nested,
  6fb39344/60ed7e50 (the top-level one is a 989-byte stub); John Wick draws 08a4e1ca (413 clips).
  The port's `scene video_bank` names the one on the glass, and a clip goes there.
- A derived `site video_surface` getter that answers another surface is commented out (JP The Pin,
  John Wick): the runtime then finds the surface of the bank the port names.
- A one-clip bank keeps its clip at the top of scene.assets (`2.asset` itself); the next clip is
  `3.asset` beside it (`video_bank.next_path`).

Seen: Star Wars LE and ELG, the Led Zeppelins, Rush, Bond LE, John Wick, JP The Pin.

Not yet:

- Munsters and Iron Maiden: the clip plays in their one-clip background banks, but the HUD's own
  artwork covers the whole glass in a game; a clip would have to go in the HUD scene.
- Metallica: played on 914f6bd9, and the song video stayed in front.
- Bond 60th: no bank among the scenes it draws in play.
- Batman and Elvira: no 60ed7e50 bank; they play video through another player.

### Screens on every title (item 164)

A mode's own screen goes into a scene the game draws in play. Three things per build:

- **The runtime's finders**, in every port: `site find_node` and `site find_text` are the
  scene lookup's typed finders (Godzilla LE 1.16 `0x587bac` is the lookup; each of its
  callers casts what it found with `__dynamic_cast`, and the one casting to `Radium::Sprite`
  is `find_node`, to `Radium::Text` `find_text`). `value node_visible_vfn 0xa8` (Sprite slot
  42, one shape on every build) and `value scene_player_scene 0x10`.
- **Which scene.** Not the attract scene: one the game renders every frame of play. The
  instrument wraps every virtual of `RadiumScene` (the scene player class) with a counter per
  object and looks every auto_loaded scene up by id during a game; the scenes whose players
  were called are the ones drawn. On Godzilla it names the four HUD scenes item 131 found by
  hand. The pick: the score panel `9d578751` where a title has it, else `7b4db7ef`, else the
  busiest one that profiles. A nested scene is named `<parent id>/<child id>` (the lookup
  takes that form; the leaf alone or the parent is not found), and the mode file's
  `screen_scene` holds 95 characters for it.
- **Its profile**, read statically (`scene_write.PROFILES`, keyed by the stock file's md5):
  the root is the Sprite data whose walk ends exactly at the end of the file. Beyond item
  131's grammar the walk knows a node's colour keys (`[u64 n]` of u32 frame + 8 floats),
  Shape (`symbol | name | f32 x4 | f32 | its fill Bitmap, inline on first occurrence`), Video
  (`symbol | name | u32 w | u32 h | u8 | u32 | 2 x [u64 n](frame name, u32 asset)`, Batman 66)
  and a Text's per-line fonts (`[u64 n](u32 font) u8 u32`). A class the file never
  registered (Avengers' HUD has no Bitmap) is registered by the first screen inline, `u32
  FLAG|id` + its name, as the game's own files do. A profile with `append` puts the screen
  after the last root child (drawn last) instead of before it; object ids start above the
  file's own where no `FLAG|id` byte pattern appears anywhere in the file.

**What is proven.** In the emulator, one scripted game per build with a magenta panel: none
before the mode, the panel and its words during it (about 63,000 magenta pixels). Proven on
all 34 latest builds: Aerosmith, Avengers, Batman 66, The Beatles, Bond 60th, Bond LE,
Deadpool LE and Pro, D&D, Elvira 3, Foo Fighters, Godzilla LE and Pro 1.16, Guardians, Iron
Maiden, Jaws, John Wick, JP LE, JP The Pin, King Kong, Led Zeppelin LE and Pro, Mandalorian, Metallica,
Munsters, Rush, Star Wars ELG and LE, Stranger Things, Sword of Rage, TMNT LE and Pro 1.59,
X-Men and Venom. `mode_project.TITLE_SCENES` carries `screen_proven` for those; the tab offers a screen
only there. JP The Pin 1.05 draws one scene in play, 60ed7e50, which is also its video bank:
a build adds the clips to it first and the screens after them (`scene_write.add_screens(...,
stock=)` moves the stock profile past what the clips inserted), and its screen is a panel with
no words (the scene has no Text).

Per scene, what the proof runs taught:

- **Covered.** A scene drawn every frame can still lie under another (D&D's `e3ff23bf`, Venom's,
  SW LE's first pick): the next candidate was used.
- **Placed.** A nested scene the game places is not at the glass's origin: Deadpool's score card
  (`9d578751/7bae4376`) sits at 742, 424 and clips to itself, so Deadpool uses
  `c3328c39/0d167902`. `SceneProfile.origin` moves a screen for a scene whose (0, 0) is not the
  glass's, and centres the 640x160 panel on the 800x480 glass of Star Wars ELG and Bond 60th.
- **No words.** Bond 60th's frame (`91b06583`, drawn over everything in play) has no Text and so
  no font: its screen is the panel alone (`font=None`), and the runtime logs `(text missing)`.
- **Nested ids.** `screen_scene` was 48 characters, so a nested id was cut and the screen was
  drawn (authored visible) but never found, shown or hidden: now 96.

### Ports in the Modes tab

The app's Modes tab makes modes as files (`mode_file.c` runs them), and it reads these
same port files: `mode_project.profile_from_port()` turns each one into the title's
profile. The tab finds the project's card (the extract's record of it, or the project's
stock image; a renamed card is read from its own `/spk/index/<game>-<version>.sidx`) and
uses the port whose `game` and `version` match. A card with no port gets a message
pointing here. What each part of the tab needs from the port:

| Tab section | Needs in the port | Also needs |
|---|---|---|
| Starts on, Shots that score | `shot` lines (and `shot_mask_bits` when the game sends 32 bits), and `switch` lines with a `switch_hit` site | a port not in `SWITCH_SHOTS_PROVEN` says its switch shots are not proven |
| Examples | `text example_start_shot` | Godzilla's ready-made modes appear wherever every shot they name exists |
| Sound: count down | the `callout` and `callout_nth` sites, and `callout countdown` | `callout ten_seconds` adds the call at 10 s; without it the count is 5..1 only. `value countdown_first <n>` when the request's list opens with something else: the clip "one" is in (Iron Maiden 1.16's 351 opens with a sting, so 1); `pm_callout_nth` adds it to any clip asked of the countdown role. `value countdown_step <n>` when every number is a request of its own: `callout countdown` names the "one" request and the others follow it by that step (Star Wars ELG 168, Munsters, Jurassic Park Pin, Batman 66 1061 count down the ids; Led Zeppelin, Sword of Rage count up; Bond 60th 542 steps by 2, each number in two voices). `value countdown_stride <n>` when one request holds every number in several voices, number by number: the clip for the count is `n * stride + countdown_first` (Deadpool LE 962 / Pro 967: five voices each, "ten" first, so first 5, stride 5) |
| Sound: the game's own call | `callout time_up` | without it nothing plays when time is up |
| Sound: my sound | the `sound_lookup` site and `callout time_up` (the call it replaces) | a time-up request with variants (Guardians' 254: "Time's up." / "Your time is up!" ...) gets the sound in place of every variant, so whichever the game picks plays it |
| Lights | everything `pm_can(PM_CAN_LIGHTS)` needs, including `value light_owner`, and `value light_lts` (the game's light language); or, item 164, the named-insert lines (`PM_CAN_LAMPS`) on a build in `mode_project.LAMPS_PROVEN` | through the inserts the tab writes `light_all <colour> pulse`: every insert the port names breathes in the mode's colour while it runs |
| Screen | everything `PM_CAN_SCREENS` needs, and `scene hud` | the HUD scene file MEASURED: its md5 has a `scene_write.py` profile |
| Clip | everything `PM_CAN_CLIPS` needs, and `scene video_bank` | the bank measured in `mode_project.TITLE_SCENES` and an added clip seen on the screen |
| The game's own modes (`stack`) | the `stock_battle_running` and `stock_multiball_running` sites and `data stock_mode_manager` (see "The game's own modes") | without them a `stack no` mode logs that the port cannot tell, and starts anyway |
| From a film: Clip, Picture, Sound | what Clip, Screen and "Sound: my sound" need | each button is greyed where its section is |
| Starts and ends: An event | `event` lines (see "Events"): a bus event needs `site hook_dispatch`, a site event its own site, as `events_arm` arms them | a mode on a title without the event its file names is refused at build |
| Advanced: points per shot, ends early when hit | `shot` lines | the title's own shots, as under Shots that score |
| Advanced: callouts, Pick | `callout ten_seconds` and `callout time_up` | any other id is typed by hand |
| Advanced: second clip | what Clip needs | greyed where Clip is |

Where a port lacks one, the tab greys that section and says why in words, and the build
leaves its lines out of the mode file (Advanced's second clip too). A port whose opening comment says `NOT RUN` is
shown as unproven. The build ships the title's port beside the mode files as
`game.port`. The CARD decides the title, not what a `mode.json` says: a mode made before
its project knew its card (every mode made before this section existed says Godzilla Pro
1.15) is matched to the card's port by shot name at build time, so a Premium 1.16 card
gets `godzilla_le-1.16.port` and Premium's masks. A mode naming a shot the card's game
lacks, or a card with no port, is refused rather than built with shots left out. A
project that names no card builds each mode for its own title, and on a card with no port
the tab shows each mode read-only with the shots of the game it was made for. Opened in the
tab on its card, such a mode shows the card's shots and says which it lacks (and which shot
now starts it); its file stays as it was, and the build keeps refusing it, until the person
edits the mode there. Advanced's fields follow the same rule: a per-shot award or an
early-ending shot on a shot the card's game lacks is dropped from the form, and a callout
id made on another title is kept only where both ports name that callout alike (Godzilla's
ten-seconds call 1291 becomes Jaws's 1387); any other id is dropped, since the same number
plays some other sound on another game, and the build refuses the mode until it is edited -
unless the two builds are ONE title (`mode_project.same_title`: another version, or the Pro beside
the Premium/LE), whose sound table numbers its calls alike, so every id is kept: each callout the
Pro and LE ports of Godzilla 1.16, TMNT 1.59 and Led Zeppelin 1.22 measured has one id on both, as
do Godzilla Pro 1.15 and 1.16. Today: Godzilla Pro 1.15 and Premium/LE 1.16 have every section; Jaws LE
1.02 has no lights (no light owner) and no screen (its score panel is not measured), and
has clips (a title card added to its bank played on the glass in the emulator); TMNT Pro and
Deadpool Pro have shots and scoring only, Deadpool LE 1.14 events too. The Beatles 1.29 has shots (its own and from
switches), 32-bit scoring, the countdown and events; lights, screen, clip, a sound of the
mode's own and `stack` are greyed. Only the two Godzilla ports name the game's own mode
queries, so `stack` is greyed on every other title, and only they, The Beatles and Deadpool LE carry
events, so "An event" is greyed on every other title.

**Copying modes to another card's project (Copy to..., under the list).** A mode is not tied
to a build: `mode_project.copy_modes(src, dest)` copies every mode folder of one project (picture,
clip and sounds too) into another card's project and matches each to that card's title exactly as
opening it there would (`retarget`). A mode that loses nothing is saved for the title, so it builds
there as it is; one that names a shot the card lacks is copied as it was, so a build there keeps
refusing it until it is opened and its shots picked, and the report (a message box, and a log line
per mode) says which and why in the tab's own words (`retarget_words`). Code modes are copied as
they are. So a Premium project's modes move to the Pro, or from 1.58 to 1.59, in one pass; what
decides how clean the move is is the two ports' shot NAMES: the Pro and LE ports of Godzilla 1.16,
TMNT 1.59 and Led Zeppelin 1.22 name their shots alike, Deadpool LE has three the Pro lacks, and a
shot a port leaves unnamed (`Shot 0x..`) never matches.

### Making a port for another game or version

1. **Get the game's program.** It is `<game>/game` on the card's games partition; the app's
   Partitions tab, or `CardImage.extract_file`, copies it out.
2. **Draft the port** from one that works, ideally the same game in another version:
   ```bash
   python3 port_tool.py <reference game> ports/godzilla_pro-1.15.port <new game> \
       -o ports/<game>-<version>.port --game <game> --version <version>
   ```
   - **Functions** are found by the shape of their first instructions, by the functions
     that call them, by the event hook whose handler calls them, or (for library calls) by
     the imported name. A loose shape match is only kept if the hook agrees; where a
     target's hook handlers disagree, both are listed as candidates. Prove the one you pick
     by draining a ball (step 5).
   - **Globals** come from lining up the code that loads them, in two places that agree. Two
     globals may be placed from one (`ONE_PLACE_DATA`, each with its reason on its draft line):
     `layered_displays`, which the program loads in one place only, and `display_effects`, which
     the runtime uses only when it points at the manager of `award_screen_arg`'s table.
   - **Shots, callouts and struct offsets** are copied, and the draft marks them unverified.
     For another title, shots, callouts, examples and the title values are left out instead.
   - An entry it cannot place is left as a comment saying why, and the runtime treats that
     capability as absent. Under it are **candidates**: the calls the reference function
     makes that the new game also has, or for a scene the first id after the same
     neighbouring strings. A candidate is a lead, not a placement. Read its code first.
   - Exit 1 means a core function is missing, and the runtime would hook nothing.
   - **A function the tool cannot place:** find the class it belongs to in both games
     (`rtti_tree.py` lists each class's virtual functions) and compare the slots. Jaws's shot
     dispatch is virtual 11 of `cmode_manager`; its only caller is the shot handler. Callout
     ids are set by the game's timed-mode class (`cmode_timed`) as three 16-bit fields.
   - **When nothing lines up, measure.** `call_probe.c` hooks every virtual of a class and
     logs each call's arguments; press switches between timestamped marks and read which
     function answered. This found TMNT Pro's shot dispatch (one call per press, the bit in
     r1) and its end of ball (a broadcast 0.6 s after a drain):
     ```bash
     python3 probe_sites.py <game> crule_manager --first <tick address> -o probe.sites
     bash build_mode.sh -p -o probe.so call_probe.c
     # preload probe.so instead of a mode, with probe.sites at /dump/probe.sites; then for
     # each switch:  echo "$(date +%s%3N) mark <id>" >> /dump/probe.log; wait 400 ms; press
     python3 probe_read.py probe.log <switch_list.txt>
     ```
     A drain tells end of ball from ball start: a broadcast right after the drain is the end,
     one about ten seconds later (after the bonus) is the next ball. Drain well into a ball:
     inside the ball saver the game serves the ball back and no ball ends.
3. **Check the words:** `python3 port_words.py <new game> <port>` must report 0 problems.
4. **Measure the shots.** Build `census_mode.c` with the draft port and start a game. Wait for
   `census ready` in the log first: a Start pressed before the game's first tick is ignored.
   For each playfield switch in `~/spike2root/dump/tables/<game>/switch_list.txt`, run
   `echo <id> > /dump/census.mark`, wait 400 ms, and press it (`swpoke.py <id> 150`). A shot
   logged before the press is credited to the switch before. Leave out flipper, trough,
   shooter lane, outlane and mechanism position switches. Write
   `echo end > /dump/census.mark` when you are done. Then:
   ```bash
   python3 shot_census.py ~/spike2root/dump/mode.log <switch_list.txt> --ref-port <reference port>
   ```
   It keeps the reference's name for a bit only when that switch's own name agrees, and
   flags a bit whose name must change as RENAMED. For another title, leave out `--ref-port`:
   every bit is then named after its switch. Spinners send several bits per spin; list one
   and say so in a comment. Rename bits in plain words ("TGT 1" becomes "Target 1").
5. **Prove it:** run `template_mode.c` on the new port in the emulator (the loop above), and
   **drain a ball while it runs**: the log must say `END (ball ended)`. A mode that only ever
   ends on its timer has not proven the end of ball. Drain after a minute of play, not in
   the ball saver's first seconds. Then note in the port file which copied entries the run
   exercised and which it did not.
6. **It shows up in the Modes tab by itself** once the file is in `ports/`: a project on that
   card offers its shots. Screen and Clip also need the title's HUD and bank scenes measured
   (see "Ports in the Modes tab").

## Events: starting a mode on what the game does

A shot is not the only thing that can start a mode. The game's rules talk to each other
through numbered **events** (a ball started, the bonus began, the player tilted), and a
mode can react to them:

```c
static void on_event(unsigned id)
{
    if ((int)id == pm_event("ball_start") && pm_begin()) start();
}
static const struct pm_mode my_mode = { .name = "BALL RUSH", .tick = on_tick, .event = on_event };
```

- `pm_event("name")` is the event's id on this game, or -1 when the port does not name it
  (or has no events at all: `pm_can(PM_CAN_EVENTS)` is 0).
- `.event` gets only the events the port names, once per firing, **on the tick thread**,
  within a tick of the game's own broadcast. It is never called from inside the game's
  broadcast, so it may call anything a tick may.
- An event is counted when the game sends it, whether or not one of the game's own
  handlers then stops the rest (the bus lets a handler veto).

A mode FILE (the Modes tab's) says the same with two keys; a file without them behaves
exactly as before:

```
starts_on  shot                  the trigger line's shots (the default)
starts_on  event ball_start [N]  the N-th time it fires, per player, across a game
ends_on    drain                 its clock, or the ball ending (the default)
ends_on    clock                 its clock only: it runs on into the next ball
ends_on    event multiball_end   that event, its clock, or the ball ending
```

A mode that starts on an event has no `trigger` line, so a `mode.so` older than events
logs the file NOT VALID instead of starting it on a shot. If the event fires while the game
does not count as in play yet (`pm_in_game()` is 0), the start is retried for 3 seconds.

### Events in a port

```
site  hook_dispatch    0x004bb42c 0xe35000cf 0xe92d4038   # the bus's dispatch(id, arg)
event ball_start       0x25                               # a bus id, 0..207
site  mball_start      0x000d521c 0xe92d40f8 0xe1a04000
event multiball_start  site mball_start                   # a CALL of this site is the event
```

The bus is two functions: `subscribe(_, id, handler, priority)` keeps a list of handlers
per id, and `dispatch(id, arg)` calls them in order. Both start `cmp rN, #207; push`. Some
things a title does are never broadcast (Godzilla's skill shot award, a multiball's
start): for those the port names the function whose call is the event. Each is optional;
a port without them simply has no events.

**Godzilla Pro 1.15** (`godzilla_pro-1.15.port`), measured with `event_probe.c` in one
marked game (item 147, run1): each bus id fired in exactly these moments of the game and in
no other. A second game (run2) ran the runtime with these lines: a mode file with
`starts_on event ball_start` started on the Start, and one with `starts_on event
multiball_start` / `ends_on event multiball_end` started and ended on those.

| Event | Id | When it fired |
|---|---|---|
| `game_start` | bus 0x4d | the Start that began the game (0x4e fires 15 ms before it) |
| `ball_start` | bus 0x25 | at the Start, and about 12 s after each drain (after the bonus); not after the last ball. A player is up and `pm_in_game()` is already 1 |
| `ball_end` | bus 0x34 | every drain that ended a ball, and the tilted ball's |
| `bonus_start`, `bonus_end` | bus 0x27, 0x28 | 20 ms after a drain's end of ball, and 12 s later; not after a tilt |
| `tilt_warning` | bus 0xc8 | the first two tilt pendulum hits |
| `tilt` | bus 0xc6 | the third hit |
| `game_over` | bus 0x47 | the last ball's drain, and never before it |
| `skill_shot` | site: RuleSkillShot's award | 0.5 s after the skill shot switch was hit right after the plunge; not for a hit 15 s later. No bus id tells those two apart |
| `multiball_start` | site: `cmode_mball` start | a forced godzilla multiball (its start screen was on the glass); every multiball's start calls it. No bus id of its own |
| `multiball_end` | site: `cmode_mball` stop | when that multiball stopped, which in the emulator was at the end of its ball, not when two of three balls had drained (see below) |

On Pro 1.15 the bus runs on the tick thread while a game is played, and it is busy (one id
fires about 2500 times a second), which is why the runtime's hook only counts.

**Godzilla Premium 1.16** (`godzilla_le-1.16.port`) carries the same ids and the same three
site events, at its own addresses. Two marked games with the runtime and the probe (item
147, run3c and run3d) proved these the same way as on Pro:

| Event | Proven on Premium 1.16 |
|---|---|
| `game_start`, `ball_start` | at the Start and in no other window; a mode file with `starts_on event ball_start` started in the same millisecond |
| `skill_shot` | within 50 ms of the skill shot switch closing right after the plunge; not for a hit 11 s later |
| `multiball_start` | a forced godzilla multiball while ball 1 was in play (its start screen was on the glass); a mode file started on it |
| `multiball_end` | when that multiball was stopped by hand (`echo "stop 1" > /dump/event.force`). That was the probe calling the stop function itself, so it proves the hook on the function, not that the game calls it when a multiball ends (on Pro 1.15 it was the game's own call) |
| `tilt_warning`, `tilt` | the first two pendulum hits, and the third |

`ball_end`, `bonus_start`, `bonus_end` and `game_over` are in the port because the functions
that send them match Pro's, but no run on Premium 1.16 measured them. In run3c a drain
about 50 s after the plunge, after only four switch hits, did not end the ball, so a ball
only ended on the tilt and the game then waited on TILT. A control boot of that sequence
with no event lines and no mode files did the same, so the event hooks are not the cause. Another Premium
1.16 boot that night did end balls on drains after about 46 switch hits per ball (item 150,
run1), so to measure these events, play that switch pass before each drain.

### Measuring events on another game

1. Write a sites file for `event_probe.c`: the bus (search the game for `cmp r1, #207;
   push` followed by a malloc of 12 bytes, and `cmp r0, #207; push`), the port's tick, and
   optionally cmode_manager's get and singleton to force stock modes on and off. Fill its
   words with `port_words.py <game> <sites> --write`.
2. `bash build_mode.sh -p -o event_probe.so event_probe.c`; preload it (as a mode, or
   through `PAD_TRACE_SO` beside a mode) with the sites at `/dump/event.sites`.
3. Play one game and mark each moment: `echo <label> > /dump/event.mark`, then do the
   thing (Start, a drain after a minute of play, three tilt hits, a skill shot press right
   after the plunge and a control press later). `echo 1 > /dump/event.force` starts stock
   mode 1, `echo "stop 23" > /dump/event.force` stops mode 23.
4. `python3 event_read.py event.log --callers <armxref.py args output> --diff skill skill_late`
   lists the ids of every window without the background ones. Name an id only when it fires
   in every window it should and in none it should not, and keep the control windows.
5. For what no id marks, find the function (`rtti_tree.py`, `armxref.py xref`) and add it
   to the sites file as `site watch_<name>`: its calls are counted per window like an id.

### What is not measured

- Extra ball, ball save, match and replay: no run earned one.
- A stock mode's start or end as an event: forcing tesla strike on and off dispatched no
  bus id of its own.
- Multiball on a natural start (locks), and add-a-ball: only a forced multiball has run.
  Nor is `multiball_end` measured on a multiball draining down to one ball: in the emulator
  the forced multiball kept asking for balls until its ball ended, so it stopped then.
- On Godzilla Premium 1.16: `ball_end`, `bonus_start`, `bonus_end` and `game_over` (see
  above), and a multiball that stops by itself (the game's own call of the stop function).
- Games with more than one player: every run was one player.
- The event's argument: `.event` gets only the id.
- Every other title and version, until a marked game names its ids.

## Reading the log

`/dump/mode.log`. The runtime writes `[pad]` lines and your mode writes `[<its name>]`
lines:

| Line | Meaning |
|---|---|
| `[pad] port /dump/game.port: godzilla_pro 1.15, 24 sites, 12 shots` | the port was found |
| `[pad] site X 0x...: expected ... found ...` | that function differs in this build; its capability is off |
| `[pad] site X 0x...: not in the game's code - not read` | the address is outside the game's code: a port for another build |
| `[pad] core site X: not in the port` | the port lacks a core part and its alternative |
| `[pad] NOT THIS GAME'S PORT ...` | wrong port: nothing hooked, the game runs stock |
| `[pad] armed: 1 mode(s); can callout lights screens clips ...` | running; this is what this game can do |
| `[pad] scores: 32-bit (...)` | the port's scoring pair is the 32-bit one |
| `[pad] switch shots: ...` / `switch shots off: ...` | the port's `switch` lines, and whether a `switch_hit` site was hooked |
| `[TARGET RUSH] ...` | your `pm_log` lines |
| `[TARGET RUSH] not started: X is running` | `pm_begin()` refused; another mode is up |
| `[mode] <name> not started (trigger shot): a battle is running` | a `stack no` mode file waited for the game's own battle (or multiball) |
| `[pad] stock modes: can tell battle multiball any` | the first stock-mode question; which kinds this port can answer |
| `[pad] lamps: 88 named inserts (24 tied to a shot)...` | the port's `lamp` lines were read; `the game counts 592 lights` once the game has counted them |
| `[pad] lamps: our layer at priority 255; the game's layers now ... (* ours)` | the first hold made the mode's lamp layer |
| `[pad] lamps: N insert(s) held (...)` / `handed back to the game` | a hold, a release |
| nothing at all | no port found, or this process is not the game (normal for the game's helper processes) |

## When something goes wrong

| You see | Look at |
|---|---|
| the game never boots, or restarts at boot | the last `[pad]` line; a crash inside `init` is your code (a NULL you did not check?) |
| the mode never starts | log the shot masks in `.shot`; check `pm_in_game()`; check `pm_begin()` did not refuse |
| points never arrive | `pm_score_add` returns what was added; the game adds nothing in some states (tilt, a menu) |
| your screen is on the glass all game | you never called `pm_show(node, 0)` in `init` |
| the screen is never found | the build did not add it, or the name differs; the Modes tab names screens `PadMode_<folder>_Screen` |
| a clip never shows | `pm_clip` returned 0: the clip name is not in this game's video bank, or `pm_can(PM_CAN_CLIPS)` is 0 |

## A checklist for writing a new mode

1. Copy `template_mode.c` to a new file, and rename the `struct pm_mode` and `.name`.
2. Decide what starts it: a shot (`pm_shot("...")`, a name from the game's port) and how
   many hits. Count per player, and reset the counts in `.ball_end`.
3. In `.shot`, while not running, count starting shots; at the target, `start()` with
   `pm_begin()` first.
4. In `.shot`, while running, score only the running player's shots with `pm_score_add`.
5. In `.tick`, count down, make the callouts, and end on time, when `pm_in_game()` goes
   false, or when the player changes.
6. In `.init`, resolve names to masks once and log what you found. In `.tick`, find and
   HIDE your screen as soon as `pm_node` returns it.
7. End cleanly everywhere: lights off, `pm_end()`, and the screen hidden a few seconds later.
8. Build, run the loop, read the log, change, repeat.

## The game's own modes: what is data and what is code (item 144)

A mode the game shipped with is compiled C++, not a file: one `cmode_*` class per mode, one
static object per mode built by `cmode_manager`'s constructor, and virtual functions that call
the engine. So "change a stock mode" means changing numbers inside the game program, and a
number can only be changed in place if it is ONE WORD the code loads. This section is the
format a stock-mode table is written in (the app's editor reads it), how the table is read off
a game ELF, and where the lines are.

### The table format (format 1)

One fact per line, whitespace-separated tokens, `#` starts a comment to the end of the line.
A table is one or more BUILD BLOCKS, each starting with a `build` line; every line after it
belongs to that build until the next `build`. VAs are ELF virtual addresses (hex, `0x`); the
ELF's program headers give the file offset. Unknown values are `?`; a fact nobody has read is
not written at all, or is written with `not measured` in its comment.

```
build   <game> <version> sha1 <40 hex>
mode    <id> <class> obj <va> vtable <va> title_msg <msg id|?>
ctor    <id> a <n|-> award <n|-> b <n|-> timer <n|->
start   <id> <how, free text to the end of the line>
number  <id> <key> <value|?> <kind> <words> <class> [shared <n>] [seen <run>]
callout <id> <request id> <key> <kind> <words>
scene   <id> <40-hex scene id> <kind> <words>
clip    <id> <name> <kind> <words>
lights  <id> <owner|?> <text to the end of the line>
shots   <id> <mask hex> <what, free text>
```

- **`<kind>`** says where the number lives, and has a fixed arity so a parser knows where it ends:

  | kind | tokens | the word(s) | a new value must |
  |---|---|---|---|
  | `imm <va>` | 1 | `mov rd, #imm` (or `mvn`): an 8-bit value rotated by an even amount | encode the same way (`stock_modes.encodable_imm8`) |
  | `movw <va>` | 1 | `movw rd, #imm16` | be below 65536 |
  | `movwt <va> <va>` | 2 | `movw` then `movt`, one register | fit 32 bits |
  | `lit <va>` | 1 | a literal-pool WORD (the va is the pool word, not the `ldr`) | fit 32 bits |
  | `data <va>` | 1 | a word in `.data`, read through a loaded address | fit 32 bits |
  | `adj <AD_NAME> <adj id>` | 2 | `get_adjustment(id)`: the operator's setting | be changed as an adjustment, not in code |
  | `code <va>` | 1 | computed by the instructions at and before va | be changed by a hook or a cave |

- **`<words>`** are the stock words at the kind's VA(s), 8 hex digits each, comma-separated (the
  stored word for `lit`/`data`; the instruction that loads the id for `adj`; `-` for none). An
  editor MUST compare them before writing and refuse a build whose words differ.
- **`<class>`**: `word` = one or two words, safe to patch in place (then refresh the game ELF's
  `.sidx` record); `adjustment` = the operator owns it; `code` = not one word; `scene` = the
  content lives in a scene file.
- **`shared <n>`**: the word sits in a function `n` mode classes use (a base-class virtual), or
  in a literal-pool word several instructions load. Changing it changes all of them.
- **`seen <run>`**: the value was also watched live in that emulator run (a log line).
- **`<key>`** names what the number is, `<role>.<call>[.<arg>]` with `@2`, `@3` for repeats in
  one mode: role = the virtual it is in (`start` v[8], `shot` v[41], `end` v[10], `stop` v[11],
  `reset` v[3], `ball_end` v[4], `start_display` v[42], `total_display` v[43], `timer` the
  duration virtuals of `cmode_timed` (v[56]/v[57] on Pro 1.15), else `v<k>`), call = the
  engine call (`caward_add`, `callout_play`, `show_start`, `ctimer_get`, `get_adjustment` ...),
  arg = which argument. Three keys stand alone: `title_msg`, `audit_started`, `audit_completed`.
  Slot numbers are per build (Premium/LE has one more slot at every `cmode` level), which is
  why the key carries the ROLE and not the slot.

An example block (Godzilla Pro 1.15, tesla strike, proven in the emulator by item 144):

```
build godzilla_pro 1.15 sha1 08d502998706d327bfbb6ea5f92ac0cee76be63b
mode 23 cmode_tesla_strike obj 0x7a2878 vtable 0x6307b8 title_msg 3242
ctor 23 a 0 award 30 b 9 timer -
start 23 start: RulePowerlines' shot handler 0x1666fc, cmode_manager_get(23) at 0x166810 then v[8]
number 23 start.caward_add 250000 movwt 0x10c228 0x10c234 e30d2090,e3402003 word seen runA
number 23 start.award_value ? code 0x10c1a4 - code   # 2,000,000 x level, folded into shifts
```

### How a table is read (the method)

1. **Get the game program** read-only (`CardImage.extract_file`, partition 2, `<game>/game`).
2. **Run the tool:** `python3 stock_modes.py <game ELF> --json out.json > table.txt`. For any build
   other than Godzilla Pro 1.15 add `--ref <Pro 1.15 game ELF>`: the engine calls (`caward_add`,
   `get_adjustment`, `show_start` ...) are then located by port_tool's masked signatures, and each
   base-class slot is mapped to its slot on this build.
   - The **mode objects** come from `cmode_manager`'s constructor: every guarded static object is
     `ctor(obj, id, a, award, b[, timer])` followed by `__aeabi_atexit(obj, destructor)`, and the
     destructor is slot 0 of exactly one class's vtable.
   - Each class's vtable is compared with its base's (an abstract base through its `<base>_null`
     twin, which keeps every slot the base implements). Only the slots it OVERRIDES are its own
     code; a number found in a function several classes hold is marked `shared`.
   - In every overridden function a linear constant tracker follows r0-r3 and the outgoing stack
     slots through `mov`/`movw`/`movt`/`ldr =lit`/`add`/`str [sp]`, forgets a register at every
     call, and keeps a value across a branch target only when every way in agrees. At each engine
     call it prints the constants the call receives, with the words they came from. A value it
     cannot follow is `code`, never a guess.
   - `cmode_timed`'s start hands v[56]() to the timer as the duration (v[57]() to timer v[18]);
     when a class keeps the base's 30 s the compiler inlined `moveq #30` copies into the base's
     reset and start, so the tool lists every site.
   - Display layers `BDL<Mode>Start/BG/Total` are paired with their mode by name; the strings
     their own virtuals load are the mode's clips.
   - `start` lines: every `cmode_manager_get(mgr, id)` whose result's START (v[8]) is called.
   - **Selector tables**: runs of 12-byte `{slot, mode id, 0}` entries. Godzilla's battle select
     screen starts `entry[index].id` from one (Pro 1.15 `0x631f44`, LE 1.16 `0x64272c`: 12, 13, 14,
     15, 16, 6, 17), and it is the ONLY start path of battles 6, 16 and 17, so a mode with no
     constant-id start line is worth a search for its id in such a table.
   - **Shots**: cmode's START sets the lit mask to `v[44]()` (r0:r1). When v[44] is a constant the
     tool prints `shots <id> <mask>` and the two halves as numbers; a mode whose own v[8] writes the
     mask after START (tesla strike: `0x48_00700000` from two `mov` words) needs a read of that v[8].
   - **Scenes are not in the mode's code.** A 40-hex scene id is built once into a global by the
     static initialiser (`.init_array`) of the source unit that uses it. To name a mode's scenes:
     (1) walk its display layers' base classes (`BDL<Mode>Start` <- `BDLModeStart`, `BDL<Mode>Total`
     <- `BDLModeTotal`, `BDL<Mode>BG` <- `BDLModeBG`), (2) find the 40-hex load that sits between
     that class's own functions (the unit), (3) confirm with the node names inside the scene file on
     the card (`CardImage.extract_file`, then printable strings of `scene.radium`). On Godzilla ten
     modes' start screens are ONE template scene (`6b877640`, "MODE TITLE"), five modes' totals
     another (`6a22f74b`), and every background plays its clip by name on the video bank
     `60ed7e50`; only a few modes own a scene (hedorah `56fadc8a`, monster rampage `7949bb14`).
3. **Watch it live** to confirm and to fill what the desk cannot: `modes/padmode.c` (Pro 1.15)
   logs `STARTED`/`STOPPED` with the caller, every `caward_add` value with `lr`, callouts, shows,
   events and message lookups, and its `padmode.start "<id>"` trigger starts any mode. A table
   value whose `lr` in the log is the table's call site + 4 is `seen <run>`. On another build use
   `call_probe.c` on the sites the table names.
4. **Compare builds** by key: the keys carry roles, so two builds' reports line up key by key
   (Godzilla Pro 1.15 against Premium/LE 1.16: 366 of 367 keys the same value and kind, the one
   extra LE key a vtable-tail artefact).

### Where the lines are

- **One word, in place (safe).** A number the code loads as a constant - `imm`, `movw`, a
  `movw`+`movt` pair, a literal-pool word, a `.data` word - in a function only that mode uses.
  Check the stock words, keep the encoding (an `imm` holds only a rotated byte, a `movw` only
  16 bits), write the word(s), and refresh the game ELF's `.sidx` record (valpatch's
  `compute_writes(fw_overlay=...)`, as the app's program-text Write does). Examples on Godzilla:
  every mode's start award, jet fighter attack's timer, title message ids, audit ids, callout /
  show / event ids passed as constants, which existing clip a total screen names, which shots a
  start lights (v[44]'s one or two words), which battle each slot of the battle select screen
  starts (one word per slot in the table the screen copies when it is built).
- **The operator's (not code at all).** A number read through `get_adjustment(id)` - most mode
  timers, ball saves, rampage scores. The ELF holds only the default; the machine's NVRAM holds
  the live value, keyed by caption. Change it in the menu, or change the default with the
  adjustment editor and know that a machine keeps what it has stored.
- **Code: a hook or a cave.** A computed value (a level times a constant folded into shifts, a
  hit count, a jackpot), a value read from a field or shared by many modes (the 30 s timer
  default is five words), a start CONDITION, which shots count, what one mode does to another.
  Do it at run time with a `mode.so` hook on the function (item 125's `pad_hook` trampoline, the
  way `padmode.c` hooks `caward_add`), or with a code cave (new instructions and a branch to them:
  a real code edit, with its own relocation checks and the record refreshed).
- **A whole-scene job.** What is on the glass: clips (the video bank, `video_bank.py`), screens and
  art (scene files, `scene_write.py`), sounds (`image.bin`). The mode code only NAMES them, so
  pointing a name at another existing asset is a word; making a new one is a card-file job.
  Stock scenes are SHARED templates (Godzilla: one start scene for ten modes, loaded once by the
  base layer's unit), so editing one changes every mode that uses it; a different screen for ONE
  stock mode is a new scene plus code that shows it (item 131's own-screen route), not a word.
- **Proven: a one-word edit plays (item 144, emulator-proven on Godzilla Pro 1.15).** On a card
  copy, tesla strike's start award (`movwt 0x10c228 0x10c234`) 250,000 -> 1,250,000 and jet fighter
  attack's timer (`imm 0xb75c0`) 20 -> 10, with the validator bypass and the game ELF's `.sidx`
  record refreshed (`valpatch.compute_writes(fw_overlay=...)`). The game booted and played with 0
  segv and no validation screen; `caward_add ... v=1250000 lr=0x10c244` on a natural and a forced
  start, the score took 1,250,000, the TESLA STRIKE TOTAL screen read 1,250,000 (stock: 250,000),
  and jet fighter attack reached its timer expiry in 22,333 ms (stock: 33,432 ms). Also measured:
  a timed mode's clock holds while no ball is in play (o2 destroyer's countdown stopped after the
  drain, and ran out with a ball in play).

## A monster in the roster

Godzilla picks its battles on the BATTLE SELECTION screen: the flippers move between seven
monsters and the Action button picks one. A mode can take one of those places, so that picking
that monster starts your mode instead of the game's battle.

**The roster cannot grow; a slot can be taken.** The seven slots are fixed in the game's compiled
code, not listed in data: the battle rule copies a table of exactly seven {slot, mode id} records,
the screen and the rule check the slot number against 6 and 7 in more than a dozen places, and the
screen's scene has exactly seven pictures, tiles and names (the evidence, with addresses, is in
item 146's entry in `plans/TODO.md`, and `tests/test_spike2_mode_roster.py` reads it out of the
program). Adding an eighth would mean moving that table and rewriting every one of those checks.

**Claiming a slot.** In C:

```c
static int on_pick(unsigned slot)
{
    if (!pm_begin()) return 0;      /* 0: the game's own battle runs */
    start_my_mode();
    return 1;                        /* 1: the battle does not start; your mode is the battle */
}

static void stop_my_mode(void)
{
    pm_end();
    pm_roster_done();                /* the ramps light again: another battle can be qualified */
}

static void on_init(void) { pm_roster_claim(0, on_pick); }   /* slot 0 is Ebirah's */
```

One thing the example leaves out: `on_pick` runs while the selection screen is still closing (it fades
and plays an intro clip for about 2.4 s), so a start screen shown inside `on_pick` is never seen. Start
the mode, or at least show its screen, about 3 seconds after the pick, from `.tick`; the mode-file
interpreter does that with the port's `roster_start_after_ms` (below).

In a mode file, one line: `roster_slot 0`. A mode with a roster slot needs `seconds` but no
`trigger`; it can have both. The value must be a slot number: `roster_slot -1`, a word, or a number
above 15 is logged and ignored (a slot the game does not have, 7-15, is logged as out of range).
`trigger <shots> 0` still starts nothing, as it did before the key existed: only the pick does.

Slots on Godzilla (Pro 1.15 and Premium 1.16): 0 Ebirah, 1 Titanosaurus, 2 Gigan, 3 Megalon,
4 King Ghidorah, 5 Megalon & Gigan, 6 King Ghidorah & Gigan. At the start of a game only some are
open; the others show as locked and the cursor skips them.

**What happens on a pick.** `on_pick` runs on the game's thread at the moment the battle would have
started, after the screen has closed its timer and played its pick sound. If it returns 1, the
battle's start never runs and the runtime clears the player's "battle qualified" state. The ramps
stay dark, so while your mode runs no other battle can be lit and the scoop opens nothing, just as
during one of the game's own battles. When your mode stops, call `pm_roster_done()`: the battle rule
then does what it does when its own battle stops, and the ramps light again. The mode-file
interpreter does this for you.

**The city counts it (fix-2).** When one of the game's battles stops, whatever the outcome, the battle
rule also marks it in the city the player is in: the cities rule keeps a mask per player per city,
bit 0 tank attack, bit 1 the battle, bit 2 bridge attack, bit 3 tesla strike, and a city whose four
bits are set is complete (the rule then posts that city's event). `pm_roster_done()` makes the same
call (bit 1, the player's current city) when the port has the `roster_city_*` lines, after checking the
city index against the city table, and logs `[pad] roster: the pick counts as the battle of player N's
city C (its mask x -> y)`. So a mode in a slot sets the same bit in the city's mask as the game's battle
would have. It does not do the other things only the game's battle does: which battle the city holds (the
battle's start writes it; a pick leaves it 0), a per-city byte at +92 that the stop sets only when bit 4
of the battle's flags is set (probably "won"; not measured), what the stop does after setting the bit
(Pro 1.15 `0x122d14` on: a branch for the first time the bit is set, and a per-player byte at +135; not
read), the battle's audits and its champion. A pick that is given back without the mode running (it
could not start, or the ball ended first) is counted too.

`pm_roster_done()` is guarded, because the rule's "battle over" acts on whichever player is up (and,
outside a game, on fields that belong to player 4). It acts only on a pick a mode took and has not
given back, and only while the player who picked is up. Called while another player is up, it waits
and happens on the first tick that player is up again; after the game has ended it does nothing (a
new game lights every player's ramps). Called with no pick held, it does nothing and says so. A mode
that took a pick and never calls it gets it called at the end of that ball.

What the mode-file interpreter does with a pick of its slot:

- its mode is not running and nothing else is: the pick is taken and the mode starts, at once or
  after the port's `value roster_start_after_ms` (see below);
- its mode is already running (started by its trigger): the pick is taken, nothing restarts, and
  the mode's END gives the pick back;
- another mode of ours is running: the pick is taken and the mode starts when that one ends;
- the mode cannot start (item 139's `starts`/`cooldown`, item 140's `stack no`, a mode in C holding
  `pm_begin`), the ball ends first, or the player changes first: the pick is given back
  (`pm_roster_done`). The slot's stock battle never runs under the new name and art.
- a mode running on a pick ends when its ball ends even with item 147's `ends_on clock` (logged as
  `ends_on clock ignored`): running on into the next ball would give the pick back at the ball's end and
  light the ramps while it still ran. Started by its trigger and never picked, it runs on as usual.
  (Tested at the desk against the host-compiled interpreter; not run in the emulator.)

What the game does with a battle that a drain interrupts is different: it remembers it, and the next
lit scoop RESUMES that battle without opening the screen. A mode in a slot is not resumed; a drain
ends it (`.ball_end`), and the next lit scoop opens the screen again.

**Its name and picture.** The screen draws each monster from its scene (`auto_loaded/cac32730...`):
a colour tile (when selected), a grey tile (when not; all seven grey tiles are ONE picture), a large
portrait, a small name banner (katakana) and a name text. The card build replaces the claimed slot's
pictures in place (same size, re-encoded; in the grey sheet only the 4x4 blocks that slot's tile
touches, so the other six grey tiles stay byte-identical) and its name text in place (as long as the
name it replaces: EBIRAH has six letters), then refreshes the scene's record in the card's manifest.
Nothing in the game program changes. `tools/spike2_emu/modes/roster_entry.py` does this for slot 0
(`map`, `build --art <picture> --name MOTHRA`, `card --card <copy>`); the art is yours to supply.

**Its spoken name.** When the cursor lands on a slot, the screen plays that slot's callout, a sound
request id kept in the screen's own slot table (Godzilla: 1888 for slot 0, which says "Ebirah!"; 1918,
1894, 1910 for slots 1-3; 0 for slots 4-6), and it plays nothing for 0. So a claimed slot is made SILENT
when it is claimed, and the game's id is put back when it is released: the old monster's name is never
heard over the new picture. To give the slot a sound of its own, call `pm_roster_callout(slot, id)`
(only the mode holding the slot can), or put `roster_callout <id>` in the mode file (0-65535; no line
means silent). Before the first write the runtime checks that the table looks like one (every id below
0x4000, at least one set) and otherwise leaves it alone.

**Playing it in the emulator** (Godzilla Pro 1.15 and Premium 1.16, the same switch ids): the Left ramp (73) and the Right
ramp (81) light a battle ("BATTLE READY"); HOLD the Right Scoop (53) for about a second
(`swpoke.py 53 1500` - a 150 ms press does nothing) and the screen opens about 11 seconds later; the
Right Flipper Button (59) moves to the next open slot; the Action Button (34) picks. The screen picks
by itself when its 13 seconds run out.

**The port lines** (Godzilla only; a port without them has no roster, and `pm_roster_slots()`
returns 0):

```
site roster_start      0x001220b8 ...   # where the battle rule calls the picked battle's start (r0 = battle, r1 = its mode id)
site roster_done       0x00122014 ...   # the rule's "battle over" for the player up
data rule_battle            0x0079d8e0  # the battle rule: its slot records begin at +8
value roster_slots          7
value roster_vec_at         8
value roster_record_size    12
value roster_id_at          4
value roster_qualified_at   83
value roster_start_after_ms 3000   # the picked mode starts this long after the pick (mode_file.c)
data roster_screen_table     0x006fc8a4   # the screen's slot table (.data): 32-byte records, the callout id at +28
value roster_screen_record_size 32
value roster_callout_at      28
site roster_city_done  0x00135394 ...   # the cities rule's "done in this city" (cities, bit), which the battle's stop calls with 1
data rule_cities             0x0079dae8  # the cities rule: the player's city index at +20+4p, the masks' vector at +44
value roster_city_bit        1
value roster_city_index_at   20
value roster_city_vec_at     44
value roster_city_record_size 16
```

Premium 1.16 has the same lines at its own addresses (`roster_start 0x001249c8`, `roster_done 0x00124924`, `rule_battle 0x007b0c70`, `roster_screen_table 0x0070e62c`, `roster_city_done 0x001387ac`, `rule_cities 0x007b0e78`). `roster_start_after_ms` is there for the screen: the selection
screen fades and plays an intro clip after the pick and is gone by about 2.4 s, so a start screen shown AT the
pick is never seen; with 3000 the start screen shows (seen at +3.3 s on Premium 1.16). A port without the value
starts the mode at the pick.

**Measured, in the emulator on Godzilla Pro 1.15 (item 146):** slot 0 renamed MOTHRA and redrawn,
selected and unselected; the other six unchanged. Picking slot 0 started a mode file's mode
(`[mode] MOTHRA START (roster pick)`, `[pad] roster: slot 0 picked (mode id 12): claimed - the game's
battle does not start`, and no start of Ebirah's battle). While it ran, four ramp shots and a held
scoop lit nothing and opened nothing. It ended on its clock and, picked again, on a drain
(`END (ball ended)`), each followed by `[pad] roster: battle over`; the screen then opened again, and
a stock slot picked through the same hook started the game's own battle (`[pad] roster: slot 1
picked (mode id 13): the game's battle`).

Also measured on Pro 1.15, in a two-player game (item 146 run4): a mode started by its trigger and then
picked (`picked while it runs - the pick is taken`) gave the pick back at its end (`[pad] roster: battle
over for player 1`) and the ramps lit a battle again; a pick while another mode ran (`it starts when that
one ends`) started the moment that mode ended; with `roster_start_after_ms 3000` the mode started 3001 ms
after the pick; on a drain the give-back came before the game moved to player 2 (the end-of-ball
callback runs while the draining player is still up); player 2 picked a stock battle through the hook, and
player 1 picked the mode again on the next ball. The pick callback runs on the same thread as tick, shot
and ball_end.

**Measured, in the emulator on Godzilla Premium 1.16 (item 146 run5, a copy of the stock card with the same
edited scene - the stock scene is byte-identical to Pro 1.15's):** MOTHRA selected and unselected on the
glass; picking slot 0 started the mode 3018 ms later with its start screen showing ("MOTHRA 1,000,000" at
+3.3 s); three shots scored; it ended on its clock with `[pad] roster: battle over for player 1`; the ramps
then lit a battle again and a stock pick (Megalon) started the game's battle (`slot 3 picked (mode id 15):
the game's battle`).

**Measured with the runtime alone (item 146 run6, Pro 1.15, no probe loaded - every earlier run also had a
probe hooked on the same instruction):** the claim wrote slot 0's callout 1888 -> 0 (read back from the
game's memory with `PAD_PEEK`); the flippers landed the cursor on slot 0 and the pick started the mode 3017 ms
later, with its start screen ("MOTHRA 1,000,000") on the glass at +3.3 s; three shots scored; it ended on its
clock with `battle over`. `roster_callout 207` in the reloaded file wrote 207; the ramps lit a battle again,
slot 0 picked again started the mode, and a drain ended it with `battle over`. On the next ball a stock slot
(Titanosaurus) started the game's battle ("GODZILLA VS TITANOSAURUS"). Removing the mode file released the
slot and put 1888 back. No crash (segv 0).

**Measured on Premium 1.16 with the runtime alone (item 146 run7, fix-2):** the callout lines run on this build too:
slot 0's id read 1888 -> 0 at the claim, 207 after `roster_callout 207`, and 1888 again when the mode file was
removed (`PAD_PEEK`), while slot 1's stayed 1918. The pick started the mode 3016 ms later with its start screen on
the glass at +3.3 s, and its end on the clock logged `battle over for player 1` then `the pick counts as the battle
of player 1's city 0 (its mask 0 -> 2)`; a watcher built into the same object read the cities rule on its own and
saw the mask go 0 -> 2 at the same moment. A stock pick (Titanosaurus) wrote the city's battle (13) at its start,
which a pick never does. A drain did not end that ball on this build (as item 147 found), so the ball was tilted;
the watcher then stopped reading between balls, so whether the tilted battle's stop set the bit was not seen.

**Measured on Pro 1.15 (item 146 run8, fix-2), with the game's own battle as the control:** the pick's end logged
`the pick counts as the battle of player 1's city 0 (its mask 0 -> 2)` and the watcher saw 0 -> 2. The watcher then
cleared the bit again, a stock pick (Titanosaurus) started the game's battle (the city's battle became 13), and a
drain ended the ball: 15 ms after the end-of-ball callback the game's own battle stop set the same bit, 0 -> 2. So
the runtime's call and the game's stop set the same bit of the city's mask (the city's battle stays 0 for a pick). The
callout lines also ran again (1888 -> 0
-> 207 -> 1888). No crash (segv 0) on either build.

**Not measured** (these paths are tested at the desk only, against the mode-file interpreter compiled
for the host and the runtime's own functions): a give-back that has to wait for its player (a mode ended
while another player is up); a pick the mode cannot start (`starts`/`cooldown`, `stack no`, a mode in C
running); a ball that ends before a waiting pick starts; a waiting pick that lapses because the game
ended or another player is up; a game ending while a pick is held; a real machine. Over a whole game:
whether a city completes with a pick as its battle (the other three bits need the city's tank attack,
bridge attack and tesla strike), what moves a player to the next city, whether the tier-2 slots and the
wizard mode open, and what the game does with a city whose battle is 0. The city advance itself was read
at the desk (Pro 1.15): `0x135bd0` writes the new city index into +20+4p, and its only direct caller is
`0x195288`, which plays the same pick sound as the battle screen (236) and starts show 179 (the battle
screen's pick starts 177), so it looks like a pick on a city screen rather than a score or a battle's stop;
what opens that screen was not read. Not checked on the glass either: the other places the program names or counts the replaced
battle, which a pick does not touch: the operator menu's adjustments ("BATTLE VS EBIRAH TIMER", "GZ VS.
EBIRAH DEFAULT CHAMP SCORE"), its audits ("GODZILLA VS EBIRAH STARTED" / "COMPLETED" - a pick counts in
neither), the champion ("GODZILLA VS. EBIRAH CHAMPION") and the battle's own award lines ("EBIRAH FINAL
BLOW!"). They are program text, which `progtext.py` can rename within each string's length.

**Known limits:**

- A claimed slot keeps the replaced battle's progress text (0/4 for Ebirah) and never shows "Completed":
  the game reads both from that battle, which never runs (seen on the glass).
- The replaced battle never completes (read from the program, not measured), so whatever the game gates on completing it may be out of
  reach: a slot's state comes from the battle's own mode (Completed when it has a stop reason) and
  the cities rule at `0x79dae8` with adjustment 334 (Pro 1.15), which gate the tier-2 slots; the
  wizard mode's qualification may depend on completions too. Once every other open slot is completed, the screen's
  two-second single-slot timer picks the claimed slot every time.
  Read further at the desk (Pro 1.15 `0x1201d8`, `0x136d30`): a slot's state reads only its own battle
  (completed), adjustment 334, and the cities rule's per-player records (which battle each of its five
  cities holds, and the player's city); it never reads another slot's completion. Since fix-2 the pick does
  count toward the city (the mask bit, above; run7, run8); the city's battle stays 0 and its +92 byte
  (probably "won") is never set. The city advance was read at the desk (`0x135bd0`, called only from `0x195288`,
  which looks like a pick on a city screen); what opens that screen, and so the tier-2 slots, was not read.
- King of the Monsters starts the four tier-1 battles (Ebirah, Titanosaurus, Gigan, Megalon) itself,
  not through the screen (item 144, seen live), so inside it the replaced battle runs as stock.
- A mode is not resumed after a drain the way the game resumes its own battles (above).

## Display priority: a mode layered on the game's display (item 154 display)

A mode's screen and clip share the glass with everything the game shows. Without a priority, the
game's own shot awards cover them: the Big loop's full-screen LOOPS, BATTLE IS LIT after the ramps,
a clip a shot starts taking the one video surface from a mode's start clip. A mode that holds a
**display priority** is, to the game's own display arbitration, a display of that priority: what
does not beat it waits, what beats it takes the screen and gives it back.

### How the game layers its display (Godzilla Pro 1.15 and Premium 1.16)

Read off both programs and measured in the emulator with `display_probe.c` (a porting instrument in
this folder, preloaded with `PAD_TRACE_SO`: it logs every request below, every clip played and every
change of the display state, and its header carries Premium 1.16's sites).

1. **Display effects.** A table of 152 effects, each a process with a priority 1-255. ONE runs at a
   time. A new effect starts when its priority is above the running one's (equal only when the running
   one allows it) and ends it; a lower one is refused, or queued when its caller asks. Most of the
   game's award effects are asked for by a **waiter** that asks again every frame, at priority 176, until
   the display is free or its time runs out (about a minute). Background effects run when nothing else
   does: attract (1), the **layered display** (29) during a game, the tilt (31). Measured: BATTLE IS LIT
   128 (177), the ramps' raid award 126 (201), the KAIJU BATTLE SELECT screen 132 (196), a multiball's
   jackpot 79 (184), the tilt warning 33 (241). The game's own mode effects sit at 183-184.
2. **Layered displays**, inside effect 29: a background (the city at 81, a mode's background at 82-86)
   and ONE foreground at a time, from a table of 111 (priorities 99-162). Each foreground is asked for
   by a waiter that waits while the layered priority now is not below its own (about 5 s for a shot
   award, a minute for a mode start). A record's flags: 0x10 **full screen**, 0x40 a **mode start**,
   0x04 a **total** (allowed at the end of a ball), 0x02 a background. Measured: Big loop 40 (113, full
   screen: LOOPS), Maser 37 (111), powerlines 47 (110), Building 101 (116), Godzilla target 48 (117),
   the Godzilla multiball start 56 (135, full screen, a mode start), the Ebirah and Titanosaurus battle
   starts 63 / 64 (105 / 104, full screen, mode starts).

**What draws over what:** the city or a mode's background; a clip played in the "ScoreFrame" crop (the
Maser, powerline, Building and tank clips, the raid award) inside the score frame; OVER those the HUD:
the score panel, the city slide-outs and a mode's own screen (scene `32e6ae28`); OVER all of it a clip
played full screen ("Normal" or no crop: LOOPS, BATTLE IS LIT, a jackpot, the tilt warning, a
multiball's intro); and over everything a clip the runtime draws (layer 0). There is ONE video
surface: whoever plays last owns it.

### The rule

While your mode holds priority P (`pm_display_priority(P)`, or `priority P` in a mode file):

- **An effect** of the game's comes through only when **its own priority beats P**, whether it starts
  directly or through a waiter. One that does not waits (a waiter keeps asking, up to its own time) or
  is refused (a direct start), as it would behind one of the game's own effects. So with P 180 the tilt
  warning (241), the battle select screen (196), the raid award (201) and a jackpot (184) come through;
  BATTLE IS LIT (177) waits.
- **A layered mode start or total** (flags 0x40 or 0x04) counts as one of the game's mode displays
  (184, the port's `value display_mode_level`): it comes through when 184 beats P. So a multiball or a
  battle start beats a mode at 180, and waits for a mode at 184 or above.
- **Any other full-screen layered display** (LOOPS, combos, the bonus) waits. **Since item 157 it is
  DROPPED instead** (not shown at all) on a port with `site layered_waiter`: a waiting one stops the
  game's drawing ("A waiting layered display froze the glass", below).
- **A framed layered display** plays under your screen, as the game layers it, except while your own
  clip plays: then it waits too, so your clip keeps the surface (dropped too since item 157).
- **Your clip** stops being drawn the moment the game plays a clip of its own (before this item the
  runtime went on drawing whatever the surface played, the game's clip over the HUD). While you hold a
  priority and the layered display plays its BACKGROUND (a multiball's loops), the background's clip
  changes are answered with your clip, as a foreground of the game's would keep the surface from them
  (not exercised: in run 6 the multiball's background waited for the mode's clip to end by itself).
- **What comes through** covers your screen for its length; your screen is in view again when it ends
  (`pm_display_covered()` says which). Nothing is hidden or redrawn: it is the game's own layering.
- **At the end** (`pm_display_priority(0)`, `pm_end()`, a ball end, leaving the game) the hold is
  released: the layered display's own priority back, its effect queue run. A display still waiting then
  plays (held off, then shown): run 3's raid award waited out a 45 s mode and started the millisecond
  the mode ended.
- A display of the game's that is ALREADY on the screen when the mode starts plays to its end; the
  hold applies to everything asked for after.

Choosing P (the game's own effect numbers):

| P | Waits while the mode runs | Still comes through |
|---|---|---|
| 0, or no `priority` line | nothing: the display as before this item | everything |
| 178-183 (a mode: **180**) | full-screen layered awards (LOOPS), BATTLE IS LIT, framed awards during the clip | the battle select screen, the raid award, jackpots, multiball and battle starts, totals, the tilt warning |
| 184-195 | also multiball and battle starts, totals, jackpots | the battle select screen (196), the raid award (201), the tilt warning |
| 230 | also the select screen and every award effect | the tilt warning (241) and the machine's own (boot 254) |

### In C

```c
static void start(void)
{
    if (!pm_begin()) return;
    pm_display_priority(180);        /* first: before the screen and the clip */
    pm_show(screen, 1);
    pm_clip("PadMode_my_mode_Clip");
}

static void on_tick(void)
{
    char words[48];
    if (!running) return;
    left--;
    /* every tick: pm_set_text sends the game only a CHANGE, so this costs nothing while the
     * words stay the same (a countdown in tenths changes ten times a second) */
    pm_snprintf(words, sizeof words, "%u.%u S  %u HITS", left / 60, left % 60 / 6, hits);
    pm_set_text(screen_words, words);
    if (left == 0) {
        pm_display_priority(0);      /* the game's display order again */
        pm_end();
        running = 0;
    }
}
```

`display_test_mode.c` is this as a rig instrument, beside `mode_file.c`:
`echo "230 25 shin_godzilla" > /dump/display_test.start` starts it (priority, seconds, the screen's folder).

### In a mode file

    priority 180

No line, or 0, is the display as before. Above 255 is 255; a word or a negative number logs and holds
nothing. An older `mode.so` logs `unknown key, skipped: priority 180` and runs the mode as before.

### The port lines

Both Godzilla ports carry them (the two tables are the same on Pro 1.15 and Premium 1.16); Premium's:

```
site display_effect_start 0x00439194 ...   # start(manager, effect, queue, force, 1): hooked to raise a hold first
site display_effect_next  0x00439578 ...   # run the effect queue (at a release)
site display_priority_now 0x00439a0c ...   # the effect priority now, as an effect waiter reads it
site layered_priority     0x0003cfcc ...   # the layered priority now, as a layered waiter reads it
data display_effects      0x007f75a4       # -> the effect manager (checked against the award screen's table)
data layered_displays     0x0070bc3c       # the layered display table
value display_host 29 / display_mode_level 184 / display_now_at 0xc / display_priority_at 0xe
value layered_record_size 16 / layered_priority_at 12 / layered_wait_for_at 0xa0 / layered_fg_at 0x58
value layered_fg_flags_at 0x60 / layered_waiter_call 0x00052efc / effect_waiter_call 0x00052d58
```

A port without them has no `PM_CAN_DISPLAY_PRIORITY`: `pm_display_priority` returns 0 and a mode file
logs `priority N not held`. A title with no layered displays (The Beatles has the framework's effect
start, next and priority-now, and nothing of Godzilla's layered-display library) can name the effect
half alone: `display_effect_start` (and `display_effect_next`, `display_priority_now`), `data
display_effects`, `award_screen_arg`, `event_current` and the four `display_*` values, and no
`layered_priority`. The hold then rides on the display effects only, and the boot log says `display
priority: on, display effects only`. No port names it that way yet: The Beatles' `display_host` is
not measured. The boot log says `[pad] display priority: on - ...`; a hold logs
`display: <mode> holds display priority N`, each display that waits for it once (`the game's layered
display 40 (priority 113, flags 0x11) waits for the hold at 180`), `covered by ...` / `in view again`,
and `priority N released`.

### What is measured (emulator-proven; nothing is flashed)

Premium 1.16 (a copy of the item 143c film-pack card: runs r2, r3, r4, r6, r7) and Pro 1.15 (a stock
card: run r5), with `mode_file.c` (`priority 180`) and `display_test_mode.c` (230). The runs and their
screenshots are the item's evidence (not in the repo); the names below are theirs.

- **The start clip plays through.** Big loop and Maser pressed inside it both waited, and the clip was
  on the glass at +2, +3.4 and +6 s (r2 `P1_0_clip2`, `P1_1_clip3`, `P1_2_panel`; on Pro with a stock
  clip, r5 `S2_0_clip`, `S2_1_clip`).
- **The screen stays readable.** Big loop after the clip: no LOOPS, the screen over the city (r2
  `P1_3_bigloop`; Pro r5 `S2_3_bigloop`); the Maser's framed clip under the screen (r2 `P1_4_maser`);
  four ramps: no BATTLE IS LIT (r2 `P1_5_ramps`, r5 `S2_5_ramps`); a multiball's jackpots (184) refused
  under 230 while the words kept changing (r2 `P2_3_ramp` .. `P2_7_words`).
- **What beats it wins, and the screen comes back.** The tilt warning (241) over the screen (r2
  `P1_6_tiltwarn`), the screen in view 3 s later (`P1_7_after_warn`; r3 `Q1_4_after_warn`); the
  Godzilla multiball start over a mode at 180 (r2 `P1_9_mb13`); at the scoop the KAIJU BATTLE SELECT
  screen (196) and, at the pick, the Titanosaurus battle start (a mode start) over a mode at 180, then the
  screen in view over the battle's own background (r7 `T2_5_scoop8`, `T2_9_pick6`, `T2_10_pick10`); the
  raid award (201, framed) under the screen (r6 `T2_4_scoop3`).
- **The clip during a multiball.** DISPLAY TEST (230) started 5 s into a multiball's background loops:
  its clip on the glass at +2, +4, +6 s, then its screen over the multiball (r6 `T3_clip_2` ..
  `T3_9_panel`).
- **Held off, then shown; the display stock again.** At every release the effect manager's priority
  went back to 1, and what had waited played: the raid award (r3 `Q1_12_total`, r5 `S2_9_end`), BATTLE
  IS LIT (r5), jackpots (r2 `P1_11_after_ramp`, `P2_9_after_ramp`), LOOPS on Pro (r5 `S3_0_bigloop`).
- **A ball end releases it.** A tilt while DISPLAY TEST held 230: `covered by the game's effect 33`,
  `END (ball ended)`, `priority 230 released`, the tilt background at priority 1 (r4).
- **Words every tick.** 1,500 `pm_set_text` calls in 25 s and the words on the glass at 15.6 / 14.3 /
  13.0 / 11.2 / 9.6 s (r2 `P2_3_ramp` .. `P2_7_words`); that only changes reach the game is a lifted
  desk test.
- Every run: throw 6 (every run's baseline), segv 0, fatal 0.

**Not measured:** a ball save, a match, extra ball and replay awards (no run earned one); the effect
queue with anything in it (no award effect asked to be queued in any run); attract after a game with a
held mode (every run's tilt left the emulated game waiting on TILT); a real machine; titles other than
Godzilla (their ports have no display lines).

### A waiting layered display froze the glass (item 157)

Found in the showcase's proof run (Premium 1.16, the showcase card, emulator): while a mode held a
priority and one of the game's full-screen layered displays waited for it with the layered display on
the glass, **the game presented no frames at all**. The emulator's own frame counter (`[eglshim] N
frames` in gzwatch.log, 60 a second otherwise) stopped for 3.8 s (KING GHIDORAH at 180, POWERLINE ATTACK
59 waiting), 5.5 s (ANGUIRUS at 180, LOOPS 40) and 8.1 s (FINAL WARS at 190, LOOPS 40), each ending the
millisecond the hold was released; two screenshots 6 s apart were identical to the pixel, score and all.
The integration branch's run 1 above froze 8.3 s the same way at 180 (LOOPS), ending when the raid
award took over; its evidence was single screenshots, which a frozen frame passes. A waiter of an
EFFECT (BATTLE IS LIT, the POWERLINE ATTACK AWARD 125) did not freeze anything.

The layered waiter is the process body the layered display's start tail-calls with r0 = the display,
r1 = the frames it may wait (3750 for a mode start, less for a shot award) and r2 = its priority; it
asks the layered priority once a frame (the `layered_priority` call that returns to
`layered_waiter_call`) and gives up, returning 0, when its frames run out. The runtime now hooks its
entry (`site layered_waiter`, Premium `0x00052ea4`, Pro `0x00052d54`; words checked against both
programs by `tests/test_spike2_mode_display.py`): a display the hold would keep waiting
(`disp_layered_must_wait`, the same rule) is given r1 = 0, so it returns at once, as when its time runs
out, and is not shown. Logged once a hold: `display: the game's layered display 40 (priority 113, flags
0x11) is dropped for the hold at 180`. What the game counted or paid for it (a loop, an award) is its
own and untouched; what changes is that such a display is no longer "held off, then shown" at the
release: it is not shown. Effects still wait and play after (BATTLE IS LIT at the end of a mode). A port
without the site keeps the old wait, freeze and all (the boot log says so).

### Display priority and named inserts in one mode

The two are independent: `priority` decides what the game may put on the GLASS while the mode runs,
the `light*` keys (and `pm_lamp_*`) which INSERTS show the mode's colours ("Lights: named inserts").
Neither touches the other's part of the game, and a mode may use both:

    name           LIGHTS AND DISPLAY
    seconds        35
    shots          0x00300000
    award          1000000
    clip_start     Mothra_godzilla_attack20
    priority       180
    light_shots    orange blink 400
    light_insert   cyan pulse 1200 BIG LOOP

At the start the hold is taken first (before the screen and the clip), the inserts after the start is
logged; at every end the hold is given up before `pm_end()`, the inserts are handed back after it. In C
the same is `pm_display_priority(180)` first in the start, then `pm_lamp_shot(...)` / `pm_lamp_set(...)`,
and at the end `pm_display_priority(0)` and `pm_lamp_release_all()` before `pm_end()` (as the two
sections' examples do).

**Measured (emulator-proven, nothing flashed): the integration branch's run 1.** A copy of the stock
Premium 1.16 card, launched as the Emulate tab launches it (muted, not cached), the PINNED
`prebuilt/mode.so` of the merged sources with the merged port and the mode file above:

- Before the mode, Big loop played LOOPS full screen (`C1_bigloop`). In the mode, the start clip played
  through a Big loop (`M0_clip`, `M1_bigloop_in_clip`, `M2_panel`; `layered display 40 (priority 113,
  flags 0x11) waits for the hold at 180`); a second Big loop left the score panel on the glass
  (`M3_bigloop`, `M3b_bigloop`); after four ramps the raid award (effect 126, 201) came through framed
  under the panel and BATTLE IS LIT (effect 128, 177) waited (`M4_ramps`, `M4b_ramps`, `M5_panel`).
- Meanwhile the shim's decoded LED block (what the virtual playfield draws, sampled every 100 ms for
  24 s): LEFT RAMP and RIGHT RAMP 255,96,0 half the time and dark half, 120 changes each (the 400 ms
  blink); BIG LOOP cyan, G = B, pulsing 40..255; MASER, not held, the game's (255 / 0, 10 changes); 111
  other channels of nodes 8 and 9 changing 2,418 times (the game's own show). Before the mode: the
  ramps white, BIG LOOP dark, 11 channels moving.
- At the end (its timer): `priority 180 released`, `3 insert(s) handed back to the game`; BATTLE IS LIT
  played at once (`E0_end`), the panel showed BATTLE READY (`E1_after`), and none of the inserts carried
  the mode's colours (the ramps steady dark with the battle lit, BIG LOOP dark and MASER 255 as before,
  14 channels moving). Big loop then played LOOPS again, `LOOPS: 4` (`E3_bigloop`): the two in the mode
  were counted, only their display waited.
- throw 6 (every run's baseline), segv 0, fatal 0. The port was read whole: 43 sites, 88 lamps, no
  `port:` line.

Not proven here: a picture of the virtual playfield window in this run (the capture found no window of
that title; the item mode-leds runs 5 and 6 have them); a ball end or tilt during a mode that holds
both; a card written by the app with both (the mode files reached the guest the rig's way).

## The showcase: five code modes that light their shots and hold a display priority (item 157)

`examples/` holds five intricate modes (KING GHIDORAH, OXYGEN DESTROYER, MASER BARRAGE, FINAL WARS,
ANGUIRUS; their rules sheets are `examples/README.md`) with their own clip, panel, music and calls. Item
157 lit them the way a rules designer lights a Stern mode and put them in the game's display order, with
two helpers in `examples/intricate_kit.h`:

- `struct kit_lamps`: every tick a mode says which SHOTS are lit and how (`kit_lamps_shot(&l, mask, rgb,
  pattern, ms)`, or an insert by name), and only a change reaches the game (`pm_lamp_shot` /
  `pm_lamp_set`, and `pm_lamp_release` for what no longer is lit); `kit_lamps_off()` hands everything
  back (`pm_lamp_release_all`) at the mode's end, a drain or a tilt. All five hold their inserts in one
  layer at priority 200, above every show the game ran (its highest measured was 145). One light
  language for the pack: SOLID = lit, no clock; BLINK = lit with a clock, faster as it runs out (700, 400,
  200, then 100 ms in its last 3 s); PULSE = optional (adds time, a head growing back); DIM = in the
  sequence, not next yet. Shots are lit through their shot bits, so the same code lights Pro 1.15's
  inserts (its shield bits name other inserts; the port's `lamp` lines say which).
- `kit_display(P)` right after `kit_begin`, before the screen and the clip; `kit_end` gives it up before
  `pm_end`. 180 for a mode, 190 for FINAL WARS (a wizard mode). ANGUIRUS joins the game's battle, whose
  own screen (timer, shot progress, what to shoot) sits where our panel does, so it YIELDS: it holds 180
  at its join only to watch `pm_display_covered()`, makes its entrance (clip, music, panel) once the
  battle's start screen is over (the screen in view for a second), then holds 180 only for 3 s moments
  (a spike, the roll lit, a roll) and gives the screen back between them; its total waits for the
  battle's own and gives way at once when another of our modes asks to start (`kit_asked`). A flash on
  any panel counts its time only while the panel is in view.
- Every mode ends on the game's `tilt` event too (`kit_is_tilt`).

The port's example light SWEEP (`kit_lights`) is no longer used by the five: the showcase's first proof
run (sc5) shows its light set includes the RGB inserts around the shots (during ANGUIRUS the LEFT RAMP
carried the sweep's 255,120,0 in 924 of 1111 samples; after FINAL WARS every ramp, loop and shield stayed
its gold for 8 s), so it made shots that pay nothing look lit.

**Measured (emulator-proven; nothing is flashed): the showcase card `card2.raw`** (the showcase project
written by the app's Write: `SternWritePipeline`, the object compiled from the five `.c` files with
`mode_file.c`), a copy booted the way the Emulate tab boots a card (`cardmodes.sh` put the card's own
object, port and five `.assets` in the guest), muted, not cached, with the app's virtual playfield
window, every mode played through by switch injection (run sc6, `C:\tmp\pad_parallel\showcase\v2\`):

- The decoded LED block (what the virtual playfield draws) every 100 ms, against the marks: MASER
  BARRAGE's LEFT RAMP 0,90,255 with RIGHT RAMP and BUILDING 0,30,90, the next shot blinking as its window
  ran (RIGHT RAMP 29 changes in the 10 s the chain broke in); OXYGEN DESTROYER's LEFT RAMP green then
  255,200,0 blinking (29 and 25 changes), MAGNA GRAB pulsing, then RIGHT RAMP white blinking (20 changes
  in 3 s); KING GHIDORAH's lit head 255,170,0 and a wounded head pulsing 0,255,60 (BUILDING 117 changes),
  MASER and MASER READY flashing together (15 changes in 2.7 s); FINAL WARS' BUILDING pulsing gold while
  lit, phase 1's ramps and loop 255,80,0 blinking (30-43 changes), the shields pulsing green, phase 2's
  target following MONSTER X, phase 3's BUILDING gold; ANGUIRUS's shields 255,80,0 blinking then solid,
  BIG LOOP 0,230,255 blinking (45 changes). All the while the game's other insert channels of nodes 8
  and 9 kept changing (659 to 2,396 changes a window). At all six ends (a timer, a win, the stop trigger,
  the ball end the tilt caused) none of the mode's colours was left 0.3-0.8 s later (`release_check.txt`).
- The virtual playfield window (`pf_*.png`, `look\sc6_playfield_best.jpg`): the colours on the ramps,
  the Building and the shield dots.
- The display: no frame freeze with the waiter fix (the render counter's only gap past boot is a 5.5 s
  pause at 95.5-101.1 s in MASER BARRAGE with no layered display waiting or dropped, which the first
  run sc5 also had at the same game time: not explained, not the hold's); LOOPS (40), POWERLINE ATTACK
  (59) and 110 dropped under holds and the panel drawn on (`31c`/`31d`, `42`/`42d` differ); the tilt
  warning (241) over OXYGEN DESTROYER's panel and the panel back 3 s later; the battle select screen
  (196) and the battle's start over ANGUIRUS, then its entrance; BATTLE IS LIT held off and played at
  MASER BARRAGE's end.
- The sound (`sc6_score.txt`): 25 plays of our own located in the capture (corr 0.41-0.99), each mode's
  bed in its 1 s windows above an off-phase control (all but one of FINAL WARS's 19; medians 0.54-0.99), only request 125 on the music
  bus while a mode ran and the game's music back after each end; 0 HF bursts at 101 marked points; of 17
  click-detector events, 13 are the game's own, 2 sit inside ours where our record steps 304-2140 and
  the capture 6064-10918, and 2 fall 16-18 ms after an END (OXYGEN DESTROYER, KING GHIDORAH) where our
  records step at most 1515 and 4673 and the capture 6225 and 15603 (the super jackpot's own shot sound
  on top, by that measure; not heard).
- throw 6 (every run's baseline), segv 0, fatal 0, 0 tasks in D state, the rig clean after.

Not proven: a real machine; how it looks or sounds in a cabinet; a drain ending a mode (a drain in sc5
did not end the ball in 25 s); the kit's own tilt path (in the emulator the tilt's ball end reached the
modes first and ended them); the game's battle ending by itself with ANGUIRUS in it (the battle's timer
did not run out in the run's window; the stop trigger ended it, so the total's wait for the battle's
own total is desk-proven only); Pro 1.15.

## Watching the game's own rules play (item 158)

To see what one of the game's OWN compiled rules does with each shot (a battle's spinner counts, a
multiball's moving targets), `stock_probe.c` is an instrument, never a card's mode: it reads a config
(`stock_probe.godzilla_le-1.16.cfg` for Godzilla Premium/LE 1.16), finds each watched rule through the
game's manager and wraps three of its vtable slots (start, stop, shot handler). Every call still goes
to the game's function; around it the probe logs the incoming shot, the rule's shot mask and lit shots
before and after, the rule's own counters, its start and stop with the caller, and the award calls.
`/dump/stockprobe.start "<id>"` starts a rule for the player up, from the tick. Build it with
`build_mode.sh -o stockprobe.so stock_probe.c`; read its log with `stock_probe_read.py`. The file
headers say everything; the addresses in the config are desk-read and checked at run time.

`lamp_watch.py` is the matching insert log: the shim's decoded LED block (`dump/padled`) sampled every
100 ms, by the insert names of the port's `lamp` lines. In a game every insert animates, so a rule's
lights read as a change against a window before it (`lamp_watch.py report`).

Emulator-proven on Premium/LE 1.16 (muted): rules 12 (battle vs Ebirah) and 4 (tank attack multiball)
started on demand with a ball in play and played their own start screens; the Ebirah spinners' counts
fell by one on each spinner's middle bit (0x200, 0x2000, 0x20000) while the Left ramp changed nothing;
a tank on the Right ramp was destroyed by it. Every switch dispatches `0x1` too, and a spinner closure
dispatches its three bits separately.


## Stock mode shots as data (item 159)

Item 158 measured that a stock mode's LIT MASK (the `initial_mask` rows of "The game's own modes",
the getter cmode's START stores) is not what two of Godzilla's rules play. Tank attack multiball (4)
never reads it: its shots are a six-entry PATH the tanks walk, and a hit on the entry a tank stands
on destroys it. Battle vs Ebirah (12) rebuilds it from three per-player SPIN COUNTS at every start.
Item 159 puts what those rules really play into the table, so the Modes tab edits it as data, and
marks the rows that do nothing. The audit of all 26 modes (the item's scratch folder,
`START_AUDIT.md`, desk-proven on both builds) found six more whose own start stores the mask again.

### Three more kinds, three marks

The grammar of "The table format (format 1)" grows, read by `pinball_decryptor/plugins/stern/
stock_modes.py` (an older reader skips a kind it does not know and keeps the row read-only):

| kind | tokens | the word(s) | a new value must |
|---|---|---|---|
| `path <va>` | 1 | a 16-byte tank path entry `{u64 position, u16 lamp, u16 id, u32 0}`: four words; the value is the position mask, the lamp and id are kept | be ONE bit the switches send alone, held by no other position; or 0 = NONE (below) |
| `qword <va>` | 1 | a u64 data pair (a spot list entry): two words | fit 64 bits |
| `insn <va>` | 1 | an instruction that LOADS the number from elsewhere (`ldr rd,[rn,#off]`); the table's value is what it loads, measured | be an 8-bit value rotated (1..255 in practice): the load becomes `mov rd,#N` on the same register; back to stock is the load word again |

- **`inert <why>`** after the class: the row is read-only and the tab says why. `inline_copy`: the
  mode's getter slot is cmode's own, and cmode's START uses an inlined copy of the base getter
  (tank attack; emulator-proven, item 158 edited-1). `start_rewrites`: the mode's own start stores
  the field again (Ebirah, emulator-proven; godzilla multiball, planet X multiball, titanosaurus,
  megalon, king of the monsters, planet X hurry-up: desk). A stale staged value for such a row is
  never written; a card that holds an older app's edit of it still goes back to stock.
- **`fixed <why>`** on a `path` row: `seed` (tanks appear there: the position is a word in the
  game's code too, `0x109cbc/0x10a660`, `0x109cd8`, `0x109cd0/0x10a5fc` on Premium/LE 1.16) or
  `goal` (every tank heads there, `0x109c78/0x10a5ec/0x10a654`). Read-only, with the reason; so
  only positions 2 (Left ramp) and 4 (Top spinner) can change.
- **`follows path`** on a row the Write keeps IN STEP with the mode's positions: the counted-shots
  words (v[47], `0x108d84..0x108d8c`: the OR of the six positions, `moveq`/`movteq`) and the spot
  list (v[48], `0x640930`, six u64: a replaced position's entry follows it; a NONE position's entry
  stays, since it is then neither lit nor counted and the game never spots it). Never staged by
  themselves; planned with the family (`stock_modes.family_words`), and back to stock with it.

**NONE** (a `path` row staged at 0): the entry becomes a whole copy of its neighbour AWAY from the
goal (lamp and id included), so the walk skips it: position 4 := position 5 is what item 158's
live-3 proved (no tank ever stood on the Top spinner, TANK 4 stayed dark, the rule ran and ended as
stock). The tab's picker offers none, then every single-bit shot of the port that no other position
holds; Big loop is never offered (the census saw it dispatched with `0x1` in one mask, and the tank
handler needs an exact 64-bit match). A choice whose OR with the other positions does not encode in
the counted-shots `moveq` is refused with the reason.

The rows (both builds; Pro 1.15's addresses desk-read on its ELF, `desk\words159.txt`):

```
number 4 path.0 0x800000000 path 0x640960 00000000,00000008,0b7f0072,00000000 word fixed seed
number 4 path.1 0x100000 path 0x640970 00100000,00000000,0b6d0090,00000000 word
number 4 path.2 0x80000 path 0x640980 00080000,00000000,0b6c0093,00000000 word fixed goal
number 4 path.3 0x800 path 0x640990 00000800,00000000,0b64009a,00000000 word
number 4 path.4 0x200000 path 0x6409a0 00200000,00000000,0b6e00ad,00000000 word fixed seed
number 4 path.5 0x2000000000 path 0x6409b0 00000000,00000020,0b80007b,00000000 word fixed seed
number 4 path.counted.lo 0x380800 movwt 0x108d84 0x108d8c 03a00b02,03400038 word follows path
number 4 path.counted.hi 0x28 imm 0x108d88 03a01028 word follows path
number 4 path.spot.0 0x80000 qword 0x640930 00080000,00000000 word follows path   (.. spot.5)
number 12 spins.left 15 insn 0x81020 e5905078 word
number 12 spins.top 40 insn 0x81028 e594607c word
number 12 spins.shield 15 insn 0x81038 e5945080 word
```
(Pro 1.15: path `0x630240`, spot list `0x630210`, counted `0x10654c 0x106554` / `0x106550`, refill
loads `0x7f850 0x7f858 0x7f868`.) Ebirah's three loads are in the refill `0x81018`, which both refill
paths run (v[5] and king of the monsters' start): the constructor's words `0x80fdc`/`0x80fec` stay,
one of them shared by two spinners, which is why the loads are the rows.

### Measured (item 159, 2026-09-23, emulator-proven on Premium/LE 1.16, muted, the app's rig)

The set built THROUGH the app (`engine.write_overrides` from a project that staged position 4 = none
and left spinner spins = 5) differs from stock at six words: the entry `0x638990/0x638998` (path[3] :=
path[4], lamp 173), `0x100d84` (counted lo `moveq r0,#0`), `0x079020` (`mov r5,#5`) and the two bypass
words. Against a stock control run with the same presses (the item's scratch runs):

- Ebirah started `pw+0x8c 5` (control 15); five single closures of the Left spinner took it 5 -> 0,
  the fifth cleared the bit (field `0x22200 -> 0x22000`) and paid the 5,000,000 stage award (`lr
  0x81858`) at once (control: 15 -> 10, no award); the top and shield spinners, the 10M and 15M
  awards and the 25M final blow (`STOP 12 reason 1 lr 0x81f2c`) followed as stock.
- Tank attack ran 132 s with 54 active states and NO record ever on 0x800 (control: 3 of 47); the
  right-side walk went bit 37 -> Right ramp -> Godzilla target; all four Top spinner presses into the
  handler changed nothing (control: one killed a tank, `w+0xa8 0->1`); the TANK 4 insert lit 5% of
  the samples (the light-show background; control 13%); the rule ended through the tilt / end-of-ball
  path (`lr 0xd6190`) as the control.
- Health both runs: segv 0 (gzwatch.log and game.out), fatal 0, [validation] 0, no GAME VALIDATION
  ERROR; the rig at 0 processes after, the app's own stage untouched.
- Revert (desk): the rows back to Stock write back exactly the four stock words over the edited ELF
  (equal to stock but for the bypass), and the Emulate tab's call says "Nothing to write".

### Not in this item

Ebirah's FINAL shot (Pop bumper or bit 42: `0x81514/0x81518`, the handler's tests `0x8175c/0x81760`,
v[38] `0x80144/0x80164` and the lamp entries) stays code; adding a shot to Ebirah (item 160's remap);
moving a seed or the goal position (the code words above would have to follow); the other 24 modes'
own shot data (each needs an item 158-style reading first). What the live initial_mask rows do in
play (modes 2, 5, 6, 9, 10, 11, 18, 21, 23, 24, 26: their getter IS called) is measured only for
tesla strike (item 144: its lights come from its own `start.lit_mask` field).

## Counts as: a stock rule takes another shot for one of its own (item 160)

Item 158 showed that a rule the game shipped with cannot be given a new shot by data alone: the
battle vs Ebirah's shot handler (Premium 1.16 `v[42]` at `0x816e8`) tests the RAW shot mask for
`0x200`, `0x2000` and `0x20000` (its spinners' middle bits) and `0x40` / bit 42 (the final blow),
and a lit, lamped Left ramp still scored nothing. So a shot the rule does not know has to ARRIVE
as the bit it tests, and that is what the runtime's stock-rules section does, from a table:

```
# stock.cfg, beside the mode files (a card: /usr/local/padmode; the rig: /dump); read twice a second
counts_as 12 Left ramp -> Left spinner
```

**What the runtime does.** The port names each rule (`rule 12 0x00636d78 Battle vs Ebirah`), the
manager's get function (`site stock_rule_get`, checked like every site), the manager (`data
stock_mode_manager`) and this build's slots (`value stock_slot_shot 42`, `stock_slot_active 14`,
`stock_field 0x18`). A rule a row names gets its shot slot WRAPPED, once, the way `stock_probe.c`
wraps it (the vtable word replaced by our function, which calls the original with r0-r3 and four
stack words passed through), and only when the object the manager returns carries the port's
vtable pointer, so a port for another build wraps nothing. In the wrap, a dispatch whose bits are
all inside a row's first shot is REPLACED by the row's second shot, one bit, while that bit is lit
in the rule's own per-player mask (the u64 at obj + 0x18 + 8 x player). It is never ORed in, and
once the rule clears the bit (Ebirah at a spinner's last spin) the shot passes through untouched:
a finished target never receives its bit again (item 158's check: a second decrement past 0 leaves
the battle unwinnable), and the `0x1` "a switch was hit" dispatch and any multi-bit mask are never
touched. An empty table, or a file that is gone, passes every shot through. While the target bit is
lit the first shot's inserts are held on the runtime's own lamp layer (priority 255) in the row's
colour and blink (Ebirah's yellow, 300 ms on / 200 ms off unless a `light <rule> <colour>
[pattern] [ms] [on ms]` line says otherwise), and handed back when the bit clears or the rule
stops; the rule's own lamp table (full, 6 entries on Ebirah) is not touched. The table is a
pointer swapped on the tick after a full rebuild, so the wrap on the game's thread never sees a
half-written row. Every decision is a `[pad] stock:` line in `mode.log`.

**The spin-count trap.** One ramp = one spin. A ramp standing in for Ebirah's left spinner needs
the spinner's 15 hits (200,000 each), unless the count word is lowered (item 159's rows). The
spinners' middle bits are `shot` lines of both Godzilla ports now (`Left spinner`, `Top spinner`,
`Shield ramp spinner` on Premium; `Right spinner` on Pro), so the table names them as it names any
shot; a mode may score on them too.

**In the app.** Modes tab, "Counts as…": a table of rows {rule, shot, counts as} for the project's
card (the rules and shots its port names; a card without a port, or a port without `rule` lines,
says so and takes no row). The rows are the project's `modes/stock.json`; Write renders
`stock.cfg` into the modes' system-partition payload (`mode_install.py --file`), Try it drops the
same file in `/dump`, and a card's own `stock.cfg` rides with its modes into the emulator
(`cardmodes.sh`). The file goes with the project's modes: a card needs the runtime, which Write
installs with at least one mode. A project of rows alone writes no table: the Write list and the
Write log say so ("NOT written ... at least one mode"), and with a mode the table's own line names
the rows ("the game's own rules take another shot (stock.cfg): ...").

**From C** (`pad_mode.h`): `pm_stock_rule_count / _at / _object / _active / _field`,
`pm_stock_counts_as(rule, from, to)` for a row of a mode's own, and for item 161
`pm_stock_rule_hook(rule, fn)`: `fn(rule, &shot, obj)` sees every shot before the game's handler,
may change it, and returns 1 to run the game's handler with it or 0 to keep it from running at
all; `pm_stock_rule_unhook` leaves the wrap passing through. A probe that wraps the same slot from
its tick (`stock_probe.c`) wraps FIRST, because the runtime's wraps go in after the modes' ticks:
the probe then logs what the game's handler receives.

**What is measured** (emulator-proven on Premium/LE 1.16, 2026-09-23, muted, the app's rig, a stock
card copy, two runs back to back with the same presses; the run object = this runtime +
`stock_probe.c` + `mode_file.c`, the probe wrapping Ebirah's `v[42]` first so its `SP SHOT` lines
say what the handler received; the pinned `prebuilt/mode.so` is built from the same runtime
source). The battle (rule 12) started by the probe's trigger with a ball in play:

- REMAP (`counts_as 12 Left ramp -> Left spinner`): the runtime wrapped the slot (`rule 12 Battle
  vs Ebirah obj 0x7b53f0 vtable 0x636d78: shot v[42] ... wrapped`). Every Left ramp closure entered
  the handler as `0x200` (`SP SHOT 12 ... shot 0x200 ... pw+0x8c 15->14`, then 14->13 ... 1->0), each
  paying 200,000 at the spinner's own site (`caward_add val 200000 lr 0x81da8`, 15 of them, all from
  ramp hits); the 15th cleared the bit (field `0x22200 -> 0x22000`) and paid the stage award
  (`val 5000000 lr 0x81858`; the glass read EBIRAH LEFT SPINNER AWARD 5,000,000). With the file
  REMOVED mid-battle (`stock.cfg gone - ... a wrapped rule with no row passes every shot through`)
  the next ramp entered as `0x100000` and changed nothing; put back (`1 counts_as row(s) live`) the
  next one counted (10->9). In the final phase (field `0x40000000040`) a ramp `passed through -
  0x200 is not lit`. The top and shield spinners ripped to 0 (10,000,000 and 15,000,000), the Pop
  bumper paid 25,000,000 and stopped the battle as won (`SP STOP 12 ... reason 1 lr 0x81f2c`; the
  glass: EBIRAH FINAL BLOW 25,000,000, FINISHING BONUS 11,000,000). LEFT RAMP (the insert oracle,
  100 ms samples): yellow 255,255,0 in 62% of the settled window (a 300 on / 200 off blink on the
  runtime's layer at 255; the control: white 100%, the base game's own light), handed back the
  moment the count hit 0 (`1 insert(s) of 0x100000 handed back`; off 100% after). Health: segv 0,
  fatal 0, `[validation]` 0, throw 6 (the boot baseline).
- CONTROL (`stock.cfg` with comments only): `0 counts_as row(s) live`, nothing wrapped; the same
  sixteen ramp closures entered as `0x100000` with `pw+0x8c 15` unchanged and no award; the left
  spinner's rip took 15->0 (its 15 x 200,000 at the same `lr 0x81da8`), the same stage awards, final
  blow and stop. LEFT RAMP white, never yellow.

Not measured: the tank (rule 4: a row is desk-checked only; a tank hit needs the exact position
bit), `light` lines, a C hook (`pm_stock_rule_hook`), a row from C, Pro 1.15 (its port lines are
desk-read from item 158's address pass), a card built by Write with `stock.cfg` on it (the file
goes through the same `mode_install.py` path as the mode files; not booted), the Modes tab's
dialog on the glass (its service is tested in-process).

## Rewriting a stock rule's shot logic (item 161)

Designed at the desk on 2026-09-23 from item 158's reading of the game's own rules (above), built on
item 160's per-rule wrap of the shot-handler vtable slot (the section above). The pieces in the repo:
`pad_stock.h` (the header an author's C sees), its implementation in `pad_mode_runtime.c` ("STOCK
RULES IN C"), `examples/ebirah_rewrite.c` (a worked example: battle vs Ebirah with three different
shots in order, then the Building), and the port lines the accessors read in both Godzilla ports. The
readable pseudo-C of Ebirah's and tank attack's own code is reference material (Stern's logic) and is
NOT in the repo. What is emulator-proven is at the end of this section.

**What it is.** A stock rule (a battle, a multiball) is a compiled C++ object; its SHOT HANDLER is one
vtable slot (v[42] on Premium 1.16, v[41] on Pro 1.15) that the game calls with every dispatched shot
while the rule is active: `(this, _, shot lo, shot hi, [sp] factor)`. Item 160's wrapper takes that
slot. Item 161 lets a C file REPLACE what the slot does:

```c
#include "pad_stock.h"
static int on_shot(struct pm_stock_rule *r, uint64_t shot, unsigned factor) { ...; return PM_STOCK_DONE; }
PM_STOCK_HANDLER(12, on_shot);          /* rule 12 = battle vs Ebirah on Godzilla */
```

The handler returns `PM_STOCK_DONE` (the game's handler is not run for this shot) or `PM_STOCK_PASS`
(it runs, after item 160's remap table when the card has one). `pm_stock_call_original(r, shot, factor)`
runs the game's handler on purpose from inside yours. A full record (`PM_STOCK_RULE`) adds `started`
(after the rule's own START ran) and `stopped` (before its STOP) callbacks. Everything else about the
rule stays the game's: its start from the select screen, its timer, its screens, its lamps, its ending.

**The stock pieces an author reaches, all through the port** (no address in C):

| Piece | Call | Port lines |
|---|---|---|
| the rule object, the player | `pm_stock_rule(id)`, `pm_stock_player()` | `site stock_get`, `data stock_mode_manager` |
| its per-player lit mask | `pm_stock_field` / `_set` | `value stock_field_at` (+8 x player) |
| lit shots, active, running | `pm_stock_lit`, `pm_stock_active`, `pm_stock_running` | `value stock_slot_lit/active`, `stock_running_at` |
| any word of the rule's own | `pm_stock_pw_get/set` (per player), `pm_stock_w_get/set` | `value <rule>_<what>_at` |
| an award, as the handler pays one | `pm_stock_award(r, value)` = caward_add(rule's award, 0, value, 0) | `site caward_add`, `value stock_award_at` |
| a show, a game event | `pm_stock_show(id)`, `pm_stock_event(id, value)` | `site show_start`, `site game_event` |
| STOP as won / not | `pm_stock_stop(r, won)` = v[11](won ? 1 : 0) | `value stock_slot_stop` |
| Ebirah's spin counters, bits, stage awards | `pm_ebirah_spins`, `pm_ebirah_spin_bit`, `pm_ebirah_stage_award` | `value ebirah_*` |
| Ebirah's FINAL BLOW | `pm_stock_final_blow(r)` | `value ebirah_final_*` |
| tank's records, counters, pieces | `pm_tank_records`, `pm_tank_destroy`, `pm_tank_seed_wave`, ... | `value tank_*`, `site tank_*`, `data tank_path` |

Two of these are worth knowing about: `pm_ebirah_stage_award(r, which)` sets that spinner's counter to
1, lights its bit and runs the GAME'S handler with the spinner's own bit, so the game pays the last spin,
gives its 5M / 10M / 15M award in completion order, shows its stage screen, posts its reminder and,
after the third, writes its final mask itself; `pm_stock_final_blow(r)` sets the field to the final
mask and runs the game's handler with the final shot (the Pop bumper's bit), so the game pays
25,000,000 and the finishing bonus, shows EBIRAH FINAL BLOW, posts its events and STOPS the battle as
WON, i.e. the battle's own ending plays. Replaying the game's handler with a chosen shot is how a
rewrite keeps the game's ending without re-implementing it; item 158 proved (emulator) that those two
paths do exactly this when the real switches drive them.

**What the example does** (`examples/ebirah_rewrite.c`): after the battle's own START it puts the Left
ramp in the field and holds its insert (yellow blink, `pm_lamp_shot`); a Left ramp hit pays what a spin
pays (200,000 x factor, `pm_stock_award`), takes the game's first stage award, and lights the Right ramp;
then the Big loop; then the Building, whose hit is the game's final blow. Any other shot does nothing,
as an unlit shot does in stock. With the file left out of the build the battle is the game's own.

**Port lines and the runtime's tables.** The accessors read about 20 `site` and 47 `value` lines per
build (the engine calls the handlers make, the slot numbers, the cmode fields, and Ebirah's and tank's
own words and pieces), in each Godzilla port right after item 160's `rule` lines. They took the
runtime's tables past their old caps (48 sites, 64 values: Premium's port now has 64 and 105), so
`N_SITES` is 80 and `N_VALUES` 128; `tests/test_stern_mode_runtime.py` reads the caps from the source
and still fails a port that outgrows one. Every `site` word pair was read from the ELF by
`port_words.py`; the Pro 1.15 twins were checked against a decompile of both builds (every function's
shape the same), and nothing on Pro has run.

**How it reaches a card (the app).** A stock-rule rewrite is a CODE MODE of the project
(`modes/<folder>/<folder>.c`, the item 149 path): Write compiles the project's code modes with
`mode_file.c` into the card's `mode.so` in the app's Linux, so nothing new is needed to carry it; it
needs no `assets.json` beyond a name, no screen, no clip (the game's own play). The wrapper installs
only for rule ids a handler registers, so a card without such a file runs stock. What the Modes tab
shows for it, under the preview switch: in "The game's own modes" a CODE row per stock rule beside the
number rows ("Shot logic: the game's own" / "rewritten by <folder>"), a "Rewrite in C..." action on a
rule that copies a per-rule template (the example, for Ebirah) into `modes/<folder>/`, and the code
mode's usual row in the modes list with "replaces the shots of battle vs Ebirah" as its kind. Try it
carries it like any code mode.

**Open at the desk, settled by the implementation:** a handler sees the shot BEFORE the remap table (a
PASS'd shot then goes through it); a rule started by King of the Monsters pays through KOTM's award
in stock, the example pays through Ebirah's own and says so; the game's START rebuilds the mask and
resets the stage index on a second START, and the example's `started` runs after it, so the field is
the example's again.

**What is measured** (emulator-proven on Godzilla Premium/LE 1.16, 2026-09-23, the app's rig muted,
a COPY of the stock LE 1.16 card, nothing flashed): the runtime, the SDK's stock probe (six battles
watched), `mode_file.c` and the example, compiled into ONE `mode.so` the code-mode way
(`modes/ebirah_rewrite/ebirah_rewrite.c`; the app's own compile command built the same source to the
same shape). The run: a boot of 57 s; a game; the battle select opened on GIGAN and the game's own
START of rule 14 ran (`lr 0x1249d4`), so the harness STOPPED it (reason 0) and started Ebirah BY THE
TRIGGER (`SP START 12 ... lr 0x408445e8 field 0x0 -> 0x22200`, the game's own 250,000 start award
paid by its START, `lr 0x8548c`); the natural start of Ebirah with the rewrite present is therefore
NOT measured (the select screen's opening cursor differs between boots and the harness presses no
flipper; the control run whose select opened on Ebirah started it the game's own way). After the
start show: `SP STATE 12 ... field 0x100000` (the example's `started` put the Left ramp in the field;
the glass showed GODZILLA VS EBIRAH, YOUR SCORE 250,000, 15 / 40 / 15 SPINS LEFT). Then, one press
each, 10 s apart: Right ramp and Building OUT OF ORDER: 0 handler entries, 0 awards; Left ramp (stage
1): one entry of the C handler, 200,000 `lr 0x40847a20` (`pm_stock_award`), then the replay of the
game's handler with the left spinner's bit, 200,000 `lr 0x81da8` + 5,000,000 `lr 0x81858` + its
award screen (`caward_build 250,000 lr 0x818ac`), field -> 0x200000 (the Right ramp); Left ramp again
and Big loop OUT OF ORDER: 0 entries; Right ramp (stage 2): 200,000 ours + 200,000 `lr 0x81dc4` +
10,000,000 `lr 0x81f60`, field -> 0x1000000000 (the Big loop); Big loop (84 then 74, stage 3): 200,000
ours + 200,000 `lr 0x81c7c` + 15,000,000 `lr 0x821bc`, field -> `0x40000400040` (the game's own final
mask, written by its third stage, plus the Building); the glass: 00 / 00 / 00 SPINS LEFT, the mode's
score 31,450,000 (= 250,000 + 3 x 400,000 + 5M + 10M + 15M), and the game's OWN words "SHOOT POP BUMPER
FOR FINAL BLOW!" (the BG layer is the game's; see below); Pop bumper (the game's final shot): 0 entries
of rule 12, refused; Building: 25,000,000 `lr 0x81ebc` + 17,000,000 `lr 0x82080` (the finishing bonus)
+ `caward_build 2,100,000 lr 0x820bc`, then `SP STOP 12 battle_ebirah p1 reason 1 lr 0x81f2c` (the
game's handler stopped the battle as WON; the example's `stopped` ran before it), the glass GODZILLA VS
EBIRAH TOTAL 73,450,000. No `SP SHOT` line of the probe for any ramp, loop or Building press: the
game's handler never saw them; its only entries are the three replays (`lr 0x4084b608`, shot 0x200 /
0x2000 / 0x20000) and their `pw+0x8c 1->0` counters. Inserts (`lamp_watch.py`, 100 ms samples): in
each window ONE insert blinks yellow, the shot that is next, the rest held by the game: settled LEFT
RAMP yellow 40% (the others the start show's red / yellow 48 / 48), after stage 1 RIGHT RAMP yellow 39%
(the others orange 100%), after stage 2 BIG LOOP yellow 60%, after stage 3 BUILDING yellow 39%; in the
control none blinks alone (all eight 48 / 48, then all orange). Health: the game's own 6 throws, segv 0
in `game.out` AND `gzwatch.log`, fatal 0, GAME VALIDATION ERROR 0, no rig process left. CONTROL (the
same object built WITHOUT the rewrite, two runs): the ordered ramp / loop / Building presses reached
the game's handler (an `SP SHOT` line each) and changed nothing, the spinners and the Pop bumper won
the battle (`reason 1 lr 0x81f2c` after the Pop bumper, EBIRAH RIGHT SPINNER AWARD 15,000,000 on the
glass); one of them started Ebirah the game's own way (`lr 0x1249d4`, its select opened on Ebirah).
Two rewrite boots before the clean one CRASHED at boot / game start (`libpthread+0x8858`, r0 0x18: the
game's own null-singleton lock, seen by item 158's CONTROL run too) when the boot was slow under other
work on the PC (the probe ready at 127 s / 134 s instead of 57 s); the harness reboots when the probe
is not ready within 110 s. The order in the wrap: the C handler runs FIRST; a PASS'd shot then goes
through item 160's counts-as row (or a mode's `pm_stock_rule_hook`), then the game's handler.

**Not measured:** Ebirah started the game's own way WITH the rewrite (above); Pro 1.15 (its port lines
are desk-only, the twins checked by decompile); the tank accessors (`pm_tank_*`, desk-only: no tank
rewrite ran); a battle started by King of the Monsters; a second START while the battle runs; the
battle's on-screen words (the BG layer's text follows the SPINNER bits, so a rewrite's shots show the
game's default line, "SHOOT POP BUMPER FOR FINAL BLOW!" after the third stage); whether the stage
screens, which name the spinner completed, read well over a ramp. A rewrite's own words would need
the rule's display layer, which this item does not touch.
