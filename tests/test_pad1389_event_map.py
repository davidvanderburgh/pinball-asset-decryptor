"""PAD-1389: a build whose event bus numbers its events differently keeps the reference's events.

King Kong LE 1.00 added one id to the event bus (it ends at 208, every newest shipped reference's at 207): every id
from 0xb6 up moved by one, and the port the app derived for it left out every numbered event - game_start and
ball_start with them, so the Play options tab offered no Score feed (nor Prolonged Competition) for it. The event map
(``ports/recipes/eventbus-207.busmap.gz``, ``port_tool.py busmap``) holds a ladder for every handler on a reference
build's bus; the target's own subscriptions tell where each id went (``portgen.fit_bus_offsets``)."""
import os
import pathlib
import sys
from collections import Counter

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
PORTS = REPO / "tools" / "spike2_emu" / "modes" / "sdk" / "ports"

from pinball_decryptor.plugins.stern import portgen as G  # noqa: E402

ELF_DIRS = [d for v in ("PAD_PORT_ELFS", "PAD_GAME_ELFS")
            for d in (os.environ.get(v) or "").split(os.pathsep) if d]


def _elf_bytes(name):
    for d in ELF_DIRS:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                return f.read()
    pytest.skip("game program not present: %s" % name)


def _votes(rbound, moved_from, delta, skip=(), every=1):
    """Votes as a build with ``delta`` ids added (or taken out) at ``moved_from`` gives them: two handlers per id."""
    out = {}
    for i in range(0, rbound + 1, every):
        if i in skip:
            continue
        out[i] = Counter({i + (delta if i >= moved_from else 0): 2})
    return out


# ---- the fit -------------------------------------------------------------------------------------
def test_an_added_id_moves_every_id_above_it_and_none_below():
    votes = _votes(207, 0xb6, 1, skip=range(0xad, 0xb6))
    m = G.fit_bus_offsets(votes, 207, 208)
    assert m[0x4d] == 0x4d and m[0x25] == 0x25 and m[0x34] == 0x34     # game_start, ball_start, ball_end
    assert m[0xc6] == 0xc7 and m[0xb6] == 0xb7 and m[207] == 208
    # where the new id went in is not known between the last unmoved id and the first moved one: left out
    assert all(i not in m for i in range(0xad, 0xb6))
    assert m[0xac] == 0xac


def test_an_id_with_no_handlers_is_placed_by_its_neighbours():
    votes = _votes(207, 0xb6, 1)
    del votes[0xc8], votes[0x28]                       # tilt_warning and bonus_end have no handlers
    m = G.fit_bus_offsets(votes, 207, 208)
    assert m[0xc8] == 0xc9 and m[0x28] == 0x28


def test_a_removed_id_moves_the_ids_above_it_down():
    votes = _votes(207, 0x60, -1)
    m = G.fit_bus_offsets(votes, 207, 206)
    assert m[0x5f] == 0x5f and m[0x60] == 0x5f and m[0x61] == 0x60
    assert m[0x4d] == 0x4d and m[206] == 205 and m[207] == 206



def test_stray_votes_do_not_move_an_id():
    votes = _votes(207, 0xb6, 1)
    votes[0x27] = Counter({0x6a: 1})                   # a ladder that found another function
    votes[0x30] = Counter({0x31: 1, 0x30: 1})          # a handler subscribed to two ids
    votes[0xc6] = Counter({0x4b: 1, 0xc7: 2})
    m = G.fit_bus_offsets(votes, 207, 208)
    assert m[0x27] == 0x27 and m[0x30] == 0x30 and m[0xc6] == 0xc7


def test_too_little_evidence_maps_nothing():
    votes = {i: Counter({i: 1}) for i in range(G.BUSMAP_MIN_IDS - 1)}
    assert G.fit_bus_offsets(votes, 207, 208) == {}
    assert G.fit_bus_offsets({}, 207, 208) == {}
    assert G.fit_bus_offsets(_votes(207, 0xb6, 1), 0, 208) == {}


# ---- where an id goes ----------------------------------------------------------------------------
def test_the_same_bus_keeps_the_id(monkeypatch):
    monkeypatch.setattr(G, "bus_bound", lambda elf: 207)
    assert G.event_id_here(object(), 0x4d, 207) == (0x4d, "")
    here, why = G.event_id_here(object(), 230, 207)
    assert here is None and "outside" in why


