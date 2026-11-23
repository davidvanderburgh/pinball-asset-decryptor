"""PAD-1536: concurrent test runs share one worker budget, and testpick
runs the tests a core / unzoned change reaches instead of everything."""

import os
import subprocess
import sys
import threading
import time
import types

import pytest

from tests import _worker_budget as wb
from tests import conftest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import testgraph  # noqa: E402
import testpick  # noqa: E402


@pytest.fixture
def budget_dir(tmp_path, monkeypatch):
    d = tmp_path / "budget"
    monkeypatch.setenv("PAD_TEST_BUDGET_DIR", str(d))
    for k in ("CI", "GITHUB_ACTIONS", "PYTEST_XDIST_AUTO_NUM_WORKERS",
              wb.HELD_ENV, "PAD_TEST_WORKERS", "PAD_TEST_WAIT"):
        monkeypatch.delenv(k, raising=False)
    yield d
    wb.release()


def _holder():
    """A live process to stand for another test run."""
    return subprocess.Popen([sys.executable, "-c",
                             "import time; time.sleep(60)"])


def _hold(d, pid, workers, where="PAD-other"):
    os.makedirs(d, exist_ok=True)
    wb._write(os.path.join(d, "run-%d.json" % pid),
              wb._record(pid, workers, where))


# -- the share --------------------------------------------------------------

def test_share_alone_takes_everything():
    assert wb.share(8, 0, 1) == 8


def test_share_splits_evenly_with_a_floor():
    assert wb.share(8, 8, 2) == 4
    assert wb.share(8, 8, 3) == 2
    assert wb.share(8, 8, 9) == wb.MIN_SHARE
    assert wb.share(1, 1, 2) == 1


# -- claims -----------------------------------------------------------------

def test_a_run_alone_gets_the_whole_budget(budget_dir):
    assert wb.claim(8, where="me") == 8
    claims, _ = wb._read(str(budget_dir))
    assert [c["workers"] for c in claims] == [8]
    wb.release()
    assert wb._read(str(budget_dir)) == ([], [])


def test_second_run_takes_half_when_half_is_free(budget_dir):
    p = _holder()
    try:
        _hold(budget_dir, p.pid, 4)
        assert wb.claim(8, where="me", wait_s=5) == 4
    finally:
        p.kill()


def test_second_run_waits_for_the_first_then_takes_all(budget_dir):
    p = _holder()
    said, got = [], []
    try:
        _hold(budget_dir, p.pid, 8)
        th = threading.Thread(target=lambda: got.append(
            wb.claim(8, where="me", say=said.append, wait_s=60, poll_s=0.1)))
        th.start()
        time.sleep(1.0)
        assert not got, "must wait while the other run holds every worker"
        assert said and "waiting" in said[0] and "PAD-other (8)" in said[0]
        _, waiters = wb._read(str(budget_dir))
        assert [w["pid"] for w in waiters] == [os.getpid()]
        p.kill()
        p.wait()
        th.join(20)
    finally:
        p.kill()
    assert got == [8]             # alone again: the whole budget


def test_a_wait_has_a_cap(budget_dir):
    p = _holder()
    said = []
    try:
        _hold(budget_dir, p.pid, 8)
        assert wb.claim(8, say=said.append, wait_s=0.3,
                        poll_s=0.05) == wb.MIN_SHARE
        assert any("anyway" in s for s in said)
    finally:
        p.kill()


def test_a_dead_run_holds_nothing(budget_dir):
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    _hold(budget_dir, p.pid, 8)
    assert wb.claim(8) == 8
    assert not os.path.exists(budget_dir / ("run-%d.json" % p.pid))


def test_a_reused_pid_holds_nothing(budget_dir):
    os.makedirs(budget_dir, exist_ok=True)
    rec = wb._record(os.getppid(), 8, "old")
    rec["created"] = (rec["created"] or 0) - 3600     # a different process
    wb._write(str(budget_dir / ("run-%d.json" % os.getppid())), rec)
    if rec["created"] == -3600:
        pytest.skip("no psutil: pid reuse is not checked")
    assert wb.claim(8) == 8


def test_disabled_on_ci_and_inside_a_run(monkeypatch, budget_dir):
    assert wb.enabled()
    monkeypatch.setenv("CI", "true")
    assert not wb.enabled()
    monkeypatch.delenv("CI")
    monkeypatch.setenv("PAD_TEST_WORKERS", "0")
    assert not wb.enabled()
    monkeypatch.setenv("PAD_TEST_WORKERS", "3")
    assert wb.enabled() and wb.budget(8) == 3
    monkeypatch.setenv(wb.HELD_ENV, "123")
    assert not wb.enabled()


