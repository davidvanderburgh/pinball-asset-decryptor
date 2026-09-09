r"""The Tk lane's xdist grouping is the shape of the Windows CI job.

``conftest.pytest_collection_modifyitems`` stamps an ``xdist_group`` marker on
every tkinter-touching test.  ``--dist loadgroup`` then keeps a group on one
worker, so the marker decides how long the slowest worker runs -- and on the
Windows runner that worker IS the job: measured 2026-09-09, the lane ran 424s
on gw0 while the other three workers finished everything else in 281s and
idled for the remaining 3m26s.

Two properties are load-bearing and neither is visible from reading a test
run, so they are pinned here:

* **Membership.**  A file reaches Tk either by importing ``tkinter`` or by
  taking the shared ``app`` fixture from ``test_gui_smoke``.  Sniffing only
  the first missed the whole batch17/32/35/36/37 family, which then raced
  ungrouped across workers for a month (fixed 2026-09-01).  A new GUI test
  file must be grouped the day it appears, with nobody remembering to mark it.

* **Group count: ONE on CI, two on a dev box.**  Splitting CI's lane looks
  like free parallelism and is not.  Measured on the real Windows runner:
  one group ran the lane in 487s on a single worker; two groups ran 467s and
  395s side by side -- 862s of total Tk work for 20 seconds of critical path,
  because window create/map/destroy serializes at the desktop layer however
  many processes ask for it.  The 16-core dev box is shallow enough on that
  curve that a 2-way split still pays (232s -> 177s, a76064c) and stays the
  default there.  Anyone reading "CI only uses one worker for a third of the
  suite" as an oversight should read those numbers first.
"""
import os
import sys

import pytest

CONFTEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conftest.py")
sys.path.insert(0, os.path.dirname(CONFTEST))
import conftest as ctf  # noqa: E402


class _Item:
    """The two attributes the hook touches: ``path`` and ``add_marker``."""

    def __init__(self, path):
        self.path = path
        self.group = None

    def add_marker(self, marker):
        assert marker.mark.name == "xdist_group"
        self.group = marker.mark.args[0]


def _group(path, *, ci, platform, monkeypatch):
    monkeypatch.setattr(sys, "platform", platform)
    if ci:
        monkeypatch.setenv("CI", "1")
    else:
        monkeypatch.delenv("CI", raising=False)
    item = _Item(path)
    ctf.pytest_collection_modifyitems(None, [item])
    return item.group


def _tests_dir():
    return os.path.dirname(CONFTEST)


def test_a_file_that_imports_tkinter_is_grouped(tmp_path, monkeypatch):
    f = tmp_path / "test_thing.py"
    f.write_text("import tkinter\n", encoding="utf-8")
    assert _group(f, ci=True, platform="win32", monkeypatch=monkeypatch)


def test_a_file_that_only_takes_the_app_fixture_is_grouped(tmp_path, monkeypatch):
    """The sniff that missed this raced five modules across workers for a month."""
    f = tmp_path / "test_thing.py"
    f.write_text("from test_gui_smoke import app  # noqa\n", encoding="utf-8")
    assert _group(f, ci=True, platform="win32", monkeypatch=monkeypatch)


def test_a_file_that_never_touches_tk_is_left_alone(tmp_path, monkeypatch):
    f = tmp_path / "test_thing.py"
    f.write_text("import json\n\n\ndef test_x():\n    pass\n", encoding="utf-8")
    assert _group(f, ci=True, platform="win32", monkeypatch=monkeypatch) is None


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_ci_keeps_the_whole_lane_on_one_worker(platform, monkeypatch):
    """Two groups cost 862s of Tk work to save 20s of wall clock. Measured."""
    d = _tests_dir()
    app = _group(os.path.join(d, "test_gui_batch18.py"), ci=True,
                 platform=platform, monkeypatch=monkeypatch)
    emu = _group(os.path.join(d, "test_multiboot_tab.py"), ci=True,
                 platform=platform, monkeypatch=monkeypatch)
    assert app == emu == "tk"


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_a_developer_box_splits_the_lane(platform, monkeypatch):
    """Off CI the split is unconditional -- it is what took 232s to 177s."""
    d = _tests_dir()
    app = _group(os.path.join(d, "test_gui_batch18.py"), ci=False,
                 platform=platform, monkeypatch=monkeypatch)
    emu = _group(os.path.join(d, "test_multiboot_tab.py"), ci=False,
                 platform=platform, monkeypatch=monkeypatch)
    assert app and emu and app != emu


def test_every_real_tk_file_in_the_tree_is_grouped(monkeypatch):
    """Membership runs against the real suite, not a fixture.

    The criterion is reaching Tk, not being named ``test_gui*``: plenty of
    ``test_gui_batch*`` files drive window logic through SimpleNamespace stubs
    and never open a root, and those belong on the fast workers.  What must
    never happen again is a file that DOES open a root racing ungrouped.
    """
    d = _tests_dir()
    ungrouped = []
    for n in sorted(os.listdir(d)):
        if not (n.startswith("test_") and n.endswith(".py")):
            continue
        with open(os.path.join(d, n), encoding="utf-8", errors="replace") as f:
            src = f.read()
        if "tkinter" not in src and "test_gui_smoke" not in src:
            continue
        if _group(os.path.join(d, n), ci=True, platform="win32",
                  monkeypatch=monkeypatch) is None:
            ungrouped.append(n)
    assert ungrouped == []


def test_the_lane_is_a_real_share_of_the_suite(monkeypatch):
    """A split that grouped almost nothing would pass every test above."""
    d = _tests_dir()
    grouped = [
        n for n in sorted(os.listdir(d))
        if n.startswith("test_") and n.endswith(".py")
        and _group(os.path.join(d, n), ci=True, platform="win32",
                   monkeypatch=monkeypatch) is not None
    ]
    assert len(grouped) > 25
