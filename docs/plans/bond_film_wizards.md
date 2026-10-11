# Bond's mini-wizards by FILM (PAD-428)

The request (a Bond owner): James Bond 007 has six films and four mini-wizards. Today a
mini-wizard lights when one KIND of thing is done across all six films (every henchman, every
villain...). Qualify the mini-wizards by a completed FILM instead, or as well: all four
things of one film. Then add mini-wizards of our own for the two films that have none.

Title: James Bond 007 LE 1.06 (`james_bond_le-1.06.port`). Pro 1.06 is a different build
with no port on main yet (PAD-420 adds ports for the latest builds); the same lines can
follow once it has one. The 60th Anniversary edition (its own rules: Bond multiball awards
"movies") was not looked at.

## How the game keeps films (read from the game program)

- **Progress**: `0x820198`, `[film 0-5][player 1-4][5 bytes]`: a count for each of the four
  parts (0 henchman, 1 villain, 2 Q Branch, 3 gadget - the gadget code calls with part 3),
  then the total. `0xff` in a byte means the part cannot be collected.
- **Collect**: `0x1d0918(film, part)` bumps the part and the total, re-counts how many films
  have each part, and lights a mini-wizard (`0x110cac`) when a part's film count reaches 6.
  When the film it was called for has just become complete (`0x1d0878(film)`: all four parts
  in), it calls **`0x1d49c0(film)`**. Nothing else calls `0x1d49c0`.
- **Film order** is the gadget table's (`0x62f168`: Geiger counter, attache case, DB5,
  powerpack, Little Nellie, ring): 0 Dr. No, 1 From Russia With Love, 2 Goldfinger,
  3 Thunderball, 4 You Only Live Twice, 5 Diamonds Are Forever. The emulator run below filled
  the From Russia With Love column of the game's own progress grid for film 1.
- **Mini-wizards**: table `0x625da0`, 4 entries of 0x20 bytes: `{index, bit, id, start,
  ready?, can-start?, ...}`. 0 Dr. No multiball (start `0x92bd8`), 1 Ahoy Mr Bond (From
  Russia With Love, `0x20530`), 2 Goldfinger wizard mode (`0xbd4dc`), 3 Disco Volante multiball
  (Thunderball, `0x7e0b0`). (PAD-436: the `id` word is each one's insert on the Right ramp, lamps
  34 DR. NO, 35 ROSA KLEBB, 36 GOLDFINGER, 43 LARGO: Ahoy is From Russia With Love's, not You Only
  Live Twice's as first written here. You Only Live Twice and Diamonds Are Forever have none.) Each has READY / ACTIVE / PLAYED game flags (the flag names table
  at `0x7a51a0`, indexed by flag id: Dr. No 78-83, Ahoy 84-89, Goldfinger 90-94, Disco
  Volante 95-101).
- **Per player** at `0x81c3f4`: `[p-1]` the selected mini-wizard index, `+0x10 + 4(p-1)` the
  lit mask, `+0x20 + 4(p-1)` the played mask. `0x110cac` lights one: it picks the next index
  not played, sets lit = ~played & 0xf and byte `0x8268bc` = 1. `0x110c10` says one is lit
  (and none blocks it), `0x110d98` starts the selected one (called from the shot handler at
  `0x1aefb0`), marking it played.

## Done in this ticket: a mode can start on a film's completion

- **Runtime**: a site event can ask for one argument value, `event <name> site <site> arg <n>`
  (r0 = n). Every event on one site shares the site's one hook.
- **Port**: `site film_complete 0x001d49c0` and six events, `film_dr_no` .. `film_daf`, args 0-5.
- **App**: the Modes tab's Starts on / Ends on lists offer "Dr. No done" ..
  "Diamonds Are Forever done" on this title; a blocks mode's event hat gets them too.
  So the two missing mini-wizards are modes of ours, started on `film_frwl` and `film_daf`.
