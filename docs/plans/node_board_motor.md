# A node board's motor: john_wick_le's car (PAD-237)

## What and why

David, 2026-09-01, on a live john_wick_le run: *"when i start a game, i
continually hear car tire screeches. I believe this is because the CarMec is
supposed to move into position when the game starts, and it is not getting
the feedback that it needs."*

He was right about the shape and the filed item (queue item 88) was wrong
about the mechanism. It assumed a COIL drove the car and planned a
`PAD_COIL_PROBE` run to find which one. There is no car coil. The car is a
motor the **node board runs by itself**, and the game only talks to the board.

## What the wire says (john_wick_le 1.01.0, node 9)

Found with `PAD_NB_TRACE=1` (the coil probe only logs changed payloads and ran
out of its 20000-line budget in attract):

| cmd | frame | what it is |
|---|---|---|
| 51 | `51 00 44 43 0f 00 00 00 d0 51 52 00 00 80 ...` once a second, **no reply asked** | configure motor 0: stop switch `0x40\|4` (CAR MOTOR HOME), `0x40\|3` (CAR MOTOR AWAY); outputs `0x50\|0x80`, `0x51`, `0x52` |
| 53 | `53 00 fa 14 c8 00` | send motor 0 HOME (speed / accel / decel: the CAR MOTOR HOME/AWAY SPEED, ACCEL, DECEL adjustments) |
| 54 | `54 00 fa 14 c8 00` | send motor 0 AWAY |
| 52 | `52 00`, every 50 ms, 4-byte reply | the board's status - byte 2 is its inputs 0..7 |

The outputs 0x50..0x52 are LED-class device records named `CAR MOTOR ENABLE`,
`CAR MOTOR CONTROL 1A`, `CAR MOTOR CONTROL 2A` (group 8, index 80/81/82). They
have x = y = 0, so `devicexy.py` drops them and they are in no cached table -
which is why nothing in the rig had ever named them. `findrec`-style: search
the ELF for a pointer to the name string; the record is `image`, `(group,
index)`, `(class, 2)` from there.

## How byte 2 was pinned down

`carcheck` / `motorcheck.sh`: boot, start a game, count cmd 53/54 on node 9 for
40 s. With the rig answering zeros: **35 x 53 and 31 x 54** - a re-send every
~0.9 s, and every send is the screech.

- `PAD_NB_CFILL=52:<v>` (every reply byte = v), 9 builds: 08 stops the 53s,
  10 stops the 54s, 01 / 03 / ff stop both, 02 / 04 / 80 change nothing.
- `PAD_NB_CREPLY=52:<bytes>` (new, exact bytes), 8 builds: only **byte 2**
  matters.
- Then the reading that explains all of it: node 9's switch bits at rest are
  `1b` - inputs 0, 1, 3, 4 sit at their INACTIVE level 1 (optos and stop
  switches are active-low). So byte 2 is the board's own inputs, raw, and a
  zero reply said HOME and AWAY made at once plus a ball at every car opto.
  `08` = HOME made with a ball at the car's front, so no 53 is needed and
  the car must go AWAY (54, never arrives); `10` the reverse; `01` = no
  ball at the car, so no move is wanted at all.
- Mirroring the node's last 0x11 switch byte into byte 2, 5 builds: nothing
  held -> 0/0; HOME or AWAY held -> 0/0; FRONT OPTO held (a ball at the car)
  -> 0 x 53, 33 x 54 (the game sends the car away and it never arrives);
  mirror off -> 35/31.

## What the rig does now (hwshim.c)

- **cmd 52 reply byte 2 = the node's first switch byte**, as the last 0x11 of
  that node was answered, on any node the game has sent a cmd 51. One state,
  two readers: the switch poll and the motor status cannot disagree.
