# My machines (PAD-783)

David, 2026-10-27, item 4 of the feature proposals (`Claude outputs/feature_proposals_2026-10-27.md`): a home page
listing the owner's machines, each with its card, project, lineage and size, buttons into the project, Transfer Mods and
Write, and a once-a-day check of the manufacturer's public code-update page that says "1.17 is out" with a link. Stern
Spike 2 first. PAD-22, 32, 35, 151, 213 and 757 all asked versions of "what carries over when new code ships" and "which
version do I need".

## What a machine is

A record the owner names, bound to the card it runs by the card's **fingerprint** (`core/lineage.py`, Stern's printer is
`stock_prints.card_print`), kept in settings.json under `machines` (`core/machines.py`, pure functions like
`project_registry`). Adding one reads the card's manifest (well under a second) and asks for a name, offering the release's
words ("Godzilla LE"). The same card file added again updates its machine; Change card... rebinds it (new code, a new
build); Remove takes it off the list and never touches the card or a project.

**A project joins the row by itself**: any project in the registry whose `.pad-lineage.json` holds the machine's print -
as the official card it is of, the card it was extracted from, one of its revisions, or the card a revision was built
over (`machines.place_in`). Only registry folders are read (no crawl), off the UI loop. The newest such project is the
row's; the others are counted.

**What the card is** (`machines.card_words`): Stock (the print is the official release's), "PAD build, rev N" (the print
is a revision of the matched project, or the card it was extracted from was), "Modified card" (a known release, changed),
"Not a known release".

**Title, edition, build** (`plugins/stern/machine_info.release_info`): from the card's `.sidx` key
(`godzilla_le-1_16_0.sidx`): the game table's title, the edition from the key's suffix (`_le` = "LE / Premium": Stern
ships one code for both; `_pro`; `_elg` / `_the_pin` = Home Edition; a bare key beside an `_le` twin = Pro), the build in
Stern's own spelling (1.16).

## The code-update watch

`core/code_watch.py`, Stern registered from `plugins/stern/manufacturer.py`:

- Stern's public page `https://www.sternpinball.com/support/game-code/` embeds every release as a download named for the
  **same key a card's .sidx carries**: `godzilla_le-1_16_0_spike2.spk.zip` (`beatles-1_29_0.spk`,
  `Ghostbusters_le-1_17_0.spk` on a few). So the newest build of a machine's release is the largest version of its key
  on the page - no title table to drift. `_spike3` builds are another board and never count (Star Wars Home has both).
  Measured 2026-10-27 on the live page: 60 Spike 2 keys, every one of the 53 stock-table releases found, each at the
  build the library holds.
- One GET with `Pinball-Asset-Decryptor/<version> (game-code check, once a day)` as User-Agent, at most once a day
  (three hours after a failed read), 20 s after start and then hourly looks at whether it is due; only while there is a
  Stern machine on the list and the "Check for new game code once a day" box is ticked. The answer is kept in
  `code_watch.json` beside settings.json. A failed read keeps the last answer.
- **Link only**: the row's "1.17 is out" opens Stern's page in the browser. The app downloads nothing from it.
- A newer build is told once per machine and build, wherever the owner is (the app opens into their last manufacturer,
  not the picker): a toast and a log line naming it (`machine_code_told`).
- A server started for tests or captures (`PAD_UI_NO_UPDATE_CHECK`) never reads the real page; `PAD_CODE_WATCH_URL`
  points it at a stub.

## The page

`MyMachines` at the top of the picker (`static/js/shell.js`), the manufacturer menu's last entry renamed "My machines and
manufacturers...". Each row: name, title + edition, build, what the card is, "is out" when newer; the card file, its size,
the project. Buttons (`webui/shellx_machines.py`):

- **Open project** - switches to Stern, Spike 2 era, opens the project (no "switch manufacturer?" question: the row said
  which). With no project yet: **Extract**, the Extract tab with the machine's card picked.
- **Transfer Mods** - opens the project and the Mod Pack tab with it as field 1 (the old extract whose mods move); field 2
  is cleared, since the tab would otherwise fill it with the open project. The one-click port above it uses the open
  project too. Primary-coloured when newer code is out.
- **Write** - opens the project on the Write tab.
- More: Show the card image, Change card..., Rename..., Remove from My machines.

## Proven

- `tests/test_machines.py` (22): release words for every stock title, the page parse on Stern's real spellings, the check
  (User-Agent, once a day, retry, failure keeps the answer, test servers never reach the site), the records, a project
  joining by fingerprint (stock, a revision, built over), and on the real web app with a stubbed page: add (the name
  question, a non-card refused), the row's words and "1.17", told once, the switch off, Transfer Mods landing on Mod Pack
  with field 1 the project, Write, Remove. Two real library cards (stock Godzilla LE 1.16 and the Heisei custom on it)
  added through the page's call: Stock / Modified card, Godzilla LE / Premium 1.16, 7.3 GB.
