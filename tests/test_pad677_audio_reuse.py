"""PAD-677: an Emulate Start (or a Write) after a small edit no longer encodes a James Bond project's
sounds again.

Three things made it encode everything (20-30 minutes on the reporter's PC):
  * the audio caches were keyed on the app's version, so every update dumped them all;
  * the appended records (a mode's own sounds and music) sat in idx order with their bodies
    right past the record array, so a mode gaining one six-second sound moved every body and
    every record after it in the firmware's chain - the songs were encoded again;
  * the final decode check decoded the same bytes again on every Start.
"""
import os
import random
import struct
import subprocess
import sys
import types

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
from pinball_decryptor.plugins.stern.spike2 import soundbank as SB

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_XOR = 0x5572ae9b


def _directory(count, md_off=0x1000):
    rnd = random.Random(677 + count)
    recs = bytearray(rnd.getrandbits(8) for _ in range(24 * count))
    for i in range(count):
        struct.pack_into("<I", recs, i * 24, 0x2000 + i * 0x800)
        struct.pack_into("<I", recs, i * 24 + 16, _XOR ^ (20000 + i * 1000))
    pad = MD.align16(24 * count) - 24 * count
    return MD.Directory(bytes(recs), count, md_off, 0x12345678,
                        pad_plain=b"\x5a" * pad, trailer=b"\xde\xad\xbe\xef")


def _edit(i, extra, body):
    return MD.GrowEdit(i, 20000 + i * 1000, 20000 + i * 1000 + extra, body)


# ---- the layout: one more sound moves no body ------------------------------------------------
def test_grow_slots_rounds_up_to_whole_steps():
    assert MD.grow_slots(0) == 0
    assert MD.grow_slots(1) == MD.GROW_SLOTS
    assert MD.grow_slots(MD.GROW_SLOTS) == MD.GROW_SLOTS
    assert MD.grow_slots(MD.GROW_SLOTS + 1) == 2 * MD.GROW_SLOTS


def test_a_sound_added_at_the_end_leaves_every_body_where_it_was():
    d = _directory(40)
    songs = [_edit(3, 900000, 2 << 20), _edit(7, 800000, 1 << 20)]
    _g, before = MD.plan_grow_records(d, songs)
    grown, after = MD.plan_grow_records(d, songs + [_edit(11, 4410, 8192)])
    assert [p.body_off for p in after[:2]] == [p.body_off for p in before]
    # and the room is past the new array, never over it
    assert after[0].body_off >= d.md_off + MD.tail_len(grown.count) + MD.BODY_PAD


def test_the_bank_size_estimate_is_the_layout_the_grow_makes():
    d = _directory(40)
    edits = [_edit(3, 900000, 2 << 20), _edit(7, 800000, 1 << 20), _edit(11, 4410, 8192)]
    _g, places = MD.plan_grow_records(d, edits)
    end = places[-1].body_off + places[-1].body_bytes
    assert E._grown_bank_bytes(d.md_off, d.count, [e.body_bytes for e in edits]) == end


def test_a_bank_of_the_modes_own_keeps_its_bodies_when_a_sound_joins():
    rec = bytearray(range(24))
    struct.pack_into("<I", rec, 16, 0x10 ^ 0xDEADBEEF)
    one = [SB.BankEdit(1890, bytes(rec), 0x10, 0x30000, 1 << 20)]
    _d, before = SB.plan_bank(one)
    _d, after = SB.plan_bank(one + [SB.BankEdit(1144, bytes(rec), 0x10, 0x300, 4096)])
    assert after[0].body_off == before[0].body_off
    # what a bank measures still matches what plan_bank lays out
    d2, _p = SB.plan_bank(one + [SB.BankEdit(1144, bytes(rec), 0x10, 0x300, 4096)])
    assert SB.bank_bytes([1 << 20, 4096]) == d2.md_off + MD.tail_len(2)


def test_the_longest_sounds_go_first_in_the_chain():
    grows = {124: (100, 170000), 1890: (6000, 21_000_000), 2149: (6000, 23_000_000),
             1144: (100, 158000), 136: (100, 158000)}
    assert E._chain_order(grows) == [2149, 1890, 124, 136, 1144]


def test_bank_edits_take_the_chain_order(monkeypatch):
    from pinball_decryptor.plugins.stern import bank_build as BB
    from pinball_decryptor.plugins.stern.spike2.emulator import BLOCK
    d = _directory(30)
    byidx = {i: {"idx": i, "length": 20000 + i * 1000, "chan": 1} for i in range(30)}
    out = BB.bank_edits({4: (0, 30000), 20: (0, 9_000_000), 9: (0, 50000)}, byidx, d)
    assert [e.idx for e in out] == [20, 9, 4]
    assert out[0].new_length == 9_000_000 + BLOCK


