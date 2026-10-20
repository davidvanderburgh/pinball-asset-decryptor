"""PAD-645 (David: "make it work on all the other games too"): the flipper buttons' sounds in attract
(PAD-641) on every Spike 2 game and version.

- Every shipped port maps the framework's switch drain (21 had a shot dispatch instead, so the
  drain was never written; :func:`.portswitch.drain_source` gives the lines without `switch`
  lines), and a port derived on the user's machine gets it too (``port_derive.framework_core``).
- A port whose shots come from switch_hit sites keeps them: a drain added for the attract sounds
  says so (``value switch_edge_shots 0``), is hooked for them alone, and its edges are no second
  shot source (pad_mode_runtime.c ``edge_shots``). Every other port keeps the drain's edges as its
  shots, switch_hit sites or not (Godzilla Pro 1.16, James Bond).
- A build no carrier was measured on (Batman 66 1.13, the older and locally derived builds) rides
  a call read off its own play tables (:func:`.mode_sounds.own_calls`).
- A card of attract sounds alone is gated by the attract test, not by the sounds-in-turn one.
Emulator-proven by a rigbatch sweep over the library (docs/plans/pad645_attract_every_build.md)."""

import os
import struct
from types import SimpleNamespace

import pytest

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_sounds as MSo
from pinball_decryptor.plugins.stern import sound_modes as SMo

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, "..", "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c")
PORTS = os.path.join(HERE, "..", "tools", "spike2_emu", "modes", "sdk", "ports")
SHIPPED = sorted(n[:-len(".port")] for n in os.listdir(PORTS) if n.endswith(".port"))


# ---- every build ---------------------------------------------------------------------------------
@pytest.mark.parametrize("name", SHIPPED)
def test_every_shipped_port_maps_what_the_attract_sounds_need(name):
    port = MP.read_port(os.path.join(PORTS, name + ".port"))
    for site in SMo.ATTRACT_SITES:
        assert site in port["site"], site
    for d in SMo.ATTRACT_DATA:
        assert d in port["data"], d
    for v in SMo.ATTRACT_VALUES:
        assert v in port["value"], v


def test_every_shipped_build_offers_them_but_tmnt_pro_1_58():
    profs = {p.key: p for p in MP.profiles(MP.PORTS_DIR).values()}
    assert len(profs) == len(SHIPPED)
    # its sound bank is read with no record's play key (the codec's validated path): nothing can carry them
    assert {k: SMo.attract_refusal(p) for k, p in profs.items() if SMo.attract_refusal(p)} == {
        "turtles_pro_1_58": SMo.NO_ATTRACT % ("TMNT Pro 1.58", "the app cannot tell which of its sound records "
                                                               "each of its sounds plays")}


def test_a_build_with_no_measured_carrier_is_offered_them():
    prof = MP.profile("batman_1_13")
    assert MSo.carriers(prof.game_dir, prof.version) is None
    assert SMo.attract_refusal(prof) == ""


def test_a_port_without_the_drain_still_says_why(monkeypatch):
    prof = MP.profile("beatles_1_29")
    real = MP.read_port

    def no_drain(path):
        port = real(path)
        port["site"].pop("switch_drain")
        return port

    monkeypatch.setattr(MP, "read_port", no_drain)
    assert SMo.attract_refusal(prof) == SMo.NO_ATTRACT % (
        prof.label, "the app has not found where its game program reads the switches or looks its sounds up")


# ---- the runtime ----------------------------------------------------------------------------------
@pytest.mark.parametrize("name", SHIPPED)
def test_only_a_drain_added_for_the_attract_sounds_leaves_the_switch_hit_sites_the_shots(name):
    with open(os.path.join(PORTS, name + ".port"), encoding="utf-8") as f:
        text = f.read()
    port = MP.read_port(os.path.join(PORTS, name + ".port"))
    added = "# ---- PAD-645: the framework's switch drain" in text
    assert (port["value"].get("switch_edge_shots", 1) == 0) == added
    hits = any(s.startswith("switch_hit") for s in port["site"])
    p = MP.profile_from_port(os.path.join(PORTS, name + ".port"))
    if port["switch"]:
        # the profile names the route the runtime takes: the drain unless the port says otherwise
        seen = MP.SWITCH_EDGE_PROVEN if (not added or not hits) else MP.SWITCH_SHOTS_PROVEN
        assert bool(p.switch_shots_note) == (name not in seen)


