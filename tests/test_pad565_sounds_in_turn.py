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
def test_the_runtime_table_names_each_file_s_record_key_beside_its_slot_s():
    slot, b, c = bytes.fromhex("9ad919226f1d0000"), bytes(range(8)), bytes(range(8, 16))
    text = SMo.cfg_text(0, 0, [], only=True, turns=[(2, slot, b), (3, slot, c)])
    assert text.splitlines()[1:] == ["only", "turn\t2\t9ad919226f1d0000\t0001020304050607",
                                     "turn\t3\t9ad919226f1d0000\t08090a0b0c0d0e0f"]
    both = SMo.cfg_text(0x7A4E78, 2, [(2, 2578, b"\x05")], False, turns=[(2, slot, b)])
    assert both.splitlines()[1:] == ["setting\t0x007a4e78\t2", "sound\t2\t2578\t05",
                                     "turn\t2\t9ad919226f1d0000\t0001020304050607"]


def test_the_runtime_swaps_the_looked_up_key_in_turn():
    """At the record lookup the modes' own sounds swap keys at (item 163), hooked once for both."""
    with open(RUNTIME, encoding="utf-8") as f:
        c = f.read()
    assert 'str_eq(f[0], "turn")' in c and "sndt_line(f[1], f[2], f[3])" in c
    assert "#define SNDT_MAX        16" in c and SMo.TURN_MAX == 16
    assert "if (sndt_live && r[1]) sndt_lookup(r);" in c
    assert c.count('hook(fn("sound_lookup"), on_sound_lookup)') == 4   # PAD-685: the jukebox's
    assert '!lookup_hooked && !hook(fn("sound_lookup"), on_sound_lookup)' in c        # the turns'
    assert '!lookup_hooked && hook(fn("sound_lookup"), on_sound_lookup)' in c         # the modes'
    assert '!lookup_hooked && !(lookup_hooked = hook(fn("sound_lookup"), on_sound_lookup))' in c   # PAD-641'


def test_the_build_writes_each_file_s_record_key_beside_its_slot_s():
    params = [{"idx": 2, "findkey": b"S" * 8}, {"idx": 40, "findkey": b"H" * 8, "grown": True},
              {"idx": 41, "findkey": b"J" * 8}]
    used = [{"rel": TANK, "slot": 2, "mode": SMo.turn_mode(2), "host": 40},
            {"rel": TANK, "slot": 2, "mode": SMo.turn_mode(3), "host": 41}]
    logs = []
    assert E._turn_key_lines(params, used, lambda t, lvl="info": logs.append(t)) == [(2, b"S" * 8, b"H" * 8)]
    assert used[0]["lines"] == 1 and "lines" not in used[1]
    assert logs == ["Sounds in turn: idx0002 - SE GZ FX TANK FIRE DOUBLE FAST 1.wav's file 3 in turn is left "
                    "out: its record did not come out of the grown bank."]


def test_the_card_record_brings_the_files_in_turn_back():
    m = SMo.clean({"turns": {TANK: ["C:/x/Tank B.wav", "C:/x/Tank C.wav"]}})
    used = [{"rel": TANK, "slot": 2, "mode": SMo.turn_mode(k), "host": 40 + k, "db": 0, "lines": 1}
            for k in (2, 3)]
    rec = SMo.read_card_record(SMo.cfg_text(0, 0, [], True, record=SMo.card_record(m, used)))
    assert rec["files"] == [] and rec["names"] == []
    assert rec["turns"] == [{"turn": 2, "slot": 2, "host": 42, "db": 0, "rel": TANK, "name": "Tank B.wav"},
                            {"turn": 3, "slot": 2, "host": 43, "db": 0, "rel": TANK, "name": "Tank C.wav"}]


