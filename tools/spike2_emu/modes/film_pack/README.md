# Godzilla film mode pack (item 143)

Seven modes for Godzilla Premium 1.16 (godzilla_le): KAIJU RUSH as it ran on the machine, and six with
footage, art and sound cut from the Godzilla films. Each folder holds the mode's `mode.json` exactly as the
Modes tab saves it. The cut files themselves (`clip.mp4`, `screen.png`, `end.wav`) are NOT here: nothing cut
from a film goes in the repo. `cuts.json` says where each came from (film, clip in/out, art frame, sound
in/out, in seconds) so they can be cut again from the same films.

| Mode | Starts on | Seconds | Scores | Award | Film | End request |
|---|---|---|---|---|---|---|
| ATOMIC BREATH | Godzilla target x2 | 25 | Building, both ramps | 750,000 | Godzilla (1954) | 1020 |
| DESTOROYAH | Right ramp x2 | 15 | both ramps, Godzilla and Maser targets | 3,000,000 | Godzilla vs. Destoroyah (1995) | 1197 |
| KAIJU RUSH | Maser target x3 | 30 | powerlines, both ramps | 1,000,000 | (title card) | 1295 |
| KING GHIDORAH | Left ramp x3 | 30 | the three powerlines | 1,250,000 | Ghidorah, the Three-Headed Monster (1964) | 1249 |
| MECHAGODZILLA | Building x3 | 20 | Powerline center, Maser and Godzilla targets | 1,500,000 | Godzilla vs. Mechagodzilla (1974) | 972 |
| MOTHRA'S SONG | shield targets x3 | 40 | shield targets, Big loop | 500,000 | Godzilla vs. Mothra (1964) | 1133 |
| SHIN GODZILLA | Powerline center x3 | 25 | both ramps, Building, Big loop | 2,000,000 | Shin Godzilla (2016) | 1174 |

Shot names are the Modes tab's (Godzilla Pro 1.15 profile); the Premium card build maps them to
godzilla_le 1.16's shot bits by name from `sdk/ports/godzilla_le-1.16.port`. The Pro profile names two
shield targets; on the Premium card MOTHRA'S SONG starts on, and scores, any of godzilla_le's three.

## Start shots and the game's own clips

A mode's clip plays the moment its start shot lands, and some shots play a clip of the game's own at that
moment, which takes the screen instead (emulator, item 143 runs 1-2): every Big loop shot plays the "LOOPS: N
CONSECUTIVE" clip, the Maser target plays a Maser cannon clip, and the left and right powerlines play
"POWERLINE DESTROYED". The left and right ramps, the Godzilla target, the Building and the centre powerline
showed the mode's own clip when they started it, and the three shield targets play no clip. So MOTHRA'S SONG
starts on the shield targets, not the Big loop. KAIJU RUSH keeps the Maser target, as on the machine card: its
title-card clip gives way to the Maser's own clip, and its screen shows when that ends. The game's own "BATTLE
IS LIT / SHOOT THE SCOOP" clip covered a mode's screen for a few seconds in the two ramp-started modes: 13 s into
KING GHIDORAH (run3) and just after DESTOROYAH ended, over its TOTAL words (run4). The ramps likely light the
battle; when that clip takes the screen is not pinned down.

## End sounds

A mode's end sound is a record appended to `image.bin` with one stock request's descriptors re-pointed at it
(item 130). The request must be one the game does not play itself. On Premium 1.16 the six film modes use
Japanese-language variants: `callout` (0x18bafc) swaps an English request for its Japanese twin through a
table of 147 (english, japanese) pairs at VA 0x648848, only while a flag is set. None of the six ids has a
movw load in the game code, and item 150's census found no constant call site for them (`armxref.py args`
on every entry point). Item 143's own census counted 1-4 u32 words equal to each id and movw loads of bases up to 32 below
it, not traced. The swap
is per player:
`0x3387f0` reads the current player, and what sets that player's flag is not traced (the strings "PLAYER
LANGUAGE SELECT" and "Japanese" point at a per-player language choice). Each id names a mono record no
other request names. The cost: a player with Japanese callouts would hear the film sounds in place of
those six lines. Item 150 found that the PLAYER LANGUAGE SELECT adjustment has a compiled default of Off on
Premium 1.16 and is the likely switch for that choice (the link to the flag is inferred, not traced): leave it
Off. KAIJU RUSH keeps 1295 (the game's own time-up call), as on the machine card.

## Building the card's p2

`mode_install.py install <card> --so mode.so --port godzilla_le-1.16.port --cfg mode.cfg --cfg mode1.cfg ...
--cfg mode6.cfg`: the first `--cfg` goes on the card as `mode.cfg`, the rest as `mode1.cfg` .. `mode6.cfg`
(item 149's form; the card was first built with an earlier `--more-cfg` flag that placed the same files).
The Premium card's `mode5.cfg` (MOTHRA'S SONG) was mapped by hand to godzilla_le's three shields: building
it again from the Pro-profile `mode.json` gives two shields, until the tab has a Premium profile.

The card was built with `godzilla_le-1.16.port` sha256 89cc0e92... and item 127's prebuilt `mode.so` sha256
8e5aac6c... . The family branch's port has since gained event lines, so a rebuild should use the branch's
current prebuilt object and port, and will not match this card's p2 byte for byte.
