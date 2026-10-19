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

## David's decision (2026-10-18): switch views at any time

David reviewed the mockups: "I especially like having the visualization of the playfield. We should be able to
switch visualizations at any point and not be beholden to one or another; for example I should be able to switch
from blocks to any of these others."

So the views are **tabs over one mode, never kinds of mode**:

- Blocks, Rule cards, Story, Playfield, Shot table, Timeline, Node graph and Script are tabs on the same
  `blocks.json`. A mode is never a "cards mode" or a "playfield mode". Switching tabs never converts anything and
  never asks first.
- An edit in any tab saves the one `blocks.json`. Every other tab redraws from it when it is opened. Undo/redo is
  one history for the mode, so an undo in Cards takes back an edit made in Blocks.
- A tab that cannot show a rule in its own way still lists it, so nothing is ever hidden. Examples: the clock
  and drain rules beside the Playfield, shot reactions under the Timeline.
- The Script tab already meets this: any `blocks.json` goes to text and back exactly (the tests). Each tab built
  later gets the same test: every block there is, edited through that tab, saved, and read back unchanged.
- **C is the one exception.** Free C cannot be read back into blocks. It stays behind "Edit as C", which warns
  that it is a one-way step, and is not one of the tabs. The Script tab is the typed form that switches freely.

## What to build, in order

1. **The tab strip and one shared program/undo** in the Modes tab, so a view is just a tab (the switch David
   asked for). Blocks stays the first tab.
2. **Playfield**, the view David singled out: the game's own playfield picture and insert positions from the
   person's card (`lampmap.py`), lit shots in their colours, a shot's card editable in place, other rules listed
   beside it. Every other tab also uses it as its shot picker.
3. **Rule cards**: the biggest gain in ease for the least work.
4. **Story** above the cards, with drag-a-rule-between-states.
5. **Script** tab with the in-app editor; the C editor reuses it.
6. Shot table, Timeline (for shows) and Node graph (as a "who uses this variable" overlay) as further tabs.

Every view writes the same program, so the blocks' limits (48 scripts, 400 blocks), checks (`problems`) and C
(`to_c`) stay exactly as they are. A view adds nothing that has to be compiled differently and cannot make a mode
the blocks could not.

## Built so far (PAD-612)

Steps 1 and 2 are in the Modes tab:

- **The tab strip.** A blocks mode's pane has the tabs **Blocks | Playfield | C it makes**, with one Undo / Redo and
  the saved line beside them. `modes_blocks.js useModeProgram` holds the one program, its one history and its saving;
  each view makes its own `useEd` (its pick and drop line) over it, so a block edited in any view is a step of the
  same history and is saved to the same `blocks.json`. A later view is one more entry in `modes.js BLOCKS_PAGES`.
- **Playfield.** `plugins/stern/playfield_art.py` reads the game's own playfield drawing off the project's card
  (`<game>/assets/nuk/images/<a test folder>/*playfield*.png`, chosen by the emulator window's rules) and the
  inserts' places from the port's `lamp ... at X,Y` lines; `modes.blocks_playfield` hands both to the page. The
  view (`modes_playfield.js`, its reading of the program in `modes_views.js`) draws every insert, the mode's lit
  ones in their color and pattern; a shot picked (on the picture or from the shot list) shows its rules as blocks,
  editable in place, grouped by when they run, with Add a rule for each, and the other rules that name it; rules not
  tied to a shot are listed below. With no picture (no card, another game's card, a title that ships none) the
  inserts are drawn on an outline and the reason is said under it.

## Built in PAD-614: steps 3-6

A blocks mode's tabs are now **Blocks | Rule cards | Story | Playfield | Shot table | Timeline | Node graph | Script |
C it makes** (`modes.js BLOCKS_PAGES`, each entry naming its view). Every one is a tab over the one program
(`useModeProgram`), so an edit in any of them is a step of the one history and is saved to the one `blocks.json`.
A rule is edited as the same blocks everywhere (`modes_blocks.js` `Script`, `Stack`, `HatBody`); what each view places
where is read off the program by plain functions in `modes_views.js`, which the tests run under Node.

- **Rule cards** (`modes_rules.js RuleCardsView`): a card per rule, the hat on top and its blocks under it, drawn as
  sentences: no colored stacks, each block marked by its family's color, every blank an underlined choice.
- **Story** (`StoryView`): WAITING → RUNNING → OVER. A shot's, an any-shot's or a game event's rule sits in the box of
  its `when` (idle / running / any time, the last under the diagram); dragging it to another box sets its `when`. The
  arrows say what starts the mode (every Start the mode block, with the Ifs around it, `storyArrows`) and what ends it
  (the clock, the drain, End the mode), with When the mode starts / ends rules on them. The clock's rules (every, N
  seconds left, a timer) work while it runs. Ball-drain rules and the variables and timers sit underneath.
- **Shot table** (`ShotTableView`): a row per shot of the card, Any shot, and each game event the mode uses; columns
  while it is not running / while it runs / any time. A cell's + adds a rule with that hat; rules tied to no shot are
  listed under it; a pressed rule opens beside the table.
- **Timeline** (`TimelineView`): the mode's seconds left to right, its moments (It starts, N s left, Every N s and its
  repeats, It ends) and seven lanes (Mode and clock, Lights, Light shows, Sound, Screen and HUD, Score and variables,
  the rest). Each block of a moment's rule is a clip on its lane (striped when an If decides it), packed into rows so
  none covers another. What adds time from a shot is said under the lanes, and the rules with no fixed time are listed.