#: folders of game programs (PAD_PORT_ELFS, else PAD_GAME_ELFS): <port name>.elf or <port name>.0.elf
ELF_DIRS = [d for v in ("PAD_PORT_ELFS", "PAD_GAME_ELFS") for d in (os.environ.get(v) or "").split(os.pathsep) if d]


@pytest.mark.parametrize("name", SHIPPED)
def test_every_shipped_ports_switch_values_are_its_own_programs(name):
    """Avengers LE/Pro 1.10 carried 1.09's generation-A record layout on a generation-B program:
    the first switch edge read a level through a number (9) and the game crashed in the runtime."""
    from pinball_decryptor.plugins.stern import portgen as G
    from pinball_decryptor.plugins.stern import portswitch as PS
    path = next((os.path.join(d, name + x) for d in ELF_DIRS for x in (".elf", ".0.elf")
                 if os.path.isfile(os.path.join(d, name + x))), None)
    if path is None:
        pytest.skip("game program not present: %s" % name)
    with open(path, "rb") as f:
        src = PS.drain_source(G.Elf(f.read()))
    port = MP.read_port(os.path.join(PORTS, name + ".port"))
    have = {n: v for n, v in port["value"].items()
            if n.startswith("switch_") and n not in ("switch_edge_shots", "switch_edge_log", "switch_hit_at")}
    assert have == dict(src["values"])
    for line in src["sites"]:
        if line.startswith("site "):
            assert port["site"][line.split()[1]][0] == int(line.split()[2], 0)


def test_a_record_with_no_pointer_where_the_values_say_turns_the_edges_off_not_the_game():
    with open(RUNTIME, encoding="utf-8") as f:
        c = f.read()
    edge = c[c.index("static void on_switch_edge(unsigned *r)"):]
    edge = edge[:edge.index("\n}\n")]
    assert "if (st < 0x10000u || desc < 0x10000u) {" in edge and "if (bad ||" in edge
    assert edge.index("st < 0x10000u") < edge.index("level = *(const unsigned char *)")


def test_the_runtime_reads_a_derived_port_to_its_end():
    """Godzilla LE 1.13's derived port is 155 KB (King Kong LE 0.96's 167 KB), its switch drain the last
    lines: a 128 KB cap had its attract sounds say "the port lacks a switch_* value"."""
    import re
    with open(RUNTIME, encoding="utf-8") as f:
        cap = int(re.search(r"#define PORT_MAX\s+(\d+)", f.read()).group(1))
    assert cap >= 1 << 20
    # and every value line of one: they name 229 (Bond 60th LE 1.10) to 267 (Godzilla LE 1.13), the drain's last
    values = int(re.search(r"#define N_VALUES\s+(\d+)", open(RUNTIME, encoding="utf-8").read()).group(1))
    assert values >= 512


def test_the_drain_hooked_for_the_attract_sounds_is_no_second_shot_source():
    with open(RUNTIME, encoding="utf-8") as f:
        c = f.read()
    # a hit counts only when switches_arm made the drain the port's shots
    assert "if (!hit || !playing || !edge_shots) return;" in c
    # the drain's edges are the shots wherever a port has one (Godzilla Pro 1.16, Bond: switch_hit sites too),
    # unless the port says the drain is there for the attract sounds alone (The Beatles 1.29 keeps switch_hit)
    assert "for (i = 0; i < port.n_site; i++) sites += is_switch_hit(port.site[i].name);" in c
    assert 'if (e && (!sites || pm_port_value("switch_edge_shots", 1))) {' in c and "edge_shots = 1;" in c
    # a card with no modes still logs the game's own requests when asked (the proof's census)
    att = c[c.index("static void att_arm(void)"):]
    att = att[:att.index("\n}\n")]
    assert 'pm_trigger("soundlog.on")' in att and "worker_log = 1;" in att


