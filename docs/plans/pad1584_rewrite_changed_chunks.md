# PAD-1584: a card rewrite sends only the chunks that changed

David's performance ideas, 2026-11-25, idea 2 of 10.  Built on PAD-1576
(free blocks skipped), PAD-1577 (read-ahead thread) and PAD-1583 (each
chunk hashed as written, verify reads the card alone).

## What it does

After a write onto a card finishes (and verifies, when verify is on), the
hash of every chunk written is remembered against that card in
`card_writes.json` (`%LOCALAPPDATA%\pinball_decryptor` on Windows,
`~/Library/Application Support/pinball_decryptor` on a Mac,
`$XDG_STATE_HOME` or `~/.local/state` on Linux; `PAD_CARD_RECORD`
overrides it).  The newest six cards are kept.

The next write finds the card's record by **reading the card's first
recorded chunk** and checking its hash (and the card's size).  A card
rewritten elsewhere, or another card of the same size, does not match.
Then, chunk by chunk:

* the record has a different hash from the new image's: the card held
  other bytes there, so the chunk is written straight away, with no read;
* otherwise (the record has the same hash, or nothing for that chunk) the
  chunk is **read off the card and compared byte for byte** with the
  image chunk.  It is left alone only if the card holds exactly those
  bytes, and written if not.

So the record only says where to look.  What is skipped is what the card was
seen to hold.  A stale or wrong record costs time, never a wrong card.  The
full verify runs afterwards as before (PAD-1583), over every chunk,
skipped ones included.

A write or verify that fails or is canceled forgets the card's record.
The menu-only write does the same skip, and afterwards replaces the
record's chunks under the menu ranges with the ones it wrote.

`PAD_WRITE_EVERY_CHUNK=1` writes every chunk, as before.

## Cost and gain

The first write onto a card, or onto a card with no record, is unchanged:
no extra reads.  On a card with a record, each chunk the image did not
change costs one read instead of one write.  SD reads run several times
faster than writes, so the edit, write, test loop, where a build changes a
few MB of a multi-GB image, writes only those MB.  The stand-in card in
`scripts/shot_pad1584.py` (64 MB image, 3 MB changed, card writes slowed)
took 4 s instead of 16 s.

## Proof

`tests/test_flash_rewrite_changed.py` covers: only the changed chunk sent;
first write sends all; a card changed behind the record's back (machine
data, a zeroed sector) is fixed; chunks the record says changed are not
read; another card or a different size is not taken for it; the opt-out;
a failed verify forgets the record; three edit rounds in a row; two cards
told apart; keep-data compared with its overlay in place; progress text;
menu-only write and the full write after it.
