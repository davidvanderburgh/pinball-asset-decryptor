# The Spike 2 game-play API: Godzilla Pro 1.15

Item 125, Phase 0. The record of how a mode is built inside the game, so that a
preloaded `mode.so` can add one. Everything here was read from the stripped game ELF
on 2026-09-15; nothing has been watched live yet unless a line says so. A `?` after a
name means its role was inferred from its callers.

- **Build:** `godzilla_pro/game`, sha1 `08d502998706d327bfbb6ea5f92ac0cee76be63b` (1.15.0).
- **Addresses:** ELF virtual addresses. The game is `ET_EXEC`, so in-process (a preloaded
  .so, `PAD_PEEK`) they are exact. A `/proc/<pid>/mem` read under qemu-user adds
  `0x10000` (see `reference_spike2_qemu_guest_base`).
- **LE and 1.16 move every address.** The LE `game_real` has `cmode_tesla_strike` at
  `0x5d0818`, not `0x6307b8`. A mode.so must locate by pattern; see `patloc.py`.

## The instruments (all read-only, all in `tools/spike2_emu/`)

| Tool | What it answers |
|---|---|
| `rtti_tree.py <elf> --vtables` | Every polymorphic class, its bases and vtable. It now also recovers leaf classes reached only through a vtable, which lifted Pro 1.15 from 415 to 461 classes and found seven modes the name scan missed. |
| `vtslots.py <elf> <class>...` | A class's slots against its base: OVERRIDE, `=base` or NEW, how widely each function is shared, and where the vptr is loaded (constructors). |
| `armxref.py dis <elf> <start> <end> \| <va>:<len>...` | Annotated disassembly: classes, vptrs, strings, PLT imports and the engine names below. |
| `armxref.py xref <elf> <va>...` | Every bl/b, literal-pool load and movw/movt pair that reaches a value. |
| `armxref.py args <elf> <fn>...` | Every call of a function with the constants in r0-r3 at the call site. It is conservative: a register loaded before an intervening call reads blank. Validated on `hook_subscribe`, where `0x312f8` = event 62, handler `0x309ec`, prio 128, the same as `evmap.sh`. |
| `patloc.py <ref> <other> name=0xVA... \| --engine` | Masked signatures unique on the reference build, and where they land on another. |

`evmap.sh` undercounts the event bus. `hook_subscribe` has **227** call sites: the 167
`bl`s it lists, plus 60 tail-call `b`s it cannot see.

## Singletons and tables

| What | Address | Notes |
|---|---|---|
| `cmode_manager` | `0x79d954` | Initialised when bit 0 of the guard at `0x79dbd8` is set. Constructor `0xd27d4`. |
| mode table | `0x7a1698[0..26]` | 27 static mode objects, filled by the manager's constructor |
| null mode | `0x7a1708` | What `get()` returns for an id above 26, after error 314 |
| `cawards_manager` | `0x79d660` | Award records at `0x79aca0 + id*280`, ids 0..36 |
| `ctimer_manager` | `0x79ac94` | Timers at `0x7a7300 + idx*112`, idx 0..29; idx 32 = the null timer `0x7a8020` |
| player scores | `0x7e4968 + 8*(p-1)` | u64 each: **the PAD_PEEK target for "the mode scored"** |
| current player | byte `0x708170` | 1..4 |
| player count | byte `0x7e2ea8` | |
| playfield multiplier | byte `0x708368` | 1..5; set by `0x4b8e7c(n)` |
| display dirty | byte `0x7e11bc` | Every mode state change sets it to 1 |
| event nodes | list `0x7b7e80`, current `0x7b7e84` | 320 B each; a node's arguments start at `+0xa0` |

## The 27 modes

Constructor arguments are `(this, id, a, award, b[, timer])`. Every mode derives from `cmode`.

