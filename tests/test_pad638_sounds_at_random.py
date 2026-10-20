"""PAD-638 (an owner: "random audio variants ... like a jukebox"): a slot's files in turn (PAD-565)
can play AT RANDOM - each play any of them but the one it played last.

The same files, records and ``turn`` lines; the project's record keeps the slots in ``sound_modes``
``random``, sounds.cfg names each one's record key on a ``random`` line, and pad_mode_runtime.c
"AT RANDOM" picks. Every road the files in turn travel (mod transfer, mod packs, the music modes
file, an extract of the card) carries the choice with them."""

import os
import re
import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import sound_modes as SMo

TANK = "audio/idx0002 - SE GZ FX TANK FIRE DOUBLE FAST 1.wav"
BOC = "audio/idx2095 - music - Blue \u00d6yster Cult - Godzilla.wav"
HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.path.join(HERE, "..", "tools", "spike2_emu", "modes", "sdk")
RUNTIME = os.path.join(SDK, "pad_mode_runtime.c")


# ---- the project's record ------------------------------------------------------------------------
def test_the_record_keeps_which_slots_play_at_random():
    m = SMo.clean({"turns": {TANK: ["b.wav"], BOC: ["c.wav"]}, "random": [TANK, "gone.wav", 7]})
    assert m.random == {TANK}
    assert SMo.to_json(m)["random"] == [TANK]
    assert SMo.clean(SMo.to_json(m)).random == {TANK}
    # only a slot with files in turn can play them at random
    assert SMo.clean({"random": [TANK]}).random == set()
    assert "random" not in SMo.to_json(SMo.clean({"turns": {TANK: ["b.wav"]}}))


# ---- the runtime's table and the card's record -----------------------------------------------------
def test_the_runtime_table_names_each_random_slot_s_key():
    slot, b = bytes.fromhex("9ad919226f1d0000"), bytes(range(8))
    text = SMo.cfg_text(0, 0, [], True, turns=[(2, slot, b)], randoms=[slot])
    assert text.splitlines()[1:] == ["only", "turn\t2\t9ad919226f1d0000\t0001020304050607",
                                     "random\t9ad919226f1d0000"]


def test_the_card_record_brings_the_random_choice_back():
    m = SMo.clean({"turns": {TANK: ["C:/x/Tank B.wav"], BOC: ["C:/x/Song B.wav"]}, "random": [TANK]})
    used = [{"rel": TANK, "slot": 2, "mode": SMo.turn_mode(2), "host": 40, "db": 0, "lines": 1},
            {"rel": BOC, "slot": 2095, "mode": SMo.turn_mode(2), "host": 41, "db": 0, "lines": 1}]
    rec = SMo.read_card_record(SMo.cfg_text(0, 0, [], True, record=SMo.card_record(m, used)))
    assert rec["random"] == [{"slot": 2, "rel": TANK}]
    # a slot none of whose files landed is not named
    used[0]["lines"] = 0
    rec = SMo.read_card_record(SMo.cfg_text(0, 0, [], True, record=SMo.card_record(m, used)))
    assert "random" not in rec


def test_the_build_writes_a_random_line_for_the_slot_s_key(tmp_path):
    params = [{"idx": 2, "findkey": b"S" * 8}, {"idx": 40, "findkey": b"H" * 8, "grown": True},
              {"idx": 2095, "findkey": b"B" * 8}, {"idx": 41, "findkey": b"J" * 8, "grown": True}]
    m = SMo.clean({"turns": {TANK: ["b.wav"], BOC: ["c.wav"]}, "random": [TANK]})
    used = [{"rel": TANK, "slot": 2, "mode": SMo.turn_mode(2), "host": 40},
            {"rel": BOC, "slot": 2095, "mode": SMo.turn_mode(2), "host": 41}]
    logs = []
    path = E._sound_modes_cfg("gr", {}, params, {}, used, m, True, str(tmp_path),
                              lambda t, lvl="info": logs.append(t))
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert ("random\t%s" % (b"S" * 8).hex()) in lines
    assert ("random\t%s" % (b"B" * 8).hex()) not in lines           # the other one takes turns
    assert "#random\t2\t" + TANK in lines


