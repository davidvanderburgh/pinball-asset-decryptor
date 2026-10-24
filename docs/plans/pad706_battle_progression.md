# PAD-706: a blocks mode in a Godzilla battle, and the battle's progression kept

David, 2026-10-24 (after PAD-699): "What are the limits on replacing these modes? Can we make all new modes in place?
Like adding stages to them?" ... "We also want our changed modes to still accumulate progression."

## What changed

- **Blocks: "When the player picks <battle> on the battle selection screen"** (hat `{"kind": "battle", "slot": n,
  "name": ...}`), offered where the build is proven (`ROSTER_PROVEN`, the profile's `roster`). The mode claims the
  slot as it loads; a pick runs the script once the screen has closed (`roster_start_after_ms`); a pick while it
  runs restarts nothing; a pick while another of our modes runs waits; a pick that starts nothing or lapses is given
  back. A mode running on a pick ends with its ball. **End the mode** gets ", the battle won".
- **The pick counts as the battle it replaced** (runtime, `pm_roster_over(won)`; `pm_roster_done()` = a loss): at the
  pick the runtime does what the battle's START writes (stopped/reason bytes cleared, the city holds the battle, its
  starts, its clock, its STARTED audit, its points zeroed) without starting it; at the mode's end it calls the game's
  `CBattle::stop` with the outcome. Won: Completed on the selection screen, wins, the COMPLETED audit, the city won and
  its award, the city progression (tier 2, the city travel screen). Lost: a lost battle, still qualified.
- **Played again until it is won** (item 3): the game restarts a lost tier-1 battle from its city pick at the next lit
  scoop (`0x198f24` / Pro 1.16 `0x195284`), not through the selection screen; `site roster_resume` hooks that START so
  a slot a mode holds is the mode's again.
- **Win rule**: blocks - a won End block wins; with none, the mode's own end (clock / End block) wins. Mode files -
  `end_shot` wins; with none, the clock wins. A drain, a tilt or the game moving on loses.
- Ports: Premium/LE 1.16 and Pro 1.16 lines (`site battle_stop / battle_started / battle_clock / roster_resume /
  roster_cursor`, `value battle_*`, `roster_city_battle_vec_at`); Pro 1.15 (archival, not booted) keeps the old
  behaviour. portgen REVISION 7 (the battles' offsets are title values).
- The Modes tab: the hat, its tips, End's choice, the form editor's battle note; de/es/fr words.

## The game's bookkeeping (read at the desk, Premium/LE 1.16; Ghidra + objdump, C:\tmp\PAD-706)

| | address | what |
|---|---|---|
| CBattle::start | 0x7fa78 | clears stopped +0x13+p, reason +0x17+p; the city's battle (+0x38 vector) unless flags & 0x10; then the cmode start 0x11dbe8 (running, starts +0x3c+4p, manager "started" 0xd47fc = STARTED audit, clock base +0x54) |
| CBattle::stop | 0x7f998 | wins +0x64+4p; cmode stop 0x7f1b0 (stopped, reason, END v[10], manager "stopped" 0xd4854 = COMPLETED audit when won); the battle rule's bookkeeping (city won byte +0x50, city award 0x124fe8, events 0x4f-0x51; lost: qualified = adjustment 174); ramps 0x1248cc; city bit 0x1387ac |
| a slot's "Completed" | Pro 1.15 0x1201d8 | the battle's stop reason, non-zero |
| the city pick | 0x198f24 | sets the player's city; a held tier-1 battle (12-15) not won there is STARTed again (`ldr r3,[r0]; ldr r3,[r3,#32]; bx r3` at 0x199038) |
| v[11] | each battle | Ebirah/Titanosaurus/Gigan/Megalon: KOTM test, CBattle::stop, the victory show; King Ghidorah/Battra: CBattle::stop(1); Megalon & Gigan multiball: its own stop (always a win) |

## Proof (emulator, muted, hidden; C:\tmp\PAD-706\rig, out_run*)

- run2 (control, stock Premium/LE): the game's own Gigan drained (STOP reason 0, the city bit, still qualified), the
  next scoop restarted it (`SP START 14 lr 0x199310`), won: reason 1, wins 1, COMPLETED audit 0 -> 1, city won.
- run4/5 (stock Premium/LE, a blocks Gigan): STARTED audit at the pick, a drain = the game's LOST battle, the next
  scoop restarted the MODE (no stock START), won: the same bytes as run2; GODZILLA CONTROLS TOKYO 5,000,000, powerup
  level 2, TRAVEL TO PARIS.
- run6 (David's Heisei 1.99D v20): the blocks Gigan won; a mode file with no end shot won by its clock; RAID TIER 2
  UNLOCKED.
- run7 (stock Pro 1.16): pick, drain, city-pick restart (0x195398), win.
- glass pair (stock Premium/LE, main's runtime vs this one): the same mode-file win - main: city untouched,
  +1,000,000; now: GODZILLA CONTROLS TOKYO, +6,000,000.

## Not done here

- Pro 1.15: no lines (its card is archival). Tier-2 slots (4-6) read at the desk, not run.
- King of the Monsters starts the four tier-1 battles itself (not through a pick): inside it the stock battle plays.
- The battle's champion is not fed the mode's points (its points this time stay 0 so its ending clip stays off).