# ---- which titles ---------------------------------------------------------------------------------
def test_bond_plays_sounds_in_turn_and_only_its_le_has_no_music_mode():
    """PAD-724: music modes on every latest build whose program can grow; Bond LE 1.06's cannot."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    for name in ("james_bond_le_1_06", "james_bond_pro_1_06"):
        assert SMo.title_refusal(MP.profile(name), turns=True) == ""
    le = MP.profile("james_bond_le_1_06")
    assert SMo.title_refusal(le) == SMo.NO_ROOM % le.label
    assert SMo.title_refusal(MP.profile("james_bond_pro_1_06")) == ""
    gz = MP.profile("godzilla_le_1_16")
    assert SMo.title_refusal(gz, turns=True) == SMo.title_refusal(gz) == ""
    other = MP.profile("godzilla_pro_1_15")
    assert SMo.title_refusal(other, turns=True) == SMo.NOT_PROVEN_TURNS % other.label


def test_the_proven_titles_ports_name_the_record_lookup_the_runtime_hooks():
    for key in SMo.TURN_PROVEN:
        with open(os.path.join(PORTS, key + ".port"), encoding="utf-8") as f:
            assert any(line.split()[:2] == ["site", "sound_lookup"] for line in f), key


def test_the_audio_tab_offers_turns_per_slot(monkeypatch):
    from pinball_decryptor.plugins.stern import mode_project as MP
    monkeypatch.setattr(SMo, "project_title", lambda project, probe=False: MP.profile("james_bond_pro_1_06"))
    why, slots = SMo.offer_turns("proj", [TANK, "music_cat01_0003.wav"])
    assert why == "" and slots == {TANK: "", "music_cat01_0003.wav": SMo.NOT_SOUND_TURN}
    monkeypatch.setattr(SMo, "project_title", lambda project, probe=False: MP.profile("james_bond_le_1_06"))
    assert SMo.offer("proj", [TANK])[0]                  # music modes are not offered on Bond LE


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
    # a file longer than its sound is cut to it, longer replacements allowed or not: the game plays
    # it for as long as its slot's descriptor says
    made["c.wav"] = _wav(tmp_path / "long_c.wav", 3.0)
    logs.clear()
    _e, _g, used = E._sound_modes_grow(str(tmp_path), params, {}, {}, m,
                                       lambda t, lvl="info": logs.append(t), longer_ok=True)
    assert used[1]["frames"] < 2 * 44100
    assert any("is cut to its slot's" in t and "the game plays it for as long as its sound" in t
               for t in logs)


# ---- carried: mod routes, the music modes file, back out of a card ---------------------------------
def test_the_mod_routes_carry_files_in_turn_with_their_slot():
    from pinball_decryptor.core import staged_changes as SC
    data = {"sound_modes": {"names": [], "slots": {BOC: {"2": "a.wav"}}, "turns": {TANK: ["b.wav", "c.wav"]}}}
    rec = SC.sound_modes_of(data)
    assert rec["slots"] == {BOC: {"2": "a.wav"}, TANK: {"t2": "b.wav", "t3": "c.wav"}}
    assert SC.sound_modes_of({"sound_modes": {"turns": {TANK: ["b.wav"]}}})["slots"] == {TANK: {"t2": "b.wav"}}
    # into another project, under the slot it paired with there
    other = "audio/idx0007 - SE TANK.wav"
    tgt = {"sound_modes": {"names": [], "slots": {}, "turns": {other: ["mine.wav"]}}}
    assert SC.merge_sound_modes(tgt, {"names": [], "slots": {other: rec["slots"][TANK]}}) == 1
    assert tgt["sound_modes"]["turns"] == {other: ["b.wav", "c.wav"]}     # the record's, in order
    assert tgt["sound_modes"]["slots"] == {}
    assert SMo.clean(tgt["sound_modes"]).turns == {other: ["b.wav", "c.wav"]}


def test_files_in_turn_go_to_the_music_modes_file_and_come_back(tmp_path):
    from pinball_decryptor.core import staged_changes as SC
    from pinball_decryptor.plugins.stern import media_share as MS
    from tests.test_webui_audio import _wav as wav
    src = str(tmp_path / "src")
    wav(os.path.join(src, *TANK.split("/")), seconds=0.3)
    mine = str(tmp_path / "mine" / "Tank B.wav")
    wav(mine, seconds=0.4, amp=700)
    SC.save(src, {"sound_modes": {"names": [], "slots": {}, "turns": {TANK: [mine]}}})
    path = str(tmp_path / "modes.zip")
    assert MS.save_music_modes(src, path) == {"slots": 1, "files": 1, "gone": []}
    dst = str(tmp_path / "dst")
    wav(os.path.join(dst, *TANK.split("/")), seconds=0.3)
    got = MS.load_music_modes(dst, path)
    copy = os.path.join(dst, "Music mode files", "Tank B.wav")
    assert got["record"]["slots"] == {TANK: {"t2": copy}}
    assert MS.replaced_music(dst, got["record"]) == []
    assert MS.put_music(dst, got["record"]) == 1
    assert SMo.load(dst).turns == {TANK: [copy]}


def test_an_extract_of_the_card_has_its_files_in_turn_back(tmp_path):
    from pinball_decryptor.core import staged_changes as SC
    from pinball_decryptor.plugins.stern import media_share as MS
    from tests.test_webui_audio import _wav as wav
    proj = str(tmp_path / "proj")
    wav(os.path.join(proj, *TANK.split("/")), seconds=0.3)
    wav(os.path.join(proj, "audio", "idx0040 - SE X.wav"), seconds=0.5, amp=900)
    m = SMo.clean({"turns": {TANK: [r"C:\mine\Tank B.wav"]}})
    used = [{"rel": TANK, "slot": 2, "mode": SMo.turn_mode(2), "host": 40, "db": 0, "lines": 1}]
    cfg = SMo.cfg_text(0, 0, [(SMo.turn_mode(2), 10, b"\x05\x01")], True, record=SMo.card_record(m, used))
    said = []
    assert MS.readback("card.raw", proj, lambda t, lvl="info": said.append(t),
                       padmode={"sounds.cfg": cfg.encode()})["music"] == 1
    copy = os.path.join(proj, "Music mode files", "Tank B.wav")
    assert SMo.load(proj).turns == {TANK: [copy]}
    assert SC.load(proj)["sound_modes"]["turns"] == {TANK: [copy]}
    # an extract already playing files in turn keeps its own
    SC.save(proj, {"sound_modes": {"turns": {TANK: ["C:/my.wav"]}}})
    assert MS.readback("card.raw", proj, padmode={"sounds.cfg": cfg.encode()})["music"] == 0
    assert SMo.load(proj).turns == {TANK: ["C:/my.wav"]}


# ---- the Audio tab ----------------------------------------------------------------------------------
def test_the_audio_tab_adds_plays_and_takes_off_files_in_turn(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _project, _sidecar, _wav as wav
    from tests.webui_harness import web_app
    rel = "audio/idx0001 - Jackpot.wav"
    monkeypatch.setattr(SMo, "offer", lambda project, rels, probe=True: ("not here", {}))
    monkeypatch.setattr(SMo, "offer_turns", lambda project, rels, probe=True: (
        "", {r: "" for r in rels}))
    proj = _project(tmp_path)
    b, c = str(tmp_path / "mine" / "Jackpot B.wav"), str(tmp_path / "mine" / "Jackpot C.wav")
    wav(b)
    wav(c)

    def entry(w):
        items = w.call("audio.menu", rel, [rel])
        return next((i for i in items if str(i.get("label", "")).startswith("Play in turn")), None)

    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        e = entry(w)
        assert e["label"] == "Play in turn" and e["icon"] == "shuffle"
        assert [s["label"] for s in e["submenu"]] == ["Add a sound to play in turn…"]
        for f in (b, c):
            w.answers.append(f)
            assert w.call("audio.menu_action", "turn_add", rel) is True
        assert _sidecar(proj)["sound_modes"]["turns"] == {rel: [os.path.normpath(b), os.path.normpath(c)]}
        r = next(r for r in w.state("audio")["rows"] if r["k"] == rel)
        assert r["tn"] == 3
        assert r["tn_tip"] == ("Each time the game plays this sound it plays the next of these, then "
                               "starts again: 1. the game's own sound; 2. Jackpot B.wav; 3. Jackpot C.wav.")
        assert w.state("audio")["status"].startswith("1 of 3 slots changed")
        e = entry(w)
        assert e["label"] == "Play in turn (3 sounds)"
        assert [s["label"] for s in e["submenu"] if not s.get("sep")] == [
            "Add a sound to play in turn…", "One after another", "At random",   # PAD-638
            "Play sound 2 (Jackpot B.wav)", "Loudness of sound 2 (0 dB)…",   # PAD-638
            "Take off sound 2 (Jackpot B.wav)",
            "Play sound 3 (Jackpot C.wav)", "Loudness of sound 3 (0 dB)…",
            "Take off sound 3 (Jackpot C.wav)"]
        assert w.call("audio.menu_action", "turn_play:3", rel) is True
        assert w.state("audio")["panes"]["rep"]["name"] == "Sound 3 in turn: Jackpot C.wav"
        assert w.call("audio.menu_action", "turn_off:2", rel) is True
        assert _sidecar(proj)["sound_modes"]["turns"] == {rel: [os.path.normpath(c)]}
    # a fresh session has them back
    with web_app(tmp_path / "again", mfr="stern", era="spike2") as w:
        _open(w, proj)
        assert next(r for r in w.state("audio")["rows"] if r["k"] == rel)["tn"] == 2


def test_a_game_without_them_says_why(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _project
    from tests.webui_harness import web_app
    rel = "audio/idx0001 - Jackpot.wav"
    monkeypatch.setattr(SMo, "offer", lambda project, rels, probe=True: ("not here", {}))
    monkeypatch.setattr(SMo, "offer_turns", lambda project, rels, probe=True: ("Not on this game.", {}))
    from pinball_decryptor.webui import compat
    said = []
    monkeypatch.setattr(compat.messagebox, "showinfo", lambda title, text, **k: said.append((title, text)))
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, _project(tmp_path))
        items = w.call("audio.menu", rel, [rel])
        e = next(i for i in items if str(i.get("label", "")).startswith("Play in turn"))
        assert [s["label"] for s in e["submenu"]] == ["Why not this sound?"]
        assert w.call("audio.menu_action", "turn_why", rel) is True
        assert said == [("Play in turn", "Not on this game.")]


# ---- every Spike 2 build ---------------------------------------------------------------------------
def test_a_record_whose_grown_copy_the_encode_skipped_is_never_a_host_again():
    """Aerosmith Pro 1.16: the grown copy of idx 925 could not be re-encoded, the encode left it
    as it was, and the game played its old bytes as noise at file 3's turn."""
    params = [_p(2, 30000), _p(925, 25000), _p(1222, 24000), _p(258, 20000)]
    slot = params[0]
    assert E._sound_mode_host(params, slot, 26000, {}, set()) == 925
    E._HOST_EXCLUDE.idxs = {925}
    try:
        assert E._sound_mode_host(params, slot, 26000, {}, set()) == 1222
    finally:
        E._HOST_EXCLUDE.idxs = None


