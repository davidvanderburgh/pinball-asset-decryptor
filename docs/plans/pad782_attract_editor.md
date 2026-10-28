# PAD-782 - attract mode editor (Stern Spike 2)

David's own ticket (item 3 of the 2026-10-27 feature proposals): a page that lists what the game shows in attract
and lets the owner add items of their own (a photo slideshow from a folder, a clip, a text card, a mode's champions),
ordered between the game's own attract screens, each with its own dwell time, previewed in the emulator; the attract
flipper sounds (PAD-641) and the mode challenge champions in attract (PAD-660/663) move under the same page. Our
content yields to the game (PAD-353); a card with attract items gets the Insider Connected gate a card of modes gets.
Done = three photos and a text card ordered between the game's attract screens, Try it shows them with their dwell
times, a built card does the same; emulator-proven on Godzilla and a clip v2 title (James Bond).

## How a Spike 2 game runs its attract mode (emulator + program, 2026-10-27)

Census runs (rig, Godzilla LE 1.16 and Bond LE 1.06, `C:/tmp/PAD-782/rig/out`): the attract mode is a list of
PAGES - the last score, PRESS START, GRAND CHAMPION, HIGH SCORE #1-#4, one page per champion category, the
tutorial clips, THIS MACHINE IS SET TO, LEARN MORE, the licence and logo pages (Bond: the QR code, the gun barrel
intro, the challenge champions). A full-screen clip of ours played over it from the tick (pm_clip) is cut short by
the game's next page that puts a clip up (Godzilla: 3.3 s in, `BridgeDestructionProgress_1`).

Program (`portattract.py`): one process, the attract SEQUENCER, walks a TABLE of pages. Each entry is a test
(shown this time round? 0 = always) and a page function the sequencer starts as a child process and waits for; the
flipper buttons step back and on (the sequencer ends the page). Two generations:

| | Godzilla LE 1.16 (older) | James Bond LE 1.06 (newer) |
|---|---|---|
| sequencer | 0x2309c | 0x2ec018 |
| table | 0x70d858, 16-byte `{test, page, float seconds, flags}`, fixed count 91 (`cmp r4, #90`), all used | 0x7a6864, 8-byte `{test, page}`, ends at the first entry with no page (40) |
| page start | `ldr r3,[r5,#0xc]; mov r0,r3; mov r1,#0; bl 0x3f3140; cmp r0,#0; beq; str r8,[r0,#0xa0]` | `ldr r0,[r6,#4]; mov r1,#0; bl 0x2fc34c; cmp r0,#0; strne r7,[r0,#0xa0]` |
| process sleep (frames) | 0x3f3200 | 0x2fc42c |

## The route (proven)

Nothing is added to the table: ONE entry's page (and its test) is pointed at a page of ours (`ait_page_<k>`, at most
16 entries take items). The game's page runs as it was, then - in the same process, which the sequencer waits for -
each item after it plays while the process sleeps a frame at a time; items "before" an entry play first. The tick
puts the item's clip up full screen (`pm_clip`) and takes it down when its time is up or the page process stops
beating (a flipper ended the page, a game began). An entry whose own test says no this time (Godzilla's last-score
page before any game was played) still shows its items: its test is ours too, says yes, and the page runs the game's
own page only when the game's test did.

- Probe 2 (`attract_probe2.c`): an 8 s clip after Godzilla's GRAND CHAMPION page and after Bond's HMSS CHALLENGE
  champion page: shown full screen, the cycle held for it, then the game's next page (HIGH SCORE #1; the coin-door
  tutorial); two cycles; segv 0.
- Run 3 (the runtime, `attract.cfg`): Godzilla two items after entry 8 (6 s + 4 s, back to back), Bond one after
  entry 20 (6.15 s); segv 0 fatal 0. Items after an entry whose test said no were not shown -> the test wrap above.

