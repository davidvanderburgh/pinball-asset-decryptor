"""PAD-641 (an owner of a James Bond 007: "Every other stern spike 2 has attract mode flipper sound samples
except James Bond"): ATTRACT FLIPPER SOUNDS - the project's own files, played in turn when a flipper button
is pressed in attract mode.

The game has no sound there to replace, so the files ride a CARRIER, a request the game never plays (the
modes' own calls' road): each is a record of its own, built as a file in turn is, and ``attract`` /
``afile`` lines in sounds.cfg tell pad_mode_runtime.c "attract flipper sounds" the carrier, its record's
key, the flipper buttons' switch ids and each file's key. Emulator-proven on Bond LE 1.06 (a card built
by Write's own code: three presses in attract played the three files in order, a press in a game played
nothing)."""

import os

import pytest

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import sound_modes as SMo

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, "..", "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c")
CARRIER = "audio/idx0046.wav"


# ---- the project's record ------------------------------------------------------------------------
def test_the_record_keeps_the_files_in_order_and_at_most_sixteen():
    files = ["C:/mine/Bond %d.wav" % k for k in range(20)]
    m = SMo.clean({"attract": files + ["", 7]})
    assert m.attract == files[:SMo.ATTRACT_MAX] and SMo.ATTRACT_MAX == 16
    assert m.any and not m.count and not m.turns
    assert SMo.to_json(m) == {"names": [], "slots": {}, "attract": files[:16]}
    assert SMo.clean(SMo.to_json(m)).attract == files[:16]
    assert not SMo.clean({"attract": []}).any and SMo.to_json(SMo.clean({})) is None


def test_the_build_puts_them_on_the_carriers_slot_once_it_has_one():
    m = SMo.clean({"attract": ["a.wav", "b.wav"], "turns": {"audio/idx0002.wav": ["t.wav"]}})
    assert m.files() == [("audio/idx0002.wav", SMo.turn_mode(2), "t.wav")]     # no carrier yet
    m.attract_rel = CARRIER
    assert m.files()[1:] == [(CARRIER, SMo.attract_mode(1), "a.wav"), (CARRIER, SMo.attract_mode(2), "b.wav")]
    a = SMo.attract_mode(2)
    # built as a file in turn is (cut to its carrier's length, its loudness), said in their own words
    assert SMo.is_turn(a) and SMo.is_attract(a) and not SMo.is_attract(SMo.turn_mode(16))
    assert SMo.attract_of(a) == 2 and m.name(a) == "in attract" and m.level(CARRIER, a) == 0
    assert SMo.who(a) == "Attract flipper sounds" and SMo.what(CARRIER, a) == "flipper sound 2"
    assert SMo.tag(CARRIER, a) == "flipper sound 2 in attract"
    assert SMo.when(a) == "at a flipper button press in attract (sound 2)"


def test_the_runtime_table_names_the_carrier_the_buttons_and_each_file():
    a, b = bytes(range(8)), bytes(range(8, 16))
    text = SMo.cfg_text(0, 0, [], True, attract={"request": 1057, "key": bytes.fromhex("04abd19370050000"),
                                                 "switches": [64, 63], "files": [(a, 800), (b, 1250)]})
    assert text.splitlines()[1:] == ["only", "attract\t1057\t04abd19370050000\t64,63",
                                     "afile\t1\t0001020304050607\t800", "afile\t2\t08090a0b0c0d0e0f\t1250"]
    assert "attract" not in SMo.cfg_text(0, 0, [], True, attract=None)


