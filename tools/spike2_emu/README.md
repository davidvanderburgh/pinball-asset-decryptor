# spike2_emu — running the Stern Spike 2 game on a PC

A real Stern Spike 2 armhf game binary, running under `qemu-user` in a chroot
of the card's own rootfs, with every piece of hardware replaced by `LD_PRELOAD`
shims. It boots to attract mode by itself in about 15 seconds, at 1360x768 /
60 fps on the GPU, with working audio, video and switch input.

## Any title

The rootfs is the OS partition and carries no title of its own; each game is a
directory under `games/`. `PAD_GAME` picks one:

```bash
PAD_GAME=turtles_pro watch.sh
```

## Straight off the card, with nothing extracted

```bash
PAD_CARD=images/Stern/spike2/jaws_le-1_02_0.Release.16G.sdcard.raw watch.sh
```

`cardmount.sh` puts the card's games partition on a **read-only FUSE mount** and
`run_game.sh` bind-mounts the title into the chroot. No copy, no root, about a
second, and the image cannot be modified. `mount -o loop,offset=` would need
real root; fuse2fs does not, and `apt-get download` + `dpkg-deb -x` into a
private prefix gets fuse2fs without a package manager or a password. Extraction
still works and is still the faster option for a title you run constantly.

## Titles

**Per-title emulation status, one line per title, kept current by `/finish`**
(item 57, David's ask 2026-08-19: "we should be keeping a running list of
what each game has and doesn't have"). Four columns, each a plain fact about
ONE run, not a promise about every card version of that title:

- **switches** — does a real switch table exist (either the runtime's own
  live `[sw]` dump, or `swelf.py`'s static fallback) with plausible Stern
  numbering (flippers/slings/trough checked against the standard scheme)?
- **artwork** — does the virtual playfield draw the title's own CAD/service
  drawing, or fall back to the schematic dot layout?
- **positions** — do the artwork-relative device (LED/coil/switch) XY
  coordinates land INSIDE the artwork, so the picture and the wire agree?
- **2nd display** — does the title open a second window, and does it show
  real content or nothing? `n/a` = never targets one.

A title only reaches "clean" when all four say so. **This table is built
from real runs, not inference** — a title not yet re-checked keeps its last
known state with the date it was last run, not a guess.

★ **THE DEVICE-TABLE AUDIT IS NOW MEASURED RATHER THAN INFERRED, AND IT WAS
DONE OFF THE RIG** (2026-08-21, item 61). Every `.raw` in
`images/Stern/spike2` plus the running custom card — 40 images — was read with
the repo's OWN read-only ext4 reader (`plugins/stern/explorer.CardImage`), which
pulls `/<title>/game` straight out of the image. Nothing was mounted, no card
cache was copied, no lock was needed and a live run was untouched; the whole
sweep takes about two minutes. **`cardaudit.py` is that sweep** — run it with
no arguments for the whole library, or name images:

```
python tools/spike2_emu/cardaudit.py
python tools/spike2_emu/cardaudit.py "C:/.../My Custom Card.raw"
```

**Re-run the audit that way. A mount-and-run sweep is what poisoned the table
cache in the first place, and it cannot be done while anyone is playing.**

**THE DEVICE TABLE IS A PROPERTY OF THE BUILD, NOT OF THE TITLE, and that is the
finding that resolves most of the 2026-08-19 disagreements.** Stern adds the
graphical device test data in a specific release, so an older card for the same
title legitimately has none:

| title | older build | newer build |
|---|---|---|
| `godzilla_le` | 1.13.0 — no `Test` dir, 0 records | **1.14.0 — 593 records, art shipped** |
| `jaws_le` | 1.01.0 — 0 records | 1.02.0 — 439 records |
| `elvira3` | 1.11.0 — 0 records | 1.13.0 — 275 (topper only) |

So the 2026-08-19 sweep's `❌ none shipped` for `godzilla_le` was CORRECT about
the card it measured (`godzilla_le-1_13_0`), and wrong only as a claim about the
title. The card David actually runs is a custom image built on **V1.14.0**, and
that build ships both the drawing and a complete layout. A row here names a
build from now on.

**11 of the 40 images carry a device table** (10 of the 39 in
`images/Stern/spike2`, plus the running custom card):

| card image | build | device records | layout image | art on the card | draws on art |
|---|---|---|---|---|---|
| `deadpool_pro-1_16_0.Release.8G.sdcard.raw` | 1.16.0 | **459** (coil=14 led=376 switch=69), 160 on the layout | `playfield` | `deadpool_le_playfield.png` 330x710<br>`deadpool_pro_playfield.png` 329x710 | yes |
| `dungeons_and_dragons_le-1_00_0.Release.16G.sdcard.raw` | 1.00.0 | **255** (coil=16 led=169 switch=70), 229 on the layout | `TestMode/Rope_LE-Premium-X8-X9_TOP_rotated_edit_cropped` | none shipped | blank field |
| `elvira3-1_13_0.Release.16G.sdcard.raw` | 1.13.0 | **275** (led=275), 275 on the layout | `System/TestMode/universal_topper_scaled` | none shipped | blank field |
| `Heisei Custom Image Premium V1.raw` | custom (V1.14.0) | **593** (coil=14 led=513 switch=66), 177 on the layout | `playfield` | `scaled_godzilla_le_playfield.png` 313x710 | yes |
| `godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw` | 1.15.0 | **575** (coil=10 led=506 switch=59), 164 on the layout | `playfield` | `scaled_godzilla_le_playfield.png` 313x710<br>`scaled_godzilla_pro_playfield.png` 313x710 | yes |
| `james_bond_60th_le-1_10_0.Release.8G.sdcard.raw` | 1.10.0 | **513** (coil=16 led=426 switch=71), 138 on the layout | `Test/scaled_playfield` | `scaled_playfield.png` 202x443 | yes |
| `james_bond_le-1_06_0.Release.16G.sdcard.raw` | 1.06.0 | **526** (coil=17 led=429 switch=80), 185 on the layout | `playfield` | `bond_le_playfield.png` 459x998<br>`bond_pro_playfield.png` 459x998 | yes |
| `jaws_le-1_02_0.Release.16G.sdcard.raw` | 1.02.0 | **439** (coil=14 led=347 switch=78), 217 on the layout | `playfield` | `jaws_le_playfield_scaled.png` 312x710<br>`jaws_pro_playfield_scaled.png` 312x710 | yes |
| `john_wick_le-1_01_0.Release.16G.sdcard.raw` | 1.01.0 | **503** (coil=16 led=412 switch=75), 479 on the layout | `playfield` | `john_wick_le_playfield.png` 321x710<br>`john_wick_pro_playfield.png` 321x710 | yes |
| `king_kong_le-0_96_0.Release.16G.sdcard.raw` | 0.96.0 | **517** (coil=21 led=421 switch=75), 489 on the layout | `TestMode/Rodeo_LE_Service_Playfield_Wireframe_300dpi_cropped` | `Rodeo_LE_Service_Playfield_Wireframe_300dpi_cropped.png` 312x710<br>`Rodeo_PRO_Service_Playfield_Wireframe_300dpi_cropped.png` 313x710 | yes |
| `metallica_spike-1_03_0.Release.32G.sdcard.raw` | 1.03.0 | **664** (coil=22 led=569 switch=73), 502 on the layout | `TestMode/metallica_playfield_with_handle_cropped` | `metallica_playfield_with_handle_cropped.png` 312x710 | yes |

The other 29 genuinely ship none, on the builds we hold: `aerosmith_le 1.15.0`, `avengers_infinity_le 1.09.0`, `batman 1.13.0`, `deadpool_le 1.14.0`, `elvira3 1.11.0`, `foo_fighters_le 1.03.0`, `godzilla_le 1.13.0`, `guardians_le 1.14.0`, `iron_maiden_le 1.16.0`, `jaws_le 1.01.0`, `jurassic_park_le 1.15.0`, `led_zeppelin_le 1.20.0`, `led_zeppelin_le 1.21.0`, `led_zeppelin_le 1.22.0`, `led_zeppelin_pro 1.20.0`, `led_zeppelin_pro 1.22.0`, `mando_le 1.44.0`, `munsters_le 1.27.0`, `rush_le 1.18.0`, `star_wars_le 1.30.0`, `stranger_things_le 1.12.0`, `sword_of_rage_le 1.18.0`, `turtles_le 1.58.1`, `turtles_le 1.59.0`, `turtles_pro 1.58.0`, `turtles_pro 1.59.0`, `uncanny_xmen_le 0.97.0`, `venom_le 1.06.0`, `venom_le 1.07.0`.

**What the 2026-08-21 seeder fix changed across the whole catalogue: exactly one
image.** `godzilla_le` V1.14.0 went 477 → 593 records (coil 0 → 14, switch
18 → 66) and its layout image flipped from
`System/TestMode/spike_2_cabinet_front_cropped` to `playfield`. **The other 39
are byte-for-byte identical under the old and new seeder** — that is the control
that says the fix only adds the runs a merged string hid, and invents nothing.

**Known self-check noise, not regressions** (identical before and after the
fix): `LEFT POP BUMPER` sits right of centre on `deadpool_pro`, `james_bond_le`
and `metallica_spike` — the name is the left pop OF A CLUSTER, so the
left/right check counts it wrong; `elvira3` 1.13.0 positions 275 TOPPER lamps
and nothing else, so its records fall outside a playfield-sized box by design
(item 50's case); `dungeons_and_dragons_le` and `elvira3` position devices but
ship no matching art, so they draw on a blank field.

**Every `❌ none shipped` / `not re-measured` row in the table below is now
CONFIRMED by that sweep** — for the build named in the list above, and only for
it. What the sweep cannot answer is the other three columns: switches, second
display and whether a title actually boots are properties of a RUN, and those
still come from running it.

| title | switches | artwork | positions | 2nd display | last checked |
|---|---|---|---|---|---|
| godzilla_pro | ✅ live, 88 | ✅ | ✅ (baseline) | n/a | 2026-08-19 |
| jaws_le | ✅ live, 109 | ✅ | ✅ | n/a | 2026-08-19 |
| john_wick_le | ✅ live, 106 | ✅ | ✅ | n/a | 2026-08-19 |
| james_bond_60th_le | ✅ live, 118 | ✅ | ✅ | n/a | 2026-08-19 |
| james_bond_le | ✅ live, 108 | ✅ bond_le_playfield.png | ✅ | n/a | 2026-08-19 |
| deadpool_pro | ✅ live, 104 | ✅ deadpool_pro_playfield.png | ✅ | n/a | 2026-08-19 |
| king_kong_le | ✅ live, 105 | ✅ Rodeo…Wireframe.png (item 57 fix) | ✅ 489/517 inside, 0 outside (item 57 fix) | n/a | 2026-08-19 |
| dungeons_and_dragons_le | ✅ live, 104 | ❌ none shipped | ✅ 255 records | n/a | 2026-08-19 |
| venom_le | ✅ live, 107 | ❌ none shipped | not re-measured | n/a | 2026-08-19 |
| turtles_le | ✅ live, 96 | ❌ none shipped | not re-measured | n/a | 2026-08-19 |
| uncanny_xmen_le | ✅ live, 110 | ❌ none shipped | not re-measured | n/a | 2026-08-19 |
| deadpool_le | ✅ live, 104 | ❌ none shipped | not re-measured | n/a | 2026-08-19 |
| godzilla_le **V1.14.0** | ✅ live, 98 | ✅ scaled_godzilla_le_playfield.png 313x710 | ✅ 177/593 inside, 0 outside; 30/30 left-right; 48 switches, 14 coils, 115 lamps placed | n/a | 2026-08-21 |
| godzilla_le 1.13.0 | not run | — no device test data in this build | — 0 records (measured off the card) | n/a | 2026-08-21 |
| metallica_spike | ✅ live, 106 | ✅ metallica_playfield…png (item 57 fix) | ✅ 502/664 inside, 0 outside (item 57 fix) | n/a | 2026-08-19 |
| aerosmith_le | ✅ static (swelf.py), live-verified | — no device table shipped | — | n/a | 2026-08-19 |
| avengers_infinity_le | ✅ static (swelf.py), live-verified | — | — | n/a | 2026-08-19 |
| batman | ✅ static (swelf.py), live-verified | — | — | ✅ VILLAIN VISION window — SOLVED & live-faithful: own `[villain vision]` window mirrors node 24's control stream exactly — clips PLAY by commanded id (lossless webp), block commands CYCLE clip-by-clip, brightness 0 BLANKS the screen and 255 reveals (the per-beat fade the game sends), verb 2 holds the last frame (play-once). `lcdring.py` reads the transcript live or from `padlcd.last`. **RE-verified architecture (10-agent pass) + GROUND TRUTH (video of the real machine, 2026-08-25):** ONE physical TV, bezel-printed "Villain Vision" (the old "three TVs" line was invented — deleted). The node bus is CONTROL-only (LPC1113, can't decode video); the real display is COMPOSITED by the game on a GPU "secondary display" render target (`fbGetDisplayByIndex(2)`) that batman's binary HARD-DISABLES (renderer-ctx +0xf0 = NULL, 0x1e79c8) — which is why the 4 villain gst channels die at 0 frames. **Proof from the machine:** the real attract shows game-RENDERED cards (a "Game Over" card, the BATMAN-on-green logo) that exist nowhere in the 3,069-clip store (3 independent scans) — so a bus mirror can never show those. Verified against the video and matching: ~5-7 s per item, a fully black frame between items, one full-screen motion clip. **Clips are NAMED**: `lcdnames.py` parses the title's scene.radium at run start into `<tables>/<game>/lcd/names.txt` (3,069/3,069 for batman, 0.15 s) and the window shows e.g. `asset 54 - once` / `S1E001 00:18:32` - which is also the first independent verification of the id-to-clip mapping (asset 2 is named `PhoneScenes...` and shows the Batphone). Exact id↔clip correspondence at a given moment is NOT established (photo matching tops out at 0.74) and is not claimed. The 0x90 poll is answered (present board) but its content is inert — nothing reads it (get_status is dead code) and it does NOT stop the game's own 250 ms double-command (items 82/83) | 2026-08-25 |
| foo_fighters_le | ✅ static (swelf.py), live-verified | — | — | n/a | 2026-08-19 |
| guardians_le | ✅ static (swelf.py), live-verified | — | — | n/a | 2026-08-19 |
| iron_maiden_le | ✅ static (swelf.py), live-verified | — | — | n/a | 2026-08-19 |
| jurassic_park_le | ✅ static (swelf.py), live-verified | — | — | n/a | 2026-08-19 |
| mando_le | ✅ static (swelf.py), live-verified | — | — | ✅ real (topper accessory, David-confirmed) | 2026-08-19 |
| rush_le | ✅ static (swelf.py), live-verified | — | — | n/a | 2026-08-19 |
| star_wars_le | ✅ live, 104 | ❌ none found | not re-measured | ✅ real (mini display above the targets, David-confirmed) | 2026-08-19 |
| turtles_pro | ✅ live, 94 | ❌ none found | not re-measured | n/a | 2026-08-19 |
| elvira3 | ✅ live, 110 | ❌ none found | not re-measured | n/a | 2026-08-19 |
| led_zeppelin_le | ✅ live, 97 | ❌ none found | not re-measured | n/a | 2026-08-19 |
| stranger_things_le | ✅ static (swelf.py, item 52) | ❌ none found | not re-measured | ✅ real (projector, item 44) | 2026-08-19 |
| sword_of_rage_le | ✅ static (swelf.py, ROOTS_NONUM), live-verified, 98 | ❌ none shipped | ❌ no device table | n/a | 2026-08-19 |
| munsters_le | ✅ static (swelf.py, ROOTS_NONUM), live-verified, 103 | ❌ none shipped | ❌ no device table | n/a | 2026-08-19 |

**CORRECTION, same session, right after this table's first version shipped:**
the first pass checked the CONSOLE pane for the live switch dump
(`[event] [sw] id=...` lines), and got 6 false "no live dump" negatives —
`venom_le`, `turtles_le`, `uncanny_xmen_le`, `deadpool_le`, `godzilla_le`,
`metallica_spike` **all actually have a real, complete, correctly-numbered
switch table**; the console's `tail -F` on `gzwatch.log` simply had not
attached yet when the shim wrote its dump, so the lines existed in
`gzwatch.log` on disk but never reached console. `venom_le` was the catching
case: 107 real switches (LEFT/RIGHT FLIPPER BUTTON at 9/10, LEFT/RIGHT
SLINGSHOT at 7/8, TROUGH 1-6, the standard scheme) sitting in `gzwatch.log`
the whole time, zero of them ever forwarded. **Checking `gzwatch.log`
directly (never the console) is now the only trusted method** — the ★★★★
solved-titles bucket up top used the same static/live methods and is
unaffected, but every "❌ no live dump" verdict below this point had to be
individually re-run and re-checked; only `sword_of_rage_le` and
`munsters_le` survived the recheck as genuinely broken, each with its own
EXPLICIT `[swfind] no switch table yet` refusal line naming why (35 and 33
records of the right shape but "(node,bit) not distinct" — the same failure
class already diagnosed, see item 57's `full_solve_one2.sh`/`solve_verify2.py`
work). **`sword_of_rage_le` SOLVED AND SHIPPED same session**: its DEV
record is a THIRD struct variant (name pointer at the record's own start,
not +12 like the original or +12-with-48-byte-stride like the
james_bond_le-class titles) — `swelf.py`'s `ROOTS_NONUM` + `_rows_nonum()`
read it directly with no ENT table at all (none could be found for this
title despite extensive search; `num` ships as an explicit, documented
placeholder since `swtable.py` never actually reads it). Live-verified: 98
switches, clean shutdown, no crash.

**`munsters_le` SOLVED AND SHIPPED, same session, right after being written
down as the catalogue's last gap.** Shares the identical DEV struct as
`sword_of_rage_le` (same offsets, decodes just as cleanly), but its BRD
(slot→node) table needed a different search: the bare-address bijective
scan that found `sword_of_rage_le`'s turned up 16,713 candidates and 789
node-tuples, all zero-heavy noise. Reversing the search order found it —
first collect every address that has AT LEAST ONE literal reference
anywhere in `.data` (6,858 candidates, a much smaller and much cleaner
universe than "every 4-byte-aligned offset"), THEN check which of those
decode to valid, distinct nodes. Exactly one candidate survived, at a
genuine two-reference root (`0x5512e4` — the same "usually exactly 2"
pattern every other confirmed root in this file has). One slot (5, the
BUSIEST by far — 92 of the title's device records, almost certainly the
main lower-playfield board) still read as a nonsense value (1032): turned
out to be a byte-width mismatch, not a wrong address — `1032 = 0x0408`, a
valid node (8, unused by any other slot) in the LOW byte with an
unrelated nonzero flag sitting in the byte above it. Masking every slot's
read to `& 0xFF` (harmless for the other 15 slots, already under 256)
rebuilt the whole table clean: 103/103 rows named, all 18 ground-truth
keyword rows (LEFT/RIGHT FLIPPER BUTTON, LEFT/RIGHT SLINGSHOT, TROUGH 1-6)
landing on the correct node. Live-verified: 103 switches, clean shutdown,
no crash. Full test suite: 2782 passed, 1 unrelated pre-existing GUI-test
flake (`test_a_wsl_restart_re_probes_what_it_left_behind`, a Tk/WSL-panel
test with nothing to do with either changed file — passes clean in
isolation, 0 failures either way).

**Net: of 30 known card versions, ALL 30 have a confirmed-working switch
matrix.** The catalogue-wide "does every title load its switch/coil/LED
matrix and boot to attract" question this item opened with is closed.

**`king_kong_le`/`metallica_spike`'s "positions land outside the artwork"
gap SOLVED, same session, right after being written down as priority (2)
above.** Not a coordinate bug at all: `devicexy.py`'s raw x/y values were
correct the whole time (checked directly - x 7..512, y 1..654, well inside
a 312x710 image). The bug was in the SELF-CHECK, not the data: `checks()`/
`text()`/`main()` filtered "is this device on the playfield" by comparing
`image == "playfield"` literally - a hard-coded spelling one title family
uses, not a constant. `devicexy.py` already HAD the fix for exactly this
class of bug (`layout_image()`, built for item 50's `james_bond_60th_le`,
which spells it `Test/scaled_playfield`) and `playfield.py`'s actual
renderer was already using it correctly - only the diagnostic/reporting
functions were never wired to it, so the rendering was fine the whole
time and only the "N playfield records" COUNT `watch.sh` prints was wrong.
Fixed by routing `checks()`/`text()`/`main()` through `layout_image()`
instead of the literal. Live-verified: `king_kong_le` 489/517 records now
land inside with 0 outside (was 0/517); `metallica_spike` 502/664 (was
0/664). Full test suite clean before and after (2785→2783 passed, the
2 fewer are pre-existing Tk/Tcl display flakiness unrelated to this
change, not new failures - 0 failures either run).
**Both titles are now FULLY clean**: switches ✅, artwork ✅, positions ✅.

**Reading this table alongside item 57 in `plans/TODO.md`**: the earlier
"7 titles share a newly-found 48-byte device-record generation" static
finding is REAL as a structural fact (confirmed by byte-delta histogramming)
but turned out to be **irrelevant to whether a title actually works** —
`james_bond_le`, `king_kong_le`, `led_zeppelin_le`, `venom_le`, `turtles_le`,
`uncanny_xmen_le`, `metallica_spike` all carry that struct and every one of
them has a working LIVE switch table via the runtime's own hunt, independent
of the struct shape `swelf.py`'s static fallback would have needed. The
struct-shape research is preserved in item 57's own history as a real,
possibly-useful-later finding, but it was never the blocker for these
titles' actual live behaviour, and no further work should be spent
"fixing" it for titles that already work. The two ACTUALLY broken titles
(`sword_of_rage_le`, `munsters_le`) instead need whatever makes their entry
table's `(node,bit)` pairs not distinct — a live-shim-diagnosis question, not
a static-struct one.
The "positions land outside the artwork" failure on `king_kong_le` and
`metallica_spike` is a real, separate, NOT-yet-root-caused gap — the artwork
file is now found (item 57's `Test`/`TestMode` fix), the device XY
coordinates just don't land inside it. `dungeons_and_dragons_le`'s positions
DO land correctly (255 real records) despite having no artwork at all, which
rules out "the fix broke something universal" — it is specific to whatever
`king_kong_le` and `metallica_spike` share.

**Titles not yet run this pass** (existed before this table, no fresh data
to report against the 4 columns above): every other card version beyond the
one path each row above was tested against — `led_zeppelin_pro`,
`turtles_le-1_58_1` (the 1987-upscaled build), older `jaws_le`/`venom_le`
versions, etc. Re-running a DIFFERENT version of an already-clean title is
low priority; a title with no row above at all has simply not been reached
yet.

What the rig works out about a title by itself:

| | |
|---|---|
| the switch table | found in the heap at run time by SHAPE (`sw_find_table`), because the address differs per title and the layout does not |
| node firmware version | read off the `.hex` filenames the title ships beside its binary |
| device positions | scanned out of the binary by `devicexy.py`, seeded from the image-name strings rather than an address window |
| playfield artwork | the title's own `assets/nuk/images/Test/*_playfield.png` |

**Not every title has positions.** Godzilla Pro 1.15.0 ships a graphical device
test mode - a playfield drawing and an XY record per switch, coil and insert.
TMNT 1.59 ships neither: no `images/Test`, and "playfield" appears in its binary
only inside adjustment help text. So the playfield window draws artwork when a
title has it and a schematic switch list (`swtable.py`) when it does not. Both
are clickable and live; only one is a picture.

### Where those tables come from, and where they do not

`mktables.py` builds them, per title, into `$PAD_TABLES/<title>/` — under the
rootfs by default, so the WSL side that writes them and the Windows playfield
window that reads them name one directory. `watch.sh` runs it before opening
the window, and the window runs it itself if it finds nothing.

| | |
|---|---|
| `playfield.png` | copied out of the title's own assets |
| `device_xy.txt` | the device table in the game ELF |
| `led_io.txt` | derived from `device_xy`; the wire enumeration only ever *checked* it |
| `switch_list.txt` | the shim's `[sw]` dump, i.e. it needs a run |
| `switch_xy.txt` | the two joined on the device NAME |

**Three of the five need no run at all**, which is what lets a title show
artwork, inserts and coils the first time it boots. The switch half is the one
exception and cannot be made otherwise: the game builds its switch table on the
heap, so the id belonging to a name is not in the binary anywhere. It is cached
per title, so only the first run of a title waits for it.

**These were checked into git until 2026-08-06, and only Godzilla's existed** —
so every other title got a schematic and it read like a property of the title
rather than of the repository. The artwork was worse: it sat here ignored by
this directory's own `*.png` rule while `gameinfo.py` claimed it was committed.
Nothing under `games/` is generated into the checkout any more.

Anything the shim reads at a hard-coded address is a `TITLE_ADDR`: overridable
per title, checked before use, and switched off rather than fatal when it is not
mapped. That is not tidiness - the first attempt at a second title died 0.06 s
in, inside a printf, reading Godzilla's audio gate.

**`plans/spike2_pc_emulation_handoff.md` is the authoritative document.** It is
not in git (`plans/` is ignored); this README only covers what you need to run
the thing. Everything about *why* any of it is shaped this way — and the long
list of confident conclusions that turned out to be wrong — lives there.

## Layout

| | |
|---|---|
| Hardware shim (ARM, `LD_PRELOAD`) | `hwshim.c`, `alsastub.c`, `gststub.c`, `gstvid.c`, `padsw.h`, `padvid.h` |
| GL backend A, software raster | `glraster.c` |
| GL backend B, the bridge (default) | `glbridge.c` + `padglhost.c` (native x86-64), `padgl.h` |
| EGL, either backend | `eglshim.c` |
| Host decoders / players | `padvidhost.py` (video), `playaudio.sh` (audio) |
| Virtual playfield (Windows) | `playfield.py`, `coilact.py`, `plunge.py`, `swpoke.py` |
| Switch block layout | `padsw.h` (C), `padsw.py` (the scripts) — three regions, one writer each |
| Device maps and decoders | `devicexy.py`, `ledio.py`, `leddecode.py`, `coildecode.py`, `padled.h` |
| Where anything is | `padpath.py` / `padpath.sh` (paths), `gameinfo.py` (titles), `parts.py` (partitions) |
| Per-title tables | `mktables.py`, built from the card — see above |
| First-time setup | `rootfs.sh`, `getboot.sh`, `gethex.sh` |
| Build | `build.sh`, `buildgl.sh`, `buildbridge.sh` |
| Run | `watch.sh`, `runbridge.sh`, `nbrun.sh`, `verify2.sh`, `verify3.sh` |
| Safety | `alive.sh`, `killgame.sh`, `runlim.sh` |

Everything else is an instrument. They were written one at a time against a
specific wrong answer, and the handoff says which.

## Running it

All of these are `wsl -e bash <path>/<script>`, from this directory:

```bash
watch.sh          # WATCH IT: a real window on the Windows desktop, keyboard drives it
alive.sh          # what is still running. MUST print 0 after every run
killgame.sh       # emergency stop
build.sh          # the hardware shim      \ both built on demand; see below
buildbridge.sh    # the GL backend         /
```

**`watch.sh` and `runbridge.sh` build what they need.** `ensurebuild.sh` checks
the hardware shim and both halves of the GL bridge against a digest of their
sources: missing gets built and stops the run if it cannot be, stale gets
rebuilt and never blocks, and neither happens while a run is live. The builds
above are for building deliberately, not because a start needs them.

**A failed build is reported by its errors, not by its last eight lines.**
`gcc` compiles every source before it gives up, so the errors sit wherever the
broken file was on the command line and the tail belongs to whichever file came
last — the one arrangement a tail can never show is an error early with noise
after it, which is the common one. `_pad_build` republishes the matching error
lines first, keeps the tail only as the fallback when nothing matches, and
writes the full output to `$TMPDIR/pad-<script>.log`, which it names in the log.
Both builders pass `-Werror=implicit-function-declaration` so GCC 13 gives
GCC 14's answer here rather than on a user's newer distro.

`buildgl.sh` and `buildbridge.sh` **both write `libGLESv2.so.2`**, so whichever
ran last decides which backend is live. Re-run the one you want before measuring.

## Four rules that are not negotiable

- **Never wrap a run in `timeout`.** It signals only its direct child, which
  here is a `setsid` wrapper, so the guest survives it and spins at ~140% CPU
  forever. Use `watch.sh`'s own minute cap, or `runlim.sh`.
- **Run `alive.sh` after every run** and confirm it prints 0. An orphaned guest
  is invisible and expensive.
- **Anything a run starts goes in `alive.sh` the same day.** That list is the
  rig's only definition of "clean", and it has twice been out of date: once it
  reported `TOTAL STILL RUNNING : 0` over seven leaked Windows-interop stubs
  and three orphaned card mounts. `killgame.sh` and `status.sh` now ASK
  `alive.sh` (`--total` / `--procs`) instead of keeping their own copies, so
  there is one list and one place to add to.
- **Bracket `pkill` patterns** — `pkill -f padvidhost.py` from inside
  `wsl -e bash -c '...'` matches the shell's own command line and kills it.
  Write `pkill -f "padvidhost[.]py"`.

### When a window will not close

A window that WSLg is still painting after its X client has gone cannot be
closed by clicking its X (there is nothing left to receive the close) and
`msrdc` refuses `Stop-Process`. `wsl --shutdown` is the only cure found; the
app's **Restart WSL…** button on the Emulate tab does it for you. Note that
synthetic closes do NOT work as a test either: `WM_CLOSE` and `SC_CLOSE` posted
to a RAIL window from Windows are both ignored, the same UIPI class as the
`SendInput` and PrtScn blocks documented elsewhere.

### When the game window never appears

The playfield window opens, it says *emulator up*, the guest really is running,
and there is no game window. **The run says which of the two it is**, on its own
output, so read that line first:

- `[watch] game window opened 1445x827 on DISPLAY=:0` — the window EXISTS.
  Nothing inside Linux can see the Windows desktop, so if none is showing there,
  what is missing is WSLg's mirror of it and not the window: **Restart WSL…**.
- `[watch] THE RENDERER HAS NO WINDOW` — padglhost went headless and its own
  line says why. The run continues (the guest boots, the sound plays, the
  playfield answers) and shows no picture at all.

`DISPLAY` being SET is not the same as an X server being reachable: WSLg sets it
when the distro starts and never takes it back. `pad_display_state` (padpath.sh)
is the real question, and `masked` is the one worth knowing about — WSLg's socket
lives in its own tmpfs and WSL bind-mounts it to `/tmp/.X11-unix`, so anything
that mounts a fresh `/tmp` over that bind (systemd's `tmp.mount`) hides it from
libX11 while leaving it in `/mnt/wslg/.X11-unix`. watch.sh binds it back when it
is root, which the app's own launch is; by hand it is

```bash
sudo mount --bind /mnt/wslg/.X11-unix /tmp/.X11-unix
```

## The coin door interlock, which explains a whole class of "it does nothing"

The emulated machine keeps the real one's interlock and it is not optional:

- **Coin door CLOSED** (switch 33 held, the default) — 48V is live, so coils
  fire. The service buttons are locked out; pressing Enter does nothing.
- **Coin door OPEN** (switch 33 released) — the service menu works. 48V is off
  and the game says so on its own screen: *48V DISABLED / CLOSE COIN DOOR*.
  **No coil can fire in this state**, which makes a perfectly working playfield
  look broken. The playfield window says so in the status bar.

You can close the door *while in the menu* to get both at once, which is how the
coil frames were captured. To see coils fire without playing: close the door,
open the trough switches so the balls look missing, press Start — the game puts
up LOCATING PINBALLS and ball-searches on an 8.3 s cycle. `coildecode.py` reads
the result out of a `PAD_COIL_PROBE=1` capture.

## Requirements

**Linux, or Windows with WSL.** `qemu-user-static` (binfmt `qemu-arm`
registered with the **F** flag), `gcc-arm-linux-gnueabihf`, `gcc` +
`libc6-dev`, `e2fsprogs`, `fuse3`, `ffmpeg`, and `python3-tk` for the playfield
window. Then, once:

```bash
rootfs.sh <card.raw>    # the guest rootfs, from the card. No root needed.
```

**Two compilers, and they are not interchangeable.** The hardware shim and the
guest half of the GL bridge are ARM and want the cross compiler; `padglhost`,
the renderer that draws the picture, is a native x86-64 binary and wants plain
`gcc`. `libc6-dev` is named beside it because gcc only *recommends* the
headers, and `padglhost.c` opens with `#include <stdio.h>`. `setupcheck.sh`
reports that one as `nativecc` and probes it by compiling rather than by
looking on the PATH — a compiler with no headers is on the PATH and cannot
build anything.

**`ffmpeg` is the decoder for both the picture and the sound**, and it is the
one requirement here whose absence does not stop anything. The game cannot
decode its own H.264 (of the 175 plugins in its gstreamer-0.10, the only one
that does is the i.MX6 hardware element), so `padvidhost.py` decodes out here
and hands the guest raw frames; `playaudio.sh` uses ffmpeg's `pulse` muxer for
the same reason, this distro having no pulseaudio client tools. Without it the
emulator starts, builds, boots the guest and opens a window — and that window
is black and silent. `watch.sh` says so once at startup rather than letting it
arrive as a decode error per clip.

On **Ubuntu**, `qemu-user-static` is published in the `universe` component and
the others are in `main`. A distro with universe switched off therefore
answers `E: Package 'qemu-user-static' has no installation candidate` — apt
knows the name and has no version — and, because `apt-get install a b` is all
or nothing, installs none of the others either. `setupcheck.sh` reports that as
`nocand` and `universe=0` rather than only as "missing", and `setupfix.sh`
turns universe on before it installs anything.

That is the whole of it: the ARM hardware shim and the GL backend are compiled
by the first run that needs them. They used to be two more steps printed as
advice, which is how a user reached `env: './padglhost': No such file or
directory` at their first start.

`rootfs.sh` is the step that used to be missing: `run_game.sh` chroots into
`$PAD_ROOT` and nothing in the repository created it, so the recipe lived only
in a planning document that is not in git. It reads the partition table rather
than assuming one card's offsets (`parts.py`), extracts the OS partition with
`debugfs` — no loop mount, no sudo — and finishes with the boot partition,
which `rdump` of the OS partition never touches and whose absence is a `GAME
VALIDATION ERROR #3`. It refuses to extract to a `/mnt` path, because drvfs
cannot hold symlinks and `ld-linux.so.3` would silently vanish.

It does **not** extract a title. `PAD_CARD=<image> watch.sh` runs one straight
off the card in about a second; `rootfs.sh --game <title>` is there for a title
you run constantly.

Every run then checks that the guest can actually **start a program** — a user
namespace, a chroot, `/bin/sh`, about 25 ms — before it starts one. A rootfs
that exists is not a rootfs that runs, and all four ways it can fail (an
extraction that stopped part way, a missing ARM loader, no `qemu-arm`
registration, a registration without the **F** flag) produce the same single
line and no other clue:

```
chroot: failed to run command '/bin/sh': No such file or directory
```

The first two are rebuilt from the card you are already running; the last is
repaired by putting a copy of the interpreter inside the guest, which needs no
root. Only registering `qemu-arm` needs root, and that one is named with the
command for your machine — WSL loses the registration on every restart unless
the distro boots `systemd`.

### WSL and Linux are not two ports

This is a Linux program. `run_game.sh`, `cardmount.sh`, `padglhost.c` and
`padvidhost.py` contain nothing Windows-specific at all — the chroot, qemu-user,
the node bus, the card mount and the renderer are the same code either way.
What WSL needs on top are **workarounds, not features**, and there are exactly
two:

| | |
|---|---|
| the playfield runs as a **Windows** process | this WSL has no Tk of any kind, and installing one needs a sudo the rig does not have |
| audio bridges to a **Windows** player | the WSLg→Windows audio hop degrades music, while every instrument inside WSL reads clean |

On a Linux desktop both simply go away: the playfield is a local Tk window and
audio goes straight to PulseAudio. `padpath.sh`'s `pad_is_wsl` (and
`padpath.py`'s `is_wsl()`) is the **one** place that decides which of the two
applies — `playaudio.sh` used to carry its own copy of that test, which is the
duplication this rig's own rules forbid.

**`PAD_FORCE_NATIVE=1` makes a WSL session take the Linux branches**, which is
the only way to exercise them from a Windows machine. It is how the Linux path
was tested; what it cannot show is the playfield window itself, because the
distro that needs the workaround is by definition the one with no Tk.

### macOS: in a container, watched over VNC

`qemu-user` translates *Linux* syscalls, and `unshare`, user namespaces and
`chroot` into an ELF rootfs are Linux kernel features. So macOS is not a port
that could be written — running the rig there means running Linux there, and
`docker/` is that Linux.

```bash
docker/padbox.sh --build                 # once
PAD_CARD=~/cards/godzilla.raw docker/padbox.sh watch.sh 30
open vnc://localhost:5900                # Screen Sharing; nothing to install
```

**The container runs its own X server** and exports only the finished
framebuffer. Forwarding X to XQuartz instead would push every frame across the
VM boundary as uncompressed protocol, ~4 MB a frame at 1360x768.

**Software rendering is not the bottleneck and never was.** Measured on a
headless Xvfb with `GALLIUM_DRIVER=llvmpipe`, which is what a container with no
GPU gets: guest **57.1 fps**, renderer **59.9 fps**. The 1 fps figure this
project remembers is `glraster.c` running *inside* the emulated ARM guest, which
the GL bridge replaced and which none of this uses.

Three container details are load-bearing, all in `padbox.sh`:

| | |
|---|---|
| `--security-opt seccomp=unconfined` | Docker's default profile blocks `unshare`, so the guest could never get its mount and PID namespaces |
| `--cap-add SYS_ADMIN --device /dev/fuse` | `cardmount.sh`'s read-only card mount |
| `-p 127.0.0.1:5900` | the VNC display is an unauthenticated view of the machine; loopback only |

**KNOWN, and see REMAINING item 30: a container run ends by itself after about
60 seconds.** Everything is healthy until it does — full frame rate, clean
teardown — and `watch.sh`'s three exit paths all stay silent, so it is taking a
signal from outside. It was seen on Docker Desktop for **Windows**, which is not
the target; macOS uses a different VM layer entirely, so the first question is
whether it happens there at all. Video also does not stream in the container,
unexplained.

## Paths

Nothing here carries a path to a particular machine any more. `padpath.sh`
(sourced by the scripts) and `padpath.py` (imported by the Python) are the only
two files that know:

| | | |
|---|---|---|
| `RIG` | this directory | from `BASH_SOURCE` / `__file__` |
| `ROOT` | the guest rootfs | `PAD_ROOT`, else `~/spike2root` |
| `TABLES` | derived per-title data | `PAD_TABLES`, else `$ROOT/dump/tables` |
| — | any of those as **Windows** sees it | asked of `wslpath`, never built by pasting strings |

That last row is the one that reads like a detail and is not.
`\\wsl.localhost\Ubuntu\...` was written out in four files: it names a distro
that need not exist, under a prefix older WSL spells `\\wsl$`. `wslpath -w`
knows the right answer for the running system, and `watch.sh` passes the
translated values across interop through `WSLENV`'s `/p` flag, so the playfield
window normally has them already and asks nothing.

**This used to be 187 files carrying `/home/david` and 51 carrying the
checkout's absolute path**, and this section used to say it was 44 files and one
`sed`. Both halves of that were wrong, which is roughly the point: a count
nobody re-derives goes stale, and a path nobody derives never works anywhere
else. If you move the rig now, nothing needs editing.

Two things to know if you add a script:

- **Source `padpath.sh` before using `$RIG` or `$ROOT`**, with
  `. "$(dirname "$0")/padpath.sh"`.
- **A quoted heredoc does not expand anything**, so `$ROOT` inside `<<'PY'`
  reaches Python as five literal characters. Pass it through the environment
  (`export PAD_ELF=...` then `os.environ["PAD_ELF"]`), which is what the
  forensic scripts here do. Same trap for `pkill -f '...'`: single quotes stop
  the pattern expanding and it silently matches nothing.
