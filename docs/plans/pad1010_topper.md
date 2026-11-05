# PAD-1010 — Topper modes

Some Stern Spike 2 titles lock a software feature behind the **topper**
accessory being fitted. The request: modify the raw game image so a cabinet
without the topper gets those features. The headline example is **Venom** —
buying the topper adds **Ghost Rider** as an eighth playable host on the
CHOOSE A HOST screen.

## The mechanism (and why it is per-game)

Every title carries a `device_usable(index)` accessor (Venom LE 0x444800) that
answers whether a given device's node board is present on the bus. The topper
is one such device (the one whose device-table record names it `…TOPPER…`;
Venom device 9 → node 12 "TOPPER"). The game asks this predicate before
offering a topper feature.

`plugins/stern/topper.py` finds that predicate generically — the accessor by
its shape, the device table it reaches through `get_board`, and every site that
calls it about the main topper board — and patches each site to report the
topper **present**:

- a thin **tail-call wrapper** (`…; b device_usable`, Venom's Ghost Rider
  check) → `mov r0,#1 ; bx lr`;
- an **inline call** (`…; bl device_usable ; cmp r0,#0 ; …`, everyone else) →
  the `bl` alone becomes `mov r0,#1`, so the function flows on (writing `bx lr`
  here would return from the middle of the feature's own code — the two forms
  are never patched alike).

Size-neutral, every site checked against its expected words. Only the gameplay
predicate changes: the node-board health layer still reads the real bus, so an
absent (optional) topper drives nothing and raises no node-board error.

**But flipping "topper present" only frees a feature where that predicate IS
the feature's gate.** It is used two ways across the library:

- **Venom**: the predicate's result ORs the Ghost Rider bit into the per-player
  host-availability mask. Flip it → the host is offered. *This is the clean,
  unlockable case.* It is also the only title whose gate is a pure tail-call
  wrapper; everywhere else the predicate is embedded in a larger function.
- **Jaws**: the inline `device_usable(topper)` call sits inside a small "is a
  valid topper present" predicate (device present AND a valid topper part). The
  mode-of-play menu consults that predicate to decide whether to show THE SHARK
  IS BROKEN. Flipping only the `device_usable` half is not enough (the part
  check still fails), but forcing the WHOLE predicate to report present unlocks
  it. Proven on the rig. *(So these are two different patches, chosen per game.)*
- **Avengers / Jurassic Park / King Kong / Rush / Foo Fighters**: here the
  `device_usable(topper)` call is in a void action that only drives the topper's
  own effect; the modes themselves start from playfield collection with or
  without the topper, so nothing is locked for this patch to free.

So the box is **offered per game**, from `topper.FEATURES`, which lists only the
games confirmed on the emulator to unlock, with the feature each adds. A title
joins it once checked, never before.

## Compatibility (what the topper adds, and whether this frees it)

### Confirmed — box offered, proven on the rig
| Game | Topper adds | Patch strategy |
|---|---|---|
| Venom LE / Pro | **Ghost Rider** — an 8th playable host on CHOOSE A HOST | `wrapper` — the `device_usable(topper)` tail-call wrapper the host-select reads |
| Jaws LE / Pro | **"The Shark Is Broken"** — a challenge (EXCLUSIVE TOPPER MODE) in CHOOSE YOUR MODE OF PLAY; alternate rules on the normal playfield | `validity_fn` — force the "is a valid topper present" predicate to report present |

Jaws, proven end to end (topper absent): the stock card drops THE SHARK IS
BROKEN from the menu; the built card shows it in red, and selecting it starts
and plays the challenge (menu → start → ball in play).

### Not freed by this patch (yet)
| Game | Topper adds | Why not |
|---|---|---|
| John Wick LE / Pro | "Tick Tock Mr. Wick" challenge (EXCLUSIVE TOPPER MODE in CHOOSE YOUR MODE OF PLAY) | gate found in data, but not in code — the reader can't be pinned with the tools this emulator has. Deferred, not offered. See below. |

**John Wick — how far it got, and the wall.** The mode-of-play menu filters each
challenge by whether its accessory board is present. Tick Tock's board is
**520-5781** (name-hash `0x1f002e80` in the `.flash` board manifest at
`0x66a3dc`). The live present/absent state sits in a 0xe0-byte accessory-node
record at **`0x71f5d4`** (`.bss`): word0 `3`/`1`, a `+0x90` present flag `1`/`0`,
and the part string/hash populated only when present — all proven by a
present-vs-absent memory diff. **Poking that record present on a topper-absent
run makes Tick Tock appear in the menu and play** (rig-proven) — so that record
*is* the gate's data.

