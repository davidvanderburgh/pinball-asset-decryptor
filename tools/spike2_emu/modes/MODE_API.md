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

## A MODE IS A FILE (item 126, emulator-proven 2026-09-15)

`mode.so` holds no rule of its own any more. It is an interpreter over a mode file -
`/dump/mode.cfg` in the rig, `modes/kaiju_rush.mode` in the repo - which it re-reads
**twice a second** and re-parses whenever the bytes change, so an edit lands in a
RUNNING game inside a second. That is what makes a mode something you choreograph
rather than rebuild.

```
name           KAIJU RUSH
trigger        0x08000000 3      # shot mask, and how many in one ball
seconds        30                # the tick clock; no game timer is free
shots          0x70300000        # what scores while it runs
award          1000000           # first shot; the Nth shot is N times this
screen_type    122               # the award-screen family
title_msg      3159              # message ids our words are put behind
total_msg      3160
title_words    KAIJU RUSH
total_words    KAIJU RUSH TOTAL
restore_after  6                 # seconds after the end to give the ids back
light_owner    538
light_on       blele --sweep 0 --lts 224 --red 0 --green 255 ...
light_off      blele --sweep 1 --lts 224 --fade 20 --rgb 0 ...
callout_at     10 1291           # id at N seconds left (up to 8 lines)
callout_count  1287              # variant (seconds - 1), for 5 down to 1
callout_end    1295
```

- **Key per line, `#` comments, decimal or `0x`.** A value that is text (a light
  command, a name) is taken verbatim to end of line, because a blele command is full
  of dashes and digits and must not be tokenised.
- **An unknown key is logged and skipped**, never fatal, so a newer editor writing a
  newer key cannot break an older `mode.so`.
- **Not JSON, and no `stat`.** The object is built `-nostdlib` with libc declared by
  hand in `hook.h`: there is no allocator and no `stat`, so the format parses against
  fixed buffers in a few dozen lines and the reload check byte-compares a re-read.
- **Proven (run 1):** the file's own values ran the mode - lights landed 6 lamps from
  413, shots scored 1M..5M - and then the file was rewritten mid-game: "reloaded while
  running - the new file is live", and the next start obeyed the new name, 12 s and 7M
  award, ending at 11,984 ms. A 10-minute soak on this build ran 14 starts and 14 ends
  with no SEGV.
- **The log prefix is `[mode]`, not `[rush]`** - the mode's name is data now. Anything
  still grepping `[rush]` matches nothing; `soak.sh` counts on the NAME, which the file
  supplies, so it keeps working.

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
| `+0x0f+p` | qualified[p] | v[6] sets it, v[19] reads it. p is 1-based, so player 1 is `+0x10` |
| `+0x13+p` | stopped this ball[p] | set once by v[11], read by v[21] |
| `+0x17+p` | stop reason[p] | v[11] stores its reason when this is 0; v[23]. **1 = completed.** |
| `+0x1b+p` | running[p] | v[12] (`strb [this+p+27]` in start). The first probe read `+0x1c+p` and printed "running 0 -> 0" over a start that had worked. |
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
| `sound_request_play(req)` | `0x2a3108` | A thin wrapper: bumps a serial at `0x7b930c` and tail-calls the worker `0x2a26f4`. The 20-byte request table at `0x771530` (the one `sound_requests.py` mines); 8 channels ×196 B at `0x7b8a9c` |
| `sound_play_worker(req, out, n, x)` | `0x2a26f4` | The real thing, and the whole play chain (below). Bounds-checks `req` against `[0x60bd34]`, walks the NUL-terminated sid list at `0x771530[req*20 + 8]`, resolves, arbitrates a channel, `hook_dispatch(0xac)`, `0x2a2044`. 9 callers - every `sound_request_*` and `callout_*` entry point funnels here |
| `sid_descriptor(sid, &keystream)` | `0x2a1f54` | sid → its descriptor. `sid >> 16` picks the table via `0x481af4`; the returned bytes are whitened by the vf2 keystream at `0x700bf4` (`VF2_VA`), and the first byte de-whitens to **5** or it is not a descriptor. This is `sfx_names.resolve_descriptor`'s function, in the game rather than under Unicorn |
| `sound_lookup(map, key8)` | `0x33c0d8` | **The container lookup, and the way in for a sound of our own.** `bucket = 0x5beea0(key.w1, map[1])`, then `find` `0x2a25e0`, then `*node` = the entry, else 0. Two arguments, no insert path, no mutex. The map is `0x7b9464` and its bucket count `0x7b9468`, both built by the static ctor `0x33c514` |
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

## A sound the game never shipped: the play chain, read 2026-09-15 (item 130)

Every `callout_play` / `sound_request_play` in this file ends in one worker, and the
worker reaches the card's audio through a hash map keyed on eight bytes. Read off
`godzilla_pro/game` with `armxref.py` (`dis`, `xref`, `args`), no rig:

```
callout_play(req)        0x187f44   swaps a city variant, then
sound_request_play(req)  0x2a3108   serial++, then
  sound_play_worker      0x2a26f4   req -> the sid list at 0x771530[req*20+8]
    sid_descriptor       0x2a1f54   sid -> descriptor (vf2-whitened, magic 5)
      key.w1 = payload.w1
      key.w2 = (payload.w2 & 0xe0001fff) | ((sid >> 16) << 13)
    sound_lookup         0x33c0d8   key -> ENTRY, via find 0x2a25e0 (all 64 bits)
    channel arbitration  0x7b8a9c   8 x 196 B, priority at +0x98
    hook_dispatch(0xac)  0x4bb42c   the engine's own veto
    start                0x2a2044
```

