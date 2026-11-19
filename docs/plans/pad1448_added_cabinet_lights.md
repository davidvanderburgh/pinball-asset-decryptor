# PAD-1448: speaker lights on titles that have none (Stranger Things, Munsters, ...)

Friday (Pinside #522): "Any chance we'd be able to get control of or add speaker light effects to stern games that don't
have them? ... Would love to add lighting to stranger things or Munsters". David (2026-11-19): investigate adding it now.

## What the titles have

- Every title from Deadpool / Godzilla on lists **node 7** "Backbox Speaker Lights" (a 520-8511-00 ws2812node) and
  names 23 RGB lights `SPEAKER 1..23` (69 device rows), Pro and LE alike. PAD's Expression lights tab (PAD-1040)
  already makes shows for them.
- 31 of 71 ports have no cabinet lights at all: Stranger Things, Munsters, Mando, TMNT, Iron Maiden, Avengers,
  Aerosmith, Beatles, Guardians, Sword of Rage, Jurassic Park Home, Star Wars ELG (and the older Batman 66 1.13
  port; 1.14 names 16 speaker lights). Their node directory has no node 7 and their light table no speaker or blade rows.
- **Their node directory DOES list node 2** "Cabinet Lights" (ws2812node, part 520-8511-00, the same board as node 7),
  group 1, with no device on it. It is the board Stern's Expression Lighting kit plugs in as; aftermarket kits that
  the game drives (Kodelia, PixlWav Expression) hang off it, and "games without expression light kits do not have
  this Node 2 board".
- The games ADDRESS-SCAN the bus (fe to nodes 0-31). A board at an address not in the directory is flagged
  "UNEXPECTED NODE ADDRESS" in the communication test (hwshim.c, D&D LE 1.00), so a board added as node 7 on these
  titles is an intruder. Node 2 is the one address they expect.

## Measured on the emulator (C:/tmp/PAD-1448, nbjob.sh / run*.sh, PAD_NB_LOG census, 2026-11-19)

| run | node 2 traffic in ~40 s of attract |
|---|---|
| Stranger Things LE 1.13, stock (census silences node 2) | fe/fa identity probes only |
| ST LE, node 2 answering (`PAD_NB_SILENT=99`, a fitted board) | registered: fe, f9 runtime info (520-8511-00, fw 1.33.0), f2, 72 x2. **No LED frames** |
| ST LE, node 2 answering + `spkprobe.so` (69 lights added) | **72 x140, 84 x69, 85 x69**: one 84/85 per added channel |
| Godzilla LE 1.16, node 7 (real speakers) | 72 x140, 84 x69, 85 x69, 86 x1640 (colour frames: attract lights them) |
| Led Zeppelin LE 1.22, node 2 (real blades) | 84/85 x96, 90-96/b0-b6 colour frames |

So once the game's own light table has lights on group 1, Stranger Things configures its node 2 board exactly as
Godzilla configures its speaker board. Nothing lights them yet, so no 86 colour frames: that is the runtime's part.

## How the lights are added (spkprobe.c, ST LE 1.13)

- Light table: 24-byte records through ONE pointer variable in .data (0x7c7994, its value in the file); device table:
  48-byte records through another (0x7c74dc). lampmap._accessors already finds both.
- Their counts are .bss variables (0x891370, 0x89cd58) copied at start-up by static initialisers from read-only
  constants (0x5dc620 = 340 lights, 0x5dc75c = 459 devices: `movw/movt r2,#const; movw/movt r3,#count; ldr r2,[r2];
  str r2,[r3]; bx lr`).
- A preloaded library's constructor runs before the game's static initialisers: it copies both tables with the new
  records appended (the trailer record kept after them), repoints the two variables, and raises the two constants
  (mprotect on their page). New device = a clone of an LED device (TOPPER 1-R) with name, group 1, index = channel;
  new light = a clone of its light with name, +0x0C a slot past the game's own (0..395) and +0x0E the new device.
- Lamp layers (port `lamp_layers`, `lamp_slot_size 40`) are sized from the light count at start-up, so the
  runtime's own layer has slots for the added lights.
- Guard: a preloaded constructor also runs in the game's `system()` children (busybox `rm`): the probe segv'd there
  (3 x `rm -> 139`). The runtime must act only in the game process.

## Status (2026-11-19): built and emulator-proven

All five steps below are in (commit ad0eb5a63 and after). On all 21 latest shipped builds that take them (Star Wars ELG
cannot: no RGB light to copy) the runtime added 69 channels on node 2, the game configured all 69, and a show's red,
green and blue reached every one of the 23 speaker pixels in the game's own frames (C:/tmp/PAD-1448 modejob.sh,
verify.py). Older shipped builds: not done (David: latest builds only). Rig slot 2's stale ballfeed.off stopped three
runs there; they passed on other rigs.

## The build

1. **portgen**: per build, `data light_tab_ptr`, `data dev_tab_ptr`, `data light_count_const`, `data
   dev_count_const`, and a clone device / light (an LED on a ws2812 board), found by pattern (the accessors and the
   static-initialiser store) - every build of every title without cabinet lights (mode features: every version).
2. **runtime**: `addcab.cfg` beside the runtime (written by the app when the owner ticks it): N speaker LEDs (23
   default, Godzilla's layout, left ring then right) and optional blades, appended before the game's initialisers,
   game process only; then the existing `cablamp` / CAB0 path paints them (pm_cab_*, cabshow.cfg).
3. **ports**: `cablamp` lines for the added lights, flagged as added, so the Expression lights tab shows the cabinet
   drawing and Write puts shows on the card.
4. **app**: on a title with no cabinet lights, the Expression lights tab offers "My cabinet has speaker lights on a
   Cabinet Lights board (node 2)" with the LED count; the help says what hardware that is.
5. **proof**: the emulator: node 2 colour frames (86/9x) carrying a show's colours (hwshim decodes node 2 strips:
   led_strip_levels), the playfield view's speaker ring lit, every affected build boots (rigbatch), no
   UNEXPECTED NODE / Tech Alert with the board answering, and a card without the option unchanged.
