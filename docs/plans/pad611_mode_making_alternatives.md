# PAD-611: other ways to make a mode, as easy as the blocks and as powerful

David asked for visual alternatives to the blocks for making modes: diagrams or anything else that is very easy
to pick up and still does everything the blocks do, maybe even everything C does.

**Short answer.** A blocks mode is one program, `blocks.json`. The blocks page is only one way of drawing it and
editing it. Any other view that reads and writes the same file has the blocks' full power for free, and a person
can switch views whenever they like. Scratch/MakeCode works this way (blocks ⇄ JavaScript ⇄ Python), and so does
Unreal (Blueprints ⇄ C++). This ticket draws one real mode in seven such views, all generated from its
`blocks.json`, and proves the typed one (the Script view) goes to `blocks.json` and back with nothing lost.

Recommendation: **Rule cards** as the default editor, the **Story** diagram above it as the overview, the
**Playfield** as the way to pick shots, **Script** for people who would rather type, and C kept as the expert's
way out, opened in an in-app editor. The rest of this file explains why.

## Today

| Way | What it is | Limits |
|---|---|---|
| Form | pages of settings (Mode, Show, Lights, Sounds, Scoring); `mode.json` read by `mode_file.c` | only what the pages ask |
| Blocks | snapped blocks (custom Preact, `modes_blocks.js`); `blocks.json` → C (`block_modes.to_c`) | 9 triggers, 36 blocks, 10 values, 8 conditions; 48 scripts / 400 blocks |
| C | the SDK template, edited in the OS's own editor; "Edit as C" turns a blocks mode into C | no way back to blocks; the C made from blocks is 913 lines for a 9-rule mode |

The trouble with the blocks shows in `before_*.png`. RAMP FRENZY has 9 rules and 26 blocks. Even on a
1500-pixel-tall window the page shows four of them. Each rule is a tall coloured stack of dropdowns, so a reader
can follow one rule at a time but can never see the mode as a whole: when it starts, what runs while it runs,
how it ends.

## The mode every mockup draws

`tools/mode_views/showcase.py` is RAMP FRENZY on Godzilla Pro 1.15. Three Left ramps start it. While it runs,
every shot scores 500,000 × a growing combo. The Right ramp is a jackpot: it adds 5 s and opens a 4-second
window in which the Big loop is a super jackpot. Ten seconds from the end the callout plays and the ramp
hurries. At the end there is a rainbow for three jackpots or more, else a fizzle. It uses a timer, two
variables, if/else, the HUD, light shows and lit shots, so every view has to show the hard parts.
`block_modes.problems` finds nothing wrong with it. It is saved through `block_modes.save` like any blocks mode,
and every view is drawn from that `blocks.json` (`scripts/shot_pad611.py`).

## The alternatives

Each one is `tools/mode_views/render_views.py <view>`, shot as `after_<view>.png`.

### 1. Story: the mode's life as a diagram (state diagram)

There are three boxes: **WAITING → RUNNING → OVER**. Arrows between them carry what moves the mode on: "Left
ramp is made, if hits of Left ramp ≥ 3" in, and "the clock runs out", "the ball drains" out. Under each arrow
sits what happens on the way through (When the mode starts / ends). Every rule sits in the box where it works,
because a blocks trigger already says so: a shot "while the mode is not running" belongs in WAITING, one "while
it runs" in RUNNING, a clock moment in RUNNING. Ball-drain and any-time rules, plus the variables and timers,
sit underneath.

- **Easy to pick up:** very. It answers the first question anyone has about a mode: how does it start, what do
  I do in it, how does it end. Pinball people already think in these states.
- **Power:** full. Every trigger has exactly one place, and the rules inside the boxes are the same rules.
  Editing moves a rule between boxes (that changes its "when") or drops a trigger onto an arrow.
- **Inspiration:** Stately/XState state charts, and the mode diagrams in pinball rule sheets.
- **Effort:** medium. The layout is fixed (three boxes), so it needs no general graph layout.