| id | class | base | a | award | b | timer |
|---|---|---|---|---|---|---|
| 0 | (null mode `0x7a1708`) | | | | | |
| 1 | cmode_godzilla_multiball | mball | | | | |
| 2 | cmode_mechagodzilla_multiball | mball | | | | |
| 3 | cmode_bridge_attack_multiball | mball | | | | |
| 4 | cmode_tank_attack_multiball | mball | | | | |
| 5 | cmode_saucer_attack_multiball | mball | | | | |
| 6 | cmode_battle_vs_megalon_and_gigan_mb | mball | | | | |
| 7 | cmode_planet_x_multiball | mball | | | | |
| 8 | cmode_monster_zero_victory_multiball | mball | | | | |
| 9 | cmode_terror_of_mechagodzilla | mball | | | | |
| 10 | cmode_king_of_the_monsters_multiball | mball | | | | |
| 11 | cmode_monster_island_madness | mball | | 28 | 17 | |
| 12 | cmode_battle_vs_ebirah | battle | 10 | 19 | 7 | 0 |
| 13 | cmode_battle_vs_titanosaurus | battle | 10 | 20 | 7 | 1 |
| 14 | cmode_battle_vs_gigan | battle | 10 | 21 | 7 | 2 |
| 15 | cmode_battle_vs_megalon | battle | 10 | 22 | 7 | 3 |
| 16 | cmode_battle_vs_king_ghidorah | battle | 26 | 23 | 7 | 5 |
| 17 | cmode_battle_vs_ghidorah_and_gigan | battle | 26 | 24 | 7 | 6 |
| 18 | cmode_super_train | timed | | 25 | 11 | 17 |
| 19 | cmode_o2_destroyer | timed | | 26 | 12 | 18 |
| 20 | cmode_king_of_the_monsters | timed | 18 | 27 | 16 | 25 |
| 21 | cmode_jet_fighter_attack | hurry_up | 4 | 29 | 8 | 7 |
| 22 | cmode_planet_x_hurry_up | hurry_up | 20 | 16 | 13 | 21 |
| 23 | **cmode_tesla_strike** | cmode | | 30 | 9 | |
| 24 | cmode_monster_rampage | timed | 18 | 31 | 10 | 14 (+15 of its own) |
| 25 | cmode_hedorah | cmode | | | 19 | |
| 26 | cmode_monster_zero | cmode | 16 | 17 | 14 | |

Blank cells were not captured by `args`, which cannot see a value built by an
intervening call. Every slot holds a real mode on Pro, so **there is no null slot to
borrow.**

## The `cmode` object

| Offset | Field | Evidence |
|---|---|---|
| `+0x00` | vptr | |
| `+0x04` | id | v[16]; the manager keys on it |
| `+0x08` | a | v[17] |
| `+0x0c` | b | v[18]; copied into display nodes (`0x10cf54`) |
| `+0x10+p` | qualified[p] | v[6] sets it, v[19] reads it (p is 1-based, so the arrays below start one element in) |
| `+0x14+p` | stopped this ball[p] | set once by v[11], read by v[21] |
| `+0x18+p` | stop reason[p] | v[11] stores its reason when this is 0; v[23]. **1 = completed.** |
| `+0x1c+p` | running[p] | v[12] |
| `+0x18+8p` | lit-shot mask[p], u64 | v[25] get, v[26] set, v[45] |
| `+0x3c+4p` | level[p] (starts) | v[32]; start increments it, v[3] clears it |
| `+0x50` | `caward*` | constructor: `caward_get(cawards_manager, award)` |
| `+0x54` | progress snapshot at start | `0x23e924(p)`; `0x7ddcc` returns the delta |
| `+0x58` | armed (byte) | v[34] |

`cmode_timed` (vtable `0x6319f0`) adds `+0x5c` timer*, then the u16 countdown callouts at
`+0x60/+0x62/+0x64` (defaults 1287/1291/1295, re-picked each start by `0x11b234` from
table `0x7a4a98`), and `+0x66` = "the 10 s callout played".

## `cmode` vtable roles (`0x626410`, 48 virtuals)

A call site is `ldr r3,[r0]; ldr r3,[r3,#4*n]; blx r3`. The game devirtualises often: it
compares the slot to the base function and inlines when they are equal. Those compares
are what make the default functions easy to find.