Every item is a CLIP in the title's video bank: a video is made into the bank's format like a slot's replacement (the
random clips' / jukebox road, `clip_variants.stage`, the project's colour profile applied); a photo or a text card is
first made into a still clip of its dwell time.

## attract.cfg (beside the runtime: /usr/local/padmode, or /dump on a rig)

    item <entry> after|before <clip name> <ms>
    champions off            (the modes' challenge champions are not shown in attract)

## Port lines (portattract.lines, written into ports and derived ports)

    data  attract_table / value attract_entry_size / value attract_page_at / value attract_count / site attract_sleep

Finder coverage of the 53 newest builds (`C:/tmp/PAD-782/sweep_find.log`): 20 found - Aerosmith (both), Batman 66,
Godzilla LE/Pro (and the Heisei customs), Guardians (both), Bond LE/Pro, JP The Pin, Stranger Things (both), TMNT
LE/Pro, X-Men LE/Pro. 16 shipped ports carry the lines. The other 33 (Avengers, Beatles, Deadpool, D&D, Elvira, Foo
Fighters, Iron Maiden, Bond 60th, Jaws, John Wick, JP LE/Pro, King Kong, Led Zeppelin, Mando, Metallica, Munsters,
Rush, Star Wars x3, Sword of Rage, Venom) start their pages another way: the finder is to be widened.

## Status / what is left (in order)

1. [done] runtime `attract items` section (pad_mode_runtime.c), test wrap, champions off; portattract.py finder;
   16 shipped ports. Rig: C:/tmp/PAD-782/rig (job3.sh/run3.sh: rt.so = runtime + mode_file.c, attract_<key>.cfg).
2. [done, run 4: Godzilla before entry 0 (its last-score page, not shown before a game), Bond after entry 3; every cycle; segv 0] the test wrap. Left: a flipper/Start during an item (the clip comes down, the game takes over); the 1 testpick failure (test_spike2_savestate_edits load-credit timing) to be checked against main.
3. [done, run 2] The finder reads the table off the data (the page 4 bytes after the test; the stride 8/12/16 the
   one under which the longest run of entries hold code; the count the index's `cmp rI, #imm` + 1, else the run to
   the first entry with no page): 45 of the 53 newest builds (new: Deadpool 12-byte, Jaws/JP/KK/LZ/Avengers 16-byte,
   Mando, Metallica, Rush, Star Wars, Iron Maiden 12-byte, Foo Fighters, John Wick, Beatles, Munsters). 44 shipped
   ports carry the lines, recipes rebuilt; port_derive writes them on derived ports (portgen REVISION 9; the Heisei
   Godzilla derives them). Left out (refused up front by the app): D&D LE/Pro, Elvira, Bond 60th, SW ELG, Sword of
   Rage LE/Pro, Venom LE/Pro - their attract starts its pages from straight-line code (Sword of Rage 0x41138: `movw
   r0, #page; bl create` one after another), no table to put items into. tests/test_pad782_attract_items.py.
4. `attract_items.py` (plugin): the project record (staged key `attract_items`: items with kind photo/clip/text/
   champions, anchor entry + before/after, dwell), naming the game's pages for the page (entry -> what it shows:
   champion pages via the challenge page sites, clip names the page plays, message text), making each item a clip
   (stills via ffmpeg, text cards rendered with the game's font), attract.cfg; the engine's Write/Try it road beside
   the random clips, gated like modes (Insider Connected); mod packs and Transfer Mods carry the files.
5. The page: a new "Attract" tab (Make group): the game's pages in order with our items between them, drag to order,
   dwell per item, add photo folder / clip / text card, champions on/off, the attract flipper sounds moved here from
   the Audio tab; Try it. Help + Write log say the Insider gate.
6. Proof: Try it on Godzilla LE 1.16 and Bond LE 1.06 with three photos and a text card; a built card; before/after
   shots of the page and the attract cycle; prebuilt runtime rebuilt; tests.
