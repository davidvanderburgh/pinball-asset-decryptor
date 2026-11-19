# PAD-1408: share a finished game with other owners

Row 20 of the PAD-1398 gap analysis (20SidedDies' Uncanny X-Men 2.0: "a simple SD card swap"). A maker's whole
game, as one file another owner loads into PAD and writes to their own card, or builds as a multi-boot Edition
beside the original, with no file of the manufacturer's inside.

## The file (`core/game_file.py`)

A zip, `<project>_game.zip` by default, holding the formats PAD already loads, side by side:

| member | what |
|---|---|
| `pad_game.json` | manifest: `kind: pad-game`, format 1, name, made_for (title, label, card), PAD version, the modes' names and folders, `modes_root`, `objects`, `stock` |
| `mod_pack.zip` | the project's Mod Pack: changed files, settings, high scores, music modes, random clips, attract items, files replaced on the card image |
| `modes.zip` | a file of the modes (PAD-1050): every mode folder, sources, pictures, clips, sounds. Saved progress (PAD-1402) is made from the sources at Write time, so it travels with them |
| `modes_root/<f>` | the loose files of the `modes` folder (counts-as rows `stock.json`, the rules sheet) |
| `code/<key>.so` | the maker's compiled code modes, kept under `code_object_key` |

**No manufacturer content.** Any member (at any depth) whose bytes are one of the maker's card's own files
(baseline MD5) is left out and only named under `stock`. A load puts those bytes back from the owner's own
extract: the card file the maker's was first, then any file of the owner's card with the same MD5, and the
untouched `.orig` copy when the owner changed it. Bytes the owner's card does not have are left out, and the log
names them. The project's own folders (`modes`, `Backups`, `.pad_game`, the non-asset folders) never count as
the card's, even when a baseline taken after they were made lists them. A file the maker changed is the maker's
own work and travels, as in a Mod Pack.

**The compiled mode travels.** On export, the object PAD keeps for the project's code modes goes in, compiled
then if none is kept. On load it goes to `<project>/.pad_game/code/<key>.so`. `compile_code_object` (and the early
compile, `prefetch_code_object`) takes it whenever the owner's sources key to it, which means the same code modes
on the same PAD. The build log then says "the maker's own mode.so is used". Any other case compiles the sources,
which are always in the file.

**A newer version loads over the last.** `.pad_game/game.json` records the game's name and the mode folders it
brought. A later load of the same name replaces those modes. A mode of the owner's with the same folder name is
kept, and the game's copy gets a name of its own beside it.

## UI

No new buttons (David, 2026-11-19: two extra Share/Load buttons were confusing). The Mod Pack tab's Export has two
boxes, both on: **Changed files and settings** and **Modes (with their compiled code)**; Modes shows only for Stern.
With Modes ticked on a project that has modes, Export writes this file (`app._share_game_worker`). Otherwise it
writes the plain Mod Pack it always did, so a pack with no modes still loads in an older PAD. Unticking Changed
files carries the modes alone. **Import Mod Pack...** recognises the file and imports it whole. The Modes tab's
Load from a file names such a file and points to Import Mod Pack.

## Proof (X-Men LE/Pro 0.98, the gap analysis's first target)

`C:/tmp/PAD-1408/proof.py`: the maker's X-Men LE 0.98 project with a blocks mode, STORY, which counts each ended
ball in saved variables, is shared as a game. Two other owners' fresh projects, X-Men LE 0.98 and X-Men Pro 0.98,
load it and build through `engine.write_overrides`, with the code cache emptied first. Both builds log "the maker's
own mode.so is used", and both `pad_mode.so` files are byte-for-byte the maker's (sha256 331861aba78f3c16…).
`saved.cfg` is made for each card's own NVM layout. Rig: `job.sh` and `go.sh` (rigbatch) boot each set, play a
game and read the mode's log and the saved store.
