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

**Led Zeppelin Pro 1.22's unnamed shots.** See Status.

What it deliberately does not do: no merge of two projects' modes, no rename on the
way, no build. The copies are for the person to look at in THAT project's Modes tab.

## Status

- 2026-09-25: branch made from main `647c6778`. Copy to..., the family rule for
  callouts, the words moved into `mode_project`, unit tests and the web-tab test,
  the help tip and the SDK doc. Proven by the targeted tests and by running the app
  from the worktree (see below).

## How to test it

- `python scripts/testpick.py` on the diff; or directly
  `python -m pytest tests/test_stern_mode_profiles.py tests/test_webui_modes.py -q -k "family or copy"`.
- In the app (from this worktree, the preview switch on): open a card project with a
  mode, Modes tab, **Copy to...** under the list, pick another card project's folder.
  The message box names each mode as "runs as it is" or "open it there and pick
  again", and the log has a line per mode. Open the other project: the modes are
  there, the ones to fix show what they lack.
- Real input: a Godzilla Premium 1.16 project's KAIJU RUSH to a Godzilla Pro 1.16
  project (carried as is), and to a TMNT Pro 1.59 project (to fix: the Powerlines and
  the Maser target are Godzilla's).