# -- the conftest hook --------------------------------------------------------

def _config(numprocesses="auto"):
    return types.SimpleNamespace(
        option=types.SimpleNamespace(numprocesses=numprocesses),
        pluginmanager=types.SimpleNamespace(getplugin=lambda name: None),
        rootpath=REPO)


def test_hook_alone_is_xdists_own_count(budget_dir, monkeypatch):
    from xdist.plugin import pytest_xdist_auto_num_workers as xdist_count
    cfg = _config()
    assert conftest.pytest_xdist_auto_num_workers(cfg) == xdist_count(cfg)
    assert os.environ[wb.HELD_ENV] == str(os.getpid())


def test_hook_shares_with_another_run(budget_dir, monkeypatch, capsys):
    monkeypatch.setenv("PAD_TEST_WORKERS", "6")
    p = _holder()
    try:
        _hold(budget_dir, p.pid, 3)
        assert conftest.pytest_xdist_auto_num_workers(_config()) == 3
    finally:
        p.kill()
    assert "3 of 6" in capsys.readouterr().err


def test_hook_leaves_workers_and_ci_alone(budget_dir, monkeypatch):
    cfg = _config()
    cfg.workerinput = {}
    assert conftest.pytest_xdist_auto_num_workers(cfg) is None
    monkeypatch.setenv("CI", "1")
    assert conftest.pytest_xdist_auto_num_workers(_config()) is None


def test_real_run_waits_then_starts_small(budget_dir, tmp_path):
    """End to end: a pytest -n auto run while another run holds the whole
    budget says it is waiting, and its claim is gone once it ends."""
    p = _holder()
    env = dict(os.environ, PAD_TEST_BUDGET_DIR=str(budget_dir),
               PAD_TEST_WORKERS="4", PAD_TEST_WAIT="1")
    for k in (wb.HELD_ENV, "CI", "GITHUB_ACTIONS",
              "PYTEST_XDIST_AUTO_NUM_WORKERS"):
        env.pop(k, None)
    try:
        _hold(budget_dir, p.pid, 4)
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
             "tests/test_pad1536_test_budget.py", "-k", "test_share_alone"],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
    finally:
        p.kill()
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-2000:]
    assert "waiting for" in out and "starting on 2 anyway" in out
    left = [n for n in os.listdir(budget_dir) if n.endswith(".json")
            and n != "run-%d.json" % p.pid]
    assert left == []


# -- the import graph -------------------------------------------------------

def _repo(tmp_path, files):
    for rel, text in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return str(tmp_path)


GRAPH_FILES = {
    "pinball_decryptor/__init__.py": "",
    "pinball_decryptor/core/__init__.py": "",
    "pinball_decryptor/core/a.py": "X = 1\n",
    "pinball_decryptor/core/lonely.py": "Y = 2\n",
    "pinball_decryptor/core/fixture_dep.py": "Z = 3\n",
    "pinball_decryptor/b.py": "def f():\n    from .core import a\n",
    "pinball_decryptor/c.py": "import pinball_decryptor.b\n",
    "pinball_decryptor/reg.py": "MODS = ['pinball_decryptor.core.a']\n",
    "pinball_decryptor/tabs/__init__.py": "NAMES = ['one']\n",
    "pinball_decryptor/tabs/one.py": "",
    "pinball_decryptor/plain.py": "",
    "tools/r_emu/tool.py": "",
    "installer/build.sh": "",
    "tests/__init__.py": "",
    "tests/conftest.py": "from pinball_decryptor.core import fixture_dep\n",
    "tests/harness.py": "import pinball_decryptor.b\n",
    "tests/test_direct.py": "from pinball_decryptor.core.a import X\n",
    "tests/test_via_b.py": "import pinball_decryptor.b\n",
    "tests/test_via_c.py": "import pinball_decryptor.c\n",
    "tests/test_string.py": "import pinball_decryptor.reg\n",
    "tests/test_harness.py": "from tests import harness\n",
    "tests/test_tabs.py": "import pinball_decryptor.tabs\n",
    "tests/test_tool.py": "P = 'tools/r_emu/tool.py'\nQ = 'r_emu'\n",
    "tests/test_build.py": "S = 'installer/build.sh'\n",
    "tests/test_plain.py": "import pinball_decryptor.plain\n",
}