def test_the_card_record_brings_them_back():
    m = SMo.clean({"attract": [r"C:\mine\Shaken.wav", "C:/mine/Bond.wav"]})
    used = [{"rel": CARRIER, "slot": 46, "mode": SMo.attract_mode(k), "host": 80 + k, "db": 0, "lines": 1}
            for k in (1, 2)]
    rec = SMo.read_card_record(SMo.cfg_text(0, 0, [], True, record=SMo.card_record(m, used)))
    assert rec["files"] == [] and "turns" not in rec
    assert rec["attract"] == [{"k": 1, "slot": 46, "host": 81, "rel": CARRIER, "name": "Shaken.wav"},
                              {"k": 2, "slot": 46, "host": 82, "rel": CARRIER, "name": "Bond.wav"}]
    used[1].update(bank=1, bank_idx=7)
    rec = SMo.read_card_record(SMo.cfg_text(0, 0, [], True, record=SMo.card_record(m, used)))
    assert SMo.card_bank_records(rec) == {1: {7}}


# ---- which builds ---------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["james_bond_le_1_06", "james_bond_pro_1_06", "james_bond_60th_le_1_11"])
def test_every_bond_build_can_have_them(name):
    assert SMo.attract_refusal(MP.profile(name)) == ""


def _no_drain(monkeypatch):
    """PAD-645: every shipped port maps the switch drain now: The Beatles' read without it"""
    real = MP.read_port

    def read(path):
        port = real(path)
        if os.path.basename(path).startswith("beatles-"):
            port["site"].pop("switch_drain", None)
        return port

    monkeypatch.setattr(MP, "read_port", read)


def test_a_build_whose_port_does_not_map_the_switch_drain_says_why(monkeypatch):
    _no_drain(monkeypatch)
    prof = MP.profile("beatles_1_29")
    assert SMo.attract_refusal(prof) == SMo.NO_ATTRACT % (
        prof.label, "the app has not found where its game program reads the switches or looks its sounds up")
    assert SMo.attract_refusal(None) == SMo.NO_TITLE_ATTRACT


def test_the_flipper_buttons_are_found_by_the_games_own_names(monkeypatch):
    from pinball_decryptor.plugins.stern import portgen as G
    from pinball_decryptor.plugins.stern import portswitch as PS
    monkeypatch.setattr(G, "Elf", lambda b: b)
    sws = [{"id": 56, "name": "UP LEFT FLIPPER EOS"}, {"id": 63, "name": "RIGHT FLIPPER BUTTON"},
           {"id": 64, "name": "LEFT  FLIPPER BUTTON"}, {"id": 65, "name": "UP LEFT FLIPPER BUTTON"}]
    monkeypatch.setattr(PS, "switches", lambda elf, info=None: sws)
    assert SMo.flipper_buttons(b"elf") == [64, 63]                  # left, right; never an upper one
    monkeypatch.setattr(PS, "switches", lambda elf, info=None: [{"id": 57, "name": "R FLIPPER BUTTON"},
                                                                {"id": 58, "name": "L FLIPPER BUTTON"}])
    assert SMo.flipper_buttons(b"elf") == [58, 57]                  # Jurassic Park's (the pin), Star Wars ELG
    monkeypatch.setattr(PS, "switches", lambda elf, info=None: [])
    assert SMo.flipper_buttons(b"elf") == []


# ---- the runtime ----------------------------------------------------------------------------------
def test_the_runtime_reads_the_lines_and_hooks_the_drain_and_the_lookup_once():
    with open(RUNTIME, encoding="utf-8") as f:
        c = f.read()
    assert 'str_eq(f[0], "attract")' in c and 'str_eq(f[0], "afile")' in c
    assert "#define ATT_FILES       16" in c
    # the record lookup takes the playing file's key first; the drain's edges reach it as well as the shots
    assert "if (att_live && r[1] && att_lookup(r)) return;" in c
    assert "if (att_live) att_edge(id, level, flags, pol, mask);" in c
    assert c.count("hook(e->addr, on_switch_edge)") == 2 and c.count("edge_hooked = hook(e->addr") == 2
    # only in attract (the mode mask's attract bit, no game), not while the last one still plays
    assert "if (!(mask & att.attract_bit) || pm_in_game()) return;" in c
    assert "if (att.plays && (long)(att.until - now) > 0) return;" in c
    assert 'pm_port_value("mode_mask_attract", 0x10)' in c
    # it works on a card with no modes (`only`): armed with the sounds.cfg it rides
    assert "att_arm();" in c and "if (n_sndt || n_bsid || att.n) return;" in c


