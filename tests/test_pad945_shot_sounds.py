"""PAD-945 (a tester on Venom LE 1.07: "use unused game's sounds on shots that don't have sound requests
for now", in Grendel Mode): SOUNDS ON SHOTS IN THE GAME'S MODES - while one of the game's modes
runs, a hit on a chosen shot plays a chosen sound (one of the game's own, or a file of the project's).

The game asks for no sound there, so each file rides a CARRIER as the attract flipper sounds do (PAD-641):
a record of its own under a pseudo mode on a request the game never plays, and ``gshot`` / ``gsfile``
lines in sounds.cfg tell pad_mode_runtime.c "a sound on a shot" the carrier, its record's key and, per
file, the game's mode, the switch, the file's record key and its length. The runtime plays it from the
switch drain while that mode's own ACTIVE virtual says it runs."""

import os

import pytest

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import sound_modes as SMo

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, "..", "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c")
CARRIER = "audio/idx0943.wav"
ROW = {"mode": 16, "mode_name": "Grendel Mode", "switch": 85, "switch_name": "R ramp made opto",
       "file": r"C:\proj\audio\idx1234 - unused.wav"}


# ---- the project's record ------------------------------------------------------------------------
def test_the_record_keeps_the_rows_a_mode_and_shot_once_and_at_most_thirty_two():
    rows = [dict(ROW, switch=40 + k, switch_name="S%d" % k) for k in range(40)]
    m = SMo.clean({"shots": rows + [dict(ROW, file=""), dict(ROW, mode="x"), dict(ROW, switch=0), 7]})
    assert len(m.shots) == SMo.SHOT_MAX == 32 and m.shots[0] == rows[0]
    assert m.any and not m.count and not m.turns and not m.attract
    m = SMo.clean({"shots": [ROW, dict(ROW, file="other.wav"), dict(ROW, mode=17, mode_name="")]})
    assert [r["file"] for r in m.shots] == [ROW["file"], ROW["file"]]          # (16, 85) once: the first
    assert m.shots[1]["mode_name"] == "mode 17"
    assert SMo.to_json(m) == {"names": [], "slots": {}, "shots": m.shots}
    assert SMo.clean(SMo.to_json(m)).shots == m.shots
    assert SMo.to_json(SMo.clean({"shots": []})) is None


def test_a_sound_on_a_shot_is_a_pseudo_mode_of_its_own():
    for k in (1, SMo.SHOT_MAX):
        mode = SMo.shot_mode(k)
        assert SMo.is_shot(mode) and SMo.is_turn(mode) and SMo.shot_of(mode) == k and SMo.turn_of(mode) == k
        assert not SMo.is_mode_turn(mode) and not SMo.is_attract(mode) and not SMo.is_juke(mode)
    # the music modes' own files in turn stay below it, the jukebox above it
    assert SMo.is_mode_turn(SMo.mode_turn(SMo.MAX_MODES, SMo.TURN_MAX)) and not SMo.is_shot(SMo.juke_mode(1))
    assert SMo.who(SMo.shot_mode(2)) == "Sounds on shots"
    assert SMo.what(CARRIER, SMo.shot_mode(2)) == "sound on a shot 2"
    m = SMo.clean({"shots": [ROW]})
    assert m.files() == []                                     # no carrier yet
    m.shot_rel = CARRIER
    assert m.files() == [(CARRIER, SMo.shot_mode(1), ROW["file"])] and m.level(CARRIER, SMo.shot_mode(1)) == 0


def test_the_runtime_table_names_the_carrier_and_each_file():
    a, b = bytes(range(8)), bytes(range(8, 16))
    text = SMo.cfg_text(0, 0, [], True, shots={"request": 943, "key": bytes.fromhex("04abd19370050000"),
                                               "files": [(16, 85, a, 1500), (12, 99, b, 800)]})
    assert text.splitlines()[1:] == ["only", "gshot\t943\t04abd19370050000",
                                     "gsfile\t1\t16\t85\t0001020304050607\t1500",
                                     "gsfile\t2\t12\t99\t08090a0b0c0d0e0f\t800"]
    assert "gshot" not in SMo.cfg_text(0, 0, [], True, shots=None)