### 2. Playfield: rules pinned to the shots

This is the game's own playfield. Each shot the mode uses is a light in the colour the mode lights it, and
clicking a shot opens its card: what it does while the mode waits, what it does while it runs, and which rules
light it. The mockup uses a drawn outline, so it has no manufacturer art. The real view would use the picture
and insert positions PAD already reads from the person's own card: `lampmap.py` reads each insert's x, y on the
game's "playfield" picture and the shot each lamp belongs to, for every Spike 2 title.

- **Easy to pick up:** the easiest of all for choosing *where*: you click the ramp, not a dropdown of 18 names.
- **Power:** full for shot rules. Rules that are not tied to a shot (the clock, the drain, timers) sit in a list
  beside it, so nothing is hidden, but those rules gain nothing from this view.
- **Effort:** medium to high: the picture and the insert positions per title, and a fallback outline where a
  title has no picture (Deadpool LE draws no playfield picture).

### 3. Timeline: the clock as a track

This looks like a video editor. The mode's 30 seconds run across the page, with marks at *start*, *10 s left*
and *end*, and lanes for Clock, Lights, Light shows, Sound, Screen/HUD and Score. What happens at each moment is
a clip on its lane. The Clock lane says what adds time ("+5 s when Right ramp is made"). Rules that happen
whenever a shot is made are listed underneath, because they have no fixed time.

- **Easy to pick up:** yes, for the show side: lining up a light show, a callout and a clip.
- **Power:** partial as a view. Most of a mode is shot-driven, not time-driven, and those rules can only be
  listed. It is the right tool for its own job: a mode's start and end shows, and the light shows' own steps
  (today a list of ten steps), not the whole mode.
- **Effort:** medium.

### 4. Shot table: a grid

There is one row per shot (and "Any shot") and three columns: *While it waits*, *While it runs*, *Any time*. An
empty cell is a "+" to fill. The clock moments and other triggers are rows of a second table.

- **Easy to pick up:** for anyone who uses spreadsheets. It is the most compact view, and empty cells show what
  is not used yet: the Building, the Godzilla target and the Maser target do nothing in this mode.
- **Power:** full (every trigger is a row).
- **Effort:** low. It is the cheapest view to build.

### 5. Node graph: triggers wired to actions

Each trigger is a node wired to its actions in order. An If splits into *yes* and *no*. Dashed wires run from
the variables and timers to every block that reads or writes them.

- **Easy to pick up:** for people who know Unreal Blueprints or Node-RED. For everyone else it is the busiest
  view. Already at 9 rules the nodes have to cut their words short and the variable wires cross, as the mockup
  shows.
- **Power:** full, and the best view for one thing: seeing which rules share a variable.
- **Effort:** high (general graph layout, wire editing). **Not recommended** as a main editor. It could be an
  overlay on the Story view ("show what uses *combo*").

### 6. Rule cards: When … Then, in words

Each rule is a card. **WHEN** "Right ramp is made (running)", then **THEN** "Score 5,000,000 / Add 5 s to the
clock / Start the window timer: 4 s …", with every underlined word a picker. It is the same structure as the
blocks, written as sentences instead of stacks of dropdowns, and three cards fit across the page.

- **Easy to pick up:** the most, alongside Story. It reads like the rules on a rule sheet. Apple Shortcuts,
  IFTTT and Home Assistant automations all landed on this shape for non-programmers.
- **Power:** full. A card is exactly a blocks script: the hat, then the blocks in order, with Ifs nested.
- **Effort:** low to medium. The pickers already exist in the blocks page. `describe.py` already has a sentence
  for every block, value, condition and trigger, and the test fails when a new block has none.

### 7. Script: the same mode as text, beside its C

This is the mode as Python-shaped text:

```python
with on.shot(shot="Left ramp", when="idle"):
    if hits(shot="Left ramp") >= 3:
        start_mode()

with on.any_shot(when="running"):
    score(points=500000 * combo)
    change(var="combo", by=1)
```

