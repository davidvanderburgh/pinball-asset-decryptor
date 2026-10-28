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

## Later

JJP and BoF register a source and a printer the same way (`code_watch.register_source`).
