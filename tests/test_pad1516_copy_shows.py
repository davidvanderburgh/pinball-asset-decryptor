"""PAD-1516: expression light shows copied in from another project.

Jim-Beam (Bond Pro 1.06): "Would it be possible to store/copy those animations to take it to other titles like Iron
Maiden?" New show's From another project lists the shows of the other projects the app knows; a copy keeps its steps
(colours and patterns over a lane play on any cabinet), keeps its song only on the same game, and a show playing a
game's own frames from its program stays in its project when the game differs.
"""
import os
import types

import pytest

from pinball_decryptor.core import project_registry, staged_changes
from pinball_decryptor.plugins.stern import cab_shows as CS
from pinball_decryptor.webui.tabs import lights as LT


def _show(name, slot=12, game=False):
    st = CS.game_step(66, 5000) if game else CS.step("pulse", 2000, "#ff0000", "#0000ff", 500, 0)
    return CS.norm_show({"name": name, "slot": slot, "loop": True, "blades": [st], "speakers": [st]})


# ---- the rules -------------------------------------------------------------------------------------------------
def test_another_games_copy_drops_its_song_and_keeps_its_steps():
    a = _show("Pulse")
    copied, left = CS.copy_shows([a], False, [], 32)
    assert left == []
    assert copied[0]["slot"] is None
    assert copied[0]["speakers"] == a["speakers"] and copied[0]["blades"] == a["blades"] and copied[0]["loop"]


def test_the_same_games_copy_keeps_its_song():
    copied, _ = CS.copy_shows([_show("Pulse", slot=229)], True, [], 32)
    assert copied[0]["slot"] == 229


def test_a_show_of_the_games_own_frames_stays_on_another_game_only():
    g = _show("Kashmir (original)", game=True)
    copied, left = CS.copy_shows([g], False, [], 32, "Led Zeppelin LE 1.22")
    assert copied == [] and left[0][0] == "Kashmir (original)" and "Led Zeppelin LE 1.22" in left[0][1]
    copied, left = CS.copy_shows([g], True, [], 32)
    assert len(copied) == 1 and left == []


def test_copies_are_named_apart_and_kept_to_the_room():
    copied, left = CS.copy_shows([_show("Pulse"), _show("Pulse"), _show("Sweep")], False, ["Pulse"], 2)
    assert [s["name"] for s in copied] == ["Pulse 2", "Pulse 3"]
    assert left == [("Sweep", "this project has room for %d shows" % CS.SHOWS_MAX)]


def test_the_source_is_not_changed():
    a = _show("Pulse")
    CS.copy_shows([a], False, [], 32)
    assert a["slot"] == 12


# ---- the page ---------------------------------------------------------------------------------------------------
class _Store:
    def __init__(self):
        self.d = {}

    def set(self, ns, **kw):
        self.d.setdefault(ns, {}).update(kw)

    def get(self, ns, k, default=None):
        return self.d.get(ns, {}).get(k, default)


class _Var:
    def __init__(self, v):
        self.v = v

    def get(self):
        return self.v


class _Win:
    def __init__(self, folder, settings):
        self.ctx = types.SimpleNamespace(store=_Store(), loop=types.SimpleNamespace(post=lambda fn, *a: fn(*a)))
        self.write_assets_var = _Var(folder)
        self.app = types.SimpleNamespace(_settings=settings)
        self.logs = []

    def append_log(self, text, level="info"):
        self.logs.append((level, text))

    def service(self, ns):
        return None


