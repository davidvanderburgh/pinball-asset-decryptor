"""PAD-565 (an owner: "assign two other sounds to a single sound and play them alternately"):
SOUNDS IN TURN - a slot's extra files, played one after the other each time the game starts it.

They ride the music modes' road (PAD-494): the project's record (``sound_modes`` ``turns``), each
file a record of its own under a pseudo mode, and ``turn`` lines in sounds.cfg that
pad_mode_runtime.c "sounds in turn" reads. No MUSIC MODE setting goes in the menu for them."""

import os

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import sound_modes as SMo

TANK = "audio/idx0002 - SE GZ FX TANK FIRE DOUBLE FAST 1.wav"
BOC = "audio/idx2095 - music - Blue \u00d6yster Cult - Godzilla.wav"
HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, "..", "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c")
PORTS = os.path.join(HERE, "..", "tools", "spike2_emu", "modes", "sdk", "ports")


# ---- the project's record ------------------------------------------------------------------------
def test_the_record_keeps_a_slots_files_in_turn_in_order():
    m = SMo.clean({"turns": {TANK: ["b.wav", "", "c.wav", 7], "bad": "x.wav"}})
    assert m.turns == {TANK: ["b.wav", "c.wav"]}
    assert m.count == 0 and m.any                       # no music mode, still something to build
    assert m.files() == [(TANK, SMo.turn_mode(2), "b.wav"), (TANK, SMo.turn_mode(3), "c.wav")]
    assert SMo.clean(SMo.to_json(m)).turns == m.turns
    assert "turns" not in SMo.to_json(SMo.clean({"slots": {BOC: {"2": "a.wav"}}}))
    assert not SMo.clean({}).any


def test_at_most_sixteen_files_play_in_turn_its_own_one_included():
    m = SMo.clean({"turns": {TANK: ["%d.wav" % i for i in range(40)]}})
    assert len(m.turns[TANK]) == SMo.TURN_MAX - 1 == 15


def test_files_in_turn_are_not_music_modes():
    m = SMo.clean({"slots": {BOC: {"2": "a.wav"}}, "turns": {TANK: ["b.wav"]}})
    assert m.count == 2 and m.menu_names() == ["Standard", "Custom A"]
    assert m.files() == [(BOC, 2, "a.wav"), (TANK, SMo.turn_mode(2), "b.wav")]
    mode = SMo.turn_mode(2)
    assert SMo.is_turn(mode) and not SMo.is_turn(SMo.MAX_MODES) and SMo.turn_of(mode) == 2
    assert m.level(TANK, mode) == 0                      # matched to the slot's own sound
    assert SMo.what(TANK, mode) == "idx0002 - SE GZ FX TANK FIRE DOUBLE FAST 1.wav's file 2 in turn"
    assert SMo.who(mode) == "Sounds in turn" and SMo.who(2) == "Music modes"
    assert SMo.tag(TANK, mode).endswith(" (file 2 in turn)")


# ---- the runtime's table -------------------------------------------------------------------------
def test_the_runtime_table_names_each_file_in_turn_and_no_setting_without_modes():
    text = SMo.cfg_text(0, 0, [(SMo.turn_mode(2), 10, b"\x05\x01"), (SMo.turn_mode(3), 10, b"\x05\x02")],
                        only=True)
    assert text.splitlines()[1:] == ["only", "turn\t2\t10\t0501", "turn\t3\t10\t0502"]
    both = SMo.cfg_text(0x7A4E78, 2, [(2, 2578, b"\x05"), (SMo.turn_mode(2), 10, b"\x05\x01")], False)
    assert both.splitlines()[1:] == ["setting\t0x007a4e78\t2", "sound\t2\t2578\t05", "turn\t2\t10\t0501"]


def test_the_runtime_reads_turn_lines_and_lets_a_music_mode_win():
    with open(RUNTIME, encoding="utf-8") as f:
        c = f.read()
    assert 'str_eq(f[0], "turn")' in c
    assert "#define SNDT_MAX        16" in c and SMo.TURN_MAX == 16
    # the music mode's own file for the asset first, its turn only without one
    assert c.index("sndm[i].mode == m") < c.index("t = n_sndt ? sndt_next(id) : 0;")