def test_the_card_record_brings_them_back():
    m = SMo.clean({"shots": [ROW, dict(ROW, mode=12, mode_name="Riot Mode", file="C:/mine/Roar.wav")]})
    used = [{"rel": CARRIER, "slot": 943, "mode": SMo.shot_mode(k), "host": 2000 + k, "db": 0, "lines": 1}
            for k in (1, 2)]
    rec = SMo.read_card_record(SMo.cfg_text(0, 0, [], True, record=SMo.card_record(m, used)))
    assert rec["files"] == [] and "turns" not in rec and "random" not in rec
    assert rec["shots"] == [
        {"k": 1, "slot": 943, "host": 2001, "mode": 16, "switch": 85, "rel": CARRIER,
         "name": "idx1234 - unused.wav", "mode_name": "Grendel Mode", "switch_name": "R ramp made opto"},
        {"k": 2, "slot": 943, "host": 2002, "mode": 12, "switch": 85, "rel": CARRIER, "name": "Roar.wav",
         "mode_name": "Riot Mode", "switch_name": "R ramp made opto"}]
    used[1].update(bank=1, bank_idx=7)
    rec = SMo.read_card_record(SMo.cfg_text(0, 0, [], True, record=SMo.card_record(m, used)))
    assert SMo.card_bank_records(rec) == {1: {7}}


# ---- which builds ---------------------------------------------------------------------------------
def test_venom_le_names_its_modes_and_takes_them():
    prof = MP.profile("venom_le_1_07")
    assert SMo.shot_refusal(prof) == ""
    modes = dict(SMo.game_modes(prof))
    assert modes[16] == "Grendel Mode" and modes[12] == "Riot Mode" and modes[17] == "Knull Mode"
    assert 59 not in modes                     # Mayhem Multiball: the port names no object of it


@pytest.mark.parametrize("name", ["venom_pro_1_07", "godzilla_le_1_16", "godzilla_pro_1_16", "jaws_le_1_02",
                                  "deadpool_le_1_16", "turtles_le_1_59", "mando_pro_1_45"])
def test_the_cpp_rule_titles_take_them(name):
    prof = MP.profile(name)
    assert SMo.shot_refusal(prof) == "" and SMo.game_modes(prof)


def test_a_title_whose_modes_have_no_object_says_why():
    prof = MP.profile("beatles_1_29")
    assert SMo.shot_refusal(prof) == SMo.NO_SHOTS % (prof.label, "the app cannot tell when one of its modes runs")
    prof = MP.profile("james_bond_le_1_06")
    assert SMo.shot_refusal(prof) == SMo.NO_SHOTS % (prof.label, "the app knows none of its modes by name")
    assert SMo.shot_refusal(None) == SMo.NO_TITLE_SHOTS


def test_the_shots_are_the_playfield_switches_by_the_games_own_names(monkeypatch):
    from pinball_decryptor.plugins.stern import portgen as G
    from pinball_decryptor.plugins.stern import portswitch as PS
    monkeypatch.setattr(G, "Elf", lambda b: b)
    sws = [{"id": i, "name": n, "image": "", "handler": 0} for i, n in (
        (0, "NOT USED"), (21, "TROUGH 1"), (85, "R RAMP MADE OPTO"), (64, "LEFT FLIPPER BUTTON"), (99, "LEFT  ORBIT"))]
    monkeypatch.setattr(PS, "switches", lambda elf, info=None: sws)
    assert SMo.shot_switches(b"elf") == [(85, "R ramp made opto"), (99, "Left orbit")]
    monkeypatch.setattr(PS, "switches", lambda elf, info=None: [])
    assert SMo.shot_switches(b"elf") == []