@pytest.fixture
def projects(tmp_path, monkeypatch):
    bond, im, lz, empty = (tmp_path / n for n in ("Bond Pro 1.06", "Iron Maiden", "Zeppelin", "Empty"))
    for p in (bond, im, lz, empty):
        p.mkdir()
    staged_changes.save(str(bond), {CS.STAGED_KEY: {"shows": [_show("Pulse", 229), _show("Sweep", 230)]}})
    staged_changes.save(str(lz), {CS.STAGED_KEY: {"shows": [_show("Kashmir (original)", 156, game=True)]}})
    settings = {}
    for p in (empty, lz, bond, im):
        project_registry.touch(settings, str(p))
    titles = {str(bond): "james_bond_pro-1.06", str(im): "iron_maiden_le-1.18", str(lz): "led_zeppelin_le-1.22"}
    monkeypatch.setattr(CS, "project_title",
                        lambda f, probe=False: types.SimpleNamespace(key=titles[f], label=titles[f]) if f in titles
                        else None)
    win = _Win(str(im), settings)
    tab = LT.LightsTab(win)
    tab._project = str(im)
    tab._shows = []
    monkeypatch.setattr(tab, "_paint", lambda: None)
    return types.SimpleNamespace(tab=tab, win=win, bond=str(bond), im=str(im), lz=str(lz))


def test_the_menu_lists_the_other_projects_with_shows(projects):
    got = projects.tab.other_shows()
    assert [p["folder"] for p in got] == [projects.bond, projects.lz]       # not itself, not one with no shows
    bond, lz = got
    assert [x["name"] for x in bond["shows"]] == ["Pulse", "Sweep"] and not bond["same"]
    assert all(not x["stays"] for x in bond["shows"])
    assert "led_zeppelin_le-1.22" in lz["shows"][0]["stays"]


def test_bond_shows_copied_into_iron_maiden(projects):
    t = projects.tab
    assert t.copy_in(projects.bond) == 0
    saved = CS.load(projects.im)
    assert [s["name"] for s in saved] == ["Pulse", "Sweep"] and all(s["slot"] is None for s in saved)
    assert CS.load(projects.bond)[0]["slot"] == 229                          # the source project stays as it was
    assert t.copy_in(projects.bond, [1]) == 2
    assert [s["name"] for s in CS.load(projects.im)][-1] == "Sweep 2"


def test_a_game_own_show_is_said_and_not_copied(projects):
    t = projects.tab
    assert t.copy_in(projects.lz) == -1
    assert CS.load(projects.im) == []
    assert any(lv == "warning" and "Kashmir (original)" in s for lv, s in projects.win.logs)


def test_only_a_known_project_is_read(projects, tmp_path):
    stray = tmp_path / "stray"
    stray.mkdir()
    staged_changes.save(str(stray), {CS.STAGED_KEY: {"shows": [_show("X")]}})
    assert projects.tab.copy_in(str(stray)) == -1


# ---- PAD-1516 round 4: recordings of a game's own cabinet lights ---------------------------------------------------
from pinball_decryptor.plugins.stern import cab_rec as CR  # noqa: E402