**The load-bearing fact, and it was already measured on another card:** the boot-time
band build registers EVERY record in `image.bin` with this map, under a key that moves
with the record's geometry. So an APPENDED record registers as its own entry, distinct
from the record it was copied from - Led Zeppelin idx 44 stock `0xf3e13d92`, its
appended copy `0xb0c13c9e`, both live, and the Sound Test played the stock one because
nothing NAMES the appended key. Item 104 solved that by re-pointing a descriptor, which
retires the stock slot. **A mode does not have to.** `mode.so` is a hook, so it can
answer `sound_lookup` itself: when the lookup key is the one the mode's chosen request
would resolve to, hand back OUR entry instead. The card keeps every stock byte, no
descriptor is re-pointed, and the neighbours are unchanged by construction.

### MEASURED FALSE: `sound_lookup` is BOOT-ONLY, so a play-time hook never fires

Run 1 of the mode with a `sound_key`: the mode ran its full 30 s, scored ten shots,
ended on its clock - and logged **`own sound: 0 substitution(s), 1 miss(es)`**. The
one-shot armed, `callout_play(1295)` fired, and `sound_lookup` was never called.

**The reading error that caused it, because it is easy to repeat.** `armxref.py args`
prints its `NAME : N call site(s)` header **AFTER** the list it belongs to. Read as a
header-first listing, `0x33c0d8` appears to be called from `0x2a26f4` (the play
worker). It is not. Its four callers are `0x33a394`, `0x33a89c`, `0x33b094`,
`0x33b4b8` - **all inside the band build**, which agrees with `xref 0x7b9464` (8
sites: 6 band build, 2 in the static ctor). The sites under the play worker belong to
`0x2a1f54`, the descriptor resolver.

**So how a sid reaches audio at PLAY time** (`0x2a2c34`..`0x2a2fc4`): a `std::map`
rooted at `0x7b92c4`, keyed by sid. The worker walks it comparing the sid against
`[node+16]` and following `[node+8]` / `[node+12]`, and `0x2a2ff8` is
`_Rb_tree_increment`, so the nodes are ordinary `_Rb_tree_node`: colour `+0`, parent
`+4`, left `+8`, right `+12`, payload from `+16`. The binding sid -> entry is built
ONCE at boot - the band build resolves each descriptor (`0x2a1f54`), computes the key,
looks the entry up (`0x33c0d8`), and inserts it into this tree. After that, playing a
sound never consults the container again.

**What this means for the item as written.** Item 130's target was "a request id our
`mode.so` can call" for a sound the game was never built with. Measured: an id the
game does not already have a tree node for is unreachable, because nothing resolves an
unknown sid at play time. The item anticipated exactly this and says to report it with
the evidence rather than quietly take the fallback. This is that report.

The appended record is still real, registered and decodable - that half is proven
above. What is not proven is reaching it by an id the game never shipped.

**The obvious next idea, and why it is NOT established.** The boot-side insert
(`0x33b310`..`0x33b364`) allocates a 40-byte node and writes: sid at `+16`, then r7 at
`+24`, r8 at `+28`, ip at `+32`, lr at `+36`. It is tempting to read lr's
`r6 + r6<<2` / again / `<<4` as "record index x 400", which would make retargeting a
sid to our record a single reversible word. **It is not that.** Between those shifts,
at `0x33b0e0`, `r3 = [r6,#32]`, `r3 <<= 1`, and `r6` is RELOADED as the byte at
`[r6,#42]`, then `ip = r6 * r3` - a product of two fields of a codec object, a size or
duration rather than an index. The four payload words are still unidentified, and
`+24`/`+28` come from `[r0,#16]` and `[r6,#20]` of objects the band build is holding.

So the next pass starts here: identify those four fields from the band build's own
caller context, and only then decide whether a sid can be pointed at our record. Do
not patch a live tree on the strength of the arithmetic above - it was wrong once
already tonight, in exactly the same way the `args` header was.

### PROVEN AT THE DESK: the bank takes a record the card never had (2026-09-15)

`modes/grow_mode_sound.sh` appends one record to a standalone `image.bin` through the
SHIPPED `masterdir` + `emulator` + `codec` code - no card build, because the rig boots
the extracted title, so the bank is a plain file. On Godzilla Pro 1.15, in 80 seconds:

| | stock | grown |
|---|---|---|
| records | 2534 | **2535** |
| file | 1,649,655,138 | 1,650,008,450 |
| rows with a findkey | 2534 / 2534 | 2535 / 2535, **all distinct** |
| stock records that moved | - | **0** |

The appended record (idx 2534, `body_off 0x6253bd92`, length 176,600 = 4.00 s) copies
idx 1369's identity but its own geometry, so it registers under **its own key**
`45df2b8b01000084` against the source's `44be2bed20000094` - the two entries coexist
and nothing names ours. Our four-second three-tone figure encodes into it and decodes
back at **peak error 0, corr 1.00000**.

Two things that make this work and are easy to get wrong:
- **`plan_grow_records` only ever APPENDS** (`new_length` must exceed `old_length`); it
  never edits a record in place, because changing a length word shifts every later
  record's decode parameters including its container key.
- **The scaffold body must be real card audio**, not zeros: the codec is driven over
  those bytes to recover the keystream, and a degenerate body gives a degenerate one.
  `warm_slots_for_grown` must also run before the encode, or the round trip silently
  fails to reproduce what it was given.

### The grown bank BOOTS and runs clean (2026-09-15)

First run on it: guest up 4m 32s, **0 `[segv]` lines and 0 fatal signals**, attract
video steady at 30.0-30.4 fps, and `/dump/audio.raw` growing past 37 MB - the game
plays normally with a record in its sound bank that the card never shipped and no
descriptor names. `install_mode_sound.sh on|off|status` swaps the banks by rename.

**A trap that cost a run, and it is about the LOG, not the sound.** `hk_log_open`
opens `/dump/mode.log` with `O_WRONLY|O_CREAT|O_APPEND`. An earlier run left that
file owned by **root** while the guest runs as **uid 1000**, so the open returned
EACCES, `hk_log_fd` stayed -1, and every single `hk_logs` call returned silently -
a fully loaded, correctly hooked `mode.so` that said nothing at all. It looks
exactly like a refusal at the gate, which is the expensive part: `hk_is_game_process`
returns BEFORE `hk_log_open`, so a real gate failure is also silent. Tell them apart
by reading the guest's own `/proc/self/maps` dump in `game.out` - if `/lib/mode.so`
is mapped there, the constructor ran and the gate passed. **Delete `mode.log` before
a run; never truncate it**, and note the tick site `0x4ec828` falls in a `rwxp`
mapping, which satisfies the gate's `r..x` test.

