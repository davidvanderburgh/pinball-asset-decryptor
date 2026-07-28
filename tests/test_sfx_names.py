"""Sound-Test-menu SFX auto-naming: the pure-logic pieces (no emulator/card).

The firmware RE (resolver drive, container-key match) is exercised end-to-end
only with a real card, but the filename application, the Whisper skip, and the
graceful-degradation contract are synthetic-testable and are where regressions
would silently mis-name or double-name files.
"""
import os

import pytest

from pinball_decryptor.plugins.stern import engine
from pinball_decryptor.core import transcribe


# ---- _apply_sfx_names: rename bare decode WAVs to their menu names -----------

def _touch(path):
    with open(path, "wb") as f:
        f.write(b"RIFF....WAVE")


def _params(*idxs):
    return [{"idx": i, "length": 44100, "chan": 1} for i in idxs]


def test_apply_names_renames_bare_files(tmp_path):
    ad = tmp_path
    for i in (1, 2, 3):
        _touch(os.path.join(ad, "idx%04d.wav" % i))
    n = engine._apply_sfx_names(
        str(ad), {1: "SE FX ZEPPELIN JACKPOT", 3: "SE FX TOUR ADVANCE"},
        _params(1, 2, 3), duration_names=False)
    assert n == 2
    got = set(os.listdir(ad))
    assert "idx0001 - SE FX ZEPPELIN JACKPOT.wav" in got
    assert "idx0003 - SE FX TOUR ADVANCE.wav" in got
    assert "idx0002.wav" in got                       # unnamed left bare


def test_apply_names_respects_duration_prefix(tmp_path):
    # With length-prefix naming the decode file leads with the duration; the
    # name is appended after the idx, preserving the sort-by-length prefix.
    ad = tmp_path
    base = engine._wav_basename({"idx": 7, "length": 44100, "chan": 1},
                                duration_names=True)
    _touch(os.path.join(ad, base))
    engine._apply_sfx_names(str(ad), {7: "SE FX SONG AWARD"},
                            _params(7), duration_names=True)
    out = os.listdir(ad)
    assert out == [base[:-4] + " - SE FX SONG AWARD.wav"]
    assert out[0].startswith(base[:-4])               # duration prefix intact


def test_apply_names_sanitizes_illegal_chars(tmp_path):
    ad = tmp_path
    _touch(os.path.join(ad, "idx0001.wav"))
    engine._apply_sfx_names(str(ad), {1: 'SE FX A/B:C*?"<>|D'},
                            _params(1), duration_names=False)
    out = os.listdir(ad)[0]
    assert not any(c in out for c in '/\\:*?"<>|')
    assert out == "idx0001 - SE FX ABCD.wav"


def test_apply_names_skips_missing_and_empty(tmp_path):
    ad = tmp_path
    _touch(os.path.join(ad, "idx0001.wav"))
    # idx 2 named but never decoded (no bare file) -> skipped, no crash.
    assert engine._apply_sfx_names(
        str(ad), {1: "SE FX X", 2: "SE FX Y"}, _params(1, 2),
        duration_names=False) == 1
    assert engine._apply_sfx_names(str(ad), {}, _params(1), False) == 0


def test_apply_names_reextract_twin_removal_pattern(tmp_path):
    # A menu-named file must match the renamed-twin regex so a re-extract's
    # cleanup drops it (else duplicates accumulate).
    named = "idx0001 - SE FX ZEPPELIN JACKPOT.wav"
    assert engine._RENAMED_AUDIO_RE.match(named)
    named_dur = "00m01s000 - idx0001 - SE FX SONG AWARD.wav"
    assert engine._RENAMED_AUDIO_RE.match(named_dur)


# ---- Whisper skips already-named decode files -------------------------------

def test_find_wavs_skips_named_decode_files(tmp_path):
    for fn in ("idx0001.wav",                          # bare -> transcribe
               "00m01s000 - idx0002.wav",              # length-prefixed bare
               "idx0003 - SE FX TOUR ADVANCE.wav",     # menu-named -> skip
               "idx0004 - Welcome back!.wav",          # prior transcript -> skip
               "music_cat05_0007.wav",                 # bare bank -> transcribe
               "music_cat05_0008 - Kashmir.wav"):      # named bank -> skip
        _touch(os.path.join(tmp_path, fn))
    got = {os.path.basename(w) for w in transcribe._find_wavs(str(tmp_path))}
    assert got == {"idx0001.wav", "00m01s000 - idx0002.wav",
                   "music_cat05_0007.wav"}


