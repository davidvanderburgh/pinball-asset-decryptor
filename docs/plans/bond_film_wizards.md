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
- The block's shot starts out at the port's `wizard_shot` (Bond: Right ramp exit opto, the ramp made).

Proven on the desk harness (`tests/test_stern_block_modes.py`, run through PAD-Runtime's gcc): lit by an event, the
shot and the insert blinking, held again after a drain, dark for player 2 and back for player 1, the shot starting it
(and paying nothing itself, as any start shot), dark while it ran and not lit again after; with a battle running the
shot left it lit ("still ready") and the next one after the battle started it; a new game put it out. The ARM build
(build_mode.sh) of a Bond mode using it with a light show and a HUD is clean. Not run on the rig or a machine.

Not done: two modes of one's own lit at the same shot, one of them lighting that shot again while it runs, leave the
other's shot lights dark from that one's end to the next ball (its insert stays lit and the shot still starts it).

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