# ---- the derived ports ------------------------------------------------------------------------------
def test_a_derived_port_with_a_shot_dispatch_gets_the_drain_and_no_switch_lines(monkeypatch):
    from pinball_decryptor.plugins.stern import port_derive as PD
    from pinball_decryptor.plugins.stern import portswitch as PS
    src = dict(sites=["#   switch_edge: how", "site switch_edge      0x00001000 0xe92d4010 0xe1a04000",
                      "#   switch_drain: the drain", "site switch_drain     0x00002000 0xe92d4ff0 0xe30892f0"],
               data={"switch_records": 0x5000, "switch_count": 0x5004, "mode_mask": 0x5008},
               values=[("switch_drain_size", 384), ("switch_record_size", 32)], how="how", generation="B")
    monkeypatch.setattr(PS, "drain_source", lambda elf, info=None: src)
    monkeypatch.setattr(PS, "switch_source", lambda elf, first_bit=0: pytest.fail("not for a port with shots"))
    monkeypatch.setattr(PS, "cur_player_via_scores", lambda elf, scores: (None, "n/a"))
    monkeypatch.setattr(PS, "ball_end_event", lambda elf: (None, "n/a"))
    monkeypatch.setattr(PS, "hook_dispatch", lambda elf: None)
    monkeypatch.setattr(PD, "_entry_line", lambda kind, name, va, tgt: "%s %s 0x%08x" % (kind, name, va))
    lines = {"site": [], "data": ["data mode_mask 0x00005008"]}
    placed = {("site", "shot_dispatch"): 0x100, ("data", "mode_mask"): 0x5008, ("site", "ball_end"): 0x200,
              ("data", "cur_player"): 0x300}
    out = PD.framework_core(object(), lines, placed, {})
    assert lines["site"] == src["sites"]
    assert lines["data"] == ["data mode_mask 0x00005008", "data switch_records 0x00005000",
                             "data switch_count 0x00005004"]
    assert out["values"] == src["values"] + [("switch_edge_shots", 0)]
    assert out["mapped"] == [] and out["switch_lines"] == []
    assert placed[("site", "switch_edge")] == 0x1000 and placed[("site", "switch_drain")] == 0x2000


def test_the_drain_source_needs_a_hookable_per_switch_call(monkeypatch):
    from pinball_decryptor.plugins.stern import portgen as G
    from pinball_decryptor.plugins.stern import portswitch as PS
    info = dict(PS.SHAPES["A"], generation="A", drain=0x2000, drain_size=456, leaf=0x1000, count=1, records=2,
                mode_mask=3, desc_table=4)
    monkeypatch.setattr(PS, "site_line", lambda elf, name, va: "site %s 0x%08x" % (name, va))
    monkeypatch.setattr(G, "is_hooked_ok", lambda elf, va: True)
    src = PS.drain_source(object(), info)
    assert [l for l in src["sites"] if l.startswith("site ")] == ["site switch_edge 0x00001000",
                                                                  "site switch_drain 0x00002000"]
    assert src["values"] == [("switch_drain_size", 456), ("switch_record_size", 0x2c), ("switch_level_at", 1),
                             ("switch_level_via", 0), ("switch_level_before", 1), ("switch_flags_at", 0x1e),
                             ("switch_polarity_at", 0x20)]
    monkeypatch.setattr(G, "is_hooked_ok", lambda elf, va: False)
    assert PS.drain_source(object(), info) is None


# ---- the build's own calls --------------------------------------------------------------------------
def _site(sid, rec):
    return SimpleNamespace(sid=sid, payload=struct.pack("<II", rec, 0))