- **The motor model** (`motor_note`, `motor_tick`): cmd 51 names each end's
  stop input; cmd 53 / 54 send the motor to an end. The stop it leaves opens
  at once; the one it is sent to closes `PAD_MOTOR_MS` later (600, inside the
  game's ~0.9 s re-send). A re-send while travelling is not a new move. The
  car starts between the stops (position unknown) and the game homes it at
  boot. Edges go into the switch MERGE tagged `m`, so the game, `[sw]` and
  every padsw reader see one state; last edge wins, so a held switch still
  overrides the car until its next move.
- `PAD_NB_MOTOR=0` puts back the zero reply and stops the model.
- Result, john_wick_le: 0 re-sends from Start; a ball at the car sends it
  away (54) and home again (53), one arrival each, `[motor] ... arrived`.

Proven: `tests/test_spike2_node_motor.py` (the real functions compiled out of
hwshim.c, fed the real frames), the rig sweeps above, and the whole-library
boot sweep below.

## Not done, and why

- **The car's ball optos** (FRONT / HOLD / BACK). Nothing carries a ball into
  the car, so they stay open: a car with no ball. Modes that lock a ball in
  the car will wait for one that never comes, as they would have before.
- **The drop target** on the same title: `DROP RESET` then `DROP TRIP` (node 9
  coils 8 and 6) fire in bursts of five pairs every ~3.3 s from Start, because
  nothing moves `DROP TARGET OPTO`. Answered in PAD-248 - see "The drop
  target (PAD-248)" below.
- **The motor's own status bits.** Bit 0 of byte 2 is CAR FRONT OPTO; no other
  byte of the 52 reply was seen to matter, and no busy or fault bit was
  looked for. If a title's board motor ever needs one, `PAD_NB_CREPLY` is the
  instrument.

## Other titles

Whole library, `rigbatch.sh` over the 33-build list with bootcheck plus the
`[motor]` config lines (2026-09-27): **33/33 boot to attract**. At least 13
titles configure a board motor (a fast boot can be stopped before cmd 51, so
"none" below is not proof of none - john_wick itself read none at 20 s):

| title | motors (cmd 53 stop / cmd 54 stop) |
|---|---|
| batman 1.13 | node 9: m1 13/8, m2 2/4 |
| deadpool_le 1.14, deadpool_pro 1.16, star_wars_elg 1.10 | node 12: m0 none/none |
| star_wars_le 1.30 | node 12 m0, node 9 m0: none/none |
| elvira3 1.13 | node 9: m0 9/3, m1 -/12, m2 -/0, m3 -/24 |
| iron_maiden_le 1.16 | node 9: m0 24/25, m1 1/0 |
| james_bond_le 1.06 | node 9: m0 1/- (the JETPACK: home opto 1, encoder optos 2 and 3) |
| jaws_le 1.02 | node 9: m0 38/32 |
| jurassic_park_le 1.16 | node 9: m0 4/6 |
| mando_le 1.44 | node 9: m0 0/1 |
| sword_of_rage_le 1.18 | node 9: m0 none/none |
| uncanny_xmen_le 0.98 | node 12: m0 4/6 |

Then `motorcheck.sh`, model on vs `PAD_NB_MOTOR=0`, 40 s from Start, on the
eight with stop switches:

- batman, iron_maiden, jaws, jurassic_park, mando, uncanny_xmen: 0 moves
  either way - nothing looped from Start, nothing changed.
- elvira3: the game sends motors 1-3 to their stops in attract; all three
  arrive in 600 ms and are never sent again.
- **james_bond_le: off = 20586 x cmd 53 in 40 s** (about 500 a second - a
  flood nobody had noticed because nothing plays a sound for it); **on = 136**,
  a pair every ~0.7 s. Improved, not answered: the JETPACK is an ENCODER
  motor (`53 00 28 20 e8 03` - speed 40, accel 32, and 1000 as a LE16 where
  john_wick sends 200) and the game wants pulses on its encoder optos while it
  moves, which this model does not make. Its own ticket, with jaws_le's
  SHARK POSITION 1..7 (the original item's generalisation; jaws showed no
  loop from Start, but its stops are inputs 38 and 32, past the byte 2 this
  reply is known to carry).

Payload of cmd 53 / 54, from the two titles: motor, speed, accel, then a LE16
(200 on john_wick = its DECEL (MS) adjustment; 1000 on the jetpack).

## The drop target (PAD-248)

john_wick_le 1.01.0, `motorcheck.sh` 40 s from Start with the car model on
(its `c40i=` field now splits node 9's coil fires by index: 06 = DROP TRIP,
08 = DROP RESET):

| run | DROP fires |
|---|---|
| nothing held | 139 (06:69, 08:70) |
| a ball held at CAR FRONT OPTO (77) | 138 |
| DROP TARGET OPTO (81) held made | 0 |

The burst on the wire: RESET, TRIP 100 ms later, five pairs 250 ms apart, a
1.8 s pause, again. A game wanting the target UP has no reason to fire TRIP
after every RESET, and the opto held made satisfies it, so the game is
dropping the target and waiting for the opto to read MADE = down.

The first RESET goes out 34 ms after the Start press: it is the game's own
start-of-game drop, not a response to anything else in the rig.

PAD-237's own sweeps disagree with each other: its `model` sweep read 140
fires with nothing held and 0 with a ball at CAR FRONT OPTO (the ticket's
"it stopped when a ball was held"), its `final` sweep the reverse - 0 with
nothing held although a game started (BALL 1 on screen), 140 with the ball.
Here, on the same card and model, three sweeps fired every time with or
without the ball. So the car is not what decides it, and why those runs were
not asked is NOT known; each rig slot keeps its own NVRAM, and a game that
has given up on a device it logged as failing is the candidate, not a
finding. None of that changes the answer: whenever the game drops the
target, the opto now says so.

`MOTOR_SETTLE` (seconds to wait after attract before Start, default 8) was
added on the way: a first sweep of three rigs at once pressed Start while
john_wick_le still showed its STANDARD GAME MODE card, no game started, and
every count read 0. 45 starts a game every time.

**The model** is `ballmodel.DropTarget` (pass 2: `DropBank`), run by the ball feeder (it already
polls the coil counters at 50 Hz and writes switches): TRIP -> the switch goes
to its down level `PAD_DROP_MS` (default 30) later, RESET -> the other level.
A bank is matched by NAME (`ballmodel.DROP_BANKS`: DROP TRIP, DROP RESET,
DROP TARGET OPTO), so only john_wick_le has one today. `PAD_DROP_TARGET=0`
turns it off, `PAD_DROP_DOWN=0` flips the polarity.

| run (model on unless said) | DROP fires |
|---|---|
| 40 s | 2 (one RESET, one TRIP; the feeder closes 81) |
| 40 s, `PAD_DROP_DOWN=0` | 139 |
| 40 s, a ball held at CAR FRONT OPTO | 2 |
| 120 s | 2 |
| 120 s, `PAD_DROP_TARGET=0` | 380 |

## Every title's banks (PAD-248, pass 2)

David: "do the other titles too". The model became `ballmodel.DropBank`: an
optional TRIP coil, a RESET coil and every switch of the bank, TRIP making
them all and RESET opening them all. `DROP_BANKS` lists 18 banks on 12
titles by name (a bank is answered only when the title has its coils AND
every switch, so "3 BANK DROP" on jaws_le and on metallica each match only
their own switches). No title without a bank resolves one (godzilla_pro: 0).

From Start with nothing held, no title but john_wick_le retries a drop coil
(11-title sweep, `coils=` field). So the proof is the other half: hold every
bank switch made (targets down) at Start. With nothing answering, the game
fires RESET until they open; with the model, once.

| title | bank(s) | RESET fires in 40 s, model off -> on |
|---|---|---|
| james_bond_le 1.06 | CENTER 3 BANK (optos) | 60 -> 1 |
| jaws_le 1.02 | 3 BANK | 45 -> 1 |
| star_wars_le 1.30 | FORCE 5 bank | 12 -> 1 |
| king_kong_le 0.97 | 4 BANK | 9 -> 2 |
| james_bond_60th_le 1.11 | INLINE (trip), LEFT 4 BANK 'BOND', CENTER 3 BANK | 5, 5, 5 -> 1, 1, 1 (c40i) |
| beatles 1.29 | LEFT 3, RIGHT 4, CENTER 4 | 3, 3, 3 -> under 3 each |
| deadpool_pro 1.16 | LIL DP 3 BANK (trip) | 3 -> 0 |
| metallica_spike 1.03 | 3 BANK | 3 -> under 3 |
| led_zeppelin_le 1.22 | 3 BANK DROP Z-E-P | 150 -> not measured |
| john_wick_le 1.01 | DROP TARGET OPTO (trip) | 139 -> 2 (pass 1) |

(`coilcount.py` prints coils fired 3 or more times, so "under 3" is a
coil that dropped out of the list; `c40i` counts node 9 exactly.)

**Not proven on the rig, and why:**

- led_zeppelin_le with the model on, and jurassic_park_the_pin either way:
  the runs landed on rig slots whose NVRAM had never finished Stern's Guided
  Setup, and sat on its language menu ignoring Start (`started=no`). The
  slot where both titles had started (rig 1) was taken by another ticket.
- deadpool_le: no rig slot ever got it to take Start, with or without the
  model and the holds (`deadpool_le.bare`) - an existing rig fault with this
  title, not this change. Its LIL DP bank is the same coils as deadpool_pro's
  (proven); which of its two 4-bank reset coils is DEAD and which is POOL
  (LEFT = DEAD, RIGHT = POOL here) is a reading of the names, not a
  measurement.

`motorcheck.sh` now says whether the game started (`started=` - the feeder
serving a ball; Start pressed up to three times) and, when it did not, prints
the feeder's last lines and the switch edges.

**Seen on the way, not this ticket:** beatles and james_bond_60th_le fire
their TROUGH eject 22 times in 40 s from Start (`coils=TROUGH=22`), and
jurassic_park_the_pin an unnamed node 8 index 1 coil as often (the eject
index on most titles); deadpool_le never takes Start on any rig.

# An encoder motor: james_bond_le's JETPACK (PAD-249)

## What was asked, and what turned out to be true

The follow-up above asked for encoder PULSES while the jetpack moves, and for
where inputs above 7 live in the 52 reply. Reading the game answered both,
and neither was the fix:

- **The 52 reply is not the board's inputs. It is a status word for the motor
  the request names** (`52 <motor>`). james_bond_le 1.06 reads it at
  0x5aa23c as two LE16s: bytes 0-1 = the position the board has counted,
  bytes 2-3 = flags. john_wick's BidirectionalMotor reads the same four bytes
  the same way (0x4f2f24, flags 0x08 done / 0x80 fault). PAD-237's "byte 2 =
  raw inputs" answered the car because its stop switches happen to sit on
  those bit positions; it is left in place for end-stop motors because it is
  measured to work there, and nothing past bit 7 needs finding.
- **No encoder pulses.** The board counts the encoder itself. The game never
  reads the encoder optos, and when it configures the motor it sends the node
  a cmd 71 mask with those two inputs cleared (0x33b4e0 -> 0x5aa5f8).

## The jetpack's protocol (EncoderMotor, JetPackMotor derives from it)

| cmd | frame (node 9) | what it is |
|---|---|---|
| 51 | `51 00 41 00 00 43 42 00 c0 42 41 20 00 28 01 ...` | configure motor 0: home opto input 1 (`0x40\|1`), ENCODER inputs 3 and 2 (payload bytes 4-5 with 0x40). A reversed variant (`c1 ... 41 42`) is sent for the second home |
| 53 | `53 00 28 20 e8 03` | home: speed 40, accel 32, LE16 time 1000 ms |
| 55 | `55 00 0a 00 40 e8 03 00` | go to position: LE16 target (signed), speed, LE16 time, flags |
| 52 | `52 00` -> 4 bytes | this motor's status: LE16 position, then flags 0x01 moving, 0x08 homed and done, 0x40 fault |

The tick (0x33b6b8 / JetPackMotor 0x1e05b8) is a small state machine: config
+ home, config + home again, then "calibrated" and position moves (the
play routines at 0x1e0244.. ask for 10, 24, 31..40, 33). Every tick it polls
52, and a reply with **none of 0x01 / 0x08 / 0x40** makes it configure and
home the motor from scratch. The zero reply did that every tick: 20586 x cmd
53 in 40 s from Start.

**hwshim.c now plays an encoder motor** (motor_note / motor_tick /
motor_status): cmd 51 with encoder inputs marks the motor; 53 homes it
(moving, then after PAD_MOTOR_MS homed at position 0 with the home opto
made); 55 sends it to a position (moving, the count climbing pro rata, the
home opto open while away from 0); 52 is answered from that state.

## The rest of the loop was rig-wide: every board re-initialised every 0.7 s

With the status answered the jetpack still homed twice every ~708 ms. Hooks
found why, one step at a time (PAD_PASS_HOOK / PAD_REG_HOOK):

1. `33aac4` (EncoderMotor home) called every 708 ms from JetPackMotor v[17],
   itself called from 0x33aba8 - the listener for **event 135**, "re-home the
   encoder motors on node N".
2. Event 135 is raised by the node service loop when it re-initialises a
   board: `34c170` fired every **101 ms** - one board per visit, the whole bus
   every ~0.7 s - always from the **fault branch** 0x34edb8.
3. That branch is taken when the `ff` status poll's word B & 0x8010211f. The
   rig answers `ff` with zeros; the bit came from the game itself: 0x5ae930
   sets bit 31 of word B when **word A differs from a per-node counter**, and
   `PAD_REG_HOOK=5ae9f0` showed that counter at 2..167 on every poll.
4. The counter is the game's count of ADDRESSED frames sent to the board since
   the last poll (0x5a8068, +1 per frame with byte 0 & 0x80; zeroed after the
   poll and by cmd f1). A real board reports how many it received; the rig
   said 0, so every visit read as "this board lost frames".

**The rig now counts what the game counts** (nb_rx_count_tx, per node, byte 0
& 31, f1 resets it) - and answers it in word A of the `ff` reply **only on a
board that carries an encoder motor** (nb_rx_count_says). `PAD_NB_RXCOUNT=0`
answers 0 everywhere again. It also corrects the item-52 note on the `ff`
reply, which read the stored zero as "the previous value is always 0".

### Why only that board

The first version answered the count on every board, and the whole-library
sweep failed exactly one build: **batman-1.13 read as stuck on Tech Alerts**.
It was not - pictures at 90/150/210/270 s show its attract cycling (high
scores, the Stern ad). What stopped was the constant re-init, and two parts of
the rig turn out to be built on it for batman's (older, swelf) generation:

- **its lamps.** cmd 70 is what this rig decodes as that generation's
  base-layer lamp write, and cmd 70 is sent ONLY inside a board init (32
  entries, one per output). batman's "~109/s through attract" (item 79) was
  the re-init loop re-sending them every visit. Answer the count and the
  playfield's lamps for that generation stop changing.
- **its attract detection.** gamestate.sh's `[led] light show running` counts
  cmd 70 for that generation (item 79), so status.sh, autoattract.sh and
  bootcheck.sh all called batman's attract "techalerts".

A real board is not re-initialised every 0.7 s, so both are measuring an
artifact - but fixing them is their own job (decode that generation's real
show families, 72/8a/96/9a, and detect attract from them). Until then the
count is said where its absence is measured to do harm: a board with an
encoder motor, where every re-init re-homes the motor. Before that motor is
configured the board still says 0, so its bring-up inits happen as before.

`PAD_NB_FLAGWATCH=<node>` is the instrument left behind: that board's flag
word and every reply the rig sends it, logged on change.

## Result

james_bond_le 1.06, motorcheck.sh, 40 s from Start:

| rig | cmd 53 sends |
|---|---|
| zero reply (`PAD_NB_MOTOR=0`) | 20586 / 19958 / 20272 |
| PAD-237 end-stop model | 136 (a pair every ~0.7 s) |
| encoder status only | 136 (re-homed by every board re-init) |
| encoder status + frame count on node 9 | **2** (the one home the game asks for at Start) |

With the count right node 9 is not re-initialised once its motor is
configured. The jetpack homes twice at boot, once at game start (event 78, by
design), and is then sent to position 10 by cmd 55 - the first position move
the game has made on the rig.

Also fixed on the way: batman-1.13 sends cmd 55 to its END-STOP motor (node 9
motor 1); the encoder change briefly let that fall into the end-stop model as
"go to end 1". An end-stop motor ignores 55 again, as under PAD-237.

**PAD-955 plays that 55.** On an end-stop motor its byte 4 names an INPUT
(`0x40|bit`), not a position count: batman 1.14 in attract sends
`55 01 48 ..` (crane to input 8, its POS. #6 AWAY stop) and `55 02 43 ..`
(turntable to input 3, TURNTABLE POS. #2, between its stops 2 and 4).
Ignored, neither arrived, and the VPX tribute table, whose turntable follows
the position switches, never turned (a player's report). The model now runs
the motor there like a 53/54: where it was opens at once, the named input
closes `PAD_MOTOR_MS` later, and a 55 naming a stop is that end. Rig, batman
1.14 from Start: `+78m +82m`, both arrived, no re-sends.

## Not done

- **jaws_le's shark is not a board motor.** SharkMotor derives from
  SingleDirectionCoilMotor: a coil runs it and the game reads SHARK POSITION
  1..7 and the UP/DOWN-MAG switches as it turns. That is a coil-driven mech
  with position switches - its own model, its own ticket.
- A motor that faults (0x40) is never simulated; the jetpack never stalls.
- ~~**The bus-wide re-init.**~~ Stopped by PAD-255, below.

## PAD-255: the count on every board

The frame count is now answered on every board (`PAD_NB_RXCOUNT=enc` keeps
PAD-249's encoder-only rule, `=0` answers 0 everywhere), so no board is
re-initialised at each service visit.

**The premise above was half wrong.** batman's lamps never leaned on the
re-init. With the count answered everywhere, batman-1.13 at 150 s sends no
cmd 70 and none of the rest of the init set (14 / 51 / 60), and its lamp plane
moves exactly as much as with the re-init running (20 s at 10 Hz):

| rig | cmd 70 per 10 s | cells changing | per node (8 / 9 / 10 / 12 / 13) |
|---|---|---|---|
| encoder-only (`enc`) | ~1100 | 128 | 50 / 37 / 6 / 10 / 25 |
| every board | 0 | 128 | 50 / 37 / 6 / 10 / 25 |

The show is the swelf family (8a / 96 / 9a / 86 ...: 0x80..0xbf) that the wide
decoders already read (led_wide_publish, led_node_wide_publish). No new
decode was needed; cmd 70 had only been "the base layer" because the re-init
kept re-sending it. The same goes for the Home Editions: their `cmd 70`
"refresh every ~100 ms" (PAD-129) was this re-init of their one board.

**What did lean on it was the attract signal.** The light-show announcer
counted cmd 70 for this generation; the wide family was never in its set. So
the wide decoders now feed it (led_show_note) once a frame is PUBLISHED,
weighted by the lamps it wrote. By lamps and not frames because a Home
Edition's show is few and wide: jurassic_park_the_pin sends one cmd 86 every
~135 ms, Tech Alerts and attract alike (22 frames in 3 s, never the 30 the rate
half asks for). The rate half only ever said "a board is being talked to";
the moving half (200 changed lamp writes in 3 s, PAD-129) decides, and is
unchanged. Attract declared, count on everywhere (hidden rigs, 150 s runs):

| title | declared | screen at 150 s |
|---|---|---|
| batman-1.13 | 118 s / 139 s | attract |
| jurassic_park_the_pin-1.05 | 69 s (frames only: never) | attract ("PLAYER 1 00") |
| star_wars_elg-1.10 | 107 s | attract (the crawl) |

Tech Alerts length varies run to run on these titles (star_wars_elg's `enc`
run in the same batch never left it inside 158 s), so the times are not a
comparison between rigs.

Side finding, not fixed here: under rigbatch, autoattract.sh logs "the game is
not running; nothing to do" and exits at once, so a hidden sweep reaches
attract only where a title's own Tech Alerts time out.

**Whole library (bootcheck.sh, rigbatch, 2026-09-28): 33 of 33 builds boot to
attract.** First pass 29 of 33; the four were rerun:

- led_zeppelin_pro-1.22 and metallica_spike-1.03 were harness casualties (a
  run killed by hand; a staged card that could not be moved into place). Both
  pass rerun, metallica booted unstaged.
- turtles_le-1.59 sat on Tech Alerts past 420 s once; rerun it passes both
  ways (130 s every board, 133 s `enc`).
- elvira3-1.13 is load-sensitive: its own dispatch watchdog fires at 134-139 s,
  just as attract begins, on a title that runs at 4 fps. Branch 3 pass / 3
  fail (the fails with 3-4 rigs busy, `enc` included), main 5 of 5; PAD-249's
  own passes landed at 134-135 s, the same edge. A 150 s run of each with the
  shim log shows the same attract (124.3 s branch, 124.5 s main) and neither
  dies. Watch it on the next sweep.

Motors unchanged (motorcheck.sh, 40 s from Start, every board and `enc`):
james_bond_le c53 = 2 (the jetpack homes as the game asks), john_wick_le
c53 = 1, drop target TRIP/RESET c40 = 2 (06:1, 08:1).

# A coil run until a switch: jaws_le's SHARK (PAD-256)

## What was asked, and what turned out to be true

The follow-up above said the shark "reads SHARK POSITION 1..7 and the
UP/DOWN-MAG switches as it turns". Half right. There are two mechs:

- **The shark** (SharkMotor -> SingleDirectionCoilMotor, jaws_le 1.02): a
  plain coil output, SHARK MOTOR UP/DOWN (node 9, coil index 0), turns a cam
  one way round. Its only switches are SHARK UP-MAG SW (input 12) and SHARK
  DOWN-MAG SW (input 13).
- **The fin** (FinMotor, "9g: Serial Motor Driver Board"): SHARK POSITION
  1..7 (inputs 38..32) are its positions. It is a board-run motor - cmd 51
  configures motor 0 with stops on inputs 38 and 32, the PAD-237 end-stop
  model already answers its 53 / 54 - and 90 s from Start the game sent it no
  move at all. Not touched here.

## The shark's protocol (node 9)

| frame | what it is |
|---|---|
| `41 00 5a e8 03 00 .. [26]=00 .. [30]=4c ..` (52 bytes) | coil 0's RULE: power 0x5a, byte 30 = the input that STOPS the coil (0x40\|12, UP) |
| `40 00` (the short, 6-byte cmd 40) | run coil 0 now, under its rule |
| `41 00 00 ..` | rule cleared |

Byte 26 is the input that FIRES a coil: the same title's RIGHT POP BUMPER
rule (`41 03 ff 03 .. [14]=18 .. [26]=5d`) carries input 29, the pop
bumper's own switch. So a rule with a stop input and no firing input is a
motor run until a switch closes.

The game's move task (0x5134c) builds the rule with a 10 s limit (0x2c0ef4),
waits for the coil service (0x2c1784) to end the run, then reads the target
switch (0x571cdc): made = arrived, otherwise it counts an error and tries
again. On the rig nothing moved either switch, so from Start:

| run (jaws_le 1.02) | shark runs (short cmd 40, coil 0) |
|---|---|
| baseline, 120 s from attract | 11 - UP twice, then DOWN every 12.5 s: 10 s of motor, 2.5 s rest |
| `PAD_COIL_MOTOR=0`, 90 s from Start | 8 |
| model on, 90 s from Start | **1** (plus the one UP before Start) |

## What the rig does now (hwshim.c, coil_motor_note / coil_motor_tick)

A cmd 41 with byte 30's 0x40 flag set and byte 26's clear marks the coil as a
motor; the short cmd 40 runs it: the input it last stopped on opens at once
(the cam leaves it) and the rule's stop input closes `PAD_MOTOR_MS` (600)
later, into the merge tagged `m` like the car. A rule cleared before that is
the coil off: nothing arrives. The board re-init's re-send of the same rule
(PAD-249: every ~0.7 s, until PAD-255 stopped it) and a second run while travelling are not new moves.
`PAD_COIL_MOTOR=0` turns it off. motorcheck.sh counts the short runs per coil
(`c40r=`).

On the rig: `[motor] 55136 ms node 9 coil 0 on, input 12 in 600 ms` ...
`reached its stop switch`, then at 77541 ms the same for input 13 with UP
opening first (`[sw] 77634 ms -79m`, `78439 ms +80m`). No retry followed.

Proven: `tests/test_spike2_coil_motor.py` (the real functions compiled out of
hwshim.c, fed jaws_le's frames), the on/off runs above, and the library sweep
below.

## Every title (library sweep, 2026-09-28)

(Measured before PAD-255 answered the frame count on every board, so the
re-init was still running; the model does not depend on it either way.)

`rigbatch.sh` over the 33-build list with motorcheck.sh (40 s from Start),
model on: **33/33 pass**. john_wick_le failed twice on the way (the run ended
10 s in; then it stalled before the guest started), both before the game ran;
its rerun passed with the model on and off alike. Five titles send a coil a
stop-switch rule and run it; `runs=` (motorcheck's new count of the short
cmd 40 on every node, boot and attract included) on vs `PAD_COIL_MOTOR=0`:

| title | coil (node:index) -> stop inputs | runs on / off |
|---|---|---|
| jaws_le 1.02 | 9:0 -> 12 (UP-MAG), 13 (DOWN-MAG) | 1 / 8 after Start (see above) |
| jurassic_park_le 1.16 | 9:1 -> 22 | 2 / 5 |
| led_zeppelin_le 1.22 | 9:6 -> 11, then 10 | 1 / 1 |
| metallica_spike 1.03 | 11:3 -> 5, then 4 | 2 / 2 |
| rush_le 1.18 | 12:0 -> 4 | 1 / 1 |

So jaws_le and jurassic_park_le were retrying a mech nobody answered; the
other three move it and do not retry in 40 s either way, and now arrive.
Which mechs those are was not read out of their games (rush_le's cached
table names input 4 EXTRA BALL (FRONT LEFT) SWITCH and lists no coil on node
12, so it is likely stale - PAD-93).

## Not done

- **The game still takes 10 s to see the shark arrive.** It clears each rule
  exactly 10 s after the run, with or without the model; only then does the
  move task read the switch. The coil service ends a run on its deadline and
  nothing found so far ends it sooner - the move task's one early exit waits
  on a per-position task id (SingleDirectionCoilMotor +32) that was not read
  out. Whether a real board reports "rule done" in some reply, and where, is
  open. Cost: anything that waits for the shark hears about it 10 s late.
- The fin's SHARK POSITION 1..7 between its end stops (above).

# A motor on two LED-class outputs: beatles' spinning record (PAD-965)

The record (SpinningDiscMotor) has no coil and no stop switches. Its device
records are two LEDs on node 8, MOTOR A0 DRIVER (output 4) and MOTOR A1
DRIVER (output 5), and the game never writes them in a lamp frame. It sends

    88 05 50 04 05 ff <ck> 00     run: the pair, then the speed
    88 05 50 04 05 00 <ck> 00     stop

Measured on beatles 1.29 (PAD_NB_TRACE=1, rig 3, 2026-11-03): one run at boot
(the record's test spin, 14.5 s to 17.7 s), then one 15 ms ahead of EVERY
burst of MAGNET-RECORD, stopped 5.2 s later - six catches, six spins. Only 00
and ff were ever sent, so which way round the speed turns it is not known.

Nothing read cmd 50, so both outputs sat at 0 in the LED plane and the Visual
Pinball table's record (lamp calls 1804/1805 -> PadRecordMotor) never turned:
every ball the magnet caught dropped off it down the middle (PAD-950 read that
as "the game never runs the motor"). hwshim.c's led_motor_publish() now puts
the speed on output A and holds B at 0 until the next cmd 50, and the lamp
frames cannot overwrite a driven output (led_motor_out). The patched table
also spins the record up in 0.6 s (SpinUp 100) where core.vbs's default takes
6 s, longer than the game runs it. Proven: tests/test_spike2_led_motor.py, and
a rig game through the bridge with lamp 1804 on 10-20 ms before each of six
MAGNET-RECORD bursts and off 5.2 s later.