def test_a_skipped_host_works_the_build_out_again_without_it(monkeypatch):
    calls, said = [], []

    def inner(*a, **k):
        calls.append(set(E._HOST_EXCLUDE.idxs))
        if len(calls) == 1:
            raise E._HostsRetry([925])
        return (None, None, None, None, None)

    monkeypatch.setattr(E, "_compute_patches_inner", inner)
    got = E._compute_patches(None, [], "proj", lambda t, lvl="info": said.append(t), None,
                             lambda: False, dest_is_device=True)
    assert got[0] is None and calls == [set(), {925}]
    assert "sound idx 925" in said[0] and "again with other records" in said[0]
    assert E._HOST_EXCLUDE.idxs is None


def test_a_build_no_port_was_shipped_for_gets_one_derived(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from pinball_decryptor.plugins.stern import clip_variants as CV
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import title_reader as TR
    image = tmp_path / "foo_fighters_le-1_03_0.Release.16G.sdcard.raw"
    image.write_bytes(b"x")
    derived = SimpleNamespace(key="foo_fighters_le_1_03")
    read = []
    monkeypatch.setattr(CV, "project_title", lambda project, probe=False: None)
    monkeypatch.setattr(MP, "project_card", lambda project: SimpleNamespace(
        game_dir="foo_fighters_le", version="1.03.0", image=str(image)))
    monkeypatch.setattr(TR, "read_card", lambda card: read.append(card) or SimpleNamespace(port_path="x.port"))
    monkeypatch.setattr(MP, "profile_for_card", lambda g, v: derived if read else None)
    assert SMo.project_title("proj", probe=True) is derived and read == [str(image)]
    assert SMo.project_title("proj", probe=False) is None          # never opens the card on the UI thread


def test_the_proof_sweep_switch_offers_turns_on_any_build_with_the_record_lookup(monkeypatch):
    from pinball_decryptor.plugins.stern import mode_project as MP
    other = MP.profile("godzilla_pro_1_15")
    monkeypatch.setattr(SMo, "TURN_PROVEN", frozenset())
    assert SMo.title_refusal(other, turns=True) == SMo.NOT_PROVEN_TURNS % other.label
    monkeypatch.setenv(SMo.TURNS_ANY_ENV, "1")
    assert SMo.title_refusal(other, turns=True) == ""
    assert SMo.title_refusal(other) == SMo.NOT_PROVEN % other.label     # music modes stay gated


def test_the_turns_are_offered_on_one_build_per_game_its_latest():
    """David: "we don't need outdated versions, just the latest versions" - every one of them
    swept in the emulator (work/artifacts/PAD-565/emulator/sweep)."""
    games = [k.rsplit("-", 1)[0] for k in SMo.TURN_PROVEN]
    assert len(games) == len(set(games)) == 53
    assert {"james_bond_pro-1.06", "james_bond_le-1.06", "godzilla_le-1.16"} <= SMo.TURN_PROVEN
    assert "godzilla_pro-1.15" not in SMo.TURN_PROVEN
    assert {"avengers_infinity_le-1.10", "avengers_infinity_pro-1.10"} <= SMo.TURN_PROVEN     # PAD-481