**Still to prove in a run:** whether an entry reached this way plays identically, and
derive that yields the appended record's key runs on this build at all - Godzilla Pro
1.15's bank is 1,649,655,138 bytes, `md_off` **`0x6252cfca`** (1,649,594,314),
**2534 records** (`0x9e6`). The arithmetic that confirms all three:
filesize - md_off = 60,824 = `masterdir.tail_len(2534)` exactly. The count is
EVEN, which is the case `tail_len` exists for: appending flips the parity and the
tail grows by 32 bytes (60,824 -> 60,856), not 24.

**The derive runs, and it is cheap** (measured 2026-09-15): boot 0.8 s, then
`derive_params` returns **2534 rows in 38.5 s**, every row carrying a findkey and
**all 2534 distinct**. `generic=True`, `FIND_BL=0x33baf8`. A key reads
`69cdade0 02020000`: `w1` a hash of the body, `w2` a small fragment id living in
the low 13 bits - consistent with `(payload.w2 & 0xe0001fff)` and `sid >> 16 == 0`.

### The measurement, and a correction to an old note

`PAD_AUDIO_OUT=/dump/audio.raw` is set by `run_game.sh` on every run, card 0, with the
centre channel beside it as `.center`. After item 127's run both files held 294,400
bytes = 1.53 s at 48 kHz stereo, **84.6% non-zero, peak 9088, rms 1930** - real audio.
The item 104 note that "the Ubuntu-side rig's PCM capture is dead (28800 bytes always)"
has not been true since; measure with `pcmstat.py`, and score against a reference with
`audioscore.py`.

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

## The vehicle, in the rig: `modes/padmode.so` (the Phase 0 probe)

`modes/build_modes.sh` builds it, and `mode.so`, into the stage. `gen_sites.py` bakes in every
site's expected first two instruction words, read from the ELF it is built for. The
run copies it to `$ROOT/lib` under the rig lock and preloads it with
`PAD_TRACE_SO=/lib/padmode.so`. Hooks are hwshim's `pad_hook` trampoline, except the
logger gets a pointer to the saved r0-r3/ip/lr. Triggers are files in `/dump`
(`padmode.start|stop|shot|score|sound`), polled from the tick hook, so everything the
probe does to the game happens on the game's own scheduler thread.

**Run 1 (2026-09-15) found the vehicle's first real rule: `LD_PRELOAD` reaches every
child the game spawns.** A `PAD_PIVOT` run exports it, and `system("rm -r -f
/connectivity/files/gkpd_3")` runs 2.3 s after boot. The probe had installed all 13
hooks in the game and logged a live `0x3ba540(6, ...)` call. It then loaded into that
child `/bin/sh`, read Godzilla's tick address with nothing mapped there, and took
SIGSEGV (`[system] ... -> 139`). `watch.sh` saw the fatal signal in the shared
`game.out` and stopped a game that was fine. The card's launcher is the same shape
(`game_monitor` is a shell loop under the same `LD_PRELOAD`). So **a mode.so must
confirm from `/proc/self/maps` that an executable `game` mapping covers its sites
before it reads a single game address.** padmode.c now does. At the desk,
`qemu-arm-static -E LD_PRELOAD=padmode.so affcat --help` runs its constructor and
writes nothing.

## How far the locators carry: Pro 1.15 against LE

`patloc.py godzilla_pro/game godzilla_le/game_real` (2026-09-15). Signatures come from
the Pro function's first 8-40 instructions. A strict mask drops branch and literal
offsets and movw/movt immediates; the loose fallback also drops data-processing
immediates and ldr/str offsets. **29 of 41 land exactly once on LE.**

- **Portable (strict):** caward_get, cmode_ctor, cmode_manager_get / started / stopped,
  cmode_timed_ctor, callout_play_nth, ctimer_get, switch_drain, event_post,
  fiber_yield, event_post_replacing, all four sound_request calls, audit_add,
  error_log, get_adjustment, player_check, message_picker, tick_body_60hz,
  show_start, **score_add**, cmode_start (v[8]), RulePowerlines' shot handler.
- **Portable (loose):** hook_subscribe, hook_dispatch, cmode_timed's expiry callback.
- **Absent on LE:** caward_add / caward_add_scaled, game_event, current_player,
  score_add_current, cmode v[10] / v[11], cmode_timed start, both tesla functions.
  `callout_play` is not unique even on Pro (two identical 40-word bodies).
- **LE has one more slot at every `cmode` level:** `cmode` 49 virtuals (Pro 48),
  `cmode_timed` 63, `cmode_tesla_strike` 51. So a slot NUMBER is not portable. A
  mode.so should find a slot by comparing the vtable against a located base
  function, which is how the game itself devirtualises.
- **The handoff's `0x25feec` is LE's `get_adjustment`:** the Pro 1.15 pattern lands
  there. That is why it read as mid-function on Pro.

A locator that misses is reached through a unique caller instead. For example,
`current_player`'s byte is a movw/movt pair inside `score_add`.

## Emulator-proven: run 2 (2026-09-15)

`PAD_PIVOT` Godzilla Pro, `PAD_TRACE_SO=/lib/padmode.so`, `PAD_PEEK=0x7e4968:8`. A game
was started with `plunge.py game` and driven with `padmode_trig.sh` and
`padmode_drive.sh`. All 13 hooks ran through boot, attract and a game without a fault.

- **A mode starts on demand.** The `padmode.start` trigger ran `get(mgr, 23)->v[8]()` on
  the tick thread mid-game:
  - `cmode_manager_started(23)` fired from `0x7dc28`, inside base start.
  - `caward_add(aw 30, 250000)` came from `0x10c244`, inside tesla's start.
  - `score_add(1, 250000)` came from `0x2fafc`, inside `caward_add`.
  - The peek of player 1's score moved from 0 to `90 d0 03 00` = 250,000.

  A second forced start after the ball ended worked the same way.