# ---- the runtime ----------------------------------------------------------------------------------
def test_the_runtime_reads_the_lines_and_plays_on_a_press_while_the_mode_runs():
    with open(RUNTIME, encoding="utf-8") as f:
        c = f.read()
    assert 'str_eq(f[0], "gshot")' in c and 'str_eq(f[0], "gsfile")' in c
    assert "gms_file(f[1], f[2], f[3], f[4], f[5]);" in c and "char *f[6];" in c   # six fields on a line
    assert "#define GMS_FILES 32" in c
    # the record lookup takes the playing file's key; the drain's edges reach it beside the attract sounds'
    assert "if (gms_live && r[1] && gms_lookup(r)) return;" in c
    assert "if (gms_live) gms_edge(id, level, flags, pol);" in c
    # in a game only, while the row's mode is ACTIVE for the player up, not while the last one still plays
    assert "if (!pm_in_game()) return;" in c and "gms_active(k)" in c
    assert "if (gms.plays && (long)(gms.until - now) > 0) {" in c
    # ACTIVE: the port's mode slot, else the mode table's, else read off the game's own query
    i = c.index('gms.slot = pm_port_value("mode_slot_active", -1);')
    assert c.index('gms.slot = pm_port_value("stock_slot_active", -1);', i) < c.index("gms.slot = mode_query_slot(0);", i)
    assert 'pm_snprintf(key, sizeof key, "block_obj_%u", gms.mode[k]);' in c
    # at the modes' shot-call priority, no steal flag
    assert "pm_sound_priority(gms.request, 3, 0)" in c
    # the carrier stopped once the file has played (its own record's silence would hold the voice bus), from a
    # tick hook of its own: a card with no modes hooks no tick of the modes'
    assert "gms.stop_at = (now + gms.ms[k] + gms.ms[k] / 8 + 120) | 1;" in c
    assert 'hook(site("tick")->addr, gms_tick)' in c and "pm_sound_stop(gms.request)" in c
    # ACTIVE is asked at the press: at arm the mode objects (C++ statics) are not built yet
    arm = c[c.index("static void gms_arm(void)"):c.index("/* ---- the jukebox (PAD-685)")]
    assert "place_vfn_at" not in arm
    # it works on a card with no modes (`only`)
    assert "gms_arm();" in c and "if (n_sndt || n_bsid || att.n || n_jmode || gms.n) return;" in c


# ---- the build ------------------------------------------------------------------------------------
def _wav(path, seconds, rate=44100, chans=1):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(chans)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * chans * int(seconds * rate))
    return str(path)