# ---- _primary_idx / _select_names: op11 binding rules ------------------------

def _desc(pairs, size=0x50):
    """Synthetic descriptor: 0x0b opcode bytes at given offsets, each followed
    (at +4) by a little-endian key."""
    import struct
    d = bytearray(size)
    d[0] = 5
    for off, key in pairs:
        d[off] = 0x0B
        struct.pack_into("<I", d, off + 4, key)
    return bytes(d)


def test_primary_idx_takes_first_marker_at_or_after_9():
    """The descriptor's variable-length field moves the op11 marker between
    builds, so the primary asset is the FIRST marker at/after offset 9 — not
    whichever of the two fixed offsets 10/28 happens to hold one (v0.61.x
    checked only those and lost a third of the coverage)."""
    from pinball_decryptor.plugins.stern.spike2 import sfx_names
    keymap = {0xAAAA: 7, 0xBBBB: 9}
    assert sfx_names._primary_idx(_desc([(10, 0xAAAA), (40, 0xBBBB)]),
                                  keymap) == 7
    # Marker at 12 (the variable-length case) is just as valid as one at 10.
    assert sfx_names._primary_idx(_desc([(12, 0xAAAA), (40, 0xBBBB)]),
                                  keymap) == 7
    # First marker wins; later ones are references to other assets.
    assert sfx_names._primary_idx(_desc([(20, 0xBBBB), (40, 0xAAAA)]),
                                  keymap) == 9
    # A 0x0b before offset 9 is header, not an opcode.
    assert sfx_names._primary_idx(_desc([(4, 0xAAAA)]), keymap) is None
    assert sfx_names._primary_idx(_desc([(20, 0xCCCC)]), keymap) is None


def test_select_names_rules():
    """Menu order breaks ties; music-length records are never event-named."""
    from pinball_decryptor.plugins.stern.spike2 import sfx_names
    secs = {1: 0.2, 30: 285.0, 40: 1.0}
    entries = [
        (100, "SE FX BLIP", 1),
        # Led Zeppelin plays mode events into shared full-song masters, so an
        # event descriptor can own a 4:45 track.  No event name is right for
        # one; leaving it bare lets the music-ID pass title the actual song.
        (99, "SE FX SEQ ZEPPELIN AWARD", 30),
        # Two entries sharing one reused sample: first in menu order wins.
        (94, "SE FX SLING LEFT", 40),
        (93, "SE FX SLING RIGHT", 40),
    ]
    assert sfx_names._select_names(entries, secs) == {
        1: "SE FX BLIP", 40: "SE FX SLING LEFT"}


# ---- validate_name_map: the names have to describe the audio -----------------

def _lz_like_map():
    """A correct-shaped map: LIT variants longer than their UNLIT twins, and
    each named bank/series sharing one sound design (so one duration)."""
    name_map, secs, i = {}, {}, 0
    for bank, lit, unlit in (("ROCK", 1.17, 0.78), ("CENTER", 1.66, 1.07),
                             ("LED", 1.15, 1.03), ("LEFT", 2.36, 1.21)):
        for letter in "KCOR":
            for kind, d in (("LIT", lit), ("UNLIT", unlit)):
                i += 1
                name_map[i] = "SE FX %s BANK TARGET %s %s" % (bank, letter, kind)
                secs[i] = d
    for series, count, d in (("ELECTRIC MAGIC NOTE", 12, 1.16),
                             ("BONUS GOLD", 8, 0.30),
                             ("EM FRENZY SPINNER A", 10, 0.70)):
        for n in range(1, count + 1):
            i += 1
            name_map[i] = "SE FX %s %d" % (series, n)
            secs[i] = d
    return name_map, secs


def test_validate_accepts_a_coherent_map():
    from pinball_decryptor.plugins.stern.spike2 import sfx_names
    name_map, secs = _lz_like_map()
    ok, report = sfx_names.validate_name_map(name_map, secs, trials=400)
    assert ok
    assert "lit/unlit" in report and "group spread" in report


def test_validate_rejects_a_shifted_map():
    """The exact failure mode that shipped twice: the names are real and the
    slots are real, but every name sits one entry off."""
    from pinball_decryptor.plugins.stern.spike2 import sfx_names
    name_map, secs = _lz_like_map()
    idxs = sorted(name_map)
    shifted = dict(zip(idxs, [name_map[i] for i in idxs[1:] + idxs[:1]]))
    ok, _ = sfx_names.validate_name_map(shifted, secs, trials=400)
    assert not ok


