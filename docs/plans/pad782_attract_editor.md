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
4. [done, run 2] `attract_items.py`: the record (staged key `attract_items`: items photo/clip/text with entry,
   after/before, seconds; champions on/off), the game's pages named off the program (`read_pages`, `project_pages`
   cached in the title cache: champion pages, clip names, the page's own names - Godzilla: Game Title, Player Id,
   Credits Press Start, 32 champion pages...; Bond: the intro logo, the tutorials), every item made a clip of the
   bank's format (photos / text cards: a still clip of their time at the reference clip's size; videos converted as a
   slot's replacement; colour profile; never cut), `PadAttract<k>` in the bank, attract.cfg. mode_write.plan(attract=):
   alone (attract_plan) or on top of modes / random clips / music modes / picture settings; p2_payload stages
   attract.cfg; engine `_attract_for_build` (the gate, the Insider sentence in the Write log); tryit.sh and
   cardmodes.sh carry attract.cfg; the runtime takes its whole gate when attract.cfg asks anything, whatever the other
   .cfg files say ("only").
   PROVEN: engine.write_overrides of a project (C:/tmp/PAD-782/proj_gz: three photos + a text card after GRAND
   CHAMPION, a game clip before the first page) on stock Godzilla LE 1.16, run like Try it (rig job5.sh): GRAND
   CHAMPION, PHOTO 1, PHOTO 2, PHOTO 3, the text card, HIGH SCORE #1 - every cycle; the clip before PLAYER 1; Start
   during an item: the item comes down, the game starts; segv 0. Insider gate armed.
   OPEN (next run): on James Bond (clip v2) the items do not reach the glass in attract - the bank's VideoSurface is
   drawn only by the main-play screen, which is not up in attract (the frames show blue / the last page held). Find
   how to put the bank scene (or a scene of ours) on the glass from an attract page: the game's attract pages show
   their clips on surfaces of their own scenes (Bond 0xb54e7508 for the intro and tutorials) - candidates: show the
   bank scene from the page process the way a page shows its scene; or put our clips into the attract scene that page
   uses and run that page's own clip code with our name; or the display_draw route (the bank's player) during an item.
5. The page: a new "Attract" tab (Make group): the game's screens in order (runs of the same name folded) with our
   items between them, drag to order, seconds per item, add photos (several at once: a slideshow) / a clip / a text
   card, champions on/off, the attract flipper sounds moved here from the Audio tab; Try it. Help + Write log + the
   page say the Insider gate (attract_items.INSIDER_WORDS). Titles the app cannot add to say why (NO_TABLE: D&D,
   Elvira, Bond 60th, SW ELG, Sword of Rage, Venom).
6. Proof: Try it on Godzilla LE 1.16 (done at the engine level, run 5) and Bond LE 1.06 (after the clip v2 fix) from
   the app; a built card on the rig; before/after shots of the page and of the attract cycle; tests.

## Next run: clip v2 in attract (found 2026-10-27, Bond LE 1.06)