RING = [{"name": "SPEAKER %d" % (i + 1), "lane": 1, "side": 0, "u": i * 1000 // 4} for i in range(4)]


def _rec_bytes(frames=3, lights=4):
    return CR.pack(25, lights, [bytes([f * 10 + k for k in range(lights) for _ in range(3)]) for f in range(frames)])


def test_a_recording_is_saved_listed_and_removed(tmp_path):
    p = str(tmp_path)
    got = CR.save(p, "Bond", "James Bond Pro 1.06", RING, _rec_bytes())
    assert (got["frames"], got["lights"], got["period"], got["seconds"]) == (3, 4, 25, 0.1)
    assert [r["name"] for r in CR.listing(p)] == ["Bond"] and CR.free_name(p, "Bond") == "Bond 2"
    with open(got["file"], "ab") as f:
        f.write(b"x")                                    # a cut or grown file is not offered
    assert CR.listing(p) == []
    CR.remove(p, "Bond")
    assert not (tmp_path / "cab_rec" / "Bond.json").exists()


def test_a_recording_with_the_wrong_lights_is_refused(tmp_path):
    with pytest.raises(CR.RecError):
        CR.save(str(tmp_path), "Bond", "x", RING[:3], _rec_bytes())


def test_each_light_takes_the_nearest_recorded_light_of_its_lane():
    two_rings = [dict(L, side=s, u=u) for s in (-1, 1) for u, L in zip((0, 500), RING)]
    lights = [{"lane": 1, "side": -1, "u": 480}, {"lane": 1, "side": 1, "u": 20}, {"lane": 1, "side": 0, "u": 990},
              {"lane": 0, "side": -1, "u": 100}]
    assert CR.source_map(two_rings, lights) == [1, 2, 0, -1]          # side kept; round the ring; no blades: -1
    # Bond's 23 one-ring speakers onto a two-ring cabinet: every light gets one
    bond = [{"lane": 1, "side": 0, "u": i * 1000 // 23} for i in range(23)]
    assert -1 not in CR.source_map(bond, [{"lane": 1, "side": s, "u": u} for s in (-1, 1) for u in range(0, 1000, 90)])


def test_the_sampler_map_names_each_lights_channels():
    assert CR.map_arg([[(7, 1), (7, 0), (7, 2)], [(2, 5)]]) == "7:1,7:0,7:2;2:5"


def test_a_recording_step_goes_into_cabshow_cfg():
    s = CS.norm_show({"name": "Bond", "slot": 3, "loop": True,
                      "speakers": [{"fx": "rec", "ms": 30000, "rec": "Bond", "from": 500, "blend": 0}]})
    text, skipped = CS.cfg_text([s], {3: [77]}, True, recs={"Bond": {"file": "cabrec0.bin", "period": 25,
                                                                        "frames": 1200, "lights": 23, "map": [0, -1]}})
    assert skipped == []
    assert "rec 0 25 1200 23 cabrec0.bin\nrecmap 0 0,-1\n" in text and "speakers rec 30000 0 0 500 0" in text
    text, skipped = CS.cfg_text([s], {3: [77]}, True, recs={})                # its recording is not there: left out
    assert skipped == ["Bond"] and "show " not in text


def test_a_bad_recording_name_is_not_kept():
    assert CS.norm_step({"fx": "rec", "rec": "../x", "ms": 100})["rec"] == ""


def test_make_a_show_of_a_recording_and_copy_it_with_its_recording(projects):
    t = projects.tab
    CR.save(projects.bond, "James Bond", "James Bond Pro 1.06", RING, _rec_bytes())
    bond = LT.LightsTab(_Win(projects.bond, projects.win.app._settings))
    bond._project, bond._shows = projects.bond, CS.load(projects.bond)
    bond.set(lights=[{"lane": 1, "side": 0, "u": u} for u in (0, 250, 500, 750)])
    bond._paint = lambda: None
    i = bond.from_rec("James Bond")
    s = CS.load(projects.bond)[i]
    assert s["speakers"][0]["rec"] == "James Bond" and s["blades"] == [] and s["loop"]
    assert s["speakers"][0]["ms"] == 75
    assert t.copy_in(projects.bond, [i]) == 0
    got = CS.load(projects.im)[0]
    assert got["speakers"][0]["rec"] == "James Bond" and CR.find(projects.im, "James Bond") is not None


def test_cabs_into_stages_the_recording_with_this_cabinets_map(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_write as MW
    p = str(tmp_path / "proj")
    CR.save(p, "Bond", "x", RING, _rec_bytes())
    monkeypatch.setattr(MP, "read_port", lambda path: {"cablamp": [("SPEAKER %d" % (i + 1), [i], 0) for i in range(2)]})
    monkeypatch.setattr(MP, "port_path", lambda prof: "x.port")
    monkeypatch.setattr(CS, "layout_from_port", lambda port: [{"lane": 1, "side": 0, "u": 0},
                                                              {"lane": 1, "side": 0, "u": 760}])
    monkeypatch.setattr(CS, "title_refusal", lambda prof, added=None: "")
    result = MW.ModePlan(project=p, profile=types.SimpleNamespace(label="IM"), port=None, build=None)
    s = CS.norm_show({"name": "B", "slot": 1, "speakers": [{"fx": "rec", "ms": 75, "rec": "Bond"}]})
    MW.cabs_into(result, str(tmp_path / "out"), [s], {1: [9]}, only=True)
    assert [os.path.basename(f) for f in result.cabrec_files] == ["cabrec0.bin"]
    cfg = open(result.cabshow_file, encoding="utf-8").read()
    assert "rec 0 25 3 4 cabrec0.bin" in cfg and "recmap 0 0,3" in cfg