def test_validate_abstains_without_enough_evidence():
    """Too few paired/grouped names to judge -> no verdict (empty report), and
    the caller falls back to the note-tonality check rather than dropping a
    real map."""
    from pinball_decryptor.plugins.stern.spike2 import sfx_names
    ok, report = sfx_names.validate_name_map(
        {1: "SE FX A", 2: "SE FX B"}, {1: 1.0, 2: 2.0}, trials=100)
    assert ok and report == ""


# ---- extract-level naming is on, with a kill switch -------------------------

def test_extract_naming_kill_switch(monkeypatch):
    monkeypatch.setenv("PINBALL_SFX_NAMES", "0")
    assert engine._load_or_build_sfx_names(
        None, None, None, [], lambda m, lvl: None) == {}


# ---- sound_test_names.csv sidecar (rename suggestions) -----------------------

def test_write_sound_test_names_sidecar(tmp_path, monkeypatch):
    """With auto-apply off, the verified menu LIST still ships as a sidecar
    so users can map names themselves (play a number in Sound Test, rename
    the slot that played — David's suggestion)."""
    from pinball_decryptor.plugins.stern.spike2 import sfx_names
    monkeypatch.setattr(
        sfx_names, "locate_menu_names",
        lambda raw: [(87, "SE FX SEQ BALL SAVE LIT"), (12, "SE FX BLIP")])
    gr = tmp_path / "game_real"
    gr.write_bytes(b"elf-ish")
    logs = []
    n = engine._write_sound_test_names(
        str(gr), str(tmp_path), lambda m, lvl: logs.append(m))
    assert n == 2
    import csv
    with open(tmp_path / engine.SOUND_TEST_NAMES_CSV,
              encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [(r["sound_number"], r["name"]) for r in rows] == [
        ("12", "SE FX BLIP"), ("87", "SE FX SEQ BALL SAVE LIT")]
    assert any("Sound Test menu list" in m for m in logs)
    # Menu-less titles: no file, no crash.
    monkeypatch.setattr(sfx_names, "locate_menu_names", lambda raw: [])
    assert engine._write_sound_test_names(str(gr), str(tmp_path / "x")) == 0


# ---- the menu -> sound-id indirection, on a synthetic firmware ---------------
#
# This is where every wrong name so far came from, and both traps are silent:
# a map built off a shifted index still resolves, still looks plausible, and
# still names real files.  The fixture pins the two of them.

_VA = 0x50000
_SEG_OFF = 0x1000


def _fake_fw(names, node_ids, lists_by_id, pad_words=1):
    """A minimal ARM ELF carrying a Sound-Test menu.

    *lists_by_id* maps node id -> sid list.  Ids count from the END of the
    block, so id 0 is written last; *pad_words* extra zero words then sit
    between the block and the pairs array, as they do on real firmware.
    """
    import struct
    body = bytearray()

    def va_of(off):
        return _VA + off

    # string pool
    str_va = {}
    for n in names:
        str_va[n] = va_of(len(body))
        body += n.encode() + b"\x00"
    while len(body) % 4:
        body += b"\x00"
    body += struct.pack("<I", 0xFFFFFFFF)      # stops the block walk-back

    # sound-id lists, highest id first (ids are counted from the end)
    for i in sorted(lists_by_id, reverse=True):
        for sid in lists_by_id[i]:
            body += struct.pack("<I", sid)
        body += struct.pack("<I", 0)           # NUL terminator
    body += struct.pack("<I", 0) * pad_words

    pairs_at = len(body)
    body += b"\x00" * (8 * len(names))
    table_at = len(body)
    for n in names:
        body += struct.pack("<I", str_va[n]) * 5 + struct.pack("<I", 0)
    for p, n in enumerate(names):
        struct.pack_into("<2I", body, pairs_at + p * 8,
                         va_of(table_at + p * 24), node_ids[p])

    ph = struct.pack("<8I", 1, _SEG_OFF, _VA, _VA, len(body), len(body), 5, 4)
    sh = struct.pack("<10I", 0, 3, 0, 0, _SEG_OFF - 1, 1, 0, 0, 1, 0)
    hdr = bytearray(b"\x00" * 0x34)
    hdr[0:8] = b"\x7fELF\x01\x01\x01\x00"
    struct.pack_into("<HHI", hdr, 0x10, 2, 40, 1)          # type, machine, ver
    struct.pack_into("<I", hdr, 0x1C, 0x34)                # e_phoff
    struct.pack_into("<I", hdr, 0x20, 0x34 + 32)           # e_shoff
    struct.pack_into("<HHHHH", hdr, 0x2A, 32, 1, 40, 1, 0)
    raw = bytearray(hdr + ph + sh)
    raw += b"\x00" * (_SEG_OFF - len(raw) - 1) + b"\x00"
    return bytes(raw + body)


def _menu_fixture(pad_words=1, category_sid=False):
    """10 SE FX entries whose node ids are deliberately NOT their positions."""
    names = ["SE FX ALPHA", "SE FX BRAVO", "SE FX CHARLIE", "SE FX DELTA",
             "SE FX ECHO", "SE FX FOXTROT", "SE FX GOLF", "SE FX HOTEL",
             "SE FX INDIA", "SE FX JULIET", "INVALID"]
    node_ids = [17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 0]
    lists_by_id = {0: []}
    for k, nid in enumerate(node_ids[:-1]):
        lists_by_id[nid] = [700 + k]                       # sid = 700 + position
    for gap in range(1, 8):                                # ids the menu skips
        lists_by_id.setdefault(gap, [900 + gap])
    if category_sid:
        # A low id (so it is met early walking back) holding a sound id from a
        # non-zero category: high half = category, low half = sub-id.
        lists_by_id[3] = [(1 << 16) | 3]
    return names, _fake_fw(names, node_ids, lists_by_id, pad_words)


def test_locate_menu_sids_follows_the_indirection():
    from pinball_decryptor.plugins.stern.spike2 import sfx_names
    names, fw = _menu_fixture()
    got = sfx_names.locate_menu_sids(fw)
    assert got == [(700 + k, n) for k, n in enumerate(names[:-1])]


@pytest.mark.parametrize("pad_words", [0, 1, 2, 3])
def test_list_block_padding_never_shifts_the_map(pad_words):
    """Trailing zero words after list id 0 split into further empty lists, and
    because ids count from the END each stray one renumbers everything.  The
    map must not move with the padding."""
    from pinball_decryptor.plugins.stern.spike2 import sfx_names
    names, fw = _menu_fixture(pad_words)
    assert sfx_names.locate_menu_sids(fw) == [
        (700 + k, n) for k, n in enumerate(names[:-1])]


def test_multi_category_sound_ids_dont_truncate_the_block():
    """The multi-category titles (Rush, Metallica, Deadpool, ...) carry the
    category in a sound id's high half, so ids run past 0x10000.  Bounding the
    block scan by VALUE stopped it at the first such id — Rush found its menu
    and then resolved nothing at all — so the scan counts list terminators."""
    from pinball_decryptor.plugins.stern.spike2 import sfx_names
    names, fw = _menu_fixture(category_sid=True)
    assert sfx_names.locate_menu_sids(fw) == [
        (700 + k, n) for k, n in enumerate(names[:-1])]


def test_displayed_number_is_a_reversed_position_not_the_sid():
    """sound_test_names.csv must keep printing the number the MACHINE shows,
    which is (N-1) - position over the whole table (OCR-verified) and has
    nothing to do with the resolver sid the naming path uses."""
    from pinball_decryptor.plugins.stern.spike2 import sfx_names
    names, fw = _menu_fixture()
    n = len(names)
    assert sfx_names.locate_menu_names(fw) == [
        ((n - 1) - p, nm) for p, nm in enumerate(names[:-1])]


# ---- build_name_map graceful degradation ------------------------------------

def test_locate_menu_names_empty_on_junk():
    # No SE FX menu present -> empty list, never raises.
    assert engine.__dict__  # sanity
    from pinball_decryptor.plugins.stern.spike2 import sfx_names
    assert sfx_names.locate_menu_names(b"\x00" * 4096) == []
    assert sfx_names.locate_menu_names(b"not an elf") == []


def test_build_name_map_never_raises_on_bad_emu(tmp_path):
    from pinball_decryptor.plugins.stern.spike2 import sfx_names

    junk = tmp_path / "game_real"
    junk.write_bytes(b"not an elf" * 512)

    class _Bad:
        _gr_path = str(junk)
    # No key0 (empty / key-less params) and un-parsable firmware both yield {}
    # rather than an exception — extract keeps plain idx names.
    assert sfx_names.build_name_map(_Bad(), []) == {}
    assert sfx_names.build_name_map(_Bad(), [{"idx": 0}]) == {}
    assert sfx_names.build_name_map(_Bad(), [{"idx": 0, "key0": 123}]) == {}