Bond's intro attract page (entry 15, 0x3677c) shows its clip through an ATTRACT VIDEO ELEMENT, not the bank:

    r4 = *(0x818c80)                       the element (its own VideoSurface: 0xb54e7508 in run 1's census)
    std::string(&s, "Attract_BondIntro_LogoOnly")
    0x1ce69c(r4, &s, 0, 1)                 play the clip by name (loop 0, show 1)
    while (0x1ce680(r4)) {                 still playing
        0x1ce788(r4); 0x1ce790(r4);        update, draw
        0x2fd144();                        the frame yield (= Bond's challenge_page_yield)
    }

The tutorials (entries 30-35, 0x37268...) use the same element. Plan: (1) a finder over the attract table's pages
for that shape (`data attract_video`, `site attract_video_play / _playing / _update / _draw`, `site attract_yield`)
and the scene whose library holds the clip that page names (CV.scene_of on the clip's card path); (2) attract_items
adds our clips to THAT scene's library on such titles (VB.add_clip, the scene rewritten); (3) the runtime's page plays
an item as the game's page does - play, then update/draw/yield until its time is up or the clip ends - instead of
pm_clip + sleep. Godzilla keeps the pm_clip route (proven). Then prove Bond LE with job5.sh and sweep which builds take
which route.

## Run 3 (2026-10-27)

Done and committed: the clip v2 ELEMENT route (portattract.element / element_lines, Bond LE/Pro; items in the element's
own scene; the runtime plays them as the game's pages do) - Bond LE emulator-proven (3 photos + text card after the last
challenge champion, Start yields). The Attract page (webui/tabs/attract.py, static/js/tabs/attract.js): screens in order
(named off the program, runs folded, "at times"), Add after/before, seconds, arrows + drag, take off, Run in emulator,
the Insider note; flipper sounds moved here from the Audio page; champions switch only with the mode-maker preview on
(concealment). A card whose clip scene the app cannot add to says so up front (attract_items.project_refusal:
Batman 66, Iron Maiden, Metallica, Munsters, Rush, Stranger Things Pro). Mod packs (.modpack_attract, "Attract files")
and Move Your Mods carry the items. Before/after shots in work/artifacts/PAD-782.

### Library sweep (C:/tmp/PAD-782/sweep: sweep_prep.py, job.sh; one magenta marker item before screen 2, the shot
taken on the item's SECOND showing - the game restarts its attract once soon after it first comes up)

- The item RUNS (the cycle holds for it, segv 0) on every build tried; on the glass (magenta measured) only on Godzilla
  LE/Pro (clip_play route), James Bond LE/Pro (element route), Foo Fighters LE and one more. On the other clip v2 titles
  (Aerosmith, Avengers, Beatles, Deadpool, Guardians, Jaws, John Wick, JP x3, King Kong, Mando, Star Wars, TMNT,
  X-Men...) the glass holds the previous screen: the clip plays on the bank's surface, which nothing draws in attract.
- Mando LE/Pro, TMNT LE/Pro, Stranger Things LE, Foo Fighters Pro: no second showing within the job's wait (their cycle
  is long, or the first showing was the only one before the cap) - re-run with a longer wait.

### NEXT RUN

1. Find, per family, how the attract pages of those titles put a clip on the glass (their tutorial / logo pages, as
   Bond's element was found: disassemble a page that names a clip of theirs, e.g. Aerosmith 1.16, Deadpool 1.16, Jaws
   1.02, Star Wars 1.31), and generalise portattract.element (or add a route) so each family plays items its own way.
   Re-run the sweep (job.sh) until the marker is on the glass on every build the page offers; titles that cannot be
   done get a refusal sentence (like NO_BANK) so the page never offers what the card cannot show.
2. Boot the real card (D:/tmp/PAD-782/gz_attract.raw, engine.write_image of proj_gz) on the rig through cardmodes.sh
   (PAD_CARD_MODES=1) and picture the items - "a built card does the same".
3. Merge main (moved to v1.274.0); rebuild prebuilt + recipes if the SDK changed; targeted tests; final shots.

### Run 3, after the report: the BUILT card (Godzilla LE 1.16)

engine.write_image of proj_gz (C:/tmp/PAD-782/card782.py -> D:/tmp/PAD-782/gz_attract.raw) first carried NO runtime:
mode_install.py only took stock/clips/sounds/picture.cfg ("attract.cfg is not a file the mode runtime reads"). Fixed
(EXTRA_FILES / STANDALONE_FILES), and the card log now speaks of "Attract items" (engine._install_modes). Booted on the
rig with its own runtime (PAD_CARD_MODES=1, rig/jobcard.sh): Insider gate armed, all five items played at their times
every cycle, PHOTO 1, 2, 3 on the glass, segv 0 fatal 0. Item 2 of NEXT RUN is done.

## Run 4 (2026-10-28): the scene show, and the library proven

- Aerosmith 1.16's own clip page (OilProjectorLoop 0x286a4) shows the video bank's scene itself every frame:
  player_advance(player, ms); scene_show(player, 3); the frame yield. An item's page now does the same while its clip
  plays on the bank's surface (runtime ait_show; `site attract_show`, portattract.scene_show: masked signature, agrees
  with all 29 ports that name scene_show; 44 ports + recipes).
- Sweep round 2 (C:/tmp/PAD-782/sweep/job2.sh: shots during up to three showings of the marker, because the game
  restarts its attract soon after it first comes up and a cut showing proves nothing): the marker is ON THE GLASS on
  31 builds - Aerosmith x2, Beatles, Foo Fighters x2, Godzilla x2, Guardians x2, James Bond x2 (element), Jaws x2,
  John Wick x2, JP The Pin, King Kong x2, Led Zeppelin x2, Mando x2, Star Wars x2, Stranger Things LE, TMNT x2, X-Men x2.
- Off: Avengers LE/Pro and JP LE/Pro (their attract clip pages play on scene 4a3b5738..., which has no Video library;
  clips added to the bank are not found on that surface - tried and dropped), Deadpool LE/Pro (video layer). Refused up
  front (attract_items.NOT_ON_GLASS, the layer route). Batman 66, Iron Maiden, Metallica, Munsters, Rush, Stranger
  Things Pro: the card's bank cannot be added to (refused when the page reads the card). Older shipped ports (e.g.
  aerosmith_le-1.15, godzilla_pro-1.15) carry no attract lines: their programs are in the archival folder; a user's
  older card gets the lines through port_derive.