It sits beside the C the card will run. **It is a real prototype, not only a picture.** `mode_script.py` turns
any `blocks.json` into this text and reads it back into exactly the same program
(`tests/test_pad611_mode_script.py`: every block, trigger, value, condition and operator, plus odd cases such as
an empty else, a variable with a space, or a key the page does not know). The text is read with Python's own
parser and never run.

- **Easy to pick up:** for anyone who has typed code. It is much shorter than C (the 9 rules are about 50
  lines; the C they make is 913) and it goes **both ways**: type, switch to blocks or cards, switch back.
  "Edit as C" is a one-way door.
- **Power:** full: the blocks' own.
- **Effort:** low for the reading and writing (done here). An in-app editor with colours and error lines would
  be the work.

### And C itself

"Maybe even just programming in C." C stays the way past the blocks' limits: anything the SDK (`pad_mode.h`)
can do. What would make it easier:

1. **An editor in the app** (CodeMirror) instead of the OS's editor, with the SDK's functions offered as you
   type and the compiler's errors on their lines (`build_mode.sh` already reports them).
2. **Start from the Script, not from 913 lines.** The C made from blocks is complete but long, because it
   carries the whole runtime with it. A person moving to C is better served by the SDK template with their
   rules filled in, which is what `sdk/examples/*.c` look like.
3. A blocks mode cannot be read back from free C. That stays one way, as it is in every tool that offers both.

### Two extras (not views)

- **Describe it in words.** You type "three Left ramps start it, the Right ramp is a jackpot that adds 5
  seconds" and get the rule cards filled in, to check and change. It needs an online AI model (cost, privacy,
  an internet connection), so it would be an optional helper, never the only way.
- **Show it by playing.** In Emulate, press "pick a shot" and shoot it, instead of choosing from a list.

## Side by side

| View | Easy to pick up | Power | Best at | Effort |
|---|---|---|---|---|
| Rule cards | ★★★★★ | full | reading and writing rules | low–medium |
| Story | ★★★★★ | full | seeing the whole mode | medium |
| Playfield | ★★★★☆ | full for shots, list for the rest | picking where | medium–high |
| Shot table | ★★★★☆ | full | overview, what is unused | low |
| Timeline | ★★★☆☆ | the show side | start/end shows, light show steps | medium |
| Script | ★★★☆☆ (★★★★★ for coders) | full, both ways | typing fast; the step to C | low (+ editor) |
| Node graph | ★★☆☆☆ | full | who uses which variable | high |
| C | ★☆☆☆☆ | beyond the blocks | anything the SDK does | editor: medium |

## What to build, in order

1. **Rule cards** as a second tab beside Blocks, on the same `blocks.json`. It is the biggest gain in ease for
   the least work.
2. **Story** above the cards: the overview, with drag-a-rule-between-states.
3. **Script** tab, with the in-app editor; the C editor reuses it.
4. **Playfield** shot picker, used by every view wherever a shot is chosen.
5. Timeline for the shows only; node graph only as a "who uses this variable" overlay; shot table if people ask
   for it.

Every view writes the same program, so the blocks' limits (48 scripts, 400 blocks), checks (`problems`) and C
(`to_c`) stay exactly as they are. A view adds nothing that has to be compiled differently and cannot make a mode
the blocks could not.

## Files

- `tools/mode_views/mode_script.py`: `blocks.json` ⇄ script text (`to_script`, `from_script`).
- `tools/mode_views/describe.py`: every block, value, condition and trigger in words.
- `tools/mode_views/render_views.py`: the seven views, drawn from any `blocks.json`.
- `tools/mode_views/showcase.py`: RAMP FRENZY.
- `scripts/shot_pad611.py`: the blocks page with RAMP FRENZY loaded, and the seven views of the same file.
- `tests/test_pad611_mode_script.py`: the round trip and the views (39 tests).
