"""PAD-800: a Spike 2 replacement SHORTER than the sound it replaces ends at its own length.

Fitted in place it was padded with silence to the stock length, and the game played it for all of
that (its descriptor declares the stock duration): a callout held its voice through the silence, a
song sat silent before it looped or the next one started.  With "Allow replacements longer or
shorter than the original" it takes the longer sounds' road instead: a record of its own length
appended, the play tables re-pointed and the declared duration moved DOWN.  Proven on the rig with
Iron Maiden LE 1.18 (C:/tmp/PAD-800): the game let a 0.5 s callout and an 8 s song go when their
audio ended, where the padded build held them for 2.04 s and 206 s.
"""
import os
import struct
import wave

import pytest

pytest.importorskip("numpy")

from pinball_decryptor.plugins.stern import engine as E          # noqa: E402
from pinball_decryptor.plugins.stern.spike2.emulator import BLOCK  # noqa: E402
from tests.test_spike2_masterdir import (                          # noqa: E402
    _FAKE_LENGTH_XOR, _edit, _fake_directory, _fake_length)


def _wav(path, seconds):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * int(seconds * 44100))
    return str(path)


def _row(idx, seconds, **kw):
    return dict({"idx": idx, "body_off": 0x1000 * (idx + 1), "length": int(seconds * 44100) + BLOCK,
                 "chan": 1, "key0": idx}, **kw)


def _said():
    lines = []
    return lines, lambda m, lvl="info": lines.append((lvl, m))


# --------------------------------------------------------------------------
# which replacements end early
# --------------------------------------------------------------------------
def test_a_clip_a_tenth_of_a_second_short_or_more_is_given_its_own_length(tmp_path):
    byidx = {0: _row(0, 2.0), 1: _row(1, 2.0), 2: _row(2, 2.0)}
    fits = {0: _wav(tmp_path / "a.wav", 0.5),        # 1.5 s short
            1: _wav(tmp_path / "b.wav", 1.95),       # 50 ms short: padded, not worth a record
            2: _wav(tmp_path / "c.wav", 1.9),        # exactly 0.1 s short
            9: _wav(tmp_path / "d.wav", 0.5)}        # no such sound
    got = E._shorter_audio_edits(byidx, fits, str(tmp_path))
    assert set(got) == {0, 2}
    assert got[0] == (2 * 44100, int(0.5 * 44100))
    assert got[2][0] - got[2][1] == E._SHORTER_MIN


def test_a_multi_band_sound_keeps_its_length(tmp_path):
    byidx = {0: _row(0, 2.0, stride=12)}           # Led Zeppelin's stride-12 records
    assert E._shorter_audio_edits(byidx, {0: _wav(tmp_path / "a.wav", 0.5)}, str(tmp_path)) == {}


def test_a_sound_with_files_in_turn_keeps_its_length():
    class _Modes(object):
        turns = {"audio/idx0007 - SPEECH.wav": ["x.wav"]}
    lines, log = _said()
    kept = E._shorter_kept_for_turns({7: (88200, 22050), 8: (88200, 22050)}, _Modes(), log)
    assert set(kept) == {8}
    assert "files in turn" in lines[0][1] and "padded with silence" in lines[0][1]


# --------------------------------------------------------------------------
# the record and the play tables
# --------------------------------------------------------------------------
def test_the_grow_planner_appends_a_shorter_record():
    from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
    d = _fake_directory(5)
    short = _fake_length(2) - 9000
    grown, places = MD.plan_grow_records(d, [_edit(2, _fake_length(2), short, 4096)])
    assert grown.count == 6 and grown.records[:24 * 5] == d.records
    assert grown.length_word(5) ^ _FAKE_LENGTH_XOR == short
    assert places[0].length == short
    with pytest.raises(MD.MasterDirError):           # its own length: written in place
        MD.plan_grow_records(d, [_edit(2, _fake_length(2), _fake_length(2), 4096)])


def test_the_declared_duration_moves_down_by_the_shrink():
    old = bytes.fromhex("9af08101571e00a0")
    new = bytes.fromhex("11223344571e00a0")
    dks = b"\x55\x66\x77\x88"
    sites = [E._DescSite(429, 0x500, bytes(8), old, 0x4F0, dks, 8160),
             E._DescSite(430, 0x600, bytes(8), bytes(8), 0x5F0, dks, 123)]
    stock_len, new_len = 90177, 22250
    params = [{"idx": 49, "grown": True, "stock_findkey": old, "findkey": new,
               "length": new_len, "stock_length": stock_len}]
    writes, expect = E._plan_descriptor_repoint(params, sites, mask=0xE0001FFF, family=True)
    shrink = E._duration_units_emitted(new_len) - E._duration_units(stock_len)
    assert shrink < 0
    assert expect == {429: ({new}, 8160 + shrink)}
    assert writes[0x4F0] == bytes(a ^ b for a, b in zip(struct.pack("<I", 8160 + shrink), dks))
    # the new duration ends where the audio does
    assert expect[429][1] * 44100 // 4000 <= new_len - BLOCK


# --------------------------------------------------------------------------
# what the log says
# --------------------------------------------------------------------------
def test_a_closed_gate_says_the_shorter_ones_are_padded():
    msg, level = E._padded_notice({3: (88200, 22050)}, "off")
    assert "padded with silence" in msg and "idx 3 (0.50 s, padded to 2.00 s)" in msg
    assert level == "info"


def test_a_budget_cut_names_shorter_and_longer_ones_apart():
    msg, _l = E._trimmed_notice({1: (44100, 88200), 2: (88200, 22050)}, "full")
    assert "idx 1 (2.00 s cut to 1.00 s)" in msg
    assert "idx 2 (0.50 s, padded to 2.00 s)" in msg
    msg, _l = E._trimmed_notice({2: (88200, 22050)}, "full")
    assert "cut" not in msg and "padded" in msg
    assert E._kept_in_slot((88200, 22050)).endswith("padded with silence")
    assert E._kept_in_slot((22050, 88200)) == "the replacement is trimmed to fit"