| Slot | Base fn | Role |
|---|---|---|
| 0, 1 | `0x7df2c`, `0x7df30` | destructor, deleting destructor |
| 2 | `0x7d1d0` | no-op |
| 3 | `0x7d278` | **reset for a new game**: v[5], level = 0, running = 0 |
| 4 | `0x7d1d4` | no-op. Tesla uses it as end of ball: `if v[14]() v[11](0)` |
| 5 | `0x7d234` | **reset for a new ball**: clears qualified, stopped and reason |
| 6 | `0x7d2f8` | qualify (unless stopped this ball) |
| 7 | `0x7d1d8` | can_start, returns 1 |
| 8 | `0x7db28` | **START**: if can_start and not running: running = 1, armed = 0, mask = v[44](), level++, v[42]() (start display), `cmode_manager_started(id)`, snapshot |
| 9 | `0x7d4b0` | resume: running = 1, mask = v[45]() |
| 10 | `0x7d5f4` | **END**: running = 0, v[43]() (total display), notify RuleHeatRay |
| 11 | `0x7d9e8` | **STOP(reason)**: once per ball; stopped = 1, reason, `0x458260(30)`, running = 0, v[10](), `cmode_manager_stopped(id, reason)` |
| 12 | `0x7d21c` | is_running |
| 13 | `0x7d1f0` | returns 0 (pending?) |
| 14 | `0x7d520` | is_active = v[12] \|\| v[13] |
| 15 | `0x7d2b0` | **on_shots(this, _, mask64, x)**: if active, v[41] |
| 16, 17, 18 | `0x7ded0`... | id, a, b |
| 19, 21, 23 | | qualified, stopped(player), reason(player); 20/22 are the current-player wrappers |
| 24 | `0x7dffc` | v[18] |
| 25, 26 | | mask get, mask set (r2:r3) |
| 27 | `0x448dc` | **title message id** (tesla: 3242) |
| 28 | `0x7dee8` | **audit "started"** (tesla: 243); `cmode_manager_started` adds 1 |
| 29 | `0x7def0` | **audit "completed"** (tesla: 244); `stopped` adds 1 when reason & 1 |
| 30, 39, 40 | | return 0 |
| 31, 33 | | no-ops. v[31] is the notify another mode calls (`0x7ddf0`) |
| 32 | `0x7dfac` | level |
| 34 | `0x7d400` | arm if a lit shot is in the shot universe; calls v[38] |
| 35 | `0x7d7b4` | has a lit shot |
| 36 | `0x7d838` | replay the shot groups from v[47] through v[15] |
| 37, 38 | | v[15] with a mask; v[38] uses the lowest lit bit (`0x1b3ae8`) |
| 41 | `0x7d334` | **on_shot default**: clear the hit bits; if the mask is now empty, v[11](1) = COMPLETED |
| 42 | `0x7d38c` | start display: `event_post_replacing(311, 0x52ec0, 2)`, `+0xa0` = 50, `+0xb8` = v[27] |
| 43 | `0x7d6b0` | total display: `event_post_replacing(255, 0x52ec0, 0x2002)`, `+0xb8` title, `+0xc0` award total, `+0xf0` = 275 if completed |
| 44 | `0x7d1e0` | initial lit mask `0x00000058_00700800` |
| 46 | `0x7df1c` | shot universe, same value |
| 47 | `0x7d588` | vector<u64> of shot groups (7, from `0x6263d8`) |

### `cmode_timed` (62 virtuals): the timer

- **v[3]** `0x11ad90`: wires the timer. Owner = this (timer v[11]); callbacks on timer
  v[37]/v[38]/v[39], with v[39] = **`0x11b108`, expiry → `mode->v[11](0)`** (stopped,
  not completed). Durations come from v[56]() and v[57](), both 30 s by default.
- **v[8]** `0x11b2d8` (start): the base start, then timer v[16](30), v[12](30), v[18](30),
  v[5]() then v[2](). This reads as reset then run, but the timer's own slots are not
  disassembled yet.
- **v[10]** (end): timer v[5]. **v[12]** is_running → timer v[7]. **v[48]** `0x11afb8` →
  timer v[3](n) (add time?).
- **v[55]** `0x11ac5c`, the countdown: callout 1291 at 10 s (v[61]), `callout_play_nth(1287, s-1)`
  from 5 s (v[59]) to 1 s (v[60]), and 1295 at 0.

## Starting and stopping a mode from outside

`RulePowerlines` (shot handler `0x1666fc`) starts tesla strike once its count reaches
the threshold:

```
0x166800  m = cmode_manager_get(0x79d954, 23)
0x166818  ((void (*)(void *))(*(void ***)m)[8])(m)    // v[8] START
```

Everyone else only reads a mode, through v[12]/v[14]. So a mode.so can start or stop
any mode with one call. `cmode_manager_started` and `stopped` both `cmp r1,#26` and
return at once for a larger id, so **a mode object of our own with id 27 runs the base
class without touching the table or the audits.**

## Engine calls