- **Node graph** (`NodeGraphView`): the plan's "who uses this variable" overlay as its own tab. Every rule a node,
  every variable, timer and shot count the rules share a node, wired solid (sets), dashed (reads) or dotted (a timer
  running out sets the rule off). Pressing one lights up its rules and lists them; it needs no general graph layout.
- **Script** (`modes_script.js ScriptView`): `mode_script.py` moved into the app (`plugins/stern/mode_script.py`;
  `tools/mode_views/mode_script.py` is now its old name). `modes.blocks_script` writes the program as text,
  `modes.blocks_read_script` reads typed text back (normalized, as `blocks.json` is) or answers the error and its line.
  A block or trigger the plain form does not name is an error on its line (a misspelling is not kept as a block the
  mode cannot run); one the app does not have in a saved file is written and read as `block({...})`, kept exactly.
  Typing that reads goes into the blocks as one step (typing merges into it); text that does not read leaves the
  blocks as they were, marks the line and offers Go to line. A side list puts any hat or block in at the cursor.
- **The editor** (`CodeEditor`): a text box over its own colored copy, lines numbered, Tab and Enter keep the indent.
  It shows the C the blocks make (read only, `CodeView`) and edits a mode written in C on its Code page (`CEditor`,
  `modes.code_text` / `code_save`, Save or Ctrl+S), so C no longer needs the OS's editor.
- **The Playfield as the shot picker** (`modes_playfield.js PickOnField`): every shot's list in a block (a hat, Light
  the mode, Set hits, a hits value, Light and Hand back) has ◎ beside it, in every view. It opens the playfield picture
  with the mode's lit shots; pressing an insert picks its shot (several shots: a menu), and for a Light block an insert
  that is no shot's lights it alone. `modes_blocks.js pickers` holds the button, so the blocks need no import of it.

Every view round-trips the mode (`tests/test_pad614_mode_views.py`): RAMP FRENZY and one of every block, hat, value and
condition, set field by field through the blocks (no change, nothing saved), every movable rule dragged through every
Story box and back, a Shot table rule added and undone, and the Script's text read back (no change) or typed (one step,
undone), each ending on the program it began with.

## Files

- `plugins/stern/mode_script.py` (PAD-614; was `tools/mode_views/mode_script.py`): `blocks.json` ⇄ script text.
- `tools/mode_views/describe.py`: every block, value, condition and trigger in words.
- `tools/mode_views/render_views.py`: the seven views, drawn from any `blocks.json`.
- `tools/mode_views/showcase.py`: RAMP FRENZY.
- `scripts/shot_pad611.py`: the blocks page with RAMP FRENZY loaded, and the seven views of the same file.
- `tests/test_pad611_mode_script.py`: the round trip and the views (39 tests).
- `plugins/stern/playfield_art.py`, `webui/static/js/tabs/modes_playfield.js`, `modes_views.js`: the Playfield view
  (PAD-612); `tests/test_pad612_mode_views.py`; `scripts/shot_pad612.py`: its proof shots.
- `webui/static/js/tabs/modes_rules.js` (Rule cards, Story, Shot table, Timeline, Node graph), `modes_script.js`
  (Script, the code editor): PAD-614; `tests/test_pad614_mode_views.py`; `scripts/shot_pad614.py`: one shot per view.