# ---- the key: the encoder's code, not the app's version --------------------------------------
def test_the_audio_cache_key_does_not_follow_the_app_version(monkeypatch, tmp_path):
    import pinball_decryptor
    gr = tmp_path / "game_real"
    gr.write_bytes(b"\x7fELF" + b"\0" * 64)
    a = E._audio_cache_base_key(str(gr), b"ident")
    monkeypatch.setattr(pinball_decryptor, "__version__", "9.99.0")
    assert E._audio_cache_base_key(str(gr), b"ident") == a
    assert E._audio_encoder_fingerprint().startswith("enc-")


def test_the_fingerprint_is_the_same_in_every_run():
    code = ("import sys; sys.path.insert(0, %r); "
            "from pinball_decryptor.plugins.stern import engine as E; "
            "print(E._audio_encoder_fingerprint())" % REPO)
    got = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          env=dict(os.environ, PYTHONHASHSEED=str(seed)),
                          timeout=120).stdout.strip()
           for seed in (1, 2, 3)}
    assert len(got) == 1 and next(iter(got)).startswith("enc-")


def _module(src):
    m = types.ModuleType("pad677_fake")
    exec(compile(src, "pad677_fake.py", "exec"), m.__dict__)
    return m


_SRC = '''
_SCALE = 3
_TAGS = frozenset(("a", "b", "c"))
_SENTINEL = object()

def _encode(x, flag=_SENTINEL):
    return _helper(x) * _SCALE if x in _TAGS else 0

def _helper(x):
    return len(x)

class _Kept:
    @property
    def size(self):
        return _helper("abc")

def _keep():
    return _Kept().size

def _unrelated():
    return "the Modes tab's words"
'''


def test_the_closure_digest_follows_what_the_encoder_reaches_and_nothing_else():
    base = E._code_closure_digest(_module(_SRC), ["_encode", "_keep"])
    # an edit the encoder never reaches, a comment, a moved line: the same
    assert E._code_closure_digest(_module(_SRC.replace("Modes tab's words", "Lights tab")),
                                  ["_encode", "_keep"]) == base
    assert E._code_closure_digest(_module("\n# a comment\n\n" + _SRC),
                                  ["_encode", "_keep"]) == base
    # a helper it calls, a constant it reads, a property it reaches: changed
    for a, b in (("return len(x)", "return len(x) + 1"), ("_SCALE = 3", "_SCALE = 4"),
                 ('frozenset(("a", "b", "c"))', 'frozenset(("a", "b"))')):
        assert E._code_closure_digest(_module(_SRC.replace(a, b)), ["_encode", "_keep"]) != base


def test_the_encoder_roots_are_all_there():
    assert all(callable(getattr(E, r, None)) for r in E._AUDIO_ENCODER_ROOTS)
    here = os.path.dirname(E.__file__)
    assert all(os.path.isfile(os.path.join(here, *m.split("/"))) for m in E._AUDIO_ENCODER_MODULES)


def test_sound_staging_is_not_redone_for_a_new_version(monkeypatch, tmp_path):
    import pinball_decryptor
    from pinball_decryptor.core import audio_slots as AS
    rep, orig = tmp_path / "rep.wav", tmp_path / "orig.wav"
    rep.write_bytes(b"RIFF1")
    orig.write_bytes(b"RIFF2")
    slot = types.SimpleNamespace(ext=".wav")
    a = AS._audio_recipe(slot, str(rep), str(orig), False)
    monkeypatch.setattr(pinball_decryptor, "__version__", "9.99.0")
    assert AS._audio_recipe(slot, str(rep), str(orig), False) == a


# ---- the final decode check -------------------------------------------------------------------
def _check(tmp_path, patches, params=None, **kw):
    gr = tmp_path / "game_real"
    if not gr.exists():
        gr.write_bytes(b"\x7fELF" + b"\0" * 64)
    params = params or [{"idx": 5, "body_off": 0x100, "length": 10, "scale": 3}]
    return E._FinalCheckCache.open(str(tmp_path / "proj"), str(gr), b"ident", patches,
                                   params, kw.get("no_restore", False), kw.get("scrap", ()))


def test_the_final_check_is_said_again_for_the_same_bytes_only(tmp_path, monkeypatch):
    lines = [("Final-bytes check: 1 replaced sound(s) decoded", "info")]
    c = _check(tmp_path, {0x100: b"body"})
    said = []
    assert not c.replay(lambda m, lv="info": said.append(m))
    c.store(lines)
    assert _check(tmp_path, {0x100: b"body"}).replay(lambda m, lv="info": said.append((m, lv)))
    assert said[0] == lines[0] and "not run again" in said[1][0]
    # another body, another table, another scrap set: checked again
    nope = lambda *a, **k: None                                  # noqa: E731
    assert not _check(tmp_path, {0x100: b"bodY"}).replay(nope)
    assert not _check(tmp_path, {0x100: b"body"},
                      [{"idx": 5, "body_off": 0x100, "length": 10, "scale": 4}]).replay(nope)
    assert not _check(tmp_path, {0x100: b"body"}, scrap={0x100}).replay(nope)
    monkeypatch.setenv("PAD_STERN_AUDIO_CACHE", "0")
    assert _check(tmp_path, {0x100: b"body"}) is None