def test_own_calls_are_single_sid_single_record_mono_requests_longest_first(monkeypatch):
    from pinball_decryptor.plugins.stern import info as I
    from pinball_decryptor.plugins.stern.spike2 import sound_requests as SR
    monkeypatch.setattr(I, "container_counts", lambda head: (600, 500))
    monkeypatch.setattr(SR, "locate_sound_requests", lambda elf, fragments: (10, 0x1000))
    by_req = {1: [10], 2: [11], 3: [12], 4: [13, 14], 5: [15], 6: [15], 7: [16], 8: [17], 9: [18]}
    monkeypatch.setattr(MSo, "request_sids", lambda elf, fragments, reqs: {r: by_req.get(r, []) for r in reqs})
    sites = [_site(10, 100), _site(11, 101), _site(12, 102), _site(13, 105), _site(14, 106), _site(15, 103),
             _site(16, 104), _site(17, 104)]
    params = [{"idx": r, "chan": 2 if r == 102 else 1, "length": length,
               "findkey": struct.pack("<II", r, 0)}
              for r, length in ((100, 5000), (101, 9000), (102, 20000), (103, 30000), (104, 40000),
                                (105, 1), (106, 1))]
    # 3 stereo, 4 two sids, 5/6 one sid two requests, 7/8 one record two sids, 9 no record
    assert MSo.own_calls(b"elf", b"head", sites, params, 0xFFFFFFFF) == (2, 1)
    assert MSo.own_calls(b"elf", b"head", sites, params, 0xFFFFFFFF, limit=1) == (2,)
    monkeypatch.setattr(SR, "locate_sound_requests", lambda elf, fragments: (None, None))
    assert MSo.own_calls(b"elf", b"head", sites, params, 0xFFFFFFFF) == ()


def _wav(path, seconds, rate=44100, chans=1):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(chans)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * chans * int(seconds * rate))