- **Proof** (emulator, rig 3, 2026-10-07; a test instrument called the game's own collect):
  three parts of From Russia With Love started nothing; the fourth marked the film complete
  and `starts_on event film_frwl` started 16 ms later while a `film_goldfinger` mode did not;
  Goldfinger's four parts started only that mode; four more parts of the complete film
  started nothing. Run twice, before and after main's runtime was merged in.

## Done in PAD-436: the GAME's own mini-wizard from a film

Built as planned below, with these differences: `pm_game_wizard(n, PM_WIZARD_LIGHT | PM_WIZARD_START)`
(start = the game's own `0x110d98`, which checks `0x110c10` itself, so no `wizard_ready` site), the
port's `site wizard_start`, `data wizard_state / wizard_table / lamps_dirty`, `text wizard_name_<n>`;
a mode file's `game_wizard light|start <name>` makes the mode a hand-over (nothing of its own runs);
the Modes tab's "The game's mini-wizard" and a block. The game's own lighting is left as it is (the
user, PAD-436: "leaving the existing mini wizard mode logic"). A mode of ours that blocks the game's
modes vetoes Ahoy's start; the runtime now keeps that wizard lit instead of letting the game mark it
played. MODE_SDK.md "The game's own mini-wizards" has the proof.

## PAD-457: the one handed over is the one that starts

The Bond owner's first game with it: all four films handed their mini-wizard over, From Russia With Love was
finished, Ahoy Mr. Bond did not start, the Right ramp's inserts cycled and the ramp started Duel on the Disco
Volante. The game's own lighting lights every one not played and its selection shots cycle among the lit ones; and
a film's last part is collected inside the henchman / villain / Q Branch mode that awards it, which the game's start
check counts as in the way. The runtime now keeps the handed-over one the only one lit and selected until it starts,
gives back what the game lit itself afterwards, retries a refused `start` that ball, and starts several in order.
MODE_SDK.md "The one handed over is the one that starts" has the detail.

Then (the same owner): every film handed out its own, Duel on the Disco Volante was played, and the Right ramp
lit the next one with no film done - the game's own lighting runs again at every more henchman, villain or gadget
once that part is in all six films, and the runtime gave back what the game had lit. "Instead of the current logic",
left open above, is now the rule for any mini-wizard a mode hands out: the modes claim theirs as they load and the
game's lighting (`site wizard_light`, vetoed) leaves a claimed one unlit; it still lights the unclaimed ones.

## PAD-503: a mini-wizard of one's own, lit at the Right ramp

The same owner made blocks modes of their own for the two films with none (DIAMOND DEATH THREAT on Diamonds Are
Forever, one on You Only Live Twice): clips, sounds, scoring, started on `film_daf` / `film_yolt`. They started the
moment the film was done; the owner wanted them as the game's four are, lit at the Right ramp with the film's villain insert
lit, and started by the ramp. The game's own table has four entries and no room for more, so the lighting is the
mode's own: a blocks statement, Light the mode at (`light_mode`: a shot, one more insert of the port's, a colour and
a pattern), and a condition, the mode is lit (`block_modes.py` "LIT AT A SHOT").