def test_the_carrier_is_one_the_build_leaves_alone_and_not_the_flipper_sounds(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_sounds as MSo
    from pinball_decryptor.plugins.stern import mode_write as MW
    prof = MP.profile("venom_le_1_07")
    calls = MSo.carriers(prof.game_dir, prof.version).calls
    slots = {calls[0]: 46, calls[1]: 47, calls[2]: 48}

    def record(elf, head, params, sites, r, mask):
        if r not in slots:
            raise MW.ModeWriteError("request %d names no record" % r)
        return slots[r]

    monkeypatch.setattr(MW, "request_record", record)
    monkeypatch.setattr(E, "_desc_key_mask", lambda params, sites, log=None: 0xFC0003FF)
    monkeypatch.setattr(SMo, "flipper_buttons", lambda elf: [64, 63])
    for name in ("game", "image.bin"):
        (tmp_path / name).write_bytes(b"\0" * 64)
    proj = tmp_path / "proj"
    (proj / "audio").mkdir(parents=True)
    for i in (46, 47, 48):
        _wav(proj / "audio" / ("idx%04d.wav" % i), 0.1)
    m = SMo.clean({"attract": ["a.wav"], "shots": [ROW]})
    logs = []
    log = lambda t, lvl="info": logs.append(t)                    # noqa: E731
    args = (str(tmp_path / "game"), str(tmp_path / "image.bin"), [], [], str(proj), {}, m, prof, [], log)
    E._attract_carrier(*args)
    E._shot_carrier(*args)
    assert m.attract_plan["slot"] == 46 and m.shot_rel == "audio/idx0047.wav"     # not the attract's
    assert m.shot_plan == {"request": calls[1], "slot": 47}
    assert logs[-1] == ("Sounds on shots: 1 sound(s) on the shots of the game's modes ride request %d "
                        "(sound idx 47, which the game never plays): R ramp made opto in Grendel Mode."
                        % calls[1])
    # none left: they are left out, and the log says why
    m, logs[:] = SMo.clean({"shots": [ROW]}), []
    E._shot_carrier(str(tmp_path / "game"), str(tmp_path / "image.bin"), [], [], str(proj),
                    {46: "x", 47: "y", 48: "z"}, m, prof, [], log)
    assert m.shots == [] and m.shot_rel == "" and len(logs) == 1
    assert logs[0].startswith("Sounds on shots: 1 sound(s) on the shots of the game's modes are left out "
                              "of this build: ")


def test_each_file_goes_on_the_card_whole_past_its_carrier(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern.spike2.emulator import BLOCK
    made = {"a.wav": _wav(tmp_path / "conv_a.wav", 0.5), "b.wav": _wav(tmp_path / "conv_b.wav", 3.0)}
    monkeypatch.setattr(SMo, "convert", lambda project, rel, mode, src, log=None: made[src])
    params = [{"idx": 943, "length": 44100 + BLOCK, "chan": 1, "findkey": b"C" * 8},
              {"idx": 10, "length": 44100 + BLOCK, "chan": 1, "findkey": b"D" * 8},
              {"idx": 11, "length": 2 * 44100, "chan": 1, "findkey": b"E" * 8},
              {"idx": 12, "length": 4 * 44100, "chan": 1, "findkey": b"F" * 8}]
    m = SMo.clean({"shots": [dict(ROW, file="a.wav"), dict(ROW, mode=12, file="b.wav")]})
    m.shot_rel = CARRIER
    logs = []
    edits, grows, used = E._sound_modes_grow(str(tmp_path), params, {}, {}, m,
                                             lambda t, lvl="info": logs.append(t), longer_ok=True)
    assert [(u["mode"], u["slot"]) for u in used] == [(SMo.shot_mode(1), 943), (SMo.shot_mode(2), 943)]
    assert len({u["host"] for u in used}) == 2 and 943 not in edits         # the carrier keeps its record
    assert used[1]["frames"] == 3 * 44100                                    # the long one whole
    assert not any("is cut to its slot's" in t for t in logs)


def test_the_table_names_each_file_s_mode_switch_key_and_length():
    params = [{"idx": 943, "findkey": b"C" * 8}, {"idx": 80, "findkey": b"A" * 8, "grown": True},
              {"idx": 81, "findkey": b"B" * 8}]
    m = SMo.clean({"shots": [ROW, dict(ROW, mode=12, mode_name="Riot Mode")]})
    m.shot_rel, m.shot_plan = CARRIER, {"request": 943, "slot": 943}
    used = [{"rel": CARRIER, "slot": 943, "mode": SMo.shot_mode(1), "host": 80, "frames": 35280},
            {"rel": CARRIER, "slot": 943, "mode": SMo.shot_mode(2), "host": 81, "frames": 44100}]
    logs = []
    got = E._shot_lines(params, used, m, lambda t, lvl="info": logs.append(t))
    assert got == {"request": 943, "key": b"C" * 8, "files": [(16, 85, b"A" * 8, 800)]}
    assert used[0]["lines"] == 1 and "lines" not in used[1]
    assert logs == ["Sounds on shots: sound on a shot 2 is left out: its record did not come out of the grown "
                    "bank."]
    assert E._shot_lines(params, [], m, logs.append) is None


def test_a_game_that_cannot_have_them_leaves_them_out_and_keeps_the_rest(tmp_path, monkeypatch):
    from pinball_decryptor.core import staged_changes as SC
    from pinball_decryptor.plugins.stern import mode_write as MW
    monkeypatch.setattr(MW, "host_refusal", lambda: "")
    monkeypatch.setattr(SMo, "project_title", lambda project, probe=False: MP.profile("beatles_1_29"))
    SC.save(str(tmp_path), {"sound_modes": {"shots": [ROW]}})
    logs = []
    got = E._sound_modes_for_build(str(tmp_path), False, lambda t, lvl="info": logs.append((t, lvl)),
                                   ext4_available=lambda: (True, ""))
    assert got == (None, None)
    assert logs == [("Sounds on shots: 1 sound(s) on the shots of the game's modes are left out of this "
                     "build: " + SMo.shot_refusal(MP.profile("beatles_1_29")), "warning")]
    # Venom: they go on, with files in turn beside them
    monkeypatch.setattr(SMo, "project_title", lambda project, probe=False: MP.profile("venom_le_1_07"))
    SC.save(str(tmp_path), {"sound_modes": {"shots": [ROW], "turns": {"audio/idx0002.wav": ["t.wav"]}}})
    logs.clear()
    modes, prof = E._sound_modes_for_build(str(tmp_path), False, lambda t, lvl="info": logs.append((t, lvl)),
                                           ext4_available=lambda: (True, ""))
    assert prof.game_dir == "venom_le" and modes.shots == [ROW] and modes.turns
    assert ("Found 1 sound(s) on the shots of the game's modes.", "info") in logs


# ---- carried: the mod routes keep them, the music modes file, back out of a card -------------------
def test_the_sidecar_routes_keep_them():
    from pinball_decryptor.core import staged_changes as SC
    rec = SC.sound_modes_of({"sound_modes": {"names": [], "slots": {}, "shots": [ROW]}})
    assert rec == {"names": [], "slots": {}, "levels": {}, "shots": [ROW]}
    # a merge of another record keeps the project's own (a music mode file coming in does not drop them)
    tgt = {"sound_modes": {"names": [], "slots": {}, "shots": [ROW]}}
    assert SC.merge_sound_modes(tgt, {"names": [], "slots": {"audio/idx0002.wav": {"2": "x.wav"}}}) == 1
    assert tgt["sound_modes"]["shots"] == [ROW] and tgt["sound_modes"]["slots"]
    other = dict(ROW, file="y.wav")
    assert SC.merge_sound_modes(tgt, {"names": [], "slots": {}, "shots": [other]}) == 1
    assert SMo.clean(tgt["sound_modes"]).shots == [other]


def test_they_go_to_the_music_modes_file_and_come_back_on_the_same_game(tmp_path, monkeypatch):
    from pinball_decryptor.core import staged_changes as SC
    from pinball_decryptor.plugins.stern import media_share as MS
    from tests.test_webui_audio import _wav as wav
    monkeypatch.setattr(MS, "_about", lambda project: {"title": "Venom LE 1.07"})
    src = str(tmp_path / "src")
    wav(os.path.join(src, "audio", "idx0002.wav"), seconds=0.3)
    a = str(tmp_path / "mine" / "Roar.wav")
    wav(a, seconds=0.4, amp=700)
    SC.save(src, {"sound_modes": {"names": [], "slots": {}, "shots": [dict(ROW, file=a)]}})
    path = str(tmp_path / "modes.zip")
    assert MS.save_music_modes(src, path) == {"slots": 0, "files": 1, "gone": [], "shots": 1}
    dst = str(tmp_path / "dst")
    wav(os.path.join(dst, "audio", "idx0002.wav"), seconds=0.3)
    got = MS.load_music_modes(dst, path)
    assert got["record"]["shots"] == [dict(ROW, file=os.path.join(dst, "Music mode files", "Roar.wav"))]
    assert MS.put_music(dst, got["record"]) == 1
    assert SMo.load(dst).shots == got["record"]["shots"]
    # another game: its modes and switches are another program's ids, so none come in
    monkeypatch.setattr(MS, "_about", lambda project: {"title": "Venom LE 1.07"} if project == src
                        else {"title": "Godzilla LE 1.16"})
    assert "shots" not in MS.load_music_modes(str(tmp_path / "gz"), path)["record"]


def test_an_extract_of_the_card_has_them_back(tmp_path):
    from pinball_decryptor.plugins.stern import media_share as MS
    from tests.test_webui_audio import _wav as wav
    proj = str(tmp_path / "proj")
    wav(os.path.join(proj, "audio", "idx0943.wav"), seconds=0.3)
    wav(os.path.join(proj, "audio", "idx2001.wav"), seconds=0.5, amp=900)
    m = SMo.clean({"shots": [dict(ROW, file=r"C:\mine\Roar.wav")]})
    used = [{"rel": CARRIER, "slot": 943, "mode": SMo.shot_mode(1), "host": 2001, "db": 0, "lines": 1}]
    cfg = SMo.cfg_text(0, 0, [], True, shots={"request": 943, "key": b"C" * 8, "files": [(16, 85, b"A" * 8, 500)]},
                       record=SMo.card_record(m, used))
    said = []
    assert MS.readback("card.raw", proj, lambda t, lvl="info": said.append(t),
                       padmode={"sounds.cfg": cfg.encode()})["music"] == 1
    back = SMo.load(proj).shots
    assert back == [dict(ROW, file=os.path.join(proj, "Music mode files", "Roar.wav"))]
    assert any(t.startswith("Sounds on shots: this card plays 1 sound(s) on the shots of the game's modes; "
                            "they are back in the Audio tab") for t in said)


# ---- the Audio tab ----------------------------------------------------------------------------------
def _offers(monkeypatch, why=""):
    monkeypatch.setattr(SMo, "offer", lambda project, rels, probe=True: ("not here", {}))
    monkeypatch.setattr(SMo, "offer_turns", lambda project, rels, probe=True: ("not here", {}))
    monkeypatch.setattr(SMo, "offer_attract", lambda project, probe=True: "not here")
    monkeypatch.setattr(SMo, "offer_shots", lambda project, probe=True: why)
    monkeypatch.setattr(SMo, "shot_choices", lambda project: (
        why, [(12, "Riot Mode"), (16, "Grendel Mode")], [(85, "R ramp made opto"), (99, "Left orbit")]))


def test_the_audio_tab_adds_plays_and_takes_off_sounds_on_shots(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _project, _sidecar, _wav as wav
    from tests.webui_harness import web_app
    _offers(monkeypatch)
    proj = _project(tmp_path)
    mine = str(tmp_path / "mine" / "Roar.wav")
    wav(mine)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        assert w.state("audio")["shots"]["n"] == 0 and w.state("audio")["shots"]["why"] == ""
        # a row's right-click: its own sound, the window open on it
        items = w.call("audio.menu", "audio/idx0002.wav", [])
        assert any(i.get("action") == "shot_here" and not i.get("disabled") for i in items)
        got = w.call("audio.menu_action", "shot_here", "audio/idx0002.wav")
        assert got["open"] == "shots" and got["data"]["pick"] == "idx0002.wav"
        assert got["data"]["modes"] == [{"value": "12", "label": "Riot Mode"}, {"value": "16", "label": "Grendel Mode"}]
        rows = w.call("audio.shots_action", "add:16:85")["rows"]
        assert rows == [{"k": 1, "mode": "Grendel Mode", "shot": "R ramp made opto", "sound": "idx0002.wav",
                         "gone": False}]
        saved = _sidecar(proj)["sound_modes"]["shots"]
        assert saved == [{"mode": 16, "mode_name": "Grendel Mode", "switch": 85, "switch_name": "R ramp made opto",
                          "file": os.path.normpath(os.path.join(proj, "audio", "idx0002.wav"))}]
        # a file of the user's, through the window's own Choose
        assert w.call("audio.shots_open")["pick"] == ""
        assert w.call("audio.shots_action", "add:12:99")["rows"] == rows        # nothing picked: nothing added
        w.answers.append(mine)
        assert w.call("audio.shots_action", "choose")["pick"] == "Roar.wav"
        rows = w.call("audio.shots_action", "add:12:99")["rows"]
        assert [r["sound"] for r in rows] == ["idx0002.wav", "Roar.wav"]
        assert w.state("audio")["shots"]["n"] == 2
        w.call("audio.shots_action", "play:2")
        assert w.state("audio")["panes"]["rep"]["name"] == "Left orbit in Riot Mode: Roar.wav"
        assert [r["sound"] for r in w.call("audio.shots_action", "off:1")["rows"]] == ["Roar.wav"]
        assert [r["file"] for r in _sidecar(proj)["sound_modes"]["shots"]] == [os.path.normpath(mine)]
    with web_app(tmp_path / "again", mfr="stern", era="spike2") as w:        # a fresh session has it back
        _open(w, proj)
        assert w.state("audio")["shots"]["n"] == 1


def test_a_game_without_them_says_why_and_adds_none(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _project
    from tests.webui_harness import web_app
    from pinball_decryptor.webui import compat
    _offers(monkeypatch, why="Not on this game.")
    said = []
    monkeypatch.setattr(compat.messagebox, "showinfo", lambda title, text, **k: said.append((title, text)))
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, _project(tmp_path))
        assert w.state("audio")["shots"]["why"] == "Not on this game."
        items = w.call("audio.menu", "audio/idx0002.wav", [])
        assert any(i.get("action") == "shot_here" and i.get("disabled") for i in items)
        assert w.call("audio.menu_action", "shot_here", "audio/idx0002.wav") is False
        assert w.call("audio.shots_action", "add:16:85")["rows"] == []
        w.call("audio.shots_action", "why")
    assert said == [("Sounds on shots", "Not on this game.")]


def test_the_page_draws_the_button_and_the_window():
    with open(os.path.join(HERE, "..", "pinball_decryptor", "webui", "static", "js", "tabs", "audio.js"),
              encoding="utf-8") as f:
        js = f.read()
    assert "s.shots ? html`<${ShotsButton}" in js and 'call("audio.shots_open")' in js
    assert 'res.open === "shots"' in js and "act(`add:${m}:${s}`)" in js and 'act("choose")' in js