def test_a_build_with_no_measured_carrier_rides_its_own_call(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_write as MW
    prof = MP.profile("batman_1_13")
    monkeypatch.setattr(MSo, "own_calls", lambda elf, head, sites, params, mask: (701, 702))
    monkeypatch.setattr(MW, "request_record", lambda elf, head, params, sites, r, mask: {701: 46, 702: 48}[r])
    monkeypatch.setattr(E, "_desc_key_mask", lambda params, sites, log=None: 0xE0001FFF)
    monkeypatch.setattr(SMo, "flipper_buttons", lambda elf: [62, 61])
    for name in ("game", "image.bin"):
        (tmp_path / name).write_bytes(b"\0" * 64)
    proj = tmp_path / "proj"
    (proj / "audio").mkdir(parents=True)
    for i in (46, 48):
        _wav(proj / "audio" / ("idx%04d.wav" % i), 0.1)
    m = SMo.clean({"attract": ["a.wav"]})
    logs = []
    E._attract_carrier(str(tmp_path / "game"), str(tmp_path / "image.bin"), [], [], str(proj), {46: "x.wav"},
                       m, prof, [], lambda t, lvl="info": logs.append(t))
    assert m.attract_plan == {"request": 702, "slot": 48, "switches": [62, 61]}
    assert logs == ["Attract flipper sounds: 1 file(s) ride request 702 (sound idx 48, a call of the game's own "
                    "that no other sound of it plays, read off its play tables); the flipper buttons are "
                    "switches 62 and 61."]
    # none found either: left out, and the log says why
    monkeypatch.setattr(MSo, "own_calls", lambda elf, head, sites, params, mask: ())
    m, logs[:] = SMo.clean({"attract": ["a.wav"]}), []
    E._attract_carrier(str(tmp_path / "game"), str(tmp_path / "image.bin"), [], [], str(proj), {},
                       m, prof, [], lambda t, lvl="info": logs.append(t))
    assert m.attract == [] and logs == [
        "Attract flipper sounds: 1 file(s) for the flipper buttons in attract mode are left out of this build: "
        "no sound of the game's that it never plays is known to carry them."]


# ---- the card's plan ----------------------------------------------------------------------------------
def test_a_card_of_attract_sounds_alone_is_gated_by_the_attract_test(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_write as MW
    prof = MP.profile("deadpool_le_1_14")
    assert SMo.title_refusal(prof, turns=True)                  # no sounds in turn on this build
    monkeypatch.setattr(MW, "find_port", lambda prof, elf: "the port")
    cfg = tmp_path / "sounds.cfg"
    cfg.write_text("only\nattract\t859\t12db800f64020050\t63,62\nafile\t1\t55293c45520e0000\t800\n",
                   encoding="utf-8")
    plan = MW.sound_modes_plan("proj", b"elf", prof, str(cfg))
    assert plan.sounds_file == str(cfg)
    # with a sound in turn on it, the sounds in turn's own gate holds
    cfg.write_text("only\nturn\t2\t00\t00\nattract\t859\t12db800f64020050\t63,62\n", encoding="utf-8")
    with pytest.raises(MW.ModeWriteError):
        MW.sound_modes_plan("proj", b"elf", prof, str(cfg))
    monkeypatch.setattr(SMo, "attract_refusal", lambda prof: "no drain here")
    cfg.write_text("only\nattract\t859\t12db800f64020050\t63,62\n", encoding="utf-8")
    with pytest.raises(MW.ModeWriteError, match="no drain here"):
        MW.sound_modes_plan("proj", b"elf", prof, str(cfg))


# ---- TMNT Pro 1.58's sound bank -----------------------------------------------------------------------
def test_the_validated_builds_own_plt_handlers_are_not_branched_through_the_got_again():
    from pinball_decryptor.plugins.stern.spike2 import emulator as EM
    handled = next(iter(EM.Spike2Emu.PLT))
    entries = {handled: 0x9000, 0x1234: 0x9004}
    # the validated build (TMNT Pro 1.58): its handler emulates the thunk whole (a second run of
    # operator new on its own pointer stopped the derive at 7 of 2053 sounds)
    assert EM.plt_branches(entries, False, EM.Spike2Emu.PLT) == {0x1234: 0x9004}
    # a generic build keeps every thunk's branch (PAD-609: the thunk branch wins there)
    assert EM.plt_branches(entries, True, EM.Spike2Emu.PLT) == entries
    assert entries == {handled: 0x9000, 0x1234: 0x9004}


def test_a_bank_whose_records_have_no_play_keys_says_why(tmp_path, monkeypatch):
    prof = MP.profile("turtles_pro_1_58")
    monkeypatch.setattr(E, "_desc_key_mask", lambda params, sites, log=None: 0xE0001FFF)
    for name in ("game", "image.bin"):
        (tmp_path / name).write_bytes(b"\0" * 64)
    m = SMo.clean({"attract": ["a.wav"]})
    logs = []
    E._attract_carrier(str(tmp_path / "game"), str(tmp_path / "image.bin"),
                       [{"idx": 1, "key0": None, "findkey": None}], [], str(tmp_path), {}, m, prof, [],
                       lambda t, lvl="info": logs.append(t))
    assert m.attract == [] and logs == [
        "Attract flipper sounds: 1 file(s) for the flipper buttons in attract mode are left out of this build: "
        "the app cannot tell which of this game's sound records each of its sounds plays, so no sound of its "
        "own can carry them."]


# ---- the game's own sound at a press: a silence of the build's own ------------------------------------
CARRIER = "audio/idx0046.wav"


def test_the_build_adds_a_silence_after_the_files_and_names_it_so():
    m = SMo.clean({"attract": ["a.wav", "b.wav"]})
    m.attract_rel, m.attract_quiet = CARRIER, "quiet.wav"
    q = SMo.attract_mode(SMo.ATTRACT_QUIET)
    assert m.files()[-1] == (CARRIER, q, "quiet.wav") and len(m.files()) == 3
    assert SMo.ATTRACT_QUIET == SMo.ATTRACT_MAX + 1 and SMo.is_attract(q) and SMo.is_turn(q)
    assert SMo.what(CARRIER, q) == "the silence the game's own sound at a press plays"
    assert SMo.tag(CARRIER, q) == "the silence for the game's own sound at a flipper button press in attract"
    assert SMo.when(q) == "in place of the game's own sound at a flipper button press in attract"
    # never saved, and no silence without a file of the project's
    assert SMo.to_json(m) == {"names": [], "slots": {}, "attract": ["a.wav", "b.wav"]}
    m.attract = []
    assert m.files() == []


def test_the_table_names_the_silence_and_the_card_record_leaves_it_out():
    params = [{"idx": 46, "findkey": b"C" * 8}, {"idx": 80, "findkey": b"A" * 8, "grown": True},
              {"idx": 90, "findkey": b"Q" * 8, "grown": True}]
    m = SMo.clean({"attract": ["C:/mine/a.wav"]})
    m.attract_rel, m.attract_plan, m.attract_quiet = CARRIER, {"request": 1057, "slot": 46, "switches": [64, 63]}, "q.wav"
    used = [{"rel": CARRIER, "slot": 46, "mode": SMo.attract_mode(1), "host": 80, "frames": 35280, "db": 0},
            {"rel": CARRIER, "slot": 46, "mode": SMo.attract_mode(SMo.ATTRACT_QUIET), "host": 90, "frames": 4410,
             "db": 0}]
    got = E._attract_lines(params, used, m, lambda t, lvl="info": None)
    assert got == {"request": 1057, "key": b"C" * 8, "switches": [64, 63], "files": [(b"A" * 8, 800)],
                   "quiet": b"Q" * 8}
    assert used[0]["lines"] == 1 and "lines" not in used[1]
    text = SMo.cfg_text(0, 0, [], True, attract=got, record=SMo.card_record(m, used))
    assert "aquiet\t" + (b"Q" * 8).hex() in text.splitlines()
    rec = SMo.read_card_record(text)
    assert [a["k"] for a in rec["attract"]] == [1]


def test_the_silence_is_a_short_mono_wav(tmp_path, monkeypatch):
    import tempfile
    import wave
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    path = E._attract_quiet_wav(lambda *a, **k: None)
    with wave.open(path) as w:
        assert (w.getnchannels(), w.getframerate(), w.getnframes()) == (1, 44100, 4410)
        assert set(w.readframes(4410)) == {0}


def test_the_runtime_has_the_games_own_sound_at_a_press_play_the_silence():
    with open(RUNTIME, encoding="utf-8") as f:
        c = f.read()
    assert 'str_eq(f[0], "aquiet")' in c and "att_quiet_line(f[1]);" in c
    # either edge of a flipper button in attract opens the window (Deadpool plays its own at the release)
    edge = c[c.index("static void att_edge(unsigned id, unsigned level, unsigned flags, unsigned polarity, "
                       "unsigned mask)\n{"):]
    edge = edge[:edge.index("\n}\n")]
    assert edge.index("att.edge_at = now;") < edge.index("/* the release */")
    # the worker's entry: any request but the carrier, within ATT_QUIET_MS of the edge, not in a game
    assert "if (att_live) att_worker(r[0]);" in c
    worker = c[c.index("static void att_worker(unsigned request)\n{"):]
    worker = worker[:worker.index("\n}\n")]
    assert "request == att.request" in worker and "ATT_QUIET_MS" in worker and "pm_in_game()" in worker
    # its record lookups take the silence, never the carrier's own
    look = c[c.index("static int att_lookup(unsigned *r)\n{"):]
    look = look[:look.index("\n}\n")]
    assert "!key_is(k, att.key)" in look and "r[1] = (unsigned)(unsigned long)att.quiet;" in look
    # the worker is hooked for it; without one the game's sound plays too
    arm = c[c.index("static void att_arm(void)"):]
    arm = arm[:arm.index("\n}\n")]
    assert "att.has_quiet = 0;" in arm and 'hook(fn("sound_worker"), on_sound_worker)' in arm
