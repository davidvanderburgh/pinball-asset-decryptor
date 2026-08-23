"""Count the game code's sound REQUESTS, mined from the game ELF.

Spike 2 audio has three tallies, and only the first two are plaintext words
in the ``image.bin`` container header (see ``info.container_counts``):

  * **sounds** — the packed cat-0 recordings Extract decodes to WAVs.
  * **sound fragments** — every audio piece the booted firmware's
    ``get_asset_descriptor`` resolver will hand out, addressed by sid.
  * **sound requests** — what the *game code* asks for ("play the Carnage
    jackpot callout").  A request is a CHAIN of fragments, so this number is
    neither of the other two, and a tester comparing counts caught the old
    "Sound requests" label on the fragment word as wrong.

The request table is a plain array in the game ELF, reachable without booting
anything.  Stern's build emits a registry of ``{data_va, count, elem_size}``
triples describing its generated tables, and the request table is the one with
20-byte records.  Each record carries a pointer into a block of NUL-terminated
u32 sid lists that sits immediately AFTER the array — the same list block
:mod:`sfx_names` walks for the Sound-Test menu, and indexed the same way, from
the end: record 0 points at the last list, the final record points at the first
one, which begins exactly where the record array stops.

That self-reference is what makes the table findable without trusting any
address: a registry triple is accepted only when its own last record points at
its own end.  A handful of unrelated tables share the shape (they come off the
same code generator), so the survivors are then judged on MEANING rather than
size — every id in a real request's chain has to be a fragment this card
actually has.  On the 39 vendor images on hand the true table addresses
essentially the whole fragment space (lowest ratio 0.9947, Led Zeppelin 1.20)
while the nearest impostor scores 0.13 or less, and the true table is 462-3517
records against a runner-up that never exceeds 49.

Validated against a tester's own machine-reported figures: Venom LE 1.07 =
1869 (exact) and Deadpool LE 1.15 = 984, which brackets cleanly against the
cards on hand (Deadpool LE 1.14 = 979, Deadpool Pro 1.16 = 984).  Anything
off-pattern returns ``None`` so Image Info simply omits the row rather than
printing a number nobody checked.
"""

from .elf import parse_elf

# Bytes per request record.  Field 2 (or 3 on some builds) is the sid-list
# pointer; the rest is playback state the count doesn't care about.
_REC_SIZE = 20
# A build with fewer than this many requests is not a Stern game (the smallest
# on hand is Led Zeppelin 1.20 at 462); the ceiling is a runaway guard.
_MIN_REQUESTS = 8
_MAX_REQUESTS = 1 << 20
# How much of the fragment space a genuine request table has to reach.  Every
# vendor image on hand lands at >= 0.9947; the margin is for a future title
# that ships fragments no request chains.
_SPAN_NUM, _SPAN_DEN = 9, 10


def locate_sound_requests(fw, fragments):
    """``(count, table_offset)`` for the game's sound-request table, or
    ``(None, None)`` when this build's table can't be identified.

    *fw* is the game ELF's bytes; *fragments* is the container header's
    fragment count, which supplies the sid ceiling every real request chain
    has to respect."""
    import numpy as np

    if not fw or not fragments or fragments <= 0:
        return None, None
    try:
        segs, _relocs = parse_elf(fw)
    except Exception:
        return None, None
    n = len(fw) // 4
    if n < 8:
        return None, None
    words = np.frombuffer(fw[: n * 4], dtype="<u4")

    # Resolve every word as if it were a VA, once — the scan asks that
    # question of millions of words and a per-word Python loop over the
    # segment list costs seconds on the 190 MB builds (Rush, Metallica).
    off = np.full(n, -1, dtype=np.int64)
    for vaddr, foff, filesz, _memsz in segs:
        if filesz <= 0:
            continue
        m = (words >= vaddr) & (words < vaddr + filesz)
        off[m] = foff + (words[m].astype(np.int64) - vaddr)

    table = off[:n - 2]
    count = words[1:n - 1].astype(np.int64)
    ok = words[2:n] == _REC_SIZE
    ok &= (count >= _MIN_REQUESTS) & (count < _MAX_REQUESTS)
    ok &= table >= 0
    ok &= table % 4 == 0
    ok &= table + count * _REC_SIZE + 4 <= len(fw)
    idx = np.flatnonzero(ok)
    if not len(idx):
        return None, None

    # Biggest first: the real table dwarfs its look-alikes, so the winner is
    # normally the first one examined, and the meaning test below is what
    # actually decides it.
    for i in idx[np.argsort(-count[idx], kind="stable")]:
        i = int(i)
        start, c = int(table[i]), int(count[i])
        end = start + c * _REC_SIZE
        last = start + (c - 1) * _REC_SIZE
        for field in range(_REC_SIZE // 4):
            # The last record's list is the FIRST one in the block, and the
            # block opens where the record array closes.
            if int(off[last // 4 + field]) != end:
                continue
            # Record 0's list is the last one, so it bounds the block.
            first = int(off[start // 4 + field])
            if first <= end or first % 4:
                break
            ids = words[end // 4: first // 4 + 1]
            ids = ids[ids != 0]
            # c lists, all but the trailing empty one carrying >= 1 sid.
            if len(ids) < c - 1:
                break
            # Multi-category titles (Rush, Metallica, Deadpool, ...) carry the
            # category in the high half of a sid, so it is the LOW half that
            # indexes fragments.
            low = int((ids & 0xFFFF).max())
            if low >= fragments:
                break
            if low * _SPAN_DEN < fragments * _SPAN_NUM:
                break
            return c, start
    return None, None


def count_sound_requests(fw, fragments):
    """The number of sound requests the game code defines, or ``None``."""
    return locate_sound_requests(fw, fragments)[0]
