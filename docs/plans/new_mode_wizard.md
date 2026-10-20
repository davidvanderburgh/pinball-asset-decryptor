# Making a new mode: the wizard (PAD-652)

David's ask: a "make new mode" button that opens a wizard, with tiles that explain the
ways of building a mode (skill it takes, what it can do), replacing the long New drop-down.
His note while it was worked: Blocks is the recommended way, C is the recommended way when
an AI agent writes the mode, and the form is a bare-minimum playground.

## What it is

- **New mode** over the Modes list (was **New ▾**, a menu of six entries and two submenus)
  opens `NewModeWizard` (`webui/static/js/tabs/modes_new.js`).
- Step 1: three tiles, in this order: **Blocks** (Recommended), **C** (Best with an AI
  agent), **Form** (Playground). Each has a pitch, a three-step skill meter with words
  (No coding / A programmer, or an AI agent / Anyone), what it can do, what it can't, and
  where you work. A way that can't be used here (no project, no port for this build, the
  mode cap) is greyed with the reason.
- Step 2, per way:
  - Blocks: the name; Make it calls `modes.new_blocks_mode`.
  - C: the name, or one of the C examples (`modes.code_example`), and Open MODE_SDK.md.
    **Make it and copy for an agent** calls `modes.new_code_mode`, then copies a brief for
    an AI agent: the game, what the mode should do (typed in the wizard), the new `.c`
    file's path, and MODE_SDK.md's path to read first (the SDK's own "If you are an AI
    agent" instructions take it from there).
  - Form: Blank mode (`modes.new`) or one of the card's form examples (`modes.example`).
- The first-mode page (a project with no mode yet) shows the same tiles in place; a tile
  opens the wizard at its step 2. Its old four-box grid is gone.
- Python is unchanged: the wizard calls the same RPCs the menu did. The old name dialog
  (`NewCodeDialog`) and `BLOCKS_WORDS` went with the menu.
- Tips (Making a mode, Modes made of blocks, Modes written in C) describe the wizard;
  de/es/fr carry its words.

## Proof

- `scripts/e2e_pad652.py <repo>`: the served app, through the page: first-mode Blocks tile,
  New mode > C with a brief and the agent copy (clipboard checked), Form > Blank, Form >
  KAIJU RUSH; each must add its mode to the project's modes folder.
- `scripts/shot_pad652.py <repo> <out> <prefix>`: the before/after shots.
