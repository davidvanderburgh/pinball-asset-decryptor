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

## Left for the next run

- **Changed against the official card.** The project's Changed row and the mod-pack export still diff against `.checksums.md5`, which is the extracted card. For a project off a modified card, the official table can still say which pictures and videos differ from stock:
  - pictures by their `radimg_..._<md5[:8]>` names;
  - videos by their file MD5 against the release's `.asset` records.
- **Transfer mods against the official card.** Find the official card for the project's release on this machine by print (recent paths and the folders cards were picked from), and offer it as the stock card the baked-in mods are compared against. Today the user has to supply a stock extract.
