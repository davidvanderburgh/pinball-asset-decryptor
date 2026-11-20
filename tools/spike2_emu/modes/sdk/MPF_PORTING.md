# Porting a game written in MPF to a Stern Spike 2 machine

This is for a maker, or the AI agent working for one, who already wrote a game in the **Mission Pinball
Framework** (MPF: a machine config and mode configs in YAML, mode code in Python) and wants it to run on a Stern
Spike 2 machine's own board and program, with no laptop, no Raspberry Pi and no bridge. It maps each part of an MPF
game onto this SDK, and ends with a whole game ported that way and played in the emulator (PAD-1410).

Read `MODE_SDK.md` first, top to bottom: it is the SDK's guide, and this file only says which of its parts each MPF
thing becomes. Then `pad_mode.h` (every call), then `examples/intricate_kit.h` (the kit: menus, meters, fades, the
HUD, timers, a new game's witness).

## What changes, and what stays

An MPF game drives the machine: its config names every switch, coil, light and ball device, and MPF runs the
trough, the flippers' rules, ball search and tilt itself. **On PAD the machine stays Stern's.** Your game runs
inside Stern's program as a mode that switches Stern's rules off (`pm_own_game`, MODE_SDK.md "The whole game"), and
Stern's program keeps doing what is not a rule:

| Stern's program keeps | So your port has no... |
|---|---|
| the trough, ball search, serving and launching balls, the shooter lane | `ball_devices:`, `playfields:`, `ball_search` |
| the flippers, slingshots and pop bumpers (the node boards fire them) | `flippers:`, `autofire_coils:` |
| tilt and its warnings, slam tilt | `tilt:` mode |
| the display engine, the sound system, the node bus | MPF-MC, `sound_system:`, a serial bridge |
| each ball's start, its end and its end-of-ball bonus; the game's end and its high-score entry, from your scores | `ball_ending` bonus code of your own (see "Not ported" for the bonus) |
| the operator's settings and audits, coin handling, attract between games | `settings:`, `credits:` |

What you write is the **rules**: scoring, modes, progress, what the buttons do, what the screen shows. Everything a
switch means comes to you as a **shot** (`.shot`), the game's own name for it, so the port never needs a switch
number.

## The shape of the port

One MPF game becomes **one code mode folder** in the card project, `modes/<slug>/`:

- `<slug>.c`: the whole game. Several `struct pm_mode`s in one file, one per MPF mode that runs as a mode
  (`PM_REGISTER` each). Shared state (player variables, counters) is plain static C between them.
- `assets.json`: what the build makes for it: its meters, fades, menus, own screen, clips, music and calls
  (`plugins/stern/code_modes.py` lists every key).
- `intricate_kit.h`: a copy of `examples/intricate_kit.h` beside the C. A new code mode (the Modes tab's New
  mode > C) starts from `template_mode.c` and does not carry the kit: copy it in.

The modes:

- **The base: your game-long mode.** MPF's mode with `game_mode: true`, `start_events: game_started` (or
  `ball_started`) and `stop_on_ball_end: false` - the one that is always running. In C: on the tick a game is in
  play (`kit_new_game` sees the new game, `pm_in_game()` and `pm_player() >= 1`), `pm_begin()`, then
  `pm_own_game(1)`. It runs through every drain (never `pm_end` it in `.ball_end`) and ends when `pm_in_game()`
  falls. Stern's modes, scoring, callouts, shows, multiballs and ball saves are off underneath it.
- **Every other MPF mode: a layer.** `pm_begin_layer(priority, flags)` runs it over the base, beside up to seven
  more (MODE_SDK.md "Several of your modes at once: layers"). MPF's priority order becomes the layer priority
  order: keep the ranking, the numbers are yours (0-255).