def test_another_bus_reads_the_id_off_the_event_map(monkeypatch):
    monkeypatch.setattr(G, "bus_bound", lambda elf: 208)
    monkeypatch.setattr(G, "busmap_for", lambda b: {"elf_sha1": "x"} if b == 207 else None)
    monkeypatch.setattr(G, "bus_id_map", lambda tgt, bm: {0x4d: 0x4d, 0xc6: 0xc7})
    here, how = G.event_id_here(object(), 0xc6, 207)
    assert here == 0xc7 and "0xc7 here for the reference's 0xc6" in how
    assert G.event_id_here(object(), 0x4d, 207)[0] == 0x4d
    here, why = G.event_id_here(object(), 0xb0, 207)
    assert here is None and "cannot tell where 0xb0 went" in why
    # no event map for the reference's bus: left out, as before the map
    here, why = G.event_id_here(object(), 0x4d, 206)
    assert here is None and "no event map" in why


def test_the_draft_writes_the_event_at_this_builds_id(monkeypatch):
    """apply_recipe's `event` lines: kept at the mapped id, left out (with why) where the map cannot tell or the id
    is past the runtime's 0..207."""
    calls = {}

    def here(tgt, ident, rbound):
        calls[ident] = rbound
        return {0x4d: (0x4d, ""), 0xc6: (0xc7, "moved"), 0xc7: (0xd0, "moved")}.get(ident, (None, "cannot tell"))

    monkeypatch.setattr(G, "event_id_here", here)
    out, report = [], Counter()
    lines = ["event game_start     0x4d", "event tilt           0xc6", "event top 0xc7", "event odd 0xb0"]
    for line in lines:
        rest = line.split(None, 1)[1]
        G._draft_event(rest, rest.split(), object(), {"bus_bound": 207}, set(), out, report)
    text = "\n".join(out)
    assert "\nevent game_start     0x4d" in "\n" + text
    assert "\nevent tilt           0xc7" in "\n" + text
    assert "# event top 0xc7   <- left out: 0xd0 here, past the ids the mode runtime watches (0..207)" in text
    assert "# event odd 0xb0   <- left out: cannot tell" in text
    assert report["event copied"] == 2 and report["event left out"] == 2
    assert calls == {0x4d: 207, 0xc6: 207, 0xc7: 207, 0xb0: 207}


# ---- the shipped map -----------------------------------------------------------------------------
def test_the_event_map_ships_for_the_newest_references_bus():
    p = G.busmap_path(207, str(PORTS / "recipes"))
    assert os.path.isfile(p)
    bm = G.load_busmap(p)
    assert bm["bus_bound"] == 207 and bm["generation"] == "B" and len(bm["handlers"]) >= 100
    for v0, v1, masks, hashes in bm["chains"]:          # hashes, masks and offsets, never the program's code
        assert set(masks) <= set("fbpw")
        assert all(isinstance(h, int) for h in hashes.values())
    assert all(isinstance(lid, int) for _i, _h, lid in bm["handlers"])


def test_every_newest_reference_has_its_event_map():
    """The references a derivation ranks first are the newest builds; their bus must have a map."""
    bounds = {G.load_recipe(str(p))["bus_bound"] for p in (PORTS / "recipes").glob("*.recipe.gz")
              if p.name.startswith(("godzilla_le-1.16", "king_kong_le-0.97", "jaws_le-1.02", "venom_le-1.07"))}
    assert bounds == {207}
    assert os.path.isfile(G.busmap_path(207, str(PORTS / "recipes")))


# ---- the real case (skips without the programs: PAD_PORT_ELFS) ------------------------------------
def test_king_kong_le_1_00_keeps_its_events_at_its_own_ids():
    old = G.Elf(_elf_bytes("king_kong_le-0.97.elf"))
    new = G.Elf(_elf_bytes("king_kong_le-1.00.elf"))
    assert G.bus_bound(old) == 207 and G.bus_bound(new) == 208
    bm = G.load_busmap(G.busmap_path(207, str(PORTS / "recipes")))
    m = G.bus_id_map(new, bm)
    assert m[0x4d] == 0x4d and m[0x25] == 0x25 and m[0x34] == 0x34      # game_start, ball_start, ball_end
    assert m[0xc6] == 0xc7 and m[0xc8] == 0xc9                          # tilt, tilt_warning moved
    assert G.bus_id_map(old, bm)[0xc6] == 0xc6
