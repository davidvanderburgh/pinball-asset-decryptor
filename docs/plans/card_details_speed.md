# PAD-626: the Card details tile fills in seconds, not minutes

David: "Loading card details tile takes a really long time. Need this to be far
more performant." (His screenshot: Godzilla LE 1.16 on Select card, the tile
still shimmering after the app was otherwise ready.)

## How it was measured

Every number below is a COLD read: before each run the card file was dropped
from the Windows file cache (a non-buffered open purges a file's cached pages
when nothing else holds them; `scripts/shot_pad626.py`'s `purge`). Without that
a card read twice in a row looks fast and hides the problem: a warm Godzilla
read took 2.1 s on main, a cold one 27 s. The cards are on D:, a spinning disk,
as David's are. Main and this branch were run in turn on the same card, and the
two reports compared: identical on all nine cards (the custom Heisei card
included: the same 658 videos and the same "modified ... 533 videos" verdict). Harness:
`C:\tmp\PAD-626\ab.sh`.

## What was slow, and why

1. **Counting the videos opened every candidate file** - a 12-byte `ftyp`
   sniff of each extensionless `.asset`, in directory order, so each one was a
   seek across the 8-16 GB image. 7.5 of a cold Munsters read's 9.8 s; 93 of a
   cold Stranger Things read's 96 s (8,500 files). Reading them in disk order
   helped some cards (Guardians 19.7 -> 4.9 s) but not the ones whose small
   files sit between big videos (Stranger Things still 93 s): those are seeks
   whatever the order.
2. **Nothing was shown until all of it was read**, the quick rows included.
3. **Every look read the card again** - each time the app started on the same
   card, the whole read again.
4. **Pure-Python scans of every word of the game program**: the adjustment
   table's name and record searches and the high-score board's
   candidate search (0.78 s on Godzilla, 8.3 s on Rush's 190 MB program).

## What changed

1. The official-release table (`stock_prints.json.xz`) now records which of
   each release's files are videos (`videos`, filled in for all 53 releases by
   `scripts/make_stock_prints.py --add-videos`; `make_release` records them for
   a new one). A file whose record in the card's own manifest and whose size on
   the card are still the release's is classified from the table and never
   opened - the trust the official-release check already puts in a card (every
   PAD build rewrites the records of the files it changes; a card that kept
   Stern's records for files it replaced, like DragonRR's Heisei card, is caught
   by the size). An official card opens none; a built one only what it
   changed. The rest are sniffed in disk order. The Compare tab and the
   official-release check walk through the same code and gain the same.
2. The report comes in two stages (`image_info.collect(partial=...)`, a
   plugin's `image_info(partial=...)`): everything but the video count first,
   the Videos row reading "counting…" and the status "Counting the videos…",
   then the whole report (the official-release row needs the videos, so it
   comes with them). Copy waits for the whole one. The Extract and Write tabs'
   Image Info windows take the same early report.
3. The finished report is kept beside the card's cached pictures
   (`%TEMP%\pad_card_preview\<card key>\info.json`), keyed by the card file's
   path, size and modified time plus the app version, manufacturer and project
   folder. The next look at the same card file shows it at once; Refresh reads
   the card again; a report that says the read failed is not kept.
4. The adjustment search finds the count word with `bytes.find` and the run
   of `AD_` name pointers with numpy; the high-score search matches the
   program's words against a numpy-built bit mask of the places that can hold
   1-3 character initials, then runs the same checks as before on those only.
   Godzilla LE 1.16 0.78 -> 0.08 s for both, Rush Pro 1.19 (a 190 MB program)
   8.3 -> 1.7 s; all 89 game programs on D: 202 -> 17 s, every one with the
   same answers (table, record, names, board rows; `C:\tmp\PAD-626\adjbase.py`).
   The Defaults tab reads the same two tables, so it opens quicker too.

## Before and after (cold, D:)

| Card | Main | This branch: first rows | whole report |
|---|---|---|---|
| Godzilla LE 1.16 | 27.0 s | 2.4 s | 2.6 s |
| Stranger Things LE 1.13 | 115.0 s | 6.1 s | 6.3 s |
| Elvira 3 1.13 | 177.2 s | 4.1 s | 4.4 s |
| James Bond LE 1.06 | 106.5 s | 8.2 s | 8.4 s |
| Star Wars LE 1.31 | 17.1 s | 1.7 s | 1.8 s |
| Mando LE 1.45 | 13.3 s | 2.0 s | 2.2 s |
| Iron Maiden LE 1.18 | 5.3 s | 1.6 s | 1.7 s |
| Guardians LE 1.14 (older build, not in the table) | 7.3 s | 3.0 s | 6.9 s |
| Heisei Godzilla 1.16 V1.5 (custom: 533 videos replaced, all sniffed) | 28.3 s | 1.9 s | 15.0 s |

The same card opened again (the next app start): shown at once from the kept
report.
