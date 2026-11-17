# PAD-1382: more service-menu settings than a game has spare rows

## The limit

Every service-menu setting of ours takes over an adjustment the game no longer reads (a DEPRECATED one,
`menu_settings.spare`). A game's adjustments cannot be added to: each one's value is eight bytes of the board's NVRAM
mirror by id, and the store is keyed by the caption. Godzilla 1.16 (and every latest Spike 2 build measured, PAD-1033)
has three. MUSIC MODE, CO-OP PLAY, HANDICAP, the three picture settings, EDITION and (Simon's branch) IMAGE SET
already want more. Before this, the planner refused what did not fit: on Godzilla LE 1.16 a card with co-op, handicaps
and the picture settings lost co-op altogether and had handicaps forced on (`artifacts/PAD-1382/emulator/build_before.log`).

## What is built

When a card wants more settings of ours than the game has spare rows, they all share two
(`menu_settings.plan_many` -> `plan_shared`):

- **MORE SETTINGS** (values 1..n, its help names them) picks one;
- the row under it (descriptor caption SETTING VALUE) is that one's value. The mode runtime writes the picked
  setting's row caption, help line, range, default and display kind over it, and its value into the row's record
  (with the record's check byte), whenever the pick changes. An accepted change there is that setting's new value.

The **values live on the card**, not in the game's store: `/dump/pad_settings.state` (one `key value` line each,
written to a temp file, fsynced, renamed), so any number of settings keep their values over a power cycle. The game's
store keeps only MORE SETTINGS's pick and the last value the row showed. Up to 8 share (MAX_VALUES). EDITION never
shares: codeselect reads it off the store before the game runs. Settings that fit keep rows of their own exactly as
before; sharing starts only when one would be refused for want of a spare row.

Each setting's reader is unchanged: its cfg line names `0xFADE0000 + 4k` (above a 32-bit process's user space)
instead of a `.nonvol` address, and `setting_addr()` (every reader: coop, handicap, music modes, picture settings)
hands it the runtime's word for setting k. `settings.cfg` (written by `menu_settings.shared_cfg_text`, beside the
runtime: `/usr/local/padmode` on a card, `/dump` in the rig) says where the two rows are and lists the settings.
MUSIC MODE's `sounds.cfg` is written before the menu is planned, so its `setting` line is re-pointed afterwards
(`engine._point_sounds_cfg`).

The rows are watched by a thread of the runtime's own (every 50 ms), not the game's tick: a card of settings only
never hooks the tick, and the menu runs whatever the game does. The thread and its nap are looked up by name
(`pthread_create`, `nanosleep`); MODE_SDK rule 2 is about a mode's code on the game's threads and still holds for
every mode. For 3 s after the pick is first seen the row is held at our value (the game reads its store at boot).
Spike 2 only: a 64-bit program never shares (its category table cannot grow yet; `plan_shared` refuses).

## Proof (emulator, Godzilla LE 1.16, `artifacts/PAD-1382/emulator`)

Override sets built by `engine.write_overrides` from main and from this branch (`C:/tmp/PAD-1382/mkset.py`, job
`job.sh`): co-op (menu), handicaps and the picture settings = five on three spare rows.

- main: Attract Mode has no CO-OP PLAY or HANDICAP row; co-op left off the card, handicaps always on.
- branch: Attract Mode lists **More Settings 1** and **Brightness 5** under it. More Settings -> 4: the row becomes
  **Co-op Play 0** with co-op's help and Current/Default values; set to 1. More Settings -> 5: **Handicap Off** (Off/On
  display); set On. Back to 4: Co-op Play reads 1. `pad_settings.state` holds `coop_play 1`, `handicap 1`.
- power cycle: the runtime reads both back, co-op arms "now Classic" and handicaps "while HANDICAP is On" (the
  features read the shared values), and the page shows More Settings 4 / Co-op Play 1.

Tests: `tests/test_pad1382_more_settings.py`.

## Round 2: the Service menu tab

David: "how does the user edit the service menu? ... a visual render of the service menu in our app". Make >
**Service menu** (Stern Spike 2; `webui/tabs/svcmenu.py`, `static/js/tabs/svcmenu.js`, `plugins/stern/service_menu.py`)
plans the project's rows exactly as a Write does (`service_menu.wanted` = the engine's own menu jobs, through
`arrange`, then `plan_many`) and draws each page that carries one as the machine draws it: the page's system rows in
the category table's order, ours, then the game's feature rows (ids 160+ whose descriptor's u16 at +0x26 names the
page). Matched row for row against Godzilla LE 1.16's Attract Mode in the emulator; the game hides 70TH BOOT SCREEN at
run time on LE, which the reproduction still lists. Values are shown where the display kind says how (low 16 bits: 1
Off/On, 9 Yes/No, 2 a number); the game words the rest itself (its value-word tables are reached through code, not
mapped yet) and those are left blank.

## Round 3: order, settings of one's own, the real menu

- **Order**: sidecar `service_menu.order`; `service_menu.arrange` sorts the build's menu jobs by it (then the engine's
  order). It sets the rows' order on a page (the category table is appended in that order) and the numbers on MORE
  SETTINGS. Values in `pad_settings.state` are by key, so a reorder loses none.
