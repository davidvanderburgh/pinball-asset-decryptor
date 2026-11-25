"""PAD-1585: Update on a machine whose card is multi-boot - every image of the game on it, the rest left alone
(core/game_update.multiboot_plan, app._start_multiboot_update)."""
import os
import threading
import time
from types import SimpleNamespace

import pytest

from pinball_decryptor.core import game_update as G

GAMES = {"new.raw": ("king_kong_le", "1.01.0"), "mod100.raw": ("king_kong_le", "1.00.0"),
         "stock100.raw": ("king_kong_le", "1.00.0"), "gz.raw": ("godzilla_pro", "1.16.0"),
         "else100.raw": ("king_kong_le", "1.00.0"), "gone100.raw": ("king_kong_le", "1.00.0"),
         "kk101.raw": ("king_kong_le", "1.01.0")}


def _reader(card):
    return GAMES[os.path.basename(card)]


def test_every_image_of_the_game_is_planned_and_every_other_row_kept(tmp_path, monkeypatch):
    proj = tmp_path / "kk mods"; proj.mkdir()
    projects = {"mod100.raw": str(proj), "gone100.raw": str(tmp_path / "deleted")}
    monkeypatch.setattr(G, "_is_stock", lambda p: os.path.basename(p) == "stock100.raw")
    rows = [(0, "gz.raw", False), (1, "mod100.raw", False), (2, "stock100.raw", False),
            (3, "else100.raw", False), (4, "gone100.raw", False), (5, "kk101.raw", False), (6, "", True)]
    label, plan = G.multiboot_plan(rows, "new.raw", reader=_reader,
                                   project_of=lambda p: projects.get(os.path.basename(p)))
    got = {i: (k, w) for i, k, w in plan}
    assert "1.01" in label
    assert got[0][0] == "keep" and "another game" in got[0][1]
    assert got[1] == ("project", str(proj))
    assert got[2] == ("stock", "")
    assert got[3][0] == "keep" and "made elsewhere" in got[3][1]
    assert got[4][0] == "keep" and "is gone" in got[4][1]
    assert got[5][0] == "keep" and "already" in got[5][1]
    assert got[6][0] == "keep" and "random card" in got[6][1]


def test_a_card_with_none_of_the_games_images_is_refused():
    with pytest.raises(G.UpdateRefused, match="No image on this card"):
        G.multiboot_plan([(0, "gz.raw", False)], "new.raw", reader=_reader, project_of=lambda p: None)


def test_the_new_extract_is_named_for_its_project_so_two_never_share_one(tmp_path):
    a = G.workspace_for(str(tmp_path / "heisei"), "Godzilla Pro 1.17")
    b = G.workspace_for(str(tmp_path / "orchestral"), "Godzilla Pro 1.17")
    assert a != b and os.path.dirname(a) == str(tmp_path) and a.endswith("heisei (Godzilla Pro 1.17)")


# ---- the app's flow, against a stand-in Multi-boot panel ----------------------------------------------
class _Panel:
    def __init__(self, rows):
        self._rows = [SimpleNamespace(path=p, title=t, members=None, keep=False) for p, t in rows]
        self._busy, self._loaded_card, self.replaced, self.updated = False, "", [], []

    def load_card(self, card):
        self._loaded_card = card
        return True

    def replace_image(self, path, index):
        self.replaced.append((index, path))
        return True

    def update_card(self, after=None):
        self.updated.append(True)
        if after:
            after()
        return True


def test_the_flow_updates_the_projects_image_swaps_the_stock_one_and_updates_the_card_in_place(tmp_path,
                                                                                               monkeypatch):
    from pinball_decryptor import app as A
    from pinball_decryptor.core import mod_port
    from pinball_decryptor.webui import multiboot_core
    proj = tmp_path / "kk mods"; proj.mkdir()
    card = str(tmp_path / "kk.multi.raw")
    panel = _Panel([("gz.raw", "GODZILLA"), ("mod100.raw", "KONG MODS"), ("stock100.raw", "KING KONG")])
    monkeypatch.setattr(G, "multiboot_plan", lambda rows, raw: (
        "King Kong LE 1.01", [(0, "keep", "another game (Godzilla Pro 1.16)"), (1, "project", str(proj)),
                              (2, "stock", "")]))
    monkeypatch.setattr(multiboot_core, "is_group", lambda r: False)
    q, asked, chains, done = [], [], [], {}

    class Q:
        def put(self, m):
            q.append(m)
            fn = getattr(m, "fn", None)
            if fn is not None:
                fn()                                    # the UI loop, at once
    app = SimpleNamespace(window=SimpleNamespace(_multiboot_panel=panel, select_tab=lambda t: None),
                          msg_queue=Q(), _cancel_requested=False)
    app._ask_on_ui = lambda title, msg: asked.append((title, msg)) or True

    def run_jobs(jobs, raw, label, after):
        chains.append(jobs)
        after([(jobs[0], "ok", "1 audio transferred")])
    app._run_update_jobs = run_jobs
    assert A.App._start_multiboot_update(app, card, "new.raw", lambda c, rep, plan: done.update(c=c, rep=rep))
    for _ in range(100):
        if done:
            break
        time.sleep(0.05)
    assert asked and "Update the card to King Kong LE 1.01?" == asked[0][0]
    assert "GODZILLA: stays as it is: another game" in asked[0][1] and "KING KONG: becomes Stern's" in asked[0][1]
    job = chains[0][0]
    assert job["project"] == str(proj) and job["row"] == 1
    assert job["workspace"].endswith("kk mods (King Kong LE 1.01)")
    assert sorted(panel.replaced) == [(1, job["output"]), (2, "new.raw")]
    assert panel.updated == [True] and done["c"] == card and set(done["rep"]) == {1, 2}


def test_a_no_at_the_question_changes_nothing(tmp_path, monkeypatch):
    from pinball_decryptor import app as A
    from pinball_decryptor.webui import multiboot_core
    panel = _Panel([("mod100.raw", "KONG"), ("stock100.raw", "KING KONG")])
    monkeypatch.setattr(G, "multiboot_plan", lambda rows, raw: ("KK 1.01", [(0, "project", str(tmp_path)),
                                                                           (1, "stock", "")]))
    monkeypatch.setattr(multiboot_core, "is_group", lambda r: False)
    started, answered = [], threading.Event()
    app = SimpleNamespace(window=SimpleNamespace(_multiboot_panel=panel, select_tab=lambda t: None),
                          msg_queue=SimpleNamespace(put=lambda m: getattr(m, "fn", lambda: None)()),
                          _run_update_jobs=lambda *a: started.append(a))
    app._ask_on_ui = lambda t, m: answered.set() or False
    assert A.App._start_multiboot_update(app, str(tmp_path / "c.raw"), "new.raw")
    assert answered.wait(5)
    time.sleep(0.2)
    assert not started and not panel.replaced and not panel.updated