- Per player, kept ball after ball (the game's own stay lit until played); a new game drops it.
- While it is lit and the mode is not running, the shot's inserts and the insert picked are held in its colour
  (`pm_lamp_shot` / `pm_lamp_set`), held again each ball and for each player up, given back while a light show of
  the mode's own paints.
- That shot made starts the mode exactly as Start the mode does (`start("its lit shot", 1)`): with the game's
  modes set to give way or held off, or waits out a multiball, it does not start while one of the game's own modes
  or a multiball runs (Ahoy, say, started off the same ramp) and stays lit for the next one. Starting, however it
  starts, puts the light out.
- The inserts are every `lamp` line of the port (`TitleProfile.inserts`, on the builds in `LAMPS_PROVEN`): on Bond LE
  the Right ramp's six are DR. NO-RIGHT RAMP, ROSA KLEBB, GOLDFINGER-RIGHT RAMP, LARGO, BLOFELD and MR. HENDERSON.
  Which is which film's villain is the game's own pairing: its per-film lamp groups at `0x7cc220` (halfwords, 8 a
  group, in film order) are the films (31 30 29 28 27 37), the Bond girls (61 62 78 79 80 81), the henchmen (59 66 60
  67 68 69) and the villains (34 35 36 43 44 45), and its villain names run DrNo, RosaKlebb, Goldfinger, Largo,
  Blofeld, Henderson in the same order as its henchmen (ProfDent ... Osato, KiddWint). So You Only Live Twice's is
  BLOFELD and Diamonds Are Forever's is MR. HENDERSON.
- The block's shot starts out at the port's `wizard_shot` (Bond: Right ramp exit opto, the ramp made).

Proven on the desk harness (`tests/test_stern_block_modes.py`, run through PAD-Runtime's gcc): lit by an event, the
shot and the insert blinking, held again after a drain, dark for player 2 and back for player 1, the shot starting it
(and paying nothing itself, as any start shot), dark while it ran and not lit again after; with a battle running the
shot left it lit ("still ready") and the next one after the battle started it; a new game put it out. The ARM build
(build_mode.sh) of a Bond mode using it with a light show and a HUD is clean.

Proven in the emulator (2026-10-10, PAD-Runtime rig 1, the stock James Bond LE 1.06 card, hidden, muted; C:/tmp/PAD-503
proof.sh): DIAMOND DEATH THREAT as blocks (film_daf -> Light the mode at Right ramp exit opto + MR. HENDERSON, magenta,
holding the game's modes off) with PAD-457's instruments. The Right ramp (switches 46, 48) before the film started
nothing; PAD-428's instrument put Diamonds Are Forever's four parts through the game's own collect (`f5=1111/4*`) and
16 ms later `lit at Right ramp exit opto for player 1`, the runtime holding the arrow and MR. HENDERSON. The shim's LED
view (node 8 = I/O group 7 + 1) had MR. HENDERSON 0 -> 255 and the RIGHT RAMP ARROW [0,0,0] -> [255,0,255]. With game
flag 139 set (one of the game's modes in the way) the ramp gave `not started (its lit shot) ... still ready` and the
lights stayed; with it cleared the next ramp gave `START (its lit shot): player 1`, both inserts handed back (LED view
0 / [0,0,0] again). No abort. A drain with the mode lit was proven on the desk harness only.

Not done: two modes of one's own lit at the same shot, one of them lighting that shot again while it runs, leave the
other's shot lights dark from that one's end to the next ball (its insert stays lit and the shot still starts it).

### Round 2 (v1.169.0 in the owner's games): the light went out with the game's mode that lit it

The owner, in the emulator: Diamonds Are Forever lit MR. HENDERSON while the mode that won its last part still ran, and
once that mode was over the Right ramp was dark; then Mr Osato (You Only Live Twice's henchman) completed the film as it
started, BLOFELD lit green, and when Mr Osato was over BLOFELD was off and the ramp started nothing. Two causes, both
reproduced on the rig (PAD-Runtime rig 1, stock card, hidden, muted; C:/tmp/PAD-503 proof.sh / proof2.sh, the
instrument rig/inwatch.c; the shipped blocks C against the fixed one, same steps):

- **The game ends play at the end of its big modes, and the blocks read the next ball as a new game.** Every one of
  Bond's multiballs and wizard modes ends with `0x3f79bc` (Dr. No, Disco Volante, Aston Martin, Little Nellie,
  Powerpack, Helicopter, James Bond and Wizard mode multiballs, Ahoy Mr. Bond, Goldfinger's wizard): mode-mask bits
  0x202, the same shutdown as its tilt, cleared only by its end of ball. `pm_in_game()` is 0 until the ball drains and
  rises for the next ball, and the blocks C took any rise for a new game: the light, its "each game" values and its
  timers were wiped. Rig, the game's own `0x3f79bc(0, 1)` with player 1 scored: shipped, the lights went at the end of
  play, the mode said "still lit at the drain", and the next ball's rise wiped it (LED view dark, the ramp started
  nothing); fixed, the lights came back with the next ball (arrow magenta, MR. HENDERSON 255) and the ramp gave
  `START (its lit shot)`. A new game is now the SDK's witness (`new_game`: player 1's score back to 0, or
  `pm_in_game()` rising while it is 0), as mode_file.c and the kit's `kit_new_game` have it.
- **The ramp started the owner's mode in the middle of the game's own mode.** The game starts a mini-wizard only when
  its check `0x110b90` says nothing of its own is in the way (its henchman, villain and Q Branch modes among them), and
  the port's flags show none of those, so a Right ramp during Mr Osato started the lit mode (rig: runs 6 and 10,
  shipped) - starting puts the light out, and the owner's mode ran under Mr Osato's screens. The ports now name the
  check (`site wizard_way`, LE 0x110b90, Pro 0x10fbc4) and `pm_game_wizard_way()` answers it; the lit shot waits on it
  whatever the mode's choice about the game's modes, and a start that waits for the game's modes waits on it too.
  Rig, fixed: the game's Mr Osato (`0x123f84`) started (way check in the way), its film done lit the mode, a Right
  ramp then gave `not started (its lit shot): one of the game's own modes is in its way - still lit`, Mr Osato ran out
  its own clock (way check clear, play kept going with slingshots) and the arrow and BLOFELD stayed lit through it.

The Right ramp's own handler (`0x1aee8c`) runs the game's modules before its mini-wizard start (`0x110d98`, last), and
the Right ramp is where the game starts its henchman and villain modes: on the rig the first Right ramp of a fresh game
started one (the check's `0x1360d4` 1 for some 88 s), and so did every later one there - the instrument collects a
film's parts without playing their modes, so the rig's ramp never runs out of them. So a mode of the game's that the
ramp starts goes first and the lit mode waits, lit, for the next ramp shot: the game's own precedence for its own
mini-wizards. In a real game the film's own henchman and villain are played by the time it is done.

### Round 3 (v1.169.3 in the owner's games): the ramp started a villain instead

The owner, both modes: the film completed, the ramp lit, the film's last mode played out - and the Right ramp "just
started a villain". Round 2's precedence in practice: the game handles a switch before the modes hear of it (the
runtime's switch hooks only count a hit; the tick hands it on), and the Right ramp starts the selected film's next
henchman or villain, so the lit mode found one running at every ramp. Now the lit mode CLAIMS its shot every tick while
it would start there (`pm_lit_claim`: the player up's, not running, nothing of the game's in the way); the runtime's
switch-edge hook, which runs as the drain hands the switch to the game, sees a hit on a claimed switch and holds off the
game's mode starts (the PAD-363 veto, every one the port's `block_start` lines hook) while the game handles it; the lit
mode starts on the tick. A refused henchman or villain is simply not started and the next ramp starts it; a refused
mini-wizard of the game's stays lit (`wizard_refused`).

Proven in the emulator (stock card, PAD-Runtime rig 1, hidden, muted; C:/tmp/PAD-503 run16, run17): You Only Live
Twice's four parts lit the mode; the Right ramp gave `lit: the game's mode 24 (Fiona Volpe) did not start - switch 48 is
YOLT WIZARD's lit shot` and `START (its lit shot)` 16 ms later, the game's check still clear. The owner's whole game:
the game's Mr Osato running when the film completed (lit); a ramp mid-Osato `not started ... still lit`; Mr Osato ran
out; the next ramp held off Under Water Fight and started the mode; it ran its 30 s out; the next ramp started the
game's own mode as ever. No abort.

The plan as it was written (PAD-428):

What the user asked first: the game's mini-wizard (its own mode, music and screens) lit
when its film is complete. The mechanism is mapped above; what a mode would do:

1. A runtime call, e.g. `pm_game_wizard_light(index)`, on the tick thread: for the player up,
   set the selected index, OR the index's bit into the lit mask (keeping the game's
   `~played & 0xf` rule, or not, by choice), and set `0x8268bc` = 1 as `0x110cac` does. The
   port names the addresses (`data wizard_state 0x81c3f4`, `data wizard_dirty 0x8268bc`,
   `site wizard_lit 0x110c10`) so a build without them simply cannot.
2. A mode-file key and a Modes tab choice ("lights the game's Goldfinger mini-wizard"), and a
   block, so a mode started on `film_goldfinger` hands the player the game's own mode.
3. Proof: light it from a film, then make the game's start shot (find the switch that reaches
   `0x1aefb0`) and see its ACTIVE flag (79 / 85 / 96 for Dr. No, Ahoy, Disco Volante) and its
   STARTED audit. Also what the game does when a lit one is already PLAYED this game.

"Instead of the current logic" (stopping the game's own part-count lighting) would mean holding
off `0x110cac`'s calls from `0x1d0b40` / `0x1d0b7c`: a separate choice for David.