| Call | Address | Behaviour |
|---|---|---|
| `current_player()` | `0x460ba0` | byte `0x708170` |
| `player_check(p)` | `0x460a90` | 1..4, else error 20 → 1 |
| `score_add(p, v64)` | `0x4b8cf4` | Refused while `global_mode_mask & 0x210` (error 24). v *= multiplier. `dispatch(161, &v)` must return nonzero, else `dispatch(162, &v)` and nothing is added. Then `scores[p-1] += v`, and notifications `0x208858`, `0x3cb96c`. Returns v. |
| `score_add_current(v64)` | `0x4b8e5c` | the above for the current player |
| `caward_get(mgr, id)` | `0x30e48` | |
| `caward_add(aw, _, v64, idx)` | `0x2facc` | `score_add_current(v)`, then award total `+0xf0[p]`, per-index `+0x84`, best `+0x90`; `0x2fa84` keeps `+0xd0` |
| `caward_add_scaled(aw, notify, idx, mult)` | `0x2fb8c` | |
| `audit_add(id, n)` | `0x422de4` | table `0x715104` ×16 |
| `get_adjustment(id)` | `0x45df38` | table `0x70a570` ×44. **The handoff's `0x25feec` is not this on Pro 1.15**: it lands mid-function. |
| `error_log(code)` | `0x457e00` | |
| `sound_request_play(req)` | `0x2a3108` | The 20-byte request table at `0x771530` (the one `sound_requests.py` mines); 8 channels ×196 B at `0x7b8a9c` |
| `sound_request_play_nth(req, n)` / `_variants(req)` / `_active(req)` | `0x2a32bc` / `0x2a3c98` / `0x2a387c` | |
| `callout_play(req)` / `_nth` | `0x187f44` / `0x18800c` | Swaps in RuleCities' city variant (`0x188308`, table `0x7a7268`), then plays |
| `event_post(id, handler, flags)` | `0x2551dc` | (handoff) |
| `event_post_replacing(id, handler, flags)` | `0x2555dc` | `0x25554c(id, 0xffff)` first |
| `show_start(id)?` | `0x4f34e0` | Table `0x719ebc` ×12; a priority gate against the running nodes (`+0x98`); returns a node with arguments at `+0xa0`. 446 call sites. |
| `game_event(id, _, v64, a, b64)?` | `0x44c320` | Tesla posts 92 at start, 93 on collect, 94 at end with the mode total |
| `ctimer_get(mgr, idx)` | `0x18b47c` | |
| `cmode_manager_get(mgr, id)` | `0xd1c10` | |
| `cmode_manager_started(mgr, id)` | `0xd246c` | |
| `cmode_manager_stopped(mgr, id, reason)` | `0xd24c4` | |
| `hook_subscribe` / `hook_dispatch` | `0x4bb380` / `0x4bb42c` | (handoff) Score events 161/162 above |

## Tesla strike, as the worked example

The class is `cmode_tesla_strike` (`0x6307b8`, 50 virtuals), constructed at `0x10ce08`
with id 23, award 30 and b 9; its object is at `0x7a2878`.

- **Start** (v[8] `0x10c0e4`): the base start. If it took: clear the per-ball bytes,
  value = **2,000,000 × level**, and `caward_add(aw, _, 250000, 0)`, so starting scores
  250,000. It sets `+0x5c` hits = 1 and **lit mask = `0x48_00700000`**, then
  `game_event(92)`.
- **Shots** (v[41] `0x10d0bc`, arguments r2:r3 = the shot mask), keyed by bit:
  - `0x2000`, the spinner: `0x2f784(aw, hits × 100,000)`, "SHOOT SPINNER TO BUILD
    TESLA STRIKE VALUE!", plus `0x185e9c(200, 3, 0)`.
  - `0x1000`: flag `+0x59`, then `0x10ce40` (`0x3ba540(121,...)` + `show_start(148)`).
  - `0x700000 | 0x48<<32`, the blue arrows: `caward_add_scaled`, then 5% into
    RuleDestructionJackpot (`0x1456c4`). hits++ and value = hits × 2,000,000, then
    the award screen `0x10ce94(3159 or 3160, value, remaining)`. That screen is
    `0x3ba540(122)` with the message id at `+0xa0`, shows 148/348/342/359, a sound
    request from `0x7a4028`, and `0x185e9c(334)`. When no lit bit is left:
    `v[11](1)` and `game_event(93)`.
- **End** (v[10]): base end, then `game_event(94, total)`.
- **Total display** (v[43] `0x10c2ec`): `event_post_replacing(245, 0x52ec0, 0x2002)` with
  title 3242, the total, clip `"Mothra_godzilla_attack20"` or
  `"Mothra_godzilla_powerlines10_2"` by completion, and 582/565.
- Slots 27/28/29 return 3242/243/244.

## Not located yet

- **How shots reach v[15].** Something turns switch closures into the 64-bit shot masks
  (`cshot`, and the per-switch descriptors behind `switch_drain 0x1e7540`) and hands them
  to the modes. A mode.so's own shots need this, or its own subscription to the
  switch event.
- **The text screen.** `0x3ba540(n, a, b, 0x6fa618)` → `0x51eab8`/`0x51eb00`, and
  `show_start`, are the candidates. The message ids (3242, 3159, 3160) are not yet
  resolved through the message table.
- **Lights.** `0x185e9c(n, a, b)` (it checks `global_mode_mask & 0x310` and calls
  `0x39fe24(7, ...)`) and the `blele` runner.
- **Free timers.** Modes take 0-3, 5-7, 14, 15, 17, 18, 21 and 25; rules take others.
- **`cgametimer`'s own slots.** The roles above come from how `cmode_timed` calls them.