- `scripts/shot_pad783.py`: the same against the real app in Edge, the two real cards, a scratch project the real
  `note_extract` wrote from the stock card, Stern's page stubbed with 1.17.

## JJP and BoF (PAD-787)

A manufacturer joins with three registrations in its `manufacturer.py`: a printer (`lineage.register_printer`), a kind
(`machines.register_kind`: maker name, release words, build spelling, the file's noun and picker types) and a source
(`code_watch.register_source`). The page, the toast and the watch line take the maker's words from the row; nothing
in `shellx_machines.py` names Stern any more.

**What a machine runs.** JJP: the full-install ISO it was installed from. BoF: the `.fun` update it last ran. Both
are one big file, so the print is `lineage.file_print`: the size, the first and last MiB and 64 slices of 64 KiB in
between, plus the header the printer read. That is a few MiB, about 0.5 s on D:. Every rebuild moves a file's layout and
size, so a PAD build never prints like its release. The CHAKAs GNR mod and the Sarah Labyrinth mod print apart from
their stock files.

**JJP release** (`plugins/jjp/machine_info.py`): the ISO's own volume ID (`Sonic-v00.926`), read from the primary
volume descriptor at 32 KiB, so a renamed copy and PAD's xorriso rebuild still read correctly. That ID is the machine's
`sidx`. JJP spells builds as decimals: `version_of` pads the fraction so `00.95` sorts above `00.926`. Every edition
runs the same ISO, so no edition is shown.

**BoF release** (`plugins/bof/machine_info.py`, `fun_head.py`): BoF stamps the build into the tar's first member.
`GDHarvest_not_harvest_20260429.x86_64` names it for Winchester; Dune's `GDHarvest_202600513` reads as 2026-05-13 (it
has a stray digit); Labyrinth's first member is the `update/` folder, whose file date is the build. `fun_head` decrypts
only the first 256 KiB of the gpg stream, in Python: SKESK v4 with S2K 3, SEIPD v1 in CFB, a compressed packet, a
literal packet, partial lengths. No gpg or WSL is needed, and it takes about 0.1 s. Bon Jovi's disk image names it in
the outer EROFS (`bon-jovi_2026.10.01.img.root-x86-64`). The `sidx` is `<game>-YYYY.MM.DD`.

**Stock tables**: `STOCK` in each `machine_info`, from David's library on 2026-10-27: 8 JJP ISOs and 5 BoF updates.
A listed release with another print reads "Modified card"; an unlisted release reads "Not a known release", the same
as Stern.

**Pages: one per title.** JJP has a support page per edition; all editions of a title link the same ISO on both
mirrors (`.../sonic/Sonic-v00.951.iso`), so `PAGES` holds one page per title. BoF's shop has a code-update page per
title, each linking one Dropbox zip named for the build (`BOF_WMH_20261001.zip`); only that name is read. A check
reads only the pages of the titles the owner has a machine of (`check(keys=)`). A title added after today's check
makes its page due at once (`due(keys=)`). The row links to its title's page. A check finishing looks again for
anything that became due while it ran: a second maker's machine added mid-check used to wait for the hourly tick.

**Lineage for JJP and BoF projects**: Extract already printed through any registered printer (`app.py`), so JJP and
BoF extracts now get a `.pad-lineage.json` too. Their Writes call `lineage.note_built` (new, shared) and record the
file they built as a revision, so a machine running a PAD build reads "PAD build, rev N" and finds its project.

**Mod Pack, not Transfer Mods**: only Stern's Mod Pack carries mods onto new code (`capabilities.mod_transfer`). On a
JJP or BoF row the button reads "Mod Pack" and opens the project on that tab, where its pack is exported for the new
code's project.

Measured 2026-10-27 on the live pages: JJP lists Sonic 0.951 (the library has 0.926), Hobbit 4.02, Wizard of Oz 8.02,
and every other library title at the build the library holds. BoF lists Labyrinth 2026-01-30 and Dune 2026-05-13 (both
as held), Winchester 2026-10-01 (the library has 04-29 and 05-27) and Bon Jovi 2026-10-14 (the library has 10-01).

Proven: `tests/test_machines_jjp_bof.py`. It uses a gpg-shaped `.fun` and an ISO built in Python; covers both printers,
the parsers on the pages' real spellings, the per-title check, both Writes' revisions, and both makers' rows on the
real web app with a stubbed page; and reads every library file when it is present. `scripts/shot_pad787.py` runs the
same against the real app in Edge with three real library files.