# ---- the build ------------------------------------------------------------------------------------
def _p(idx, length, chan=1, **kw):
    return dict({"idx": idx, "length": length, "chan": chan, "findkey": bytes([idx % 256]) * 8}, **kw)


def _wav(path, seconds, rate=44100, chans=1):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(chans)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * chans * int(seconds * rate))
    return str(path)


def test_the_carrier_is_the_first_whose_sound_the_build_leaves_alone(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_sounds as MSo
    from pinball_decryptor.plugins.stern import mode_write as MW
    prof = MP.profile("james_bond_le_1_06")
    calls = MSo.carriers(prof.game_dir, prof.version).calls
    slots = {calls[0]: 46, calls[1]: 47, calls[2]: 48}
    def record(elf, head, params, sites, r, mask):
        if r not in slots:
            raise MW.ModeWriteError("request %d names no record" % r)
        return slots[r]

    monkeypatch.setattr(MW, "request_record", record)
    monkeypatch.setattr(E, "_desc_key_mask", lambda params, sites, log=None: 0xF0000FF6)
    monkeypatch.setattr(SMo, "flipper_buttons", lambda elf: [64, 63])
    for name in ("game", "image.bin"):
        (tmp_path / name).write_bytes(b"\0" * 64)
    proj = tmp_path / "proj"
    (proj / "audio").mkdir(parents=True)
    for i in (46, 48):
        _wav(proj / "audio" / ("idx%04d.wav" % i), 0.1)
    m = SMo.clean({"attract": ["a.wav"]})
    logs = []
    log = lambda t, lvl="info": logs.append(t)                    # noqa: E731
    # idx 46 is replaced by this build, 47 is not in the project: 48 it is
    E._attract_carrier(str(tmp_path / "game"), str(tmp_path / "image.bin"), [], [], str(proj), {46: "x.wav"},
                       m, prof, [], log)
    assert m.attract_rel == "audio/idx0048.wav"
    assert m.attract_plan == {"request": calls[2], "slot": 48, "switches": [64, 63]}
    assert logs == ["Attract flipper sounds: 1 file(s) ride request %d (sound idx 48, which the game never "
                    "plays); the flipper buttons are switches 64 and 63." % calls[2]]
    # none left: the files are left out, and the log says why
    m, logs[:] = SMo.clean({"attract": ["a.wav"]}), []
    E._attract_carrier(str(tmp_path / "game"), str(tmp_path / "image.bin"), [], [], str(proj),
                       {46: "x.wav", 48: "y.wav"}, m, prof, [], log)
    assert m.attract == [] and m.attract_rel == "" and len(logs) == 1
    assert logs[0].startswith("Attract flipper sounds: 1 file(s) for the flipper buttons in attract mode are "
                              "left out of this build: ")


def test_each_file_goes_on_the_card_as_a_record_of_its_own_cut_to_its_carrier(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern.spike2.emulator import BLOCK
    made = {"a.wav": _wav(tmp_path / "conv_a.wav", 0.5), "b.wav": _wav(tmp_path / "conv_b.wav", 3.0)}
    monkeypatch.setattr(SMo, "convert", lambda project, rel, mode, src, log=None: made[src])
    params = [_p(46, 44100 + BLOCK), _p(10, 44100 + BLOCK), _p(11, 2 * 44100), _p(12, 4 * 44100)]
    m = SMo.clean({"attract": ["a.wav", "b.wav"]})
    m.attract_rel = CARRIER
    logs = []
    edits, _grows, used = E._sound_modes_grow(str(tmp_path), params, {}, {}, m,
                                              lambda t, lvl="info": logs.append(t), longer_ok=True)
    assert [(u["mode"], u["slot"]) for u in used] == [(SMo.attract_mode(1), 46), (SMo.attract_mode(2), 46)]
    assert len({u["host"] for u in used}) == 2 and 46 not in edits       # the carrier keeps its record
    assert used[0]["frames"] == 22050 and used[1]["frames"] < 2 * 44100  # the long one cut to the carrier
    assert all(t.startswith("Attract flipper sounds: ") for t in logs)
    assert any("flipper sound 2" in t and "is cut to its slot's" in t for t in logs)
    assert E._SMo_tag(CARRIER, SMo.attract_mode(2)) == "flipper sound 2 in attract"


def test_the_table_names_each_file_s_record_key_and_length(tmp_path):
    params = [{"idx": 46, "findkey": b"C" * 8}, {"idx": 80, "findkey": b"A" * 8, "grown": True},
              {"idx": 81, "findkey": b"B" * 8}]
    m = SMo.clean({"attract": ["a.wav", "b.wav"]})
    m.attract_rel, m.attract_plan = CARRIER, {"request": 1057, "slot": 46, "switches": [64, 63]}
    used = [{"rel": CARRIER, "slot": 46, "mode": SMo.attract_mode(1), "host": 80, "frames": 35280},
            {"rel": CARRIER, "slot": 46, "mode": SMo.attract_mode(2), "host": 81, "frames": 44100}]
    logs = []
    got = E._attract_lines(params, used, m, lambda t, lvl="info": logs.append(t))
    assert got == {"request": 1057, "key": b"C" * 8, "switches": [64, 63], "files": [(b"A" * 8, 800)]}
    assert used[0]["lines"] == 1 and "lines" not in used[1]
    assert logs == ["Attract flipper sounds: flipper sound 2 is left out: its record did not come out of the "
                    "grown bank."]
    assert E._attract_lines(params, [], m, logs.append) is None


def test_a_game_that_cannot_have_them_leaves_them_out_and_keeps_the_rest(tmp_path, monkeypatch):
    from pinball_decryptor.core import staged_changes as SC
    from pinball_decryptor.plugins.stern import mode_write as MW
    monkeypatch.setattr(MW, "host_refusal", lambda: "")
    _no_drain(monkeypatch)
    monkeypatch.setattr(SMo, "project_title", lambda project, probe=False: MP.profile("beatles_1_29"))
    SC.save(str(tmp_path), {"sound_modes": {"attract": ["a.wav"]}})
    logs = []
    got = E._sound_modes_for_build(str(tmp_path), False, lambda t, lvl="info": logs.append((t, lvl)),
                                   ext4_available=lambda: (True, ""))
    assert got == (None, None)
    assert logs == [("Attract flipper sounds: 1 file(s) for the flipper buttons in attract mode are left out "
                     "of this build: " + SMo.attract_refusal(MP.profile("beatles_1_29")), "warning")]
    # Bond: they go on, with no music mode (Bond has none) and files in turn beside them
    monkeypatch.setattr(SMo, "project_title", lambda project, probe=False: MP.profile("james_bond_pro_1_06"))
    SC.save(str(tmp_path), {"sound_modes": {"attract": ["a.wav"], "turns": {"audio/idx0002.wav": ["t.wav"]}}})
    logs.clear()
    modes, prof = E._sound_modes_for_build(str(tmp_path), False, lambda t, lvl="info": logs.append((t, lvl)),
                                           ext4_available=lambda: (True, ""))
    assert prof.game_dir == "james_bond_pro" and modes.attract == ["a.wav"] and modes.turns
    assert ("Found 1 sound(s) for the flipper buttons in attract mode.", "info") in logs


# ---- the Audio tab ----------------------------------------------------------------------------------
def test_the_audio_tab_adds_plays_and_takes_off_the_flipper_sounds(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _project, _sidecar, _wav as wav
    from tests.webui_harness import web_app
    monkeypatch.setattr(SMo, "offer", lambda project, rels, probe=True: ("not here", {}))
    monkeypatch.setattr(SMo, "offer_turns", lambda project, rels, probe=True: ("not here", {}))
    monkeypatch.setattr(SMo, "offer_attract", lambda project, probe=True: "")
    proj = _project(tmp_path)
    a, b = str(tmp_path / "mine" / "Shaken.wav"), str(tmp_path / "mine" / "The name's Bond.wav")
    wav(a)
    wav(b)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        st = w.state("audio")["attract"]
        assert st["files"] == [] and st["why"] == "" and st["max"] == 16
        for f in (a, b):
            w.answers.append(f)
            assert w.call("audio.attract_action", "add") is True
        assert _sidecar(proj)["sound_modes"]["attract"] == [os.path.normpath(a), os.path.normpath(b)]
        st = w.state("audio")["attract"]
        assert st["files"] == ["Shaken.wav", "The name's Bond.wav"]
        assert st["tip"][-1] == "In turn: 1. Shaken.wav; 2. The name's Bond.wav."
        assert w.call("audio.attract_action", "play:2") is True
        assert w.state("audio")["panes"]["rep"]["name"] == "Attract flipper sound 2: The name's Bond.wav"
        assert w.call("audio.attract_action", "off:1") is True
        assert _sidecar(proj)["sound_modes"]["attract"] == [os.path.normpath(b)]
        assert w.call("audio.attract_action", "off:5") is False
    # a fresh session has them back
    with web_app(tmp_path / "again", mfr="stern", era="spike2") as w:
        _open(w, proj)
        assert w.state("audio")["attract"]["files"] == ["The name's Bond.wav"]


def test_a_game_without_them_says_why_and_adds_none(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _project
    from tests.webui_harness import web_app
    from pinball_decryptor.webui import compat
    monkeypatch.setattr(SMo, "offer", lambda project, rels, probe=True: ("not here", {}))
    monkeypatch.setattr(SMo, "offer_turns", lambda project, rels, probe=True: ("not here", {}))
    monkeypatch.setattr(SMo, "offer_attract", lambda project, probe=True: "Not on this game.")
    said = []
    monkeypatch.setattr(compat.messagebox, "showinfo", lambda title, text, **k: said.append((title, text)))
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, _project(tmp_path))
        assert w.state("audio")["attract"]["why"] == "Not on this game."
        assert w.call("audio.attract_action", "add") is False
        assert w.call("audio.attract_action", "why") is True
    assert said == [("Attract flipper sounds", "Not on this game.")]


def test_the_page_draws_the_button_from_the_tabs_state():
    path = os.path.join(HERE, "..", "pinball_decryptor", "webui", "static", "js", "tabs", "audio.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "s.attract ? html`<${AttractButton}" in js
    assert 'call("audio.attract_action", "add")' in js and "Why not on this game?" in js


# ---- carried: mod routes, the music modes file, back out of a card ---------------------------------
def test_the_mod_routes_carry_them_as_they_are():
    from pinball_decryptor.core import staged_changes as SC
    data = {"sound_modes": {"names": [], "slots": {}, "attract": ["a.wav", "b.wav"]}}
    rec = SC.sound_modes_of(data)
    assert rec == {"names": [], "slots": {}, "levels": {}, "attract": ["a.wav", "b.wav"]}
    tgt = {"sound_modes": {"names": [], "slots": {}, "attract": ["mine.wav"],
                           "turns": {"audio/idx0002.wav": ["t.wav"]}}}
    assert SC.merge_sound_modes(tgt, rec) == 1
    assert tgt["sound_modes"]["attract"] == ["a.wav", "b.wav"]               # the record's
    assert tgt["sound_modes"]["turns"] == {"audio/idx0002.wav": ["t.wav"]}   # the rest kept
    assert SMo.clean(tgt["sound_modes"]).attract == ["a.wav", "b.wav"]
    # a record without them leaves the project's own
    tgt = {"sound_modes": {"names": [], "slots": {}, "attract": ["mine.wav"]}}
    SC.merge_sound_modes(tgt, {"names": ["", "Two"], "slots": {}})
    assert tgt["sound_modes"]["attract"] == ["mine.wav"]


def test_the_transfer_plan_carries_them(tmp_path):
    from pinball_decryptor.core import mod_transfer as MT
    plan = {"sound_modes": {"matched": [], "remapped": [], "names": [], "levels": {}, "attract": ["a.wav"]}}
    tgt, record = {}, {"sound_modes": {}}
    MT._apply_sound_modes(tgt, plan, record, {}, False)
    assert tgt["sound_modes"]["attract"] == ["a.wav"]


def test_they_go_to_the_music_modes_file_and_come_back(tmp_path):
    from pinball_decryptor.core import staged_changes as SC
    from pinball_decryptor.plugins.stern import media_share as MS
    from tests.test_webui_audio import _wav as wav
    src = str(tmp_path / "src")
    wav(os.path.join(src, "audio", "idx0002.wav"), seconds=0.3)
    a, b = str(tmp_path / "mine" / "Shaken.wav"), str(tmp_path / "mine" / "Bond.wav")
    wav(a, seconds=0.4, amp=700)
    wav(b, seconds=0.5, amp=900)
    SC.save(src, {"sound_modes": {"names": [], "slots": {}, "attract": [a, b]}})
    path = str(tmp_path / "modes.zip")
    assert MS.save_music_modes(src, path) == {"slots": 0, "files": 2, "gone": [], "attract": 2}
    dst = str(tmp_path / "dst")
    wav(os.path.join(dst, "audio", "idx0002.wav"), seconds=0.3)
    got = MS.load_music_modes(dst, path)
    folder = os.path.join(dst, "Music mode files")
    assert got["record"]["attract"] == [os.path.join(folder, "Shaken.wav"), os.path.join(folder, "Bond.wav")]
    assert MS.put_music(dst, got["record"]) == 1
    assert SMo.load(dst).attract == got["record"]["attract"]
    # a project with its own keeps them when the record comes in beside them
    SC.save(dst, {"sound_modes": {"attract": ["C:/my.wav"]}})
    assert MS.put_music(dst, got["record"], keep_own=True) == 0
    assert SMo.load(dst).attract == ["C:/my.wav"]


def test_an_extract_of_the_card_has_them_back(tmp_path):
    from pinball_decryptor.plugins.stern import media_share as MS
    from tests.test_webui_audio import _wav as wav
    proj = str(tmp_path / "proj")
    wav(os.path.join(proj, "audio", "idx0046.wav"), seconds=0.3)
    wav(os.path.join(proj, "audio", "idx0084.wav"), seconds=0.5, amp=900)
    wav(os.path.join(proj, "audio", "idx0085.wav"), seconds=0.6, amp=500)
    m = SMo.clean({"attract": [r"C:\mine\Shaken.wav", r"C:\mine\Bond.wav"]})
    used = [{"rel": CARRIER, "slot": 46, "mode": SMo.attract_mode(k), "host": 83 + k, "db": 0, "lines": 1}
            for k in (1, 2)]
    cfg = SMo.cfg_text(0, 0, [], True, attract={"request": 1057, "key": b"C" * 8, "switches": [64, 63],
                                                "files": [(b"A" * 8, 500), (b"B" * 8, 600)]},
                       record=SMo.card_record(m, used))
    said = []
    assert MS.readback("card.raw", proj, lambda t, lvl="info": said.append(t),
                       padmode={"sounds.cfg": cfg.encode()})["music"] == 1
    folder = os.path.join(proj, "Music mode files")
    assert SMo.load(proj).attract == [os.path.join(folder, "Shaken.wav"), os.path.join(folder, "Bond.wav")]
    assert any(t.startswith("Attract flipper sounds: this card's flipper buttons play 2 sound(s) in attract "
                            "mode; they are back in the Audio tab") for t in said)


def test_the_chain_encode_takes_the_modes_and_the_flipper_sounds_levels_together():
    """PAD-679 (Bond LE, 13 flipper sounds beside code modes' own music: "Your edits could not be
    prepared: keywords must be strings"): both level maps are keyed by an int sound idx, which
    dict(a, **b) refuses. The flipper sounds' own entry wins over the modes' for the same idx."""
    used = [{"rel": CARRIER, "slot": 801, "mode": SMo.attract_mode(1), "host": 2400},
            {"rel": CARRIER, "slot": 801, "mode": SMo.attract_mode(2), "host": 2401, "level_ref": 46}]
    assert E._chain_level_refs({2149: 1890, 2400: 7}, used) == {2149: 1890, 2400: 801, 2401: 46}
    assert E._chain_level_refs({}, used) == {2400: 801, 2401: 46}
    assert E._chain_level_refs({2149: 1890}, None) == {2149: 1890}


# ---- round 2 (the owner: "Only allow playing the flipper sounds every so often like 30 seconds") -----
def test_the_record_keeps_the_time_between_two_with_the_files():
    m = SMo.clean({"attract": ["a.wav"], "attract_gap": "30"})
    assert m.attract_gap == 30
    assert SMo.to_json(m)["attract_gap"] == 30
    assert SMo.clean({"attract_gap": 30}).attract_gap == 0                 # no files: nothing to space out
    assert "attract_gap" not in SMo.to_json(SMo.clean({"attract": ["a.wav"]}))
    assert [SMo.clean_gap(v) for v in ("x", -5, 12.4, 10 ** 6)] == [0, 0, 12, SMo.ATTRACT_GAP_MAX]
    assert SMo.ATTRACT_GAPS[:3] == (0, 10, 30)


def test_the_runtime_table_says_the_time_between_two():
    a = bytes(range(8))
    att = {"request": 1057, "key": b"C" * 8, "switches": [64, 63], "files": [(a, 800)], "gap_ms": 30000}
    assert "agap\t30000" in SMo.cfg_text(0, 0, [], True, attract=att).splitlines()
    att.pop("gap_ms")
    assert not any(line.startswith("agap") for line in SMo.cfg_text(0, 0, [], True, attract=att).splitlines())


def test_the_build_puts_the_time_between_two_in_the_table():
    params = [{"idx": 46, "findkey": b"C" * 8}, {"idx": 80, "findkey": b"A" * 8, "grown": True}]
    m = SMo.clean({"attract": ["a.wav"], "attract_gap": 60})
    m.attract_rel, m.attract_plan = CARRIER, {"request": 1057, "slot": 46, "switches": [64, 63]}
    used = [{"rel": CARRIER, "slot": 46, "mode": SMo.attract_mode(1), "host": 80, "frames": 35280}]
    assert E._attract_lines(params, used, m, lambda *a, **k: None)["gap_ms"] == 60000
    rec = SMo.read_card_record(SMo.cfg_text(0, 0, [], True, record=SMo.card_record(m, used)))
    assert rec["attract_gap"] == 60


def test_the_runtime_waits_the_time_between_two():
    with open(RUNTIME, encoding="utf-8") as f:
        c = f.read()
    assert 'str_eq(f[0], "agap")' in c and "att_gap_line(f[1]);" in c
    assert "return now + (att.gap_ms > d ? att.gap_ms : d);" in c
    assert c.count("att.until = att_next(now, att.ms[") == 2         # a new press and the replay at the release


def test_the_time_between_two_is_carried_with_the_files(tmp_path):
    from pinball_decryptor.core import staged_changes as SC
    from pinball_decryptor.core import mod_transfer as MT
    rec = SC.sound_modes_of({"sound_modes": {"attract": ["a.wav"], "attract_gap": 30}})
    assert rec["attract_gap"] == 30
    tgt = {"sound_modes": {"attract": ["mine.wav"], "attract_gap": 10}}
    SC.merge_sound_modes(tgt, rec)
    assert tgt["sound_modes"]["attract"] == ["a.wav"] and tgt["sound_modes"]["attract_gap"] == 30
    tgt = {}
    MT._apply_sound_modes(tgt, {"sound_modes": {"matched": [], "remapped": [], "names": [], "levels": {},
                                                "attract": ["a.wav"], "attract_gap": 120}}, {"sound_modes": {}},
                          {}, False)
    assert tgt["sound_modes"]["attract_gap"] == 120


def test_the_audio_tab_sets_the_time_between_two(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _project, _sidecar, _wav as wav
    from tests.webui_harness import web_app
    monkeypatch.setattr(SMo, "offer", lambda project, rels, probe=True: ("not here", {}))
    monkeypatch.setattr(SMo, "offer_turns", lambda project, rels, probe=True: ("not here", {}))
    monkeypatch.setattr(SMo, "offer_attract", lambda project, probe=True: "")
    proj = _project(tmp_path)
    a = str(tmp_path / "mine" / "Shaken.wav")
    wav(a)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        assert w.call("audio.attract_action", "gap:30") is False          # no files yet
        w.answers.append(a)
        assert w.call("audio.attract_action", "add") is True
        st = w.state("audio")["attract"]
        assert st["gap"] == 0
        assert [g["label"] for g in st["gaps"]] == [
            "Any time", "At most one every 10 seconds", "At most one every 30 seconds",
            "At most one every 1 minute", "At most one every 2 minutes", "At most one every 5 minutes"]
        assert w.call("audio.attract_action", "gap:30") is True
        assert _sidecar(proj)["sound_modes"]["attract_gap"] == 30
        st = w.state("audio")["attract"]
        assert st["gap"] == 30 and st["tip"][-1] == "At most one every 30 seconds."
        assert w.call("audio.attract_action", "gap:0") is True
        assert "attract_gap" not in _sidecar(proj)["sound_modes"]


def test_they_never_play_while_a_high_score_s_initials_are_entered():
    """The owner: "Disallow playing attract mode sounds when entering high scores". The flipper buttons pick
    the letters there, and the game's end-of-game high scores call runs until the initials are in: one
    wrapper of it (shared with PAD-640's challenge scores) holds chg_scores_running for the whole call."""
    with open(RUNTIME, encoding="utf-8") as f:
        c = f.read()
    assert c.count("hook_wrap(at, (void *)scores_wrap)") == 1               # wrapped once, for both
    assert 'hook_wrap(fn("challenge_scores")' not in c
    assert "if (chg_scores_on) return chg_scores_wrap(r0, r1, r2, r3);" in c
    assert "|| !(chg_scores_game = scores_orig)) {" in c and "chg_scores_on = 1;" in c
    edge = c[c.index("static void att_edge(unsigned id, unsigned level, unsigned flags, unsigned polarity, "
                     "unsigned mask)\n{"):]
    edge = edge[:edge.index("\n}\n")]
    assert edge.index("if (chg_scores_running) {") < edge.index("pm_sound(att.request);")
    arm = c[c.index("static void att_arm(void)"):]
    assert 'if ((!site("challenge_scores") && !site("game_scores")) || !scores_wrap_arm())' in arm[:arm.index("\n}\n")]
    assert 'fn("challenge_scores") ? fn("challenge_scores") : fn("game_scores")' in c


def test_every_shipped_port_names_the_game_s_end_of_game_high_scores():
    """`site game_scores` on every build (PAD-641 round 2: 69 of 69, the older versions read off their cards), the
    same function as `site challenge_scores` wherever a port has both."""
    import glob
    ports = sorted(glob.glob(os.path.join(HERE, "..", "tools", "spike2_emu", "modes", "sdk", "ports", "*.port")))
    assert len(ports) >= 69
    for p in ports:
        port = MP.read_port(p)
        assert "game_scores" in port["site"], os.path.basename(p)
        if "challenge_scores" in port["site"]:
            assert port["site"]["game_scores"] == port["site"]["challenge_scores"], os.path.basename(p)


def test_a_derived_port_gets_the_game_s_end_of_game_high_scores(monkeypatch):
    from pinball_decryptor.plugins.stern import portchallenge as PC
    from pinball_decryptor.plugins.stern import portgen as G
    assert G.generated("site", "game_scores 0x004e87dc 0xe92d4ff0 0xe24dd0bc")   # never carried from a reference
    monkeypatch.setattr(PC, "_scores_fn", lambda e: None)
    assert PC.game_scores(PC.Elf.__new__(PC.Elf)) == []
