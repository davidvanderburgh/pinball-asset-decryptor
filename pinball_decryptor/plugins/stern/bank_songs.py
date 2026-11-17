"""PAD-1378: music modes for the songs in a Spike 2 game's own sound banks.

Seven Spike 2 titles keep their licensed songs in ``image-scNN.bin`` banks beside ``image.bin``
(Deadpool, Dungeons & Dragons, Foo Fighters, James Bond 1.06, John Wick, Metallica, Rush; an
extract decodes them as ``music_catNN_NNNN.wav``, NNNN the record's index in bank NN).  The game
plays such a song by a sound id of the bank's own, ``NN << 16 | n``, which its request lists hold
as they hold any other: Deadpool LE 1.16's lists name 89 of them.  The resolver takes ``n`` as a
fragment of the bank's own table, whose descriptor names the bank's records by key, the same
script an ``image.bin`` sound id has (several records: an intro, then the song looped).

A music mode's file for such a song therefore goes the way PAD-608 sends a mode file into a sound
bank of this app's: its own record in a bank of ours, one fragment for each of the game's bank
sound ids that plays the song, and a ``bsid`` line per fragment, so the runtime points the request
at our id while the setting says that mode (``pad_mode_runtime.c`` ``blist_play``, unchanged: it
swaps whole 32-bit ids).  Each fragment's descriptor is the game's own for that id with every play
of the song's record (and of the parts it plays with it) naming the file's record
(:func:`mode_descriptor`), so the file plays in place of the whole sound, looping where the song
loops.

What each of the game's bank sound ids plays is read here (:func:`read_banks`) through the game's
own loader and resolver, on the emulator, as the extract's Sound Test naming does
(:func:`.spike2.category.bank_sound_test_names`).
"""
import collections
import struct

#: Room each descriptor read gets (a bank's descriptors run to their end op well inside it)
DESC_READ = 0x100


class BankSongs:
    """One of the game's banks: *rows* ``{record: derived row}`` (``length``, ``chan``,
    ``key0``) and *plays* ``{sound id: (descriptor, extent, [record, ...])}`` - each of the
    bank's sound ids, its de-whitened descriptor (the first *extent* bytes its own) and the
    records its plays name, in order (``None`` for a key that names none of them)."""

    def __init__(self, cat, rows, plays):
        self.cat = int(cat)
        self.rows = dict(rows)
        self.plays = dict(plays)

    def sids_of(self, record):
        """The bank's sound ids whose descriptor plays *record*."""
        return sorted(s for s, (_d, _e, recs) in self.plays.items() if int(record) in recs)


def play_records(desc, extent, key0_to_idx):
    """The records descriptor *desc*'s plays name (its first *extent* bytes), by the first four
    bytes of each play's key (the rest carries bits the game fills from the sound id's bank)."""
    from . import engine as E
    out = []
    for o, pl in E._own_payloads(bytes(desc), extent):
        out.append(key0_to_idx.get(struct.unpack_from("<I", bytes(pl), 0)[0]))
    return out