def test_the_runtime_reads_the_random_line_and_picks_at_random():
    with open(RUNTIME, encoding="utf-8") as f:
        c = f.read()
    assert 'str_eq(f[0], "random")' in c and "sndt_random_line(f[1])" in c
    assert c.count("t->pick = sndt_next(t);") == 2          # at the lookup and at the worker
    nxt = c[c.index("static unsigned char sndt_next("):]
    nxt = nxt[:nxt.index("\n}\n")]
    assert "clipv_rand()" in nxt and "if (!t->random)" in nxt


# ---- the pick, compiled out of pad_mode_runtime.c -------------------------------------------------
_HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
@STATE@
@FUNCS@
int main(int argc, char **argv)
{
    struct sndt t = {0};
    unsigned i, n = (unsigned)atoi(argv[2]);
    t.n = (unsigned char)atoi(argv[1]);
    t.random = (unsigned char)atoi(argv[3]);
    for (i = 0; i < n; i++) { t.pick = sndt_next(&t); t.plays++; printf("%u ", t.pick); }
    printf("\n");
    return 0;
}
"""


def _c_function(src, signature_re):
    m = re.search(signature_re, src)
    assert m, signature_re
    i, depth = src.index("{", m.start()), 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[m.start():j + 1]
    raise AssertionError(signature_re)


@pytest.fixture(scope="module")
def picks(tmp_path_factory):
    if os.name == "nt" or sys.platform == "darwin":
        pytest.skip("the harness needs a host ELF C toolchain")
    cc = next((c for c in ("gcc", "cc", "clang") if shutil.which(c)), None)
    if not cc:
        pytest.skip("no host C compiler")
    with open(RUNTIME, encoding="utf-8") as f:
        src = f.read()
    struct = src[src.index("struct sndt {"):src.index("};", src.index("struct sndt {")) + 2]
    state = ("#define SNDT_MAX 16\n" + struct + "\nstatic unsigned clipv_rng;\n")
    funcs = [_c_function(src, r) for r in (r"static unsigned clipv_rand\(void\)",
                                            r"static unsigned char sndt_next\(")]
    d = tmp_path_factory.mktemp("sndt")
    (d / "h.c").write_text(_HARNESS.replace("@STATE@", state).replace("@FUNCS@", "\n".join(funcs)))
    exe = d / "h"
    r = subprocess.run([cc, "-std=gnu17", "-O1", "-Wall", "-o", str(exe), str(d / "h.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    def run(n, plays, random):
        out = subprocess.run([str(exe), str(n), str(plays), str(int(random))], capture_output=True,
                             text=True, check=True).stdout.split()
        return [int(x) for x in out]
    return run


def test_in_turn_plays_its_own_first_then_each_in_order(picks):
    assert picks(3, 7, False) == [0, 1, 2, 0, 1, 2, 0]


def test_at_random_never_plays_one_twice_running_and_plays_them_all(picks):
    got = picks(5, 400, True)
    assert all(0 <= k < 5 for k in got)
    assert all(a != b for a, b in zip(got, got[1:]))
    assert set(got) == set(range(5))
    assert got[:12] != [0, 1, 2, 3, 4, 0, 1, 2, 3, 4, 0, 1]   # not in turn


# ---- carried: mod routes, the music modes file, back out of a card ---------------------------------
def test_the_mod_routes_carry_the_random_choice_with_the_slot():
    from pinball_decryptor.core import staged_changes as SC
    data = {"sound_modes": {"names": [], "slots": {}, "turns": {TANK: ["b.wav"], BOC: ["c.wav"]},
                            "random": [TANK]}}
    rec = SC.sound_modes_of(data)
    assert rec["random"] == [TANK]
    other = "audio/idx0007 - SE TANK.wav"
    tgt = {"sound_modes": {"names": [], "slots": {}, "turns": {other: ["mine.wav"]}}}
    assert SC.merge_sound_modes(tgt, {"names": [], "slots": {other: rec["slots"][TANK]},
                                      "random": [other]}) == 1
    assert tgt["sound_modes"]["random"] == [other]
    assert SMo.clean(tgt["sound_modes"]).random == {other}
    # a record giving the slot files in turn and not at random takes the choice off
    assert SC.merge_sound_modes(tgt, {"names": [], "slots": {other: {"t2": "x.wav"}}}) == 1
    assert "random" not in tgt["sound_modes"]


def test_a_mod_pack_carries_the_random_choice():
    from pinball_decryptor.core import modpack
    rec, files, gone = modpack.pack_sound_modes({"names": [], "slots": {TANK: {"t2": __file__}},
                                                 "random": [TANK, BOC]})
    assert rec["random"] == [TANK] and not gone


def test_the_transfer_plan_carries_the_random_choice(tmp_path):
    from pinball_decryptor.core import mod_transfer as MT
    tgt = {}
    sm = {"matched": [{"src_rel": TANK, "tgt_rel": "audio/idx0009 - TANK.wav",
                       "repl": {"t2": "b.wav"}}], "names": [], "levels": {}, "random": [TANK]}
    record = {MT._SOUND_MODES_KEY: {}}
    MT._apply_sound_modes(tgt, {MT._SOUND_MODES_KEY: sm}, record, {}, False)
    assert tgt["sound_modes"]["random"] == ["audio/idx0009 - TANK.wav"]


def test_the_random_choice_goes_to_the_music_modes_file_and_comes_back(tmp_path):
    from pinball_decryptor.core import staged_changes as SC
    from pinball_decryptor.plugins.stern import media_share as MS
    from tests.test_webui_audio import _wav as wav
    src = str(tmp_path / "src")
    wav(os.path.join(src, *TANK.split("/")), seconds=0.3)
    mine = str(tmp_path / "mine" / "Tank B.wav")
    wav(mine, seconds=0.4, amp=700)
    SC.save(src, {"sound_modes": {"names": [], "slots": {}, "turns": {TANK: [mine]}, "random": [TANK]}})
    path = str(tmp_path / "modes.zip")
    MS.save_music_modes(src, path)
    dst = str(tmp_path / "dst")
    wav(os.path.join(dst, *TANK.split("/")), seconds=0.3)
    got = MS.load_music_modes(dst, path)
    assert got["record"]["random"] == [TANK]
    assert MS.put_music(dst, got["record"]) == 1
    assert SMo.load(dst).random == {TANK}


def test_an_extract_of_the_card_has_the_random_choice_back(tmp_path):
    from pinball_decryptor.plugins.stern import media_share as MS
    from tests.test_webui_audio import _wav as wav
    proj = str(tmp_path / "proj")
    wav(os.path.join(proj, *TANK.split("/")), seconds=0.3)
    wav(os.path.join(proj, "audio", "idx0040 - SE X.wav"), seconds=0.5, amp=900)
    m = SMo.clean({"turns": {TANK: [r"C:\mine\Tank B.wav"]}, "random": [TANK]})
    used = [{"rel": TANK, "slot": 2, "mode": SMo.turn_mode(2), "host": 40, "db": 0, "lines": 1}]
    cfg = SMo.cfg_text(0, 0, [], True, record=SMo.card_record(m, used))
    assert MS.readback("card.raw", proj, padmode={"sounds.cfg": cfg.encode()})["music"] == 1
    assert SMo.load(proj).random == {TANK}


# ---- the Audio tab ----------------------------------------------------------------------------------
def test_the_audio_tab_switches_a_slot_s_files_to_random_and_back(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _project, _sidecar, _wav as wav
    from tests.webui_harness import web_app
    rel = "audio/idx0001 - Jackpot.wav"
    monkeypatch.setattr(SMo, "offer", lambda project, rels, probe=True: ("not here", {}))
    monkeypatch.setattr(SMo, "offer_turns", lambda project, rels, probe=True: (
        "", {r: "" for r in rels}))
    proj = _project(tmp_path)
    b = str(tmp_path / "mine" / "Jackpot B.wav")
    wav(b)

    def entry(w):
        items = w.call("audio.menu", rel, [rel])
        return next((i for i in items if str(i.get("label", "")).startswith("Play ")
                     and i.get("submenu")), None)

    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        assert [s["label"] for s in entry(w)["submenu"]] == ["Add a sound to play in turn…"]
        assert w.call("audio.menu_action", "turn_order:1", rel) is False    # no files yet
        w.answers.append(b)
        assert w.call("audio.menu_action", "turn_add", rel) is True
        order = [s for s in entry(w)["submenu"] if s.get("radio")]
        assert [(s["label"], s["checked"]) for s in order] == [("One after another", True),
                                                                ("At random", False)]
        assert w.call("audio.menu_action", "turn_order:1", rel) is True
        assert _sidecar(proj)["sound_modes"]["random"] == [rel]
        e = entry(w)
        assert e["label"] == "Play at random (2 sounds)"
        assert [s["checked"] for s in e["submenu"] if s.get("radio")] == [False, True]
        r = next(r for r in w.state("audio")["rows"] if r["k"] == rel)
        assert r["tn"] == 2 and r["tr"] is True
        assert r["tn_tip"].startswith("Each time the game plays this sound it plays one of these at "
                                      "random, never the same one twice in a row: 1. ")
        assert w.call("audio.menu_action", "turn_order:1", rel) is False    # already
    with web_app(tmp_path / "again", mfr="stern", era="spike2") as w:
        _open(w, proj)
        assert next(r for r in w.state("audio")["rows"] if r["k"] == rel).get("tr") is True
        assert w.call("audio.menu_action", "turn_order:0", rel) is True
        assert "random" not in _sidecar(proj)["sound_modes"]
        w.call("audio.menu_action", "turn_order:1", rel)
        assert w.call("audio.menu_action", "turn_off:2", rel) is True       # its last file
        assert "random" not in (_sidecar(proj).get("sound_modes") or {})


# ---- round 2: each file in turn has a loudness of its own -----------------------------------------
def test_each_file_in_turn_keeps_its_own_loudness():
    m = SMo.clean({"turns": {TANK: ["b.wav", "c.wav"]},
                   "turn_levels": {TANK: {"2": 4, "3": 0, "4": 9, "x": 2}, BOC: {"2": 3}}})
    assert m.turn_levels == {TANK: {2: 4}}           # file 4 does not exist, 0 is no offset
    assert m.level(TANK, SMo.turn_mode(2)) == 4 and m.level(TANK, SMo.turn_mode(3)) == 0
    assert SMo.to_json(m)["turn_levels"] == {TANK: {"2": 4}}
    assert SMo.clean(SMo.to_json(m)).turn_levels == m.turn_levels
    # a record without levels of its own (music modes from before) still gives turns theirs
    assert SMo.clean({"turns": {TANK: ["b.wav"]}, "turn_levels": {TANK: {"2": -6}}}).level(
        TANK, SMo.turn_mode(2)) == -6


def test_the_build_gives_each_file_in_turn_its_own_loudness(tmp_path, monkeypatch):
    from tests.test_pad565_sounds_in_turn import _p, _wav
    from pinball_decryptor.plugins.stern.spike2.emulator import BLOCK
    made = {s: _wav(tmp_path / ("conv_" + s), 0.5) for s in ("b.wav", "c.wav")}
    monkeypatch.setattr(SMo, "convert", lambda project, rel, mode, src, log=None: made[src])
    params = [_p(2, 44100 + BLOCK), _p(10, 44100 + BLOCK), _p(11, 44100 + BLOCK)]
    m = SMo.clean({"turns": {TANK: ["b.wav", "c.wav"]}, "turn_levels": {TANK: {"3": -5}}})
    _e, _g, used = E._sound_modes_grow(str(tmp_path), params, {}, {}, m, lambda *a, **k: None)
    assert [u["db"] for u in used] == [0, -5]
    rec = SMo.read_card_record(SMo.cfg_text(0, 0, [], True, record=SMo.card_record(
        m, [dict(u, lines=1) for u in used])))
    assert [t["db"] for t in rec["turns"]] == [0, -5]


def test_the_routes_carry_each_file_in_turn_s_loudness(tmp_path):
    from pinball_decryptor.core import staged_changes as SC
    data = {"sound_modes": {"names": [], "slots": {}, "turns": {TANK: ["b.wav", "c.wav"]},
                            "turn_levels": {TANK: {"3": -5}}}}
    rec = SC.sound_modes_of(data)
    assert rec["levels"] == {TANK: {"t3": -5}}
    other = "audio/idx0007 - SE TANK.wav"
    tgt = {}
    assert SC.merge_sound_modes(tgt, {"names": [], "slots": {other: rec["slots"][TANK]},
                                      "levels": {other: rec["levels"][TANK]}}) == 1
    assert tgt["sound_modes"]["turn_levels"] == {other: {"3": -5}}
    assert tgt["sound_modes"]["levels"] == {}
    assert SMo.clean(tgt["sound_modes"]).level(other, SMo.turn_mode(3)) == -5
    # a file whose number shifted (a gap in the record) keeps its own level
    SC.merge_sound_modes(tgt, {"names": [], "slots": {other: {"t2": "x.wav", "t5": "y.wav"}},
                               "levels": {other: {"t5": 7}}})
    assert tgt["sound_modes"]["turns"][other] == ["x.wav", "y.wav"]
    assert tgt["sound_modes"]["turn_levels"] == {other: {"3": 7}}


def test_the_music_modes_file_and_the_card_carry_each_file_s_loudness(tmp_path):
    from pinball_decryptor.core import staged_changes as SC
    from pinball_decryptor.plugins.stern import media_share as MS
    from tests.test_webui_audio import _wav as wav
    src = str(tmp_path / "src")
    wav(os.path.join(src, *TANK.split("/")), seconds=0.3)
    mine = str(tmp_path / "mine" / "Tank B.wav")
    wav(mine, seconds=0.4, amp=700)
    SC.save(src, {"sound_modes": {"names": [], "slots": {}, "turns": {TANK: [mine]},
                                  "turn_levels": {TANK: {"2": 6}}}})
    path = str(tmp_path / "modes.zip")
    MS.save_music_modes(src, path)
    dst = str(tmp_path / "dst")
    wav(os.path.join(dst, *TANK.split("/")), seconds=0.3)
    got = MS.load_music_modes(dst, path)
    assert MS.put_music(dst, got["record"]) == 1
    assert SMo.load(dst).turn_levels == {TANK: {2: 6}}
    # an extract of a card built with it
    proj = str(tmp_path / "proj")
    wav(os.path.join(proj, *TANK.split("/")), seconds=0.3)
    wav(os.path.join(proj, "audio", "idx0040 - SE X.wav"), seconds=0.5, amp=900)
    m = SMo.clean({"turns": {TANK: [r"C:\mine\Tank B.wav"]}, "turn_levels": {TANK: {"2": 6}}})
    used = [{"rel": TANK, "slot": 2, "mode": SMo.turn_mode(2), "host": 40, "db": 6, "lines": 1}]
    cfg = SMo.cfg_text(0, 0, [], True, record=SMo.card_record(m, used))
    assert MS.readback("card.raw", proj, padmode={"sounds.cfg": cfg.encode()})["music"] == 1
    assert SMo.load(proj).turn_levels == {TANK: {2: 6}}


def test_the_audio_tab_sets_each_file_s_loudness(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _project, _sidecar, _wav as wav
    from tests.webui_harness import web_app
    from pinball_decryptor.webui import compat
    rel = "audio/idx0001 - Jackpot.wav"
    monkeypatch.setattr(SMo, "offer", lambda project, rels, probe=True: ("not here", {}))
    monkeypatch.setattr(SMo, "offer_turns", lambda project, rels, probe=True: (
        "", {r: "" for r in rels}))
    proj = _project(tmp_path)
    b, c = str(tmp_path / "mine" / "Jackpot B.wav"), str(tmp_path / "mine" / "Jackpot C.wav")
    wav(b)
    wav(c)

    def labels(w):
        items = w.call("audio.menu", rel, [rel])
        e = next(i for i in items if str(i.get("label", "")).startswith("Play ") and i.get("submenu"))
        return [s["label"] for s in e["submenu"] if not s.get("sep")]

    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        for f in (b, c):
            w.answers.append(f)
            assert w.call("audio.menu_action", "turn_add", rel) is True
        assert "Loudness of sound 2 (0 dB)…" in labels(w)
        monkeypatch.setattr(compat.simpledialog, "askstring", lambda *a, **k: "-4")
        assert w.call("audio.menu_action", "turn_level:3", rel) is True
        assert _sidecar(proj)["sound_modes"]["turn_levels"] == {rel: {"3": -4}}
        assert "Loudness of sound 3 (-4 dB)…" in labels(w)
        r = next(r for r in w.state("audio")["rows"] if r["k"] == rel)
        assert "3. Jackpot C.wav at -4 dB" in r["tn_tip"]
        # in the Replacement player, the loudness box is that file's own
        import time
        w.call("audio.select", [rel])
        time.sleep(0.6)                                           # the row loads 250 ms on
        w.drain()
        assert w.call("audio.menu_action", "turn_play:2", rel) is True
        st = w.state("audio")
        assert st["level_label"] == "Sound 2's loudness:" and st["level"] == "0"
        assert w.call("audio.set_level", rel, "3") is not False
        assert _sidecar(proj)["sound_modes"]["turn_levels"] == {rel: {"2": 3, "3": -4}}
        # taking off sound 2 moves sound 3 (and its loudness) up to 2
        assert w.call("audio.menu_action", "turn_off:2", rel) is True
        assert _sidecar(proj)["sound_modes"]["turn_levels"] == {rel: {"2": -4}}
        assert w.state("audio")["level_label"] == ""
