# PAD-233 - a multi-boot card names what a pair of versions costs

Queue item 97. Part 2 (node firmware gate) shipped with item 90; part 3 (a
settings safe in select.sh) was replaced by PAD-226's per-image stores. This
ticket did what was left.

## What the machine does (the premise)

Spike 2 settings, audits and high scores live in `/data/nv/<title>/NVM`
(and the board), each record keyed by SHA1 of the operator menu's CAPTION.
Two builds of one title therefore share every setting they spell the same
way. A setting only one build has falls back to its default while the other
runs (and the three-deep ring loses it after two boots of the other build); a
setting Stern renamed reverts on every swap.

## (a) Named, per card - `mkmulticard.py`

`attach_settings` reads each game ELF's adjustment captions
(`spb.elf_captions`: AD name, caption, menu/service/debug) only when a title
is on the card at more than one version. `settings_pairs` / `settings_cost`
turn that into a paragraph per pair of builds: how many carry, which fall back
(menu settings named, debug ones counted), which revert. It is printed as
`== settings` by plan / build / verify / inspect, put in the refusal, written
to inspect's JSON as `settings_cost`, and shown in the app's version alarm.

Checked against the rig's September round trip: TMNT Pro 1.59.0 / 1.58.0 reads
228 shared, 43 / 13 build-only (40 / 10 once the 3 renamed are split out).

## (b) At select time - `note=` in images.conf

`note=<N>|<text>` - one line the selector draws in the counter's row while
image N's card is highlighted ("Game code 1.58.0: 228 settings carry over
from 1.59.0, 53 do not"). build and update write it from the versions they
read; inject carries the card's own. The emulator carries it on the group
lines' gate (index-keyed). Older selectors ignore the key.

## (c) The way back - `plugins/stern/spb.py`

Reads an `.SPB` export or a raw NVM generation, names settings from a game
ELF, sets one by caption (value + check), and carries settings by caption
from one file into another (an old version's save into a fresh save of the
new one). Re-signs the container; writes an NVM file's `.crc32` sidecar.

Checks, verified on 7 real saves (TMNT 1.58/1.59, Godzilla 1.15, Batman 1.13)
and the rig stores: adjustment = low byte `0xFF - bytesum(value)`; audit =
`0xFFFF - bytesum(value words)`. Command line:
`python -m pinball_decryptor.plugins.stern.spb show|set|carry`.

## Owed

- No GUI for the `.SPB` tool yet; it is a command line.
- A carried `.SPB` has not been loaded on a machine. The single-setting
  write matches the July hardware-accepted edit, but a many-setting carry has
  not been tried.
- High-score and audit records are read-only.
