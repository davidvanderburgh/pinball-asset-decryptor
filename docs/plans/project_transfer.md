# Carry a card project's modes to another card (Pro beside Premium, 1.58 to 1.59)

## What and why

David, 2026-09-25: *"when i make modes for say a premium game in spike 2, i expect
them to easily transfer to the pro version. is that easy right now, or do we have to
re-make all the modes for a differnet model? also, what abuot from one version (like
1.58 to 1.59) of a game?"* Then, to the three cheap wins named in the answer: *"yes
implement it"*.

The state before this branch: a mode is already portable by design. Its file names
shots by NAME, never by bit, and its picture, clip and sounds live in its own folder;
the CARD decides the title at build time and the app matches every shot by name
against the target card's port (`mode_project.retarget`). What was missing:

1. **No way to move modes between projects** but copying `modes/<slug>/` folders by
   hand, then opening each one in the tab to learn what it lost.
2. **A hand-typed callout id was dropped on any other build**, even the Pro beside the
   Premium of the same game, because the app assumed another build's sound table
   numbers its calls differently. Within one title it does not.
3. **Led Zeppelin Pro 1.22's port left eleven shots unnamed** (`?`, `? 2` ...), so
   those shots could never match the LE's by name.

## Design

**Copy to..., under the Modes list** (`webui/tabs/modes.py: copy_to`, page button in
`static/js/tabs/modes.js`). It asks for the other project's folder and calls
`mode_project.copy_modes(src, dest)`:

- The destination decides the title: its card (`project_profile(dest)`) and that
  card's port. A folder that names no card, a card the app has not read, or a build
  with no port is refused in words, as is this project itself (Duplicate does that).
- Every mode folder is copied whole (picture, clip, sounds, `mode.json`) under a free
  slug. The spec is retargeted exactly as opening it there would retarget it. A mode
  that loses nothing is SAVED for the destination's title, so it builds there as it
  is. A mode that names a shot the card lacks is copied AS IT WAS: the build there
  keeps refusing it until it is opened and its shots picked, which keeps the
  guarantee that a mode is never built with shots silently left out.
- Code modes (`modes/<slug>/<slug>.c`) are copied as they are; when the slug has to
  change, the C file follows the folder's new name.
- The report (`CopyReport`) is one message box and one log line per mode, in the same
  words the tab uses when a mode is opened on another card (`retarget_words`, moved
  from the tab into `mode_project` so both say the same thing).
- Nothing in the source project changes.

**Callout ids within one title** (`mode_project.same_title`, `title_family`). A game
dir with its model word taken off is the title: `godzilla_pro` and `godzilla_le` are
`godzilla`; `james_bond_60th_le` and `james_bond_le` stay two titles, as do
`star_wars_le` / `star_wars_elg` and `jurassic_park_le` / `jurassic_park_the_pin`. A
callout id typed by hand on one build of a title is kept on another build of it. The
evidence: every callout the Pro and LE ports of Godzilla 1.16, TMNT 1.59 and Led
Zeppelin 1.22 measured has the same id on both, as do Godzilla Pro 1.15 and 1.16
(`test_title_family_and_callouts_kept_within_it` pins this). Another title's id is
still dropped: the same number plays some other sound there.

**Led Zeppelin Pro 1.22's unnamed shots** are named after the LE 1.22 port's names
for the same bits, at the desk (no rig): both builds' `cshot` objects (read with
`portshots.cpp_shots`' unicorn machine) carry a MESSAGE ID per shot at +12, the same
id per bit on both (3029..3057 and 3061 in mask order; the LE adds 0x40000000 =
3160), and the Pro's own switch table has the same switches (3 BANK DROP-Z/E/P,
ICARUS TARGET, LEFT/RIGHT ORBIT, the three RAMP EXIT OPTOs). The one to read with
care is 0x200000, the LE's SIDE RAMP EXIT OPTO: the Pro has no side ramp switch
(HERMIT TARGET stands in its table where the LE has the ELECTRIC MAGIC SPINNER OPTO),
yet a press made that shot in the Pro's check. The port's header says all this. The
recipe was rebuilt (`port_tool.py recipe`). Check this game on 2026-09-26 (the app's
own flow, this worktree, the Pro card in the emulator): 25 of the 30 shots came from
their switches, every one of the 11 renamed among them, a drain ended the ball and 5
events fired. Which switch made each is not in the record: the rig's switch list names
this build's node-9 switches (ids 78-91) "?", so the check reports "?" for them, and the
raw mode log with the marks was cleared by a run another session started right after.
Owed: a census read straight after the run (or the rig naming those switches) would
tie each name to its switch.

What it deliberately does not do: no merge of two projects' modes, no rename on the
way, no build. The copies are for the person to look at in THAT project's Modes tab.
Message ids are not read statically (the remap is filled at boot and the sorted u16
id runs are per module); the message oracle in `reference_spike2_message_oracle_godzilla`
is the way to read a `cshot`'s own name if that is ever wanted.

## Status

- 2026-09-25: branch made from main `647c6778`. Copy to..., the family rule for
  callouts, the words moved into `mode_project`, unit tests and the web-tab test,
  the help tip and the SDK doc (`a89dd3ae`). Then Led Zeppelin Pro's shots named
  and its recipe rebuilt. Proven by the targeted tests (`test_stern_mode_profiles`,
  `test_webui_modes`, `test_app_run_logic_modes`, `test_stern_port_derive`,
  `test_stern_mode_runtime`) and a copy between real card projects on this machine
  (see below). Done: David can merge it.

## How to test it

- `python scripts/testpick.py` on the diff; or directly
  `python -m pytest tests/test_stern_mode_profiles.py tests/test_webui_modes.py tests/test_stern_port_derive.py -q`.
- In the app (from this worktree, the preview switch on): open a card project with a
  mode, Modes tab, **Copy to...** under the list, pick another card project's folder.
  The message box names each mode as "runs as it is" or "open it there and pick
  again", and the log has a line per mode. Open the other project: the modes are
  there, the ones to fix show what they lack.
- Real input (done 2026-09-25, `copy_modes` from a script): a real Godzilla Premium
  1.16 project with nine modes (eight form modes with their films, 211 MB, and one
  code mode) into a Godzilla Pro 1.16 project: all eight carried as they are, the
  code mode as it is. The same into a TMNT Pro 1.59 project: all eight "open it there
  and pick again", each naming the Godzilla shots TMNT lacks (Powerlines, Maser and
  Godzilla targets, Building, Big loop, the shields) and the start shot it falls back
  to (Center loop). The source project was unchanged.
- In the app (done 2026-09-26, the server from this worktree in the browser, preview
  switch on): Project menu > Open project on a copy of that Godzilla Premium project,
  Modes tab lists its 8 modes + 1 in C, **Copy to...** under the list, the folder
  dialog on an empty Godzilla Pro 1.16 project, Choose this folder. The "Copy modes"
  box read "Copied 9 modes ... 8 run on Godzilla Pro 1.16 as they are; 1 code mode
  copied as it is" with a line per mode, the log had the same lines, and opening the
  destination project showed "Godzilla Pro 1.16 · 21 shots · 8 modes + 1 in C" with
  ATOMIC BREATH "Ready to build". On disk: 9 folders, 203 MB, every mode.json now
  titled for Pro 1.16, the code mode's C file in place.
