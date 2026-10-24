# Combos as blocks (PAD-708)

David, 2026-10-24: "Do we already have logic in place for combos in the blocks?" There was none: King Caesar's TAG
TEAM was a timer, a variable and a 1 ms timer per follow-up shot.

## What the blocks have now

- **The hat** `{"kind": "combo", "shots": [...], "seconds": N, "when": "any|idle|running", "name": "..."}`: its
  shots made in that order, each within N seconds (0.5 to 60, tenths) of the one before. 2 to 6 steps; a step is a
  shot of the card's, `"*"` (any shot), `"lit"` (a shot this mode has lit as it is made, not held dark) or a list
  of up to 4 shots (one of them). Palette: "When a shot follows a shot (a combo)" and "When a lit shot follows a lit
  shot"; on the hat, `+` adds a step, `or` an alternative, `x` takes one out.
- **The combos in a row** (`{"k": "combo_chain"}`), per player: +1 for each shot that makes one or more combos; 0
  when the window of the last one lapses, at the ball's end, as the mode starts and ends, at a new game.
- **A combo's shots made so far** (`{"k": "combo_steps", "combo": "<name>"}`): 0 once its window lapses.

## How it is judged (the C, `block_modes._COMBO_C` / `_COMBO_SHOT_C`)

In each mode's own C, on the shots it hears (`on_shot`), so no runtime change and every title, LE or Pro, the same.
Per combo: its steps made so far and when the last was made. On a shot (before any script runs, the lit mask as it
was): the window lapsed -> 0; the shot is the next step -> +1 (all of them: made, and the shot may begin the next
one, so lit-after-lit chains); else the shot is the first step -> it begins again from there; else nothing.

**Other shots between do not break a combo** (decision below): the ball passes spinners, lanes and pops, which are
named shots too, on its way from the Godzilla target to the pops. The hand-built TAG TEAM allowed them, and an
ordered combo would hardly ever be made if they broke it. Only the window ends a combo.

A combo moves on only while its When holds (`running`: the mode's state before the shot, as shot hats are judged),
and the start of the mode clears every combo and the chain, so the shot that starts it begins nothing.

## The desk player and the rules sheet

`blocks_sim` judges combos the same way (tests check the desk harness's C and the desk player give the same scores).
Two older differences from the C were fixed along the way: a shot's When is judged by the mode's state before the
shot, and a mode that does not end on a drain runs on past one. The rules sheet's player tries a running combo's
shots in order when no one shot does anything, notes a combo against the stage whose shot made it ("(combo Godzilla
target, then Pop bumper or Mecha exit bottom within 20 s)"), and words a combo that starts a mode as its start rule.

## Proof

- `tests/test_pad708_combos.py`: checks, words, the C, the script view, the desk player, the rules sheet, and the
  desk harness (in order and out, the window, the chain and its ends, ordered steps, lit and dark shots, one of
  several shots, shots between).
- Rig sweep, every title's newest build in the card cache (30): a mode built from the title's port lights its shots
  and has a lit-after-lit combo and an any-any-any ordered combo; the job presses the title's own playfield switches
  until mode.log shows both, the steps counted and 2 in a row.
- Godzilla, David's Heisei 1.99D card: a ramp pair, ramp -> loop -> ramp (with its steps), a lapsed window, and TAG
  TEAM twice (2 in a row); then his converted King Caesar replayed through its stages to TAG TEAM's three combos.