- **Settings of one's own**: sidecar `service_menu.custom` `[{key, name, values, default}]`, key `custom_<name>`;
  `service_menu.CustomMenu` is a menu job like the engine's, registering its captions in `menu_settings.SETTINGS`
  (Attract Mode). Planned like the built-ins (a spare row, else shared). `settings.cfg` gets `custom <key> <address>`
  (a row's .nonvol word or a shared one) and the runtime's `pm_setting(key)` (pad_mode.h) reads it - the card's own
  code is the generic reader. A setting that makes the GAME behave differently needs that behaviour built (a ticket),
  as image sets will.
- **The real menu** (off until ticked): `EmulateTab.menu_shot` prepares the same override set a Start prepares (and
  reuses it), then `tools/spike2_emu/menushot.sh` boots hidden and muted, walks `service_menu.walk(rank, row)` and
  glshots the frame. Walk, measured on Godzilla LE 1.16: 25, 25, Adjustments (5th), Machine Settings (3rd), then the
  page by its place among categories 8-17 that have rows, in number order (Attract Mode 16 = 8th), then the row.
  Refused while the Emulate tab has a run up; a Start waits while a read holds the rig.

## Round 4: every project, every menu

David, on his own project: "This game's service menu could not be read (The card image could not be opened ... No
such file or directory ...). we need to make this work for all game images".

- **Which program** (`service_menu.find_program`): the card the project records when it is there; else any card of the
  same game and version (by its own index, `probe_card_title`) among the project's recorded paths, its own Write output
  (`build/`), the cards the app's settings name and every card in those folders; else the copy kept from the last read
  (`titles/menu_programs/<game>-<version>.elf`). The tab says which card it read. David's project (its recorded card,
  stock image, Write original and Emulate card all gone) reads in 0.6 s from its `build` v38 card.
- **Every page**: all Machine Settings pages (categories 8-17 that have rows, in number order), named by the game's own
  page-name table (`category_names`: five language pointers and a zero a line, category c c lines above the INVALID
  line - the linker shares string tails, so INVALID ends another string), with or without rows of ours.
- **The older dot-matrix menu** (`StandardList`, 22 of 53 newest builds): Standard Adjustments (the id list, ours at
  the end) and Feature Adjustments (the id range). Measured on Aerosmith LE 1.16 and Venom LE 1.07 in the emulator:
  icons DIAG AUD ADJ NET UTIL RED QUIT; ADJ's STANDARD FEATURE PREV QUIT; one adjustment a screen ("STANDARD ADJUSTMENT
  #n", the ROW caption upper case - so the runtime's live rename shows there too - its value); MINUS from #1 wraps to
  the last row; the caption blinks (menushot.sh keeps the frame with the most lit pixels).
- **Bug found by it**: the settings sharing MORE SETTINGS all name the row under it, and a Standard list listed it
  once per shared setting (#97-#101 on Aerosmith). `menu_settings._new_rows` lists each new row once, for every table.
- **Spike 3**: its 64-bit tables (`wide_category_names`, the table's own field offsets), rows from `spike3_menu`; the
  game's own feature rows are not mapped there yet, and the real menu stays Spike 2 (Spike 3's emulator opens no
  settings page).
- **Write**: settings of one's own alone are a reason to Write (`_own_settings_for_build`, the picture settings' gate),
  and a card whose only runtime need is `settings.cfg` gets the runtime by `mode_write.settings_plan`.

## Round 5: a page of our own, only the app's settings

David: "it's really weird to shove in these settings into the 'attract mode' tab. can't we add our own 'custom code'
tab ... we should just be checking off items that exist (making a new one here doesn't make sense ...) ... better
highlight the 'custom code' tab and how the user gets there. the other tabs can be read-only and shown secondarily".

- **Custom Code page** (`menu_settings.own_page`, OWN_CATEGORY 15): Machine Settings lists the categories 8-17 that have
  rows; on all 38 newest builds with category pages, 15 (Wireless Audio Devices) has none, so it is never shown. Every row
  of ours goes there (`plan_many` gives each a `category`), its name line's string rewritten in place to "Custom Code"
  and the Machine Settings list's help for it (the menu entry naming that line, its help two words after) to "Settings
  added by this card's custom code.". Refused (rows stay where each setting names) when the page holds anything of the
  game's, a string is shared or has no room. Emulator-proven on Godzilla LE 1.16 and Jaws LE 1.02: the page shows
  between Audio Configuration and Attract Mode with our rows. The dot-matrix Standard list games have no pages to add:
  ours stay the last rows of Standard Adjustments, which the tab says.
- **No settings of one's own**: CustomMenu, the sidecar's `custom`, `settings.cfg`'s `custom` lines, the runtime's
  `pm_setting`, the Write gate and `settings_plan` are gone; the sidecar keeps only `order`.
- **The tab**: the app's page first (the way there as steps, the Machine Settings list with Custom Code lit, the page,
  the real menu); the app's settings ticked and ordered on the right; the game's other pages below, read-only.
- Values still live in `/dump/pad_settings.state` on the card (David: "we can build our own non-volatile storage on the
  sd card, right?" - yes, since round 1): the game's menu rows are the only limit, and two hold any number.
