# PAD-786: an option so a final wizard does not end the game

## The ask

Joe_Blasi on Pinside (post #383, then #385): "the wizard modes that END THE GAME, way to turn that off". Asked which
ones, he pointed at pinballrulesheets.com/other/games-with-lock-point-stealing.html, section "Features That Can End
Game". Its Spike 2 entries:

| title | what ends the game |
|---|---|
| Godzilla (Premium/LE) | King of the Monsters, Monster Island Mayhem (the card's own name: MONSTER ISLAND MADNESS) |
| James Bond 007 (Premium/LE) | Her Majesty's Secret Service, MI6 Multiball |
| Jaws | Super Celebration Multiball |
| John Wick (Premium/LE) | Special Assignment |
| Jurassic Park (Premium/LE) | Escape Nublar, When Dinosaurs Ruled the Earth |
| Elvira's House of Horrors | Wild Market Value |

The first answer on this ticket (challenge games are one ball) was the wrong reading: these end a NORMAL game, for
every player, before their balls are played. None of these cards has an operator adjustment for it (all six
newest builds' adjustment names checked: only ball save / timer settings, and Godzilla / JP's service-menu test
settings QUALIFY/LIGHT/START <wizard>).

## The framework, read off Godzilla LE 1.16 (addresses are that build's)

- Bus dispatch `0x3fcdf8(id, arg)`: walks the handler list `*(0x7d671c + 4*id)`, nodes `{fn, u8 prio @+4, next @+8}`;
  a handler returning 0 stops the walk and the dispatch returns 0. Registration `0x3fcd4c(r0, id, fn, prio)`.
- End of ball `0x2a7cc8`: dispatch 0x35 (end-of-ball handlers), 0x34 (ball_end), bonus..., then the advance
  `0x338950`; it returns 0 = game over (`0x2a7bb8`: dispatch 0x47 game_over, status `0x7d116a |= 0x18`), else the
  next ball (`0x2a76f0`).
- Advance `0x338950`: a byte flag = 1, dispatch 0x90(&flag) (a handler can clear it), the extra-ball test
  (`challenge_extra_ball` site `0x2b2cd8`), then next player (`0x713b94` player, `0x713b95` ball, `0x7d116c` player
  count) or next ball against the balls-per-game getter `0x338820` (AD_BALLS_PER_GAME, id 80); flag 0 or ball past
  the last = game over; dispatch 0x91 at the end.
- Other ends: "end this ball now" `0x38af58(a, b)` (`challenge_end_ball` site: status `|= 0x202`), the LEFT+START force
  end `0x2a80b0` (AD_ALLOW_FORCE_ENDGAME id 91; status = 0x18), called only from the two LEFT+START handlers.
- Live, on the rig (stock + defaults patched, a game on, ball 1): the handler lists read from guest memory matched the
  static ones exactly - 0x35: 0x55ba0 0x1aa884 0x3c2084; 0x34: 0xd623c/128 0x3c2024; 0x47: 0x7cd04 0x1d9968 0x3c2144;
  0x8e: 0x5513c 0x5244f4; **0x90 and 0x91 empty** in normal play. So a wizard that ends the game either registers on
  0x90 while it runs (read the list again WITH the wizard running), or ends it another way (set the ball past the last,
  call the game-over path). That is the next thing to find.
- Rules are C++ objects: `RuleKingOfTheMonsters` vtable 0x645c28 (methods around 0x159d74-0x15a578 and 0x2a1xx stubs).

## Rig recipe (scratch: C:\tmp\PAD-786)

- `dump.py`: each title's game ELF out of its card into `elf/` (AdjustmentTable via explorer.adjustment_table()).
- A patched ELF (`AdjustmentTable.patched_bytes({...})`, e.g. START_KING_OF_THE_MONSTERS 1, FREE_PLAY 1) booted through
  `kotm_job.sh`: the card mounted with cardmount.sh, an overlayfs (lower = the card's title dir, upper = our `game`)
  as `PAD_GAME_DIR` (PAD_CARD unset after job_begin), the slot's `data/nv/<title>` wiped; run through rigbatch as root
  (`list_gz.txt`). Free play showed, so the patched defaults are read.
- `gmem.py <slot> handlers <ev..>` / `poll`: guest memory via /proc/<pid>/mem, base from /proc/<pid>/maps (the game
  file's offset-0 mapping minus 0x8000).
- Open problems of the rig run: START KING OF THE MONSTERS = On did not start KOTM at the game's start; the ball was
  never served/launched by `plunge.py plunge` (score 00, BALL 1 to the end, drains drained nothing), and status.sh
  read "attract" all game long. Next: `plunge.py serve` (or the trough coil) after the start, and look for KOTM
  after a plunge, a scoop, or with QUALIFY/LIGHT on as well.

## Plan

1. Godzilla LE: get KOTM (or Monster Island Madness) running on the rig, read the 0x90/0x91 lists and poll the
   ball/player bytes and status while it ends; find the call that ends the game.
2. The same on the other titles (Bond LE/Pro 1.06, Jaws LE/Pro 1.02, John Wick LE/Pro 1.02, JP LE/Pro 1.16,
   Elvira 1.13), by the same framework shapes (`adv.py` finds each build's advance function).
3. A card option (Defaults tab, beside Coin door), offered only on builds where the site is found: "A final wizard
   does not end the game" - the game plays on to the remaining balls. Patch generically by shape, as coin_door.py.
4. Prove on the emulator per build: the wizard ends, ball 2 follows; stock still ends the game.

## Run 3 (2026-10-28): the mechanism found and proven on Godzilla LE 1.16

- A rig instrument mode (scratch `C:	mp\PAD-786\calltest_mode.c`, built with build_mode.sh, loaded as PAD_MODE_SO
  with the title's port) calls a game function from a tick (`/dump/call.go`) and logs bytes and bus handler chains
  as they change. `call_job.sh` (rigbatch) boots the stock card, or a patched game program by overlay (`ELFDIR`).
- The final wizard is started directly: Godzilla LE's King of the Monsters is mode 20, object 0x7b5a68, START
  0xc5fac (game_mode_blocks.read_modes; its START also forfeits every extra ball). 30 rounds of target hits
  (48,76,78,79,80,85,86) finish it; the next drain then ends ball 1 and **balls 2 and 3 end within one tick each,
  GAME OVER** (stock, reproduced three times).
- Why: an event 0x26 handler (runs as each ball starts; Godzilla LE 0x56228) reads a per-player word of a rule
  singleton (0x7b0cfc + 0x34 + 4*player) and, when it is set, starts a process (id 0x175) whose body is a one-word
  stub `b <end of ball>` (0x55660 -> 0x2a7cc8): the ball ends as it starts. Its 0x25 sibling (0x5612c) reads the
  same word and refuses the ball's start. The game-over vote (0x90) is not used.
- Patch proven: both reads `ldr rN, [r0, #0x34]` (0x56158, 0x56250) -> `mov rN, #0`: after King of the Monsters
  ball 2 played 50 s and ball 3 45 s (score kept, normal playfield), then the ordinary GAME OVER. Patching the 0x25
  handler alone changed nothing.
- The same stub shape (finder.py: the ball advance -> its end-of-ball -> a one-word `b` stub -> the one handler that
  starts it) is on 21 newest builds. Joe's six titles, with the condition each checks:
  Godzilla LE/Pro and Jurassic Park LE/Pro: the per-player word (+0x34) of a rule singleton;
  Bond LE/Pro 1.06: FG_WIZARD_MODE_MULTIBALL_PLAYED (0x86); Elvira 1.13: FG_WILD_MARKET_VALUE_PLAYED (0x45);
  John Wick LE/Pro 1.02: FG_SPECIAL_ASSIGNMENT_MODE_PLAYED (0x7e) with a game-state test; Jaws LE/Pro 1.02: not read yet.
  Also found, conditions not yet identified (may not be wizards): Avengers LE/Pro 1.10, Bond 60th 1.11 (its
  whole-game challenge?), Led Zeppelin LE/Pro 1.22 (team play flag in it), Metallica 1.04 (game-mode index 6), Rush
  LE/Pro 1.19, Sword of Rage LE/Pro 1.19.

## Left

1. Classify every guard (Jaws and the extra titles); find each title's 0x25-style ball-start refusal on the same
   condition.
2. `pinball_decryptor/plugins/stern/final_wizard.py` (shape-found, like coin_door.py) + a Defaults-tab option where a
   build's guard is a proven final wizard; mod packs / transfers carry it; help + de/es/fr.
3. Emulator proof per title family (the wizard START called by calltest, played out, balls after it play), stock
   control still ends the game; unit tests on the finder against the real ELFs where present.

## Run 4 (2026-10-28): shipped on the branch

- The refusal (bus 0x25) matters: with only the ender patched, Godzilla LE's balls after King of the Monsters
  started without their ball start (ball 3 drained at its first drain, no save). Both are patched.
- The same ender also ends CHALLENGE games: Godzilla's King of the Monsters challenge game (game-play mode 4, set
  in attract) ended through it as shipped and played on to 3 balls with the word patch. Avengers' ender is
  challenge-only (game flag 0x12), Jaws switches on the game-play mode (Standard = case 1 reads the wizard's
  state; the challenges 8-12 have their own cases), John Wick's tests its challenge-mode states before the
  Special Assignment flag. The patch keeps every challenge ending but the WORD titles' own wizard challenge (no room
  for a test without a code cave; the box's note says so).
- `plugins/stern/final_wizard.py` (shapes WORD / FLAG / STATE, found generically) offers the patch on exactly the
  11 newest builds of Godzilla, Jurassic Park, James Bond 007, Elvira, John Wick and Jaws; nothing elsewhere.
- Emulator, stock vs patched, the wizard's mark set in ball 1 (rig: C:\tmp\PAD-786 call_job.sh + calltest_mode.c,
  batch14): Bond LE 1.06, Elvira 1.13, John Wick LE 1.02, Jaws LE 1.02, Jurassic Park LE 1.16 - stock: balls 2 and 3
  started and ended within milliseconds, GAME OVER; patched: each played ~40 s, then the ordinary GAME OVER.
- Defaults tab "Final wizard" box (staged `final_wizard: plays_on`), Build step beside the coin door, mod packs and
  transfers, help + de/es/fr. Tests: tests/test_pad786_final_wizard.py (synthetic shapes, the tab, every newest
  build where the library is).
