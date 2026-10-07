# Project revision history across machines (PAD-427)

Step 2 of better revision control. Step 1 was PAD-426, the official Stern stock fingerprints (`stock_fingerprints.md`).

## Why

David (PAD-421): "users will be doing multiple revisions across multiple computers, we need some better revision control for the whole app", and "a lot of times with revisions like this, we are treating the last version of revisions as stock".

Everything that tied a project to its cards was a recorded path. `extract_source.card_relation` and `_names_this_image` paired a card with a project by path, then name + size, then (PAD-421) renamed = old path gone + same size + mtime. The build record beside a card names its project by absolute path. All of that breaks when a project or a card moves to another computer. Name + size also takes a card rebuilt over the source for the source itself, because every card built for one machine is the same size.

## The card's fingerprint

`stock_prints.card_print(card)` gives `{"print", "sidx", "label", "official"}`:

- One metadata walk of the data partition plus its `.sidx`. Nothing else is read: no video sniffing, no hashing. That is 0.04-0.5 s on a warm card.
- The print is a SHA-1 over the sidx name and every manifest file's path, REAL size (from the inode) and manifest MD5. When the real size disagrees with the record, the file's MD5 counts as `-`. PAD rewrites the record of every file it builds, so any two PAD builds that differ in a file have different prints.
- The one case it can't tell apart: a card built elsewhere that swapped a file for one of exactly the same size and left Stern's record alone. The deep stock check (PAD-426) catches that one.
- The official card's print comes from the table alone (`release_print`), so "official" means print == the release's print.
- `check_card` (Card details, the after-Extract stamp) takes the same print on its walk. Deep or not, the print is the same.

`core/lineage.py` caches prints per card by `(size, mtime_ns)` in `card_prints.json` beside settings.json. `card_print(path)` answers from the cache. `card_print(path, measure=True)` opens the card through the registered printer, which the Stern manufacturer module registers. Core stays plugin-free.

## The record: `.pad-lineage.json` in the project folder

```
{"format": 1, "id": "<uuid>",
 "stock":  {"sidx", "label", "print"},
 "source": {"print", "name", "status", "label", "rev", "at"},
 "revs":   [{"rev", "print", "parent", "parent_rev", "name", "built", "host", "app"}],
 "imported": [{"id", "from", "rev", "print", "pack"}]}
```

- **Extract** (the after-Extract thread in app.py, beside the PAD-426 stamp) calls `note_extract`. These cases keep the history:
  - re-extracting one of the project's own revisions;
  - re-extracting its source;
  - re-extracting the official card.

  Any other card starts a new history with a new `id`, because the folder's baseline is now that card.
- **Build** (`pipeline._note_build_lineage`, after `write_image`) prints the output and the card it was built over, then appends the revision:
  - parent rev 0 = the official card;
  - parent rev n = one of this project's own revisions;
  - parent rev `None` = an unknown card.

  A rebuild with nothing changed has the same print, so it refreshes that revision instead of adding one. The build record beside the card gets `lineage: {id, rev, print, parent, parent_rev}`. The log says "This card is rev N of official Godzilla LE 1.16."
- It is a dotfile, so the baseline, the slot scanners and mod packs' file diff skip it. A folder copy takes it along.

## What reads it

- `card_relation(card, project, measure=False)`: the lineage decides first when the card's print is known.
  - print = source → `source`; = a revision → `build` (with `rev`);
  - the same official card under any name → `source`.

  Otherwise the path rules answer as before, with one exception: when the project's source print is known and the card's print is not it, the name + size match no longer makes the card the source. That is the "last revision taken as stock" case. Worker-thread callers measure (Emulate, the Extract tab's project/card check, the scene re-read's worker), and the UI-loop re-check reads the cache they just filled.
- `other_card_recorded` (the build warning, PAD-176), by print:
  - building onto the source or onto a revision of this project gives no warning;
  - building onto the official card when the project came off a modified card warns, because the baked-in mods would be lost;
  - any card the lineage doesn't know warns.
- `built_card_source` (Transfer mods' "carry the baked-in mods" question) also reads the PAD-426 stock verdict. A project extracted from a modified card counts even when that card was built on another computer and has no build record here.
- **Extract / This project**: a "Revisions" row, for example "Rev 2 of official Godzilla Pro 1.16 - last built 2026-10-07 09:40 on GARAGE-PC", with every revision in its tooltip.
- **Mod packs** carry the lineage in `.modpack.json`. Import compares the pack's source print with the folder's, so two computers' differently-named copies of one card are the same card and no different-card warning appears. Two different cards with the same file name do get the warning. Import records the pack's project and revision under `imported`.

## Proven

- `tests/test_project_lineage.py` (14) covers:
  - the Stern print on fake ext4 cards: official = the table's print, rename-proof, deep = not deep;
  - the revision chain;
  - a project and its cards moved to another computer;
  - the PAD-421 shape: built in place, folder copied beside the card, original deleted;
  - name + size no longer making a card the source;
  - a project off a modified card warning on stock;
  - `built_card_source` from the verdict;
  - re-extract keeping or restarting the history;
  - the cache following the file stamp;
  - a pre-lineage project keeping its source;
  - mod packs both ways;
  - the build pipeline's record.
- Real cards, through the registered Stern printer: official Godzilla Pro 1.16 as the source, and a Heisei custom card as rev 1 with the project folder copied elsewhere and the original deleted. The results were `source` rev 0, `build` rev 1, and Aerosmith `other` with the warning. Each print took 0.15 s.

## The extract measured against the official card (run 2)

`stock_prints.project_off_stock(project)` says which of the project's EXTRACTED files are not the official card's. That is what the card it came off already carried, measured against Stern's release rather than against that card. It reads only the project's own sidecars, with no card and no hashing (0.0-0.1 s):

- **Clips and loose pictures** are byte copies of their card files. Each one's baseline MD5 (`.checksums.md5`, taken at extract) is compared with the release's record, via `video/manifest.txt` / `images/manifest.txt` (output -> card path).
- **Scene textures** (`scene.assets/N.asset`) are decoded, so only their card size (the manifest's bytes column) is compared. A same-size swap is missed.
- **Radium pictures** carry their digest in the file name.
- **The release** comes from the project's lineage, else the extract's stock stamp, else the picture folder at `card_version`. Failing those, it comes from the title folder: the table holds one release per title, the latest. That is refused when the card's file name names another version, so a stock 1.13 extract is never called modified against 1.16.

Real extracts:

| Extract | Videos differing from official |
|---|---|
| official Godzilla LE 1.16 | 0 of 658 |
| Heisei 1.5 | 533 (the same 533 the card check counts) |
| `Desktop\gzho` | 0, pictures included |

Where it shows (core reaches it through `lineage.register_off_stock`, which the Stern manufacturer module registers):

- **Extract / This project**: an "Off stock" row under Changed, e.g. "In the extract itself: 533 videos differ from the official Godzilla LE 1.16 card. Changed above counts only what was changed since the extract."
- **Mod-pack export** logs how many of those files are NOT in the pack, because they are the folder's baseline rather than changes, and points to Transfer mods.
- **Transfer mods**: when the old extract came off a modified card (`built_card_source`, which now includes the PAD-426 verdict) and field 3 is empty, `lineage.find_official_extract` looks through the recent projects and the folders beside it. It looks for an extract of the same release taken from the official card (lineage source official, or stock stamp official, with a baseline). It fills field 3 and logs it. It fills the field once per old extract, so clearing it sticks.

Not done, on purpose: the pack does not ADD the baked-in files. 533 videos is GBs, and Transfer mods is the route for a modified card's own content.