@pytest.fixture
def graph(tmp_path):
    return testgraph.Graph(_repo(tmp_path, GRAPH_FILES), cache=False)


def test_graph_function_imports_and_depth(graph):
    tests, conf = graph.tests_reaching("pinball_decryptor/core/a.py", 2)
    assert not conf
    assert {"tests/test_direct.py", "tests/test_via_b.py",
            "tests/test_string.py", "tests/test_harness.py"} <= tests
    assert "tests/test_via_c.py" not in tests          # three imports away
    far, _ = graph.tests_reaching("pinball_decryptor/core/a.py", None)
    assert "tests/test_via_c.py" in far
    assert "tests/test_plain.py" not in far


def test_graph_names_by_string(graph):
    assert graph.tests_reaching("pinball_decryptor/tabs/one.py", 2)[0] == {
        "tests/test_tabs.py"}
    assert graph.tests_reaching("tools/r_emu/tool.py", 2)[0] == {
        "tests/test_tool.py"}
    assert graph.tests_reaching("installer/build.sh", 2)[0] == {
        "tests/test_build.py"}


def test_graph_sees_conftest_imports(graph):
    assert graph.tests_reaching("pinball_decryptor/core/fixture_dep.py")[1]


def test_pick_narrows_a_core_change(graph):
    got, why, notes = testpick.graph_pick(["pinball_decryptor/core/a.py"],
                                          graph)
    assert why is None and "tests/test_direct.py" in got
    assert "within 2 imports" in notes[0]


def test_pick_goes_full_when_it_must(graph, monkeypatch):
    pick = testpick.graph_pick
    assert "conftest" in pick(["pinball_decryptor/core/fixture_dep.py"],
                              graph)[1]
    assert "no test reaches" in pick(["pinball_decryptor/core/lonely.py"],
                                     graph)[1]
    assert "not in the import graph" in pick(["pinball_decryptor/gone.py"],
                                             graph)[1]
    monkeypatch.setattr(testpick, "GRAPH_MOST", 0.1)
    assert "most of the suite" in pick(["pinball_decryptor/core/a.py"],
                                       graph)[1]


def test_pick_untested_python_outside_core_runs_nothing(tmp_path):
    files = dict(GRAPH_FILES)
    files["scripts/oneoff.py"] = ""
    g = testgraph.Graph(_repo(tmp_path, files), cache=False)
    got, why, notes = testpick.graph_pick(["scripts/oneoff.py"], g)
    assert (got, why) == (set(), None)
    assert "no test reaches it" in notes[0]


def test_eligibility():
    assert testpick.graph_eligible(*_why("pinball_decryptor/core/x.py"))
    assert testpick.graph_eligible(*_why("pinball_decryptor/app.py"))
    assert testpick.graph_eligible(*_why("tools/spike3_emu/mks3multi.py"))
    assert testpick.graph_eligible(*_why("installer/build_linux.sh"))
    for hard in ("tests/conftest.py", "pytest.ini", "requirements.txt",
                 ".github/workflows/tests.yml",
                 "pinball_decryptor/__init__.py"):
        assert not testpick.graph_eligible(*_why(hard)), hard


def _why(path):
    kind, val = testpick.classify(path)
    assert kind == "full", path
    return path, val


def test_changed_files_counts_new_untracked_files(tmp_path, monkeypatch):
    repo = _repo(tmp_path, {"a.py": ""})
    subprocess.run(["git", "-C", repo, "add", "a.py"], check=True)
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c",
                    "user.email=t@t", "commit", "-qm", "x"], check=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_new.py").write_text("")
    monkeypatch.setattr(testpick, "REPO", repo)
    assert testpick.changed_files(None) == ["tests/test_new.py"]


def test_real_repo_core_change_is_not_the_full_suite():
    """The case behind the ticket: on this repo a core module's change
    picks a fraction of the suite (sparse_card: PAD-1535's file)."""
    g = testgraph.Graph(REPO)
    got, why, _ = testpick.graph_pick(
        ["pinball_decryptor/core/sparse_card.py"], g)
    assert why is None
    assert 0 < len(got) < 0.25 * len(g.test_files())
    got, why, _ = testpick.graph_pick(["tools/spike3_emu/mks3multi.py"], g)
    assert why is None and 0 < len(got) < 0.25 * len(g.test_files())