def test_the_card_record_brings_the_files_in_turn_back():
    m = SMo.clean({"turns": {TANK: ["C:/x/Tank B.wav", "C:/x/Tank C.wav"]}})
    used = [{"rel": TANK, "slot": 2, "mode": SMo.turn_mode(k), "host": 40 + k, "db": 0, "lines": 1}
            for k in (2, 3)]
    rec = SMo.read_card_record(SMo.cfg_text(0, 0, [], True, record=SMo.card_record(m, used)))
    assert rec["files"] == [] and rec["names"] == []
    assert rec["turns"] == [{"turn": 2, "slot": 2, "host": 42, "db": 0, "rel": TANK, "name": "Tank B.wav"},
                            {"turn": 3, "slot": 2, "host": 43, "db": 0, "rel": TANK, "name": "Tank C.wav"}]


# ---- which titles ---------------------------------------------------------------------------------
def test_bond_plays_sounds_in_turn_but_has_no_music_mode():
    from pinball_decryptor.plugins.stern import mode_project as MP
    for name in ("james_bond_le_1_06", "james_bond_pro_1_06"):
        prof = MP.profile(name)
        assert SMo.title_refusal(prof, turns=True) == ""
        assert SMo.title_refusal(prof) == SMo.NOT_PROVEN % prof.label
    gz = MP.profile("godzilla_le_1_16")
    assert SMo.title_refusal(gz, turns=True) == SMo.title_refusal(gz) == ""
    other = MP.profile("godzilla_pro_1_15")
    assert SMo.title_refusal(other, turns=True) == SMo.NOT_PROVEN_TURNS % other.label


def test_the_bond_ports_name_the_resolver_the_runtime_wraps():
    for port in ("james_bond_le-1.06", "james_bond_pro-1.06"):
        with open(os.path.join(PORTS, port + ".port"), encoding="utf-8") as f:
            assert any(line.split()[:2] == ["site", "sound_resolve"] for line in f), port


def test_the_audio_tab_offers_turns_per_slot(monkeypatch):
    from pinball_decryptor.plugins.stern import mode_project as MP
    monkeypatch.setattr(SMo, "project_title", lambda project, probe=False: MP.profile("james_bond_pro_1_06"))
    why, slots = SMo.offer_turns("proj", [TANK, "music_cat01_0003.wav"])
    assert why == "" and slots == {TANK: "", "music_cat01_0003.wav": SMo.NOT_SOUND_TURN}
    assert SMo.offer("proj", [TANK])[0]                  # music modes are not offered on Bond


# ---- the build ------------------------------------------------------------------------------------
def _wav(path, seconds, rate=44100, chans=1):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(chans)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * chans * int(seconds * rate))
    return str(path)


def _p(idx, length, chan=1, **kw):
    return dict({"idx": idx, "length": length, "chan": chan, "findkey": bytes([idx % 256]) * 8}, **kw)


def test_each_file_in_turn_goes_on_the_card_as_a_record_of_its_own(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern.spike2.emulator import BLOCK
    made = {s: _wav(tmp_path / ("conv_" + s), secs) for s, secs in (("b.wav", 0.5), ("c.wav", 0.7))}
    monkeypatch.setattr(SMo, "convert", lambda project, rel, mode, src, log=None: made[src])
    params = [_p(2, 44100 + BLOCK), _p(10, 44100 + BLOCK), _p(11, 44100 + BLOCK), _p(12, 2 * 44100)]
    m = SMo.clean({"turns": {TANK: ["b.wav", "c.wav"]}})
    logs = []
    edits, grows, used = E._sound_modes_grow(str(tmp_path), params, {}, {}, m,
                                             lambda t, lvl="info": logs.append(t))
    assert [(u["mode"], u["slot"]) for u in used] == [(SMo.turn_mode(2), 2), (SMo.turn_mode(3), 2)]
    assert len({u["host"] for u in used}) == 2 and 2 not in edits      # the slot keeps its record
    assert [u["frames"] for u in used] == [22050, int(0.7 * 44100)]
    assert all(t.startswith("Sounds in turn: ") for t in logs)
    assert any("file 3 in turn" in t and "at its turn (file 3)" in t for t in logs)
    assert not any("MUSIC MODE" in t for t in logs)
    assert E._SMo_tag(TANK, SMo.turn_mode(3)).endswith("(file 3 in turn)")