- **Calling `score_add` from our own code works.** `score_add(1, 12345)` from the .so
  (r0 = player, r2:r3 = the u64) returned 12345, and the score peek read 3,850,315.
- **How shots reach a mode.** The shot handler `0x18601c` takes a 64-bit mask, finds
  it in a 24-byte table at `0x7a6e38` (an audit id at `+18`), and calls
  `cmode_manager::v[7]` `0xd1a9c(mgr, _, mask, 1)`. That walks the 27-entry table and
  calls every mode's **v[15]**; the call site is `0xd1ad4`. Each playfield switch makes
  two dispatches: bit 0 (`0x1`, "a playfield switch"), then its own shot bit. A mode
  sees a shot only through v[41], and only while v[14] says it is active.
- **End of ball** is `0xd3dcc`, which calls **v[4]** on all 27 modes. Tesla's v[4] stops
  it with reason 0: `STOPPED id=23 reason=0` from `0xd3e00` when the rig's ball drained.
- **Tesla scored nothing from the ramps or the building.** Its v[41] received bits 20,
  21 and 22 (also when injected straight into v[15]) and added no score. So its lit
  mask is set by a rule we have not traced; the ramps and building bits alone don't
  light it.

### Switch → shot bit (godzilla Pro 1.15, one 150 ms `swpoke` each)

| Switch | Shot bit(s) after the `0x1` dispatch |
|---|---|
| 73 L Ramp Made Opto | `0x00100000` (bit 20) |
| 81 R Ramp Made Opto | `0x00200000` (bit 21) |
| 77 Building Hit Opto | `0x00400000` (bit 22) |
| 76 Godzilla Target | `0x00080000` |
| 48 Maser Target | `0x08000000` |
| 78 / 79 / 80 Pwrline Left / Center / Right | `0x10000000` / `0x20000000` / `0x40000000` |
| 85 / 86 Shield Target Left / Right | `0x80000000` / `0x1_00000000` |
| 46 Skill Shot | `0x4_00000000` |
| 74 Big Loop Exit, 82 Big Loop Enter | `0x10_00000000`, in the same mask as `0x1`; scored 500,000 then 1,030,000 through `caward_add_scaled` |
| 47 / 83 / 84 spinners (Left / Top / Right) | three bits each: `0x80`, `0x200`, then `0x400` 770 ms later / `0x800`, `0x2000`, `0x4000` / `0x2_00008000`, `0x20000`, `0x40000` |
| 75 Building Exit, 50 Mecha Exit Top | only `0x1` |
| 53 Right Scoop | nothing within 1.5 s |

The spinner rows are read as one poke's sequence, because all three spinners show the
same shape. That reading is not separately proven.

## Not located yet
- **The text screen.** `0x3ba540(n, a, b, 0x6fa618)` → `0x51eab8`/`0x51eb00`, and
  `show_start`, are the candidates.
- **Which award-screen types carry which video.** Type 122 is tesla's powerline tower;
  `0x3ba540` has 131 call sites across dozens of types, and a Godzilla clip for KAIJU
  RUSH is one of them.

## Text of our own on the screen: emulator-proven (run 4, 2026-09-15)

- **The screen.** The probe's `padmode.text "122 3445 1000000"` called
  `0x3ba540(122, 0, 0, 0x6fa618)`, wrote message 3445 at `+0xa0` and 1,000,000 at
  `+0xa8` (count at `+0xb0`). Its handler started show 231 and looked the message up
  from `0x10d968`, and a `shotwin.py` capture showed "TIME LEFT" over "1,000,000" on
  tesla strike's powerline-tower clip, still up 1.2 s later.
- **Our words.** `padmode.msgset 3159` pointed that id's group (`0x744c60[remap[3159]]`,
  index 3159) at `{"KAIJU RUSH" x5, 0}`. The same screen with 3159 then read
  **"KAIJU RUSH" over "5,000,000"** on the capture, and the msg hook logged the display
  code reading id 3159 as "KAIJU RUSH". `msgrestore` put "TESLA STRIKE AWARD" back.
  Every id the remap sends to that index changes with it, so borrow an id nothing
  else is showing; tesla's own award ids qualify while tesla is not running.

## The light-show runner (located 2026-09-15, not yet driven)

The 242 `blele`/`blela` strings are commands for one runner:

- **`0x1c3454(owner, group, command, 0)`** is a one-instruction branch into the parser
  `0x1c2b6c`, which reads `--lts`/`--sweep`. It has 94 call sites. The owners they pass
  most often are 325 (15), 538 (12), 236 (9), 540 and 484 (8 each) and 539 (7);
  `0x1c34cc` is a five-caller variant that takes a list of commands.
- **The group** comes from `0x4bf294(set, 0, 0, 0)`. That allocates a lamp group
  (`0x3c14d4`) and, for a non-zero set below `[0x5ec028]`, adds every lamp in the
  0-terminated u16 list `0x7257a8[set]` (`0x4be448(group, lamp, 255)`).