- **A mode that only asks the player something** (MPF's carousel or a selection mode) need not be a mode: the
  base opens a **menu** (`kit_menu`).

A layer begins in **its own** `.tick`: the runtime knows which mode is calling by the callback it is in, so a call
made from the base's tick is the base's. MPF's `start_events` therefore become a flag the base (or another layer)
sets and the layer's tick reads: `want_sentinel = 1` in the base, `if (want_sentinel && pm_begin_layer(50, 0))`
in the Sentinel's tick.

## MPF to PAD, part by part

### Modes

| MPF | PAD |
|---|---|
| `mode: start_events: x` | a flag set where `x` happens; the mode begins in its own tick |
| `mode: stop_events: x` | `pm_end()` in the mode's own callback where `x` happens |
| `priority: 300` over one at 200 | `pm_begin_layer(80, 0)` over one at `pm_begin_layer(50, 0)` |
| `game_mode: true` (the game-long base) | the base: `pm_begin()` + `pm_own_game(1)` |
| `stop_on_ball_end: true` | `.ball_end`: `pm_end()` |
| `stop_on_ball_end: false` (it resumes next ball) | `.ball_end`: keep its state in the player's record and `pm_end()`; on the next ball's first shot the base asks for it again and it begins where it was. Or keep it running: a layer is not ended by a drain unless it ends itself. |
| a mode that pauses the ones under it (a wizard) | `pm_begin_layer(p, PM_LAYER_PAUSE_BELOW)`; the ones under read `pm_paused()` and hold their clocks |
| `use_wait_queue: true` | a menu holding the ball (`KIT_MENU_HOLD_LANE`, `KIT_MENU_HOLD_SCOOP`) |
| mode code (`class MyMode(Mode)`, `mode_start`, `mode_stop`) | the `pm_mode`'s callbacks: `.tick` 60 times a second, `.shot`, `.ball_end`, `.event`, `.init` once |

### Events

MPF is an event bus; a port has none. Each event becomes the place in C where it happens:

| MPF event | PAD |
|---|---|
| `game_started`, `game_ending` | `kit_new_game()` returns 1; `pm_in_game()` falls |
| `ball_started` | the first `.shot` after a `.ball_end` (the game's own ball start is not yours to hook; `pm_event("ball start")` where the port names the event) |
| `ball_will_end`, `ball_ending` | `.ball_end` |
| `player_turn_started` | `pm_player()` changes: swap to that player's record |
| `s_<switch>_active` for a playfield switch | `.shot`, with `shot & pm_shot("Left ramp exit opto")` (the port's names; test bits, never `==`) |
| `s_action_active`, `s_flipper_left_active`, `s_start_active` | the button shots: `pm_shot("Action button")`, `"Left flipper button"`, `"Start button"`, their `released`, `held 1 s`, `held 3 s` (MODE_SDK.md "The cabinet buttons as shots") |
| `combo_switches:` (flipper + Action) | `pm_shot("Left flipper + Action button")`, `"Right flipper + Action button"`, `"Both flipper buttons"` |
| `timer_<name>_complete`, `logicblock_<name>_complete` | the line of C where your counter or tick count reaches its end |
| an event with a condition (`event{current_player.x>=3}`) | an `if` |

The game's own events (a multiball starting, a skill shot...) are `.event` callbacks, by the names the port gives
(`pm_event(name)`, MODE_SDK.md "Events").

### Shots and lights

| MPF | PAD |
|---|---|
| `shots:` with `switch:` | the port's shot names (`ports/<game>-<version>.port`, `shot` lines; `pm_shot_count`, `pm_shot_at` list them) |
| `shot_groups:` | a mask: `pm_shot("Left ramp exit opto") \| pm_shot("Right ramp exit opto")` |
| `shot_profiles:` (unlit, lit, flashing) | the state is your own int; the light is `pm_lamp_set(names, rgb, pattern, period_ms)` on the shot's inserts (the port's `lamp` lines; MODE_SDK.md "Lights: named inserts") |
| a higher mode's shot with `block: true` | `pm_shot_claim()` in the higher layer's `.shot`; the ones under it see `pm_shot_taken()` and skip it |
| `light_player:`, `show_player:` | `pm_lamp_set`, the kit's `kit_show` (light shows of your own), `pm_game_show_named` (one of the game's), `pm_cab_show` (the cabinet's expression lights) |

### Logic blocks, timers and variables

| MPF | PAD |
|---|---|
| `counters:` (count up or down, `count_complete_value`) | an int and an `if` |
| `accruals:`, `sequences:` | bits in an int; a step index |
| `timers:` (`start_value`, `direction: down`) | a tick count: 60 a second, counted down in `.tick` (the kit's `kit_timer` adds the game's countdown calls) |
| `player_vars:` | a `struct` per player, `P[5]`, indexed by `pm_player()` (1-4); switch the live one when the player up changes |
| `score` | `pm_score_add(player, points)` (and `pm_score_sub`). Under `pm_own_game` every point on the score is yours |
| `variable_player:` | the C that adds to the score and the player's record |
| `machine_vars:` with `persist: true` | **saved progress**: `pm_saved_put("key", 0, value)` / `pm_saved_get("key", 0, default)` - player 0 is the machine's |
| per-player progress kept between games (a story chapter, New Game Plus, unlocks) | `pm_saved_put("key", p, value)` for player p 1-4: their Insider Connected login while logged in, else the player slot. Read again when `pm_saved_stamp(p)` changes (MODE_SDK.md "Saved progress") |
| `high_score:` | the game's own high scores, from your score. Records of your own (a best Sentinel fight...): the Modes tab's High scores (MODE_SDK.md "Records of your own") |

Saved keys are letters, digits and `_ . : -`, up to 47 characters; values are `long long`; the whole store is
16 KB. Prefix your keys with the game's slug (`xstory:chapter`). The operator clears it with the service menu's
SAVED PROGRESS row, and a factory reset clears it.

### Balls

| MPF | PAD |
|---|---|
| `ball_saves:` (`active_time`) | `pm_ball_save(seconds)` |
| `multiballs:` (`ball_count`, `shoot_again`) | `pm_multiball_start(balls, ball_save_seconds)`; `pm_balls_in_play()` |
| `add_a_ball` | `pm_multiball_add(n, ball_save_seconds)` |
| `ball_holds:`, `ball_locks:` | `pm_device_keep(name, n)` by the game's own name for the device; `pm_scoop_hold(ms)` |
| ending a multiball | `pm_drain_to_one()` |
| `flippers:` enable/disable | `pm_flippers(0)` / `pm_flippers(1)` (the base only) |
| a coil of a toy (`coils:` + `pulse`) | `pm_coil_pulse(name)`, `pm_coil_hold(name, ms)`, `pm_toy(name, move)`, `pm_kickback(on)`: the game's own devices by name (MODE_SDK.md "The flippers, in a mode that is the whole game") |
| a coil or switch you added to the machine | `pm_spare_drive`, `pm_spare_shot` (MODE_SDK.md "Spare switches and outputs") |

### The screen and the sound

MPF-MC draws slides of any widgets. A Spike 2 mode's screens are **built into the game's own scenes when the card
is written**, from what `assets.json` names, and the C shows, hides and fills them:

| MPF | PAD |
|---|---|
| `slides:` / `slide_player:` with text | the mode's own screen (`"screen": true`), its words by `pm_set_text`; the HUD at the glass's edges (`"hud"`, the kit's `kit_hud`) |
| a bar or meter widget (health, energy) | **meters**: up to 4 a mode (`"meters": [{"label", "color"}]`), the kit's `kit_meter_set(m, value, most, words)` |
| a full-screen colour, a fade | **fades**: up to 3 a mode (`"fades": [{"color", "style": "flat" or "glow"}]`), `kit_fade_to(f, percent, ms)` |
| `carousel:`, a selection screen | **menus**: up to 2 a mode (`"menus": [{"title", "color"}]`), `kit_menu_open`, `kit_menu_shot`, `kit_menu_tick` (MODE_SDK.md "A menu picked with the flippers"). One at a game's start waits for the game's own start-of-game video by itself (below) |
| a video widget | clips: up to 32 a mode (`"clips"`, `pa_clip_full`, `pa_clip_event`), or a game clip by name (`pm_clip`) |
| `sound_player:` | calls: up to 16 a mode (`"calls"`, `pa_call`), or the game's own callouts (`pm_callout`) |
| `music_player:` | music beds: one plus 6 more a mode (`"music"`, `"beds"`, `pa_music_bed`) |
| attract slides | the Attract tab: your own attract in place of the game's |

Node names follow the folder: `PadMode_<slug>_Meter<k>`, `..._Fade<k>`, `..._Menu<k>`, numbered in the order
`assets.json` lists them. Every screen the build adds is visible until your mode hides it; the kit's `..._tick`
calls find each one (the scene may load after `.init`), hide it, and then draw only what changed: call them every
tick from the base.

### Python

Mode code in Python becomes C in the callbacks, under MODE_SDK.md's rules: never block or sleep (count ticks), no
allocation, threads, files or stdio (static variables, `pm_snprintf`, `pm_log`), and only from your callbacks.
`pm_log` writes `/dump/mode.log`: it is the port's `self.debug_log`.

## Not ported

- **Hardware config.** Switches, coils, lights and devices are Stern's; you use the port's names for them. A device
  the app does not know the game's command for is not yours to fire (MODE_LIMITS.md).
- **Stern's end-of-ball bonus.** The game keeps its bonus: on Uncanny X-Men 0.98 its switch handlers count every
  playfield switch toward it themselves, so a ball ends with the game's bonus added on top of your points
  (MODE_SDK.md "The whole game").
- **The game's start-of-game video.** Stern's program plays it when Start is pressed, over every screen of yours, and
  no flipper press skips it (Uncanny X-Men 0.98's runs about 15 s). The kit's menu waits it out by itself, and
  `pm_start_film()` says when it is up for a screen of your own at the game's start (MODE_SDK.md "A menu at the game's
  start").
- **MPF-MC's free drawing.** No widget can be made at run time: every screen is built when the card is written,
  from `assets.json`.
- **Settings and audits of your own.** The operator's settings stay the game's (the Defaults tab sets them).
- **Anything outside the machine**: files, the network, Python libraries.

## The worked example: UNCANNY STORY (PAD-1410)

A small whole game in the shape of 20SidedDies' Uncanny X-Men 2.0, written first as an MPF game and then ported by
following this file. The full source is in the repository: `docs/plans/pad1410_mpf_port/mpf/` (the MPF game) and
`docs/plans/pad1410_mpf_port/xstory/` (`xstory.c`, `assets.json`).

The MPF game: a game-long `future` mode (priority 100: every ramp 1,000 and a point on the Mutant Meter, three left
ramps in a ball start the Sentinel, the Action button spends a full meter on the mutant's ability); a `roster`
carousel at each player's first ball (CYCLOPS, STORM, WOLVERINE, the ball waiting in the shooter lane, the last pick
the default); `sentinel` (200: a health bar of 6, a 10 s ball save, two Xjet hits start the Phoenix, defeating it
moves the player's story chapter on, kept between games); `phoenix` (300: a 2-ball multiball on a 30 s clock, a
health bar of 4, its right ramp `block: true`). Cyclops' ability is the Optic Blast: the glass fades to black with
a red glow.

The port, in one file:

```c
static const struct pm_mode future = { .name = "FUTURE", .init = fut_init, .tick = fut_tick,
                                       .shot = fut_shot, .ball_end = fut_ball_end };
static const struct pm_mode sentinel = { .name = "SENTINEL", .tick = sentinel_tick, .shot = sentinel_shot,
                                         .ball_end = sentinel_ball_end };
static const struct pm_mode phoenix = { .name = "PHOENIX", .tick = phoenix_tick, .shot = phoenix_shot,
                                        .ball_end = phoenix_ball_end };
PM_REGISTER(future); PM_REGISTER(sentinel); PM_REGISTER(phoenix);
```

The base starts with each game, has the whole game, and opens the roster:

```c
static void fut_tick(void)
{
    if (kit_new_game(&game)) new_game();                     /* game_started: every P[] back to its start */
    if (!pm_in_game()) { if (fut_on) fut_end("the game is over"); fut_done = 0; }
    else if (!fut_on && !fut_done && pm_player() >= 1) {
        if (pm_begin()) { pm_running_name("FUTURE"); pm_own_game(1); fut_on = 1; }
    }
    if (fut_on && !P[up].asked &&                           /* roster: ball_started{ball==1}; it waits for the */
        kit_menu_open(&roster, "CHOOSE YOUR MUTANT", MUTANTS, 3, P[up].mutant, 10000, KIT_MENU_HOLD_LANE))
        P[up].asked = 1;                                     /* game's start-of-game video by itself */
    int got = kit_menu_tick(&roster);
    if (got >= 0) { P[up].mutant = got; pm_saved_put("xstory:mutant", up, got); }
    ...                                                      /* the meters' and fades' ticks */
}
```

`variable_player`, the `sentinel_lit` counter and the Action button's ability, in the base's `.shot`:

```c
static void fut_shot(uint64_t s)
{
    if (!fut_on || kit_menu_shot(&roster, s)) return;        /* the menu's buttons are the menu's */
    if (pm_paused() || pm_shot_taken()) return;              /* a layer above kept this shot */
    if (s & S_ACTION) { ability(); return; }                 /* s_action_active{mutant_meter>=3} */
    if (!(s & (S_LEFT | S_RIGHT | S_XJET | S_DR))) return;
    award("FUTURE shot", 1000);                              /* variable_player: score 1000 */
    if (P[up].meter < METER_FULL) P[up].meter++;             /* mutant_meter: 1 */
    if ((s & S_LEFT) && ++P[up].lit >= 3) { P[up].lit = 0; want_sentinel = 1; }   /* start_mode_sentinel */
}
```

A layer begins in its own tick; `block: true` is a claim:

```c
static void phoenix_tick(void)
{
    if (!phoenix_on) {
        if (!want_phoenix || !pm_begin_layer(80, 0)) return;     /* priority 300 over the Sentinel's 200 */
        want_phoenix = 0; phoenix_on = 1; phoenix_hp = 4; phoenix_ticks = 30 * 60;
        pm_multiball_start(2, 10);                               /* phoenix_mb: 2 balls, shoot_again 10s */
        return;
    }
    kit_meter_set(&m_phoenix, phoenix_hp, 4, 0);                 /* the phoenix_bar widget */
    if (phoenix_ticks) phoenix_ticks--;
    if (phoenix_hp <= 0) { award("PHOENIX defeated", 100000); phoenix_end("defeated"); }
    else if (!phoenix_ticks) phoenix_end("phoenix_escaped");
}
static void phoenix_shot(uint64_t s)
{
    if (!phoenix_on || pm_paused() || pm_shot_taken()) return;
    if (s & S_RIGHT) { pm_shot_claim(); phoenix_hp--; award("PHOENIX hit", 20000); }   /* block: true */
}
```

The story, kept between games (`machine_vars` with `persist: true`, and the per-player chapter):

```c
P[up].chapter++;
pm_saved_put("xstory:chapter", up, P[up].chapter);                         /* this player's */
pm_saved_put("xstory:sentinels", 0, pm_saved_get("xstory:sentinels", 0, 0) + 1);   /* the machine's */
```

`assets.json` names what the build makes:

```json
{ "format": 1, "name": "UNCANNY STORY", "seconds": 600, "screen": false,
  "meters": [{"label": "SENTINEL", "color": "#e02020"}, {"label": "PHOENIX", "color": "#ffb000"},
             {"label": "MUTANT METER", "color": "#20b0ff"}],
  "fades": [{"color": "#000000", "style": "flat"}, {"color": "#ff0000", "style": "glow"}],
  "menus": [{"title": "CHOOSE YOUR MUTANT", "color": "#ffb000"}] }
```

## Building and trying it

1. In the app: Modes > New mode > C (tick "It ports a game I wrote in MPF" to have this file named in what is
   copied for the agent). Put the port in the new `<slug>.c`, copy `examples/intricate_kit.h` beside it, and
   write `assets.json`.
2. **Try it** builds the card's modes and plays them in the emulator; a **Write** puts them on a card. Both build
   the screens `assets.json` names, `buttons.cfg` (the button shots) and `saved.cfg` (the saved-progress store,
   added when the C calls `pm_saved_`).
3. Read `/dump/mode.log` (the rig's: MODE_SDK.md "The loop"). `pm_log` every rule's step: it is how the port is
   checked against the MPF game's behaviour.
4. Without a playfield, the emulator's switches are pressed by number: the rig's
   `dump/tables/<game>/switch_list.txt` names each (`swpoke.py <id>`), and `buttons.cfg` gives the buttons' ids.

## What was proven (PAD-1410)

UNCANNY STORY, built by the app's own Write from the files above, on Uncanny X-Men LE and Pro 0.98 in the emulator
(hidden, muted; `docs/plans/pad1410_mpf_port.md` has the run): the roster after the game's start-of-game video (the
flippers moving,
Action picking, the ball waiting in the shooter lane); three left ramps starting the Sentinel layer with its health
bar and ball save; a right ramp hitting it; Action spending a full Mutant Meter on the Optic Blast (the fade, 3
damage); two Xjet hits starting the Phoenix layer over it, its health bar beside the Sentinel's and its 2-ball
multiball; the right ramp the Phoenix's alone while it ran; both defeated; the score at every step exactly the
game's own points. Then a power cycle: the next game read back CHAPTER 2 and the last pick, and a second power cycle
kept the next pick.