def read_banks(gr_path, img_path, banks, log, cancel=None):
    """``{cat: BankSongs}`` for the game's banks *banks* ``{cat: local path}``: each derived on a
    fresh emulator (its records), then loaded by the game's own loader on another, every fragment
    of its table resolved by the game's own resolver and its descriptor read.  A bank that cannot
    be read is left out (logged); ``{}`` when the build's bank loader cannot be driven."""
    from .spike2 import category as C
    from .spike2 import sfx_names as SN
    from . import engine as E
    if not banks:
        return {}
    files = sorted((int(c), p) for c, p in banks.items())
    rev = C._find_revalidate(gr_path, img_path, files, log)
    if rev is None:
        return {}
    out = {}
    for cat, path in files:
        if cancel is not None and cancel():
            break
        try:
            emu = C.CatEmu(gr_path, img_path)
            try:
                emu.boot()
                emu.set_category_file(path)
                rows = emu._derive_cat(cat, rev)
            finally:
                emu.close()
            if not rows:
                raise RuntimeError("its records could not be read")
            with open(path, "rb") as f:
                nfrag = struct.unpack_from("<I", f.read(0x68), 0x5c)[0]
            emu = C.CatEmu(gr_path, img_path)
            try:
                emu.boot()
                emu.register_bank(cat, path, revalidate=rev)
                resolver, ans = SN._find_resolver(emu)
                if resolver is None:
                    raise RuntimeError("the game's descriptor resolver could not be located")
                d2, mm, got = emu.DESC2, emu._mm_cat, {}
                for n in range(int(nfrag)):
                    sid = (cat << 16) | n
                    emu.mu.mem_write(ans, b"\x00" * 0x40)
                    st = emu.call(resolver, (sid, ans), limit=5_000_000)
                    if st[0] != "ok" or not d2 <= st[1] < d2 + emu.cat2size:
                        continue
                    off = st[1] - d2
                    ks = struct.unpack("<I", bytes(emu.mu.mem_read(ans, 4)))[0] - emu.VF2_VA
                    if not 0 <= ks < 0x3F00:
                        continue
                    body = bytes(mm[off:off + DESC_READ])
                    vf2 = bytes(emu.mu.mem_read(emu.VF2_VA + ks, len(body)))
                    got[sid] = (off, bytes(a ^ b for a, b in zip(body, vf2)))
            finally:
                emu.close()
            keys = collections.Counter(r.get("key0") for r in rows)
            k0 = {r["key0"]: r["idx"] for r in rows if r.get("key0") is not None and keys[r["key0"]] == 1}
            ext = E._descriptor_extents([o for o, _d in got.values()], DESC_READ)
            plays = {}
            for sid, (off, desc) in got.items():
                if desc[:1] != b"\x05":
                    continue
                plays[sid] = (desc, ext[off], play_records(desc, ext[off], k0))
            out[cat] = BankSongs(cat, {r["idx"]: r for r in rows}, plays)
        except Exception as e:  # noqa: BLE001 - that bank's songs play their own
            log("Music modes: the songs of the game's sound bank image-sc%02d.bin could not be "
                "read (%s); their files are left out." % (cat, e), "warning")
    return out


def mode_descriptor(desc, extent, key, units):
    """The game's bank descriptor *desc* (its own bytes the first *extent*) for a sound id that
    plays a song with a music mode's file, rewritten so that file's bank record (key *key*,
    verbatim, as a bank's descriptor names its record) plays in place of the whole sound: the
    first play names it, a later play in the same stretch of the script as the first is dropped
    with its wait (an intro's song after it), and a play in a loop the first is not in names it
    too (a song that looped after its intro now loops the file).  Its declared length is the
    file's (*units*, 1/4000 s) for each play kept.  ``None`` when the script holds an op the
    engine does not know (:func:`.engine._desc_ops`)."""
    from . import engine as E
    from .spike2 import soundbank as SB
    ops = E._desc_ops(desc, extent)
    if ops is None or not any(b[0] == 0x0b for b in ops):
        return None
    out, mark, first, kept, drop_wait = [], 0, None, 0, False
    for b in ops:
        if drop_wait:
            drop_wait = False
            if b[0] == 0x11:
                continue
        if b[0] == 0x07:
            mark += 1
        if b[0] == 0x0b:
            if first is None:
                first = mark
            elif mark == first:
                drop_wait = True
                continue
            b = b[:4] + bytes(key)
            kept += 1
        out.append(b)
    head = bytearray(desc[:E._DESC_OPS_AT])
    struct.pack_into("<I", head, E._DESC_DUR_OFF, max(1, int(units) * kept) & 0xFFFFFF)
    body = bytes(head) + b"".join(out)
    return (body + bytes(max(0, SB.DESC_SLOT - len(body))))[:SB.DESC_SLOT]