- **Tesla's award show** (`0x1cbd2c`) passes set 0, an empty group, and names the lamps
  inside the command. Its commands are "blele --sweep 0 --lts 224 --red 255 --green 140
  --blue 55 --freq 10 --use_alpha 1 --alpha 255" (orange), or the green `--red 0
  --green 255 --blue 0` form, both with owner 538. That handler is a show fiber, and it
  attaches a cleanup callback to its event (`0x255bb8(event, 0x1b6880, 0, 1)`), so the
  game's own light commands live and die with a show.
- **The parser's other tokens** include `--remove`, `--end`, `--once` and
  `--set_cur_element`.

`padmode.blele "<owner> [p<prio>] <command>"` runs one command from the tick, and
`modes/bleletest.sh` judges it with `ledact.py` from `modes/blele_cases.txt`: a
command, a `--remove` guess, and a repeat of both.

**Run 6: at priority 0 the commands ran and lit nothing measurable.** Tesla's orange
sweep and the `--remove` guess each ran twice, in a game with a ball in play. All four
returned 1, each in a fresh lamp group. Their pre-to-post distances were 1093, 629,
1037 and 1574 mean-L1, against 1472 of noise, and none fired a fade shape or touched
a cell the pre window had not.

**The group's second argument is a PRIORITY, and run 6 passed 0.** The disassembly
explains the result:
- `0x4bf294` never reads r1 itself. It calls the allocator `0x3c14d4(0, r1, ...)` with
  r1 still in place.
- The allocator stores r1 as the group's byte `+4` and the current event
  (`[0x7b7e84]`) at `+16`, then links the group into the list at `0x7dd4ec`, ordered by
  that byte.
- Tesla's handler passes the value `0x4f3740()` returns. That function walks the event
  list `0x7b7e80` for the node with flag `0x20` whose `+150` matches the current event's,
  and returns its byte `+152`: the running show's lamp priority.

A group at priority 0 sits under every show the game is running. So the probe now
takes `p<prio>`.

The parser has no priority token of its own. It hands the parsed effect to
`0x1bf2dc(prio, group, arg4)` for a slot, and records the owner per slot in the u16
vector `0x7a82bc`.

**Run 7: priority 255 made no measurable difference either.** The same four commands
ran in fresh groups at priority 255. The current event read `nil` from the tick. All
four returned 1, and they scored 672, 1078, 1092 and 1150 mean-L1 against 1224 of
noise, again with no new fade shape or cell.

Four `shotwin.py` captures of the virtual playfield, which draws each insert in its
live colour, did not settle it:

| When | Inserts lit | What the capture showed |
|---|---|---|
| Before the first sweep | 53 | The field in its normal colours |
| Just after the first sweep | 22 | Most of the field dark |
| 4 s later | 32 | A pale warm wash over the upper inserts |
| Just after the last `--remove` | 23 | Most of the field dark |

The game's own animation moves the lit count that much, and no capture caught the
repeat sweep, so the wash is not attributed to the command.

Still open, cheapest first:
- **A one-shot sweep.** `--sweep 0 --freq 10` may finish inside the 0.8 s before the
  post window opens. Capture the playfield every 100 ms straight after the command.
- **The group's event.** The allocator stores `[0x7b7e84]` at `+16`, and from the tick
  that is `nil`. Tesla's handler runs inside a show fiber with a live event, and
  attaches the cleanup `0x1b6880` to it through `0x255bb8`. Make the call from inside
  an event: post one (`0x2551dc`) whose handler runs the command.
- **The set.** Nothing references the `--lts` string from code or data as a plain
  pointer, so how set 224 becomes lamps has not been read yet.

### The positive control: the game DOES use this parser (run 10, 2026-09-15)

The probe now hooks the parser `0x1c2b6c` itself and logs every call the game makes.
(The runner `0x1c3454` is a single `b` into it, which cannot be relocated into a
trampoline, so the hook goes on the parser.) In one game:

- **29 calls, all of them the game's own.** 24 at game start, then **5 during 60 s of
  play - and those five were TESLA STRIKE's award**, owner 538, `--lts 224`, the green
  variant with `--end 1` and `--end 3`: the very command runs 6, 7 and 9 sent. Attract
  made none at all, which is why nothing showed there.
- **The game's call shape** (`0x1c34cc`, its list-taking form): `r0` owner, `r1` group,
  `r2` the command string, and **`r3` a zeroed 8-byte scratch on the caller's own
  stack** which the parser fills and the caller then appends to a vector. So the `0` we
  passed as the fourth argument was never the difference.
- Its commands look like `--sweep <id> --lt 149 --level 255 --rgb 0 --use_alpha 1
  --delay_start 40 --loop --delay_loop 89`, and `--lts_light` appears beside `--lts`.

**So the road is right and the measurement was wrong.** Tesla's set 224 is a single
lamp, and `ledact` averages the whole playfield, so it could not have seen tesla's own
award either - which means the "nothing happened" readings of runs 6, 7 and 9 were
never evidence. The next measurement reads the lamp slots directly instead
(`dump_group_slots` in the probe): a group's slot array is `group[0] + id*40`, byte
`+36` is the written flag, and the probe now dumps it after our command AND after each
of the game's own, side by side.

### Run 11: what a light command actually writes, and WHEN

Our command and the game's own were run in one game and read at the lamp slots
(`dump_group_slots`), not at the LEDs.

- **The game's tesla award writes lamps 413-420**: `+2 0`, `+3 255`, `+8 20`, flag
  `+36 1` - eight lamps, the powerline tower. So a command does reach the slots, and
  the instrument can see it.
- **The ids are 413-420 against a 585-lamp slot array**, while the lamp table
  `0x71b06c` holds 260 entries. So slots are indexed by a light index of 585, NOT by
  that table, and set 224's "lamp 177" is an id in a different space.
- **The write does not happen at parse time.** The game's first two calls dumped
  "none written" as well; the lamps appeared only on a dump 1.5 s later. A sweep lands
  on later frames.
- **So our own "none written" proved nothing**: our dump was taken a millisecond after
  our call. The probe now has `padmode.slots`, which re-dumps the group our last
  command used, and `scratchpad/run12_slots.sh` reads it at 0.2, 1, 2, 4, 8 and 12 s.

Geometry, confirmed against the game's own resolver `0x3be84c`: bounds-check the id
against `[0x7b10b4]` (585), base `[0x7dc4c4]` for the global bank or the bank passed in
for a group's own, stride 40 (`id + id<<2`, then `<<3`).

### RUN 12: OUR LIGHT COMMAND LIGHTS THE LAMPS

Tesla's own green command, sent through `padmode.blele` with `ev` (a live show event
made current, priority 145 from that show), then the same group re-read over 12 s:

| When | What our group held |
|---|---|
| at the call | nothing written yet |
| **+0.2 s** | **lamps 413-420 written**, `+3 255`, flag `+36 1`, `+2` = 0/255/0/0/255/0/0/255 |
| +1 s | the same eight, `+2` moved again - the sweep animating |
| +2 s on | lamp 515 at `+8 31` |

Those are **the same eight lamps the game's own tesla award writes** (seen in the same
run, group `0x7dd730`, `+3 255` `+8 20`). Ours differs only in `+8` (fade), because the
game's sweep carries `--fade 20` in its second line.

**What 413-420 ARE is not proven.** They are above the 260-entry lamp table
`0x71b06c`, so they are ids in the 585-entry slot index, and nothing read so far names
them. Tesla strike is the powerline mode, so its own award lighting them makes the
powerline tower the obvious guess - but it is a guess, and a playfield capture did not
settle it either.

**So the command works, and every earlier "nothing happened" was the instrument.** A
light command writes nothing at parse time - it writes on later frames - and
`ledact`'s playfield average could never have seen eight lamps anyway. The recipe:

1. Make a live show event current (`[0x7b7e84]`, from the list at `0x7b7e80`, a node
   with flag `0x20` at `+2` and a show id at `+0x96`), and take its lamp priority from
   `0x4f3740()`.
2. `group = 0x4bf294(0, prio, 0, 0)`.
3. `0x1c3454(owner, group, command, 0)` - owner 538 for tesla's own commands.
4. Restore the previous current event.
5. Read back `group[0] + id*40` to prove it: byte `+36` is the written flag.

A group comes from a pool of 48 (`0x3c1700`), so a mode must not take a fresh one per
start: `0x3c15cc(group)` frees one, under the lamp mutex.

### RUN 14: KAIJU RUSH LIGHTS ITS OWN SHOW - emulator-proven

The mode fires tesla's own green sweep at its start and the fade at its end, through
`hook.h`'s `gz_blele`. In a played game, with the mode's shots taken on the RAMPS ONLY
so tesla strike could not start and light the same lamps behind it:

```
90348 [blele] owner 538 group 0x007dd6b8 arg3 0x00000000 lr 0x4085ac44 "blele --sweep 0 --lts 224 --red 0 --green 255 ..."
90349 [rush] lights on: group 0x7dd6b8
90350 [rush] KAIJU RUSH START (trigger): player 1, 30 s, score 0
90832 [rush] lights on landed: 6 lamps written, first 413
...
120415 [rush] lights off: group 0x7dd6b8
120415 [rush] KAIJU RUSH END (time ran out): 10 shots, awarded 55000000, 30067 ms wall
120915 [rush] lights off landed: 4 lamps written, first 353
```

`lr 0x4085ac44` is our `.so`, so the command is ours. **Six lamps from 413 were written
0.48 s after the call**, and the game's own tesla award did not run until 92981 - after
that window - so nothing else wrote them. After the fade, 413-420 are no longer held
(what remains is another show's, from 353). Which inserts those are is not established
(see run 12 above): what is proven is that our command writes the same lamps the game's
own award writes.

**A count read at call time is always 0.** Run 13 logged exactly that and proved
nothing; the count has to come from a later tick, which is what `lights_check` does.

**The written flag is never cleared, so the COUNT drifts.** Over a soak the same mode
reports "7 lamps written, first 412", then "first 353": a group keeps whatever earlier
commands left in it, and `gz_group_written` counts slots the group currently holds, not
what the last command wrote. Run 14's reading is still clean - that group had just been
allocated, and the game's own award ran after the window - but the evidence is WHICH
lamps appear, not how many. A test that needs the count to be exact must start from a
fresh group.

### The soak on the build that ships (lights included)

`modes/soak.sh 10` again, on the build with the lights in it: **14 cycles, 14 starts
and 14 ends, 0 new `[segv]`, 0 fatal signals, guest still up**, one game climbing to
258,580,000. The mode fired its lights on every cycle (16 "lights on", 15 landings).

**What those landings do NOT show.** The lowest written lamp read 300 ten times, 353
three times, and 413 or 412 once each - because one group is reused and the written
flag is never cleared, so "first" is only the lowest id the group currently holds. Run
14 is the clean proof (a freshly allocated group, no game command in the window, first
413); the soak proves the mode runs its lights every cycle without faults, not which
lamps it wrote each time.

### The regression bar, and what the PROBE costs

| 60 s in a game | renderer fps | video NEW/s | guest fps | faults |
|---|---|---|---|---|
| stock, no .so at all | 60.0 (30) | 30.0 | 58.6 (180) | 0 |
| probe + mode, no lights (run 5) | 60.0 (30) | 30.0 | 58.7 (180) | 0 |
| probe + mode WITH lights, after the soak | 58.3 (28) | 29.1 | 59.4 (170) | 0 |
| **mode only, no probe (run 15)** | **59.9 (30)** | **29.9** | **58.2 (180)** | **0** |

The third row is about 3% short on the renderer, **and it is not a reading of the
mode**: that probe hooks 17 sites including the light parser and writes slot dumps
(3,780 log lines in the run), and the measurement followed a 10-minute soak. The probe
is a debugging tool, not part of a mode.

**The mode itself costs nothing measurable**: 59.9 against 60.0 renderer fps, 29.9
against 30.0 video, 0 faults, with `PAD_MODE_SO` alone and no `PAD_TRACE_SO`
(`scratchpad/run15_modeonly.sh`).

**And that run replicated the lights with no probe loaded at all** - nothing of ours in
the process but `mode.so`:

```
86901 [rush] lights on: group 0x7dd6b8
86902 [rush] KAIJU RUSH START (trigger): player 1, 30 s, score 0
87383 [rush] lights on landed: 6 lamps written, first 413
116885 [rush] KAIJU RUSH END (time ran out): 29984 ms wall
```

### The lamp and light-set tables (read 2026-09-15)

- **Light sets: `0x7257a8[set]`**, each a 0-terminated u16 list of lamp ids, with the
  count in `[0x5ec028]` = 12,359. 1,582 sets carry at least one lamp. **Tesla's set 224
  is a SINGLE lamp (177)**, which matters for measurement: one insert cannot be seen in
  a playfield-wide average, so every "nothing happened" reading before this was also
  consistent with the command working. The biggest sets are 548 (120 lamps), 207 (104),
  208 (101), 210 (100), 211 (99), 209 (96) and 3 (92).
- **Lamps: `0x71b06c[id]`**, 8 bytes each, `[0x5ec000]` = 260 entries. Byte `+4` is a
  kind: 162 are kind 2, 90 kind 1, 5 kind 4 and 2 kind 5. `0x4be448(group, lamp, 255)`
  switches on it, and a kind-3 entry is a composite whose pointer holds sub-lamp ids,
  each handed to `0x3bef7c` - which takes the mutex at `0x7e36cc` and writes the id and
  a byte into a slot from `0x3be898`. Set 548's lamps are ordinary kind-1 and kind-2
  entries, not composites.

## Measuring lights: `modes/ledact.py`, validated (run 4)

What does NOT see a show: counting LED activity (a game baseline read 52.8 level
changes/s; with tesla forced on, 8.2/s, because a show replaces the ambient animation)
and the set of cells that move (every insert on nodes 8 and 9 animates in a game).

What does: per-cell **mean level** and **change rate** between windows, plus the **fade
shapes** fired (node, start, end, target level from the fade ring). Two back-to-back
8 s baselines were 915 mean-L1 / 11.7 rate-L1 apart with no unique fade shape. With
tesla forced on the window was 4806-4995 / 84-89 from them, with 13 fade shapes
neither fired (`9:16-22>0` at 1.25/s). A window after stopping tesla was still ~4800
from the old baselines, because the lamp state drifts with the game. So
`modes/lightprobe.sh` takes a fresh pre-window before every show it tests.

**Ruled out (run 4): hand-starting tesla strike's shows as a mode's lights.**
`lightprobe.sh` tried each show that tesla's condition entries start, each against a
fresh pre-window, in a game with a ball in play:

| Show | Result |
|---|---|
| 95 | 2360 mean-L1, no new fade shape |
| 96 | 10 new fade shapes on node 9 (2570) on its first window. **It did not repeat:** 716 with 4 shapes, then 2766 with 0, against that round's noise of 2095 |
| 344 | 3 shapes on the first window, 0 on the repeat |
| 346 / 351 / 356 | nothing new (351 was already gone when killed) |
| 231, the award screen's show, as a control | moved more than any of them (4086) |

The `9:76-78` shapes turned up after 96 and 344 alike, so they are the game's own
animation. With a ball in play the ambient lamp animation drowns these shows, or
they are not lamp shows, or they need the fields tesla's award sets. The next
candidate is `0x185e9c(n, a, b)`: the game called it with 2000/3 at game start, 334
in tesla's award and 200/3 on its spinner (`padmode.fx`, `lightprobe.sh fx:n:a:b`).
Also untested: the `blele` runner.

**`0x185e9c`: inconclusive (run 5).** `lightprobe.sh` fired each call twice:

| Call | Result |
|---|---|
| first `(2000, 3, 0)` | **A strong footprint:** 5191 mean-L1, 15 fade shapes and 84 cells the pre window never had, including full-range fades to 255 across node 8 (`8:14-48>255`, `8:14-59>255`, `8:23-35>255`) - a playfield flash |
| the repeat of `(2000, 3, 0)` | 467 mean-L1, only `9:47-74>` shapes |
| `(334, 0, 0)` and `(200, 3, 0)` | 809-1909 mean-L1, only `9:47-74>` shapes |

The `9:47-74>` shapes, at random target levels, turned up in every window after the
first, and that round's two-window noise was 4111 against ~900 before. That reads as
the ball draining into attract, whose lamp sweep is those shapes. Every call returned
1. **It is very likely not a light at all.** `0x185e9c` clamps n against a table indexed
by adjustment 335 and calls `0x39fe24(7, ...)` only when n beats `0x39fd78(7)`.
`0x39fe24` is the DEVICE driver entry: its 17 callers include `ControlCoil::v[58]`
(`0x4fc7c`), and it tail-calls `0x39f7fc`. So `0x185e9c` drives device 7 - a coil,
flasher or motor, whose strength an adjustment limits - and the first window's LED
flash was most likely the game's, not the call's. The check is the coil-fire counters
in the same `padled` block (`coil[16][16]` at 1556, `coil_gen` at 2068) around one call:
`modes/coilact.sh`.

## Messages: ids go through a RUNTIME remap (corrected 2026-09-15)

`msg_lookup(id)` `0x34a764`: if `id < [0x5ec0c8]` (3949), then
`idx = (*(u16 **)0x7b9654)[id]`, `group = 0x744c60[idx]` (a `{en,de,fr,es,it,0}` block
of `char *`), and `message_picker(group)` `0x485918` returns the current language.
**The remap is filled at run time**, so an id cannot be read statically as a row of
`0x748a10`. An earlier line here "ruled out" v[27] being a message id on exactly
that mistake. Read live through the remap (the probe's `padmode.msgdump` writes all
3949):

- v[27]'s **3242 = "TESLA STRIKE"**, and 3159 / 3160 = "TESLA STRIKE AWARD" / "TESLA
  STRIKE COMPLETED". So v[27] IS the title message.
- 3150 "SHOOT FLASHING POWERLINE TARGET TO START TESLA STRIKE", 3152 "%d MORE
  TARGET%P1//S/% TO START TESLA STRIKE", 3156 "SHOOT SPINNER TO BUILD TESLA STRIKE
  VALUE!", 3157 "SHOOT BLUE ARROWS TO COLLECT TESLA STRIKE AWARD!", 3161 "TESLA STRIKE
  IS RUNNING", 3445 "TIME LEFT".
- The small numbers a display event carries (50, 77, 90, 232, 275, 565, 582) are NOT
  message ids: 232 reads "DR. PINBALL" and 565 "PRESS 'BACK' TO EXIT".

**Who shows a mode's title.** With tesla forced on, the probe's msg hook caught id 3242
looked up from `0x445f4`. That is inside a background display layer's refresh
(`0x44598`): `mode = layer->v[21]()`, `title = mode->v[27]()`, `msg_lookup(title)`, then
`0x55c1f4(layer, std::string)` sets the text placeholder in the layer's scene.
`BDLTeslaStrikeBG::v[13]` (`0x10fc20`) fetches 3156, the instruction line, the same way.
Title text therefore belongs to the 27 modes' own scenes. A mode of ours shows text
through a screen that takes a message id (above), and gets its OWN words by pointing
an otherwise unused message group at a `{"KAIJU RUSH" x5, 0}` block. `0x744c60` is
plain `.data` (the ELF has no RELRO). The probe's `padmode.msgset` / `msgrestore` do
that; not yet run.

**Lights are shows, started by condition.** A table walked by `0x431a44` pairs a
`global_mode_mask` filter (`+8`) and a condition function (`+12`) with a show id
(`+16`). When the condition holds and the show is not running (`0x255d7c`), it calls
`show_start(id)`; when it stops holding, `show_kill(id)` (`0x255dd4`). Forcing tesla on
started shows 346, 96, 95 and 356 from that walker (`lr` `0x431aac`). Which show ids
are lamp shows is the next measurement (`modes/ledact.py` against `dump/padled`).

## KAIJU RUSH, a mode of our own: emulator-proven (run 3, 2026-09-15)

`modes/mode.c`, loaded by `PAD_MODE_SO=/lib/mode.so` beside the probe. In a
`plunge.py game` on godzilla_pro, `modes/rush_test.sh` did the following:

- Three Maser Target pokes, each seen at the shot dispatch as `0x08000000`, **started
  it**: "KAIJU RUSH START (maser target x3): player 1, 30 s, score 75000".
- Pwrline L, C, R, then the L and R ramps **scored 1M, 2M, 3M, 4M, 5M** through
  `score_add`. The probe logged each add from `mode.so` (`lr` `0x40859dcc`) next to the
  game's own awards for the same switches, and the score peek climbed to 15,725,000.
- **The tick clock ran it for 30 s and ended it:** "20 s left" ... "1 s left", then
  "END (time ran out): 5 shots, awarded 15000000, score 75000 -> 15725000, 30099 ms
  wall", so the tick holds 60 Hz in the rig.
- **Callouts:** 1291 at 10 s and 1295 at the end went through `callout_play`, from
  `mode.so`. The 5..1 countdown uses `callout_play_nth` → `0x2a32bc`, which that probe
  build did not hook, so those five are not yet shown. The next probe build hooks it.
- Both objects hooked the tick and the shot dispatch at once: `hook.h`'s site check
  follows the sibling's trampoline, and the probe installed 15 hooks, KAIJU RUSH 3.

### Run 5: KAIJU RUSH with its own text (2026-09-15)

`mode.c` borrows messages 3159/3160 for the mode and puts up the award screen (type
122) at start, on each shot, and at the end. In a played game, `shotwin.py` captures
read **"KAIJU RUSH / 1,000,000"** at start and **"KAIJU RUSH TOTAL / 15,000,000"** at
the end, all on tesla's powerline clip. The probe logged `0x3ba540(122)` from `mode.so`
for each shot and the end, and the display code reading 3160 as "KAIJU RUSH TOTAL".

The whole countdown is now seen:
- **10 s:** `callout 1291`.
- **5 s to 1 s:** `request_nth 1287 n=4` down to `n=0`, through `callout_play_nth` (`lr` `0x188060`).
- **End:** `callout 1295`.

It ran 30,100 ms of wall time. The mode log then said "borrowed messages 3159/3160
restored", six seconds after the end.

### The 10-minute soak (run 5, 2026-09-15)

`modes/soak.sh 10` kept one game going for ten minutes. Every 45 s it started KAIJU
RUSH and played the mode's five shots:
- **14 cycles, 14 starts, 14 ends.** Every end read "time ran out": 5 shots,
  15,000,000 awarded, 29,983 ms of wall time.
- The score climbed from 16,475,000 to 233,865,000 within the one game.
- **0 new `[segv]` lines and 0 new fatal signals.** The guest was still up at the end.

### The stock regression bar: unchanged with the .so absent (run 8, 2026-09-15)

`modes/regress.sh stock 60` in a run launched with no `PAD_TRACE_SO` and no
`PAD_MODE_SO`, measured over 60 s of a game in progress, against the same bar taken
with both objects loaded:

| | stock (run 8) | with the objects (run 5) |
|---|---|---|
| renderer fps | 60.0 (30 samples) | 60.0 (30 samples) |
| video NEW/s | 30.0 | 30.0 |
| guest (eglshim) fps | 58.6 (180 samples) | 58.7 (180 samples) |
| new fault lines | 0 | 0 |
| new Radium Errors | 0 | 0 |
| `padmode.log` / `mode.log` | absent / absent | present / present |

**Measure it in a GAME, not in attract.** The first try started the game 3 s into the
guest's life, while it was still booting, so the coin and Start went nowhere and the
60 s ran in attract: 59.7 renderer and 56.1 guest fps, which would have read as a
regression that is not there. `scratchpad/run8_stock.sh` waits for a guest up at
least 60 s, then proves the mode mask left attract before it measures.

Not yet: its lights.
- **Lights.** `0x185e9c(n, a, b)` (it checks `global_mode_mask & 0x310` and calls
  `0x39fe24(7, ...)`) and the `blele` runner.
- **There are no free timers, so a mode.so keeps its own clock.** `ctimer_get` has 66
  call sites. Its constants reach 4, 8-13, 15-20, 22-24 and 26-29, and the mode
  constructors add 0-3, 5-7, 14, 17, 18, 21 and 25: every index from 0 to 29. The
  obvious clock is to count frames from a hook on `tick_body_60hz`.
- **`cgametimer`'s own slots.** The roles above come from how `cmode_timed` calls them.