def test_the_patch_audit_owns_an_appended_body_a_word_below_its_record():
    """Every longer (and now shorter) sound on Iron Maiden LE 1.18 warned "matches no sound's
    write window -- please report this build log": its appended body's window starts one word
    below the record, as any window may, and the audit took that only for stock sounds."""
    p = {"idx": 49, "body_off": 0x4e2d8a4e, "length": 132500, "chan": 1, "grown": True}
    lines, log = _said()
    body = b"\x00" * (2 * (132500 + E._APPENDED_TAIL))
    assert E._audit_audio_patches([p], {0x4e2d8a4c: body}, log) == 0
    assert "every byte inside its own sound's window" in lines[-1][1]


# --------------------------------------------------------------------------
# the option says so
# --------------------------------------------------------------------------
def test_the_option_and_its_help_name_shorter_replacements():
    import pinball_decryptor.webui as webui_pkg
    from pinball_decryptor.webui.help_content import HELP_CONTENT
    js = os.path.join(os.path.dirname(webui_pkg.__file__), "static", "js", "tabs", "audio.js")
    with open(js, encoding="utf-8") as f:
        src = f.read()
    assert 'label="Allow replacements longer or shorter than the original' in src
    assert "Shorter ones too." in src
    help_ = dict(HELP_CONTENT["Replace Audio"])["Longer replacements (Advanced Audio Options)"]
    assert "0.1 s shorter than the original" in help_
    why = E._audio_grow_gate(False)[1]
    assert '"Allow replacements longer or shorter than the original"' in why


# --------------------------------------------------------------------------
# the wait after the play moves with it
# --------------------------------------------------------------------------
#: sid 915's descriptor on Iron Maiden LE 1.18 (request 429, "SPEECH: LOOP JACKPOT 3"), plain:
#: duck the music, play the record, wait 6579 (1601 short of the declared 8180), bring it back
SPEECH = bytes.fromhex(
    "050201f41f0000020008090028000000140000001400010000000902200000001900000019000100"
    "00000b000000a154ca47c9f1f10310b319000009003c00000014000000ecffffff0000090218000000")


def test_the_speech_wait_is_found_after_its_play():
    (off, _pl), = E._own_payloads(SPEECH)
    assert E._wait_after(SPEECH, off) == (off + 9, 6579)
    assert E._wait_after(SPEECH, off, extent=off + 10) is None


def test_the_repoint_moves_the_wait_with_the_declared_duration():
    """Rig, Iron Maiden LE 1.18: with only the declared duration moved, a 0.5 s call for the
    2.04 s one held its channel 3.45 s (the stock call 1.88 s) and a 0.5 s one for a 3.67 s call
    7.1 s, the script still waiting out the stock gap."""
    mask = 0xFC0003FF
    old = E._play_key(SPEECH[46:54], 915, mask)
    new = E._play_key(bytes.fromhex("23740a47c9f1a982"), 915, mask)
    (off, _pl), = E._own_payloads(SPEECH)
    ks = bytes(range(7, 7 + len(SPEECH)))
    wait_at, wait = E._wait_after(SPEECH, off)
    site = E._DescSite(915, 0x9000 + off, ks[off:off + 8], SPEECH[46:54], 0x9003, ks[3:7], 8180,
                       0x9000 + wait_at, ks[wait_at:wait_at + 4], wait)
    params = [{"idx": 49, "grown": True, "stock_findkey": old, "findkey": new,
               "length": 22250, "stock_length": 90177}]
    writes, expect = E._plan_descriptor_repoint(params, [site], mask=mask, family=True)
    moved = expect[915][1] - 8180
    got = bytes(a ^ b for a, b in zip(writes[0x9000 + wait_at], ks[wait_at:wait_at + 4]))
    assert struct.unpack("<I", got)[0] == 6579 + moved
    assert expect[915][1] - struct.unpack("<I", got)[0] == 1601      # the gap kept


def test_a_site_without_a_wait_writes_only_its_key_and_duration():
    site = E._DescSite(1, 0x100, bytes(8), bytes(8), 0x40, bytes(4), 400)
    assert site.wait is None and E._moved_wait_write(site, -100) == {}


def test_a_bank_descriptor_keeps_the_gap_to_its_end():
    from pinball_decryptor.plugins.stern import bank_build as BB
    out = BB.compose_descriptor(SPEECH, bytes(8), 2000, False)
    (off, _pl), = E._own_payloads(out)
    assert struct.unpack_from("<I", out, 3)[0] == 2000
    assert E._wait_after(out, off)[1] == 2000 - 1601
    # a sequence's record moves its own wait
    mask = 0xFC0003FF
    k = E._play_key(SPEECH[46:54], 915, mask)
    seq = BB.seq_descriptor(SPEECH, 915, {k: bytes(8)}, {k: -6180}, mask)
    assert E._wait_after(seq, off)[1] == 6579 - 6180


def test_a_music_mode_file_on_a_speech_sound_keeps_the_gap():
    mask = 0xFC0003FF
    k = E._play_key(SPEECH[46:54], 915, mask)
    host = bytes.fromhex("23740a47c9f1a982")
    host = E._play_key(host, 915, mask)
    d, done = E._mode_descriptor_swaps(SPEECH, 915, mask, {k: (host, 2000, 8180)})
    (off, _pl), = E._own_payloads(d)
    assert done == {k}
    assert struct.unpack_from("<I", d, 3)[0] == 2000 and E._wait_after(d, off)[1] == 399
