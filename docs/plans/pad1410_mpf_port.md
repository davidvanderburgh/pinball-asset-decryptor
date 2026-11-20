# MPF to PAD: a porting guide, proven with a whole X-Men game (PAD-1410)

Row 19 of the Uncanny X-Men 2.0 gap analysis (`pad1398_xmen20_gap_analysis.md`): a maker who already wrote a game in
the Mission Pinball Framework (YAML config + Python) needs to know how its parts map onto PAD's mode SDK, now that the
targets exist (the whole game PAD-1400, layers PAD-1401, saved progress PAD-1402, button shots PAD-1403, menus
PAD-1404, meters and fades PAD-1405, the game's devices PAD-1406).

## What shipped

- `tools/spike2_emu/modes/sdk/MPF_PORTING.md`, beside `MODE_SDK.md` (so every install has it): what stays Stern's
  (no hardware config in a port), the shape of a port (one code mode folder; the game-long mode is the base with
  `pm_own_game`, every other MPF mode a layer by priority; a layer begins in its own tick), then part by part: modes,
  events, shots and lights, logic blocks / timers / variables / persisted variables, balls, the screen and sound,
  Python; what does not port; the worked example; building and trying it.
- The worked example, `pad1410_mpf_port/`: `mpf/` is the MPF game (machine config + four mode configs), `xstory/`
  is its port (`xstory.c`, `assets.json`), made by following the guide.
- The new-mode wizard's C step: "From the Mission Pinball Framework" opens the guide (`modes.open_mpf_doc`), and
  "It ports a game I wrote in MPF (YAML and Python)" adds a line naming it to the brief copied for an agent.
- MODE_SDK.md: the guide in its file table, and "A menu at the game's start" (below).

## The game (UNCANNY STORY)

FUTURE, the base (MPF priority 100, `game_mode`): the whole game; every ramp 1,000 and a point of the Mutant Meter;
three left ramps in a ball start the Sentinel; Action spends a full meter (3) on the mutant's ability against the
topmost enemy (Cyclops 3 damage with the Optic Blast fade, Storm and Wolverine 2). The roster (MPF carousel): a menu
at player 1's first ball, CYCLOPS / STORM / WOLVERINE, the ball held in the shooter lane, the last pick (saved) the
default. SENTINEL, layer 50 (MPF 200): a health bar of 6, a 10 s ball save, right and DR ramps hit it, two Xjet hits
start the Phoenix, defeating it moves the player's chapter on (saved) and the machine's count; a drain keeps it for
the next ball. PHOENIX, layer 80 (MPF 300): a 2-ball multiball with a 10 s save, a health bar of 4, a 30 s clock, the
right ramp its own (`pm_shot_claim`: MPF's `block: true`).

## Proof (emulator, hidden, muted, 1x; rig kit C:/tmp/PAD-1410)

`mkset.py` builds each set the way a maker's project is built: a scratch project off the card, New mode > C
(`mode_tryit.new_code_mode`), the port and the kit copied in, the app's own Write (`engine.write_overrides`): the HUD
scene with 3 meters, 2 fades and the menu, `buttons.cfg`, `saved.cfg`, `pad_mode.so`. `job.sh` (rigbatch, `go.sh`)
plays three games with two power cycles between them; switch ids come from the slot's `switch_list.txt` by name
(Left Ramp Exit Opto 84, Right Ramp Exit Opto 98 LE / 93 Pro, XJET Tgt 50, DR Ramp Exit 56), button ids from
`buttons.cfg` (Action 34, left 68, right 67).

| Step | Uncanny X-Men LE 0.98 | Uncanny X-Men Pro 0.98 |
|---|---|---|
| the runtime finds Meter1-3 (20 levels), Fade1-2 (16 steps), Menu1 (5 rows) | yes | yes |
| game 1: FUTURE has the whole game; the roster opens after the game's intro, on CYCLOPS; right, right, left, left, Action picks CYCLOPS | yes | yes |
| three left ramps: SENTINEL begins as a layer at 50 over FUTURE; the game's ball saver on for 10 s | yes | yes |
| a right ramp: Sentinel 5 of 6; Action: CYCLOPS hits it for 3 (2 left), the black + red glow fade | yes | yes |
| two Xjet: PHOENIX begins at 80 over SENTINEL (3 of ours run); 2 balls served, 10 s save | yes | yes |
| two right ramps: Phoenix 2 of 4, the Sentinel saw neither (claimed) | yes | yes |
| a left ramp fills the meter; Action: CYCLOPS hits the PHOENIX for 3: defeated, its layer ends | yes | yes |
| two DR ramps: SENTINEL DEFEATED, CHAPTER 2 saved | yes | yes |
| the score after the last award = every point the mode gave | 214,000 = 214,000 | 214,000 = 214,000 |
| the store after game 1 | `m xstory:games 1`, `p1 xstory:mutant 0`, `p1 xstory:chapter 2`, `m xstory:sentinels 1` | the same |
| power cycle; game 2 reads CHAPTER 2, CYCLOPS, 1 Sentinel; the menu opens on CYCLOPS; right + Action picks STORM | yes | yes |
| power cycle; game 3 reads STORM; the menu opens on STORM; game 3 on this machine | yes | yes |

rigbatch run r4: 2/2 pass (265 s each).

## Found on the way: a menu at the game's start is hidden by the game's intro

The first runs passed every log check, but the frames showed no menu: Uncanny X-Men 0.98 plays its start-of-game
video (the city, the Sentinels, "CHANGE THE PAST. SAVE THE FUTURE.") over the whole glass when Start is pressed, and
the menu, opened as the game began, was drawn under it and picked by its 10 s time out unseen. PAD-1404's own proof
opened its menu 10 s into a game, so it never met this. Measured (probe builds, LE): `pm_display_covered`,
`pm_game_words` and `pm_clip_playing` read 0 all through the video, and a flipper press does not skip it under the whole game; it lasts about 15 s from the game's start (the
menu opened at 13.0 s was still under its fade-out). The port opens the roster 17 s after the game began on player 1's
first ball (later players have no such video), and a ball in play before then keeps the last pick instead of a menu
over a live ball. MODE_SDK.md's menu section and the guide say so.

PAD-1464 since: the runtime sees the film (`pm_start_film`) on every Spike 2 build and the kit's menu waits for it
by itself, so the port opens the roster at FUTURE's start again and its 17 s wait is gone
(`docs/plans/pad1464_start_film.md`).

## Tests

`tests/test_pad1410_mpf_porting.py`: the guide sits beside MODE_SDK.md and every `pm_` / `kit_` / `pa_` call it names
exists in the SDK; the example's assets.json is a valid code mode, its C finds exactly the screens its assets.json
makes, asks only for shots both X-Men ports have (or a button shot), and uses only SDK calls; the wizard offers the
guide and names it in the brief only when ticked. `tests/test_pad652_new_mode_wizard.py` (the wizard's calls) and
`tests/test_app_run_logic_modes.py` (the C step opens MPF_PORTING.md beside MODE_SDK.md).