What could not be found is the **code that reads it**. Every static route is
exhausted: no Ghidra xref, no `movw/movt` or add/orr immediate that builds any
address in the table (capstone value-tracking over all of `.text`), no literal
pool, no relocation, and — scanning the whole live process — no stored pointer
to the table anywhere (only one coincidental byte match inside a library). It is
reached purely through runtime pointer chains. The two dynamic tools that would
pin it are both absent here: **qemu-user has no data watchpoints** (the gdbstub
rejects `Z3`/`Z4`) and this **qemu build has no TCG plugins** (`-plugin`
unknown). A guest-side fault-probe (`rig/jwprobe.c`: `LD_PRELOAD` via
`PAD_TRACE_SO`, `mprotect` the node page to `PROT_NONE`, log the faulting PC)
was built and confirmed guest `mprotect` *does* fault under qemu — but with the
page unreadable for ~15 s of menu activity the game never faulted on it, i.e.
the menu does **not** read `0x71f5d4` at display time. So the gating read is
indirected further (a cached roster, or a copy the census builds), and pinning
it needs more work: fix the probe's SIGSEGV handler (the self-test read crashed
instead of logging — the ARM `ucontext`/`sigaction` path is off) and widen the
watched range to catch what the menu *does* read, or use real hardware / a
watchpoint- or plugin-capable qemu. Scratch for all of this is under
`C:\tmp\PAD-1010\rig` (`jwprobe.c`, `ptrhunt.py`, `dumpstate.py`) and
`gh/` (the Ghidra decompiles: menu builder `FUN_00334b94`, census
`FUN_00237c88`, accessors `FUN_0023639c`/`FUN_003f2ca8`).

### Topper adds a mode that is NOT locked by the topper (patch does nothing)
Avengers Infinity (Gem Mania), Jurassic Park (Goat Mania), King Kong (Golden
Gary Treasure Hunt), Rush (Topper Frenzy), Foo Fighters (Toy Time), Metallica
(And Justice For All MB topper variant). On each of these the `device_usable(
topper)` call sits in a **void action that fires the topper's own effect when
the topper is present** (Jurassic Park 0x1a532c, Avengers 0x1261f4, Foo
Fighters 0x8015c: `… device_usable ; popeq (return) ; read a game-state bit ;
post an effect`) — **not** in the code that decides whether the mode can start.
Those modes are reached by collecting items in play (gems / letters / clues /
band members via playfield shots) regardless of the topper; the topper only
adds its display. So nothing is locked for this patch to free — flipping the
gate would merely drive the topper's effect to an absent board. These games are
deliberately **not** in `FEATURES`.

### Topper is lights / a motorised toy / a second display — nothing gated
Mandalorian (Razor Crest hologram), Star Wars LE/Pro (C-3PO head), Star Wars
Home (R2-D2), Sword of Rage (Black Knight head), Munsters (Raven clock), Led
Zeppelin, Deadpool, X-Men, TMNT (Technodome), Iron Maiden (lamp effects), James
Bond / 60th, Godzilla, D&D, Elvira, Aerosmith, Batman, Beatles, Guardians,
Stranger Things, Jurassic Park The Pin.

## Proof

- **Venom LE, emulator, topper absent** (`PAD_TOPPER=0` silences node 12/14):
  cycling CHOOSE A HOST on the stock card shows only the four base hosts (Eddie
  Brock, Flash Thompson, Gwen Stacy, Peter Parker); on the card built with the
  Topper box ticked the cycle also offers **Ghost Rider**. Same card, same
  no-topper setup; only the patched game program differs, and it booted and
  started a ball normally.
- **Safety**: patched King Kong (big mech motor), Deadpool (topper motor) and
  Godzilla boot to attract and start a game under no-topper with no node-board
  error and no motor stall — the flip never touches the motor/mechanism
  predicates (those are separate devices, deliberately skipped).

## App integration

A **Topper** box on the Defaults tab (beside Coin door / Final wizard), offered
only on `FEATURES` games, naming the feature. Staged as `topper: unlocked`,
baked by `explorer.write_adjustment_defaults` → `_with_topper(elf, title)`
(which re-checks the title, so a mod pack cannot carry the choice onto another
game), carried by mod packs and transfers, with help and de/es/fr.

Scratch/RE: `C:\tmp\PAD-1010` (game ELFs, Ghidra project `gh/`, rig jobs).
