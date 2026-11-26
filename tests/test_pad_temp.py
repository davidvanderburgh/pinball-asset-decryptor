"""PAD-1596: every name the app gives the temp folder is in core/pad_temp.py,
and the space keeper uses who made a folder to know when it is a leftover."""

import ast
import json
import os
import subprocess
import sys
import tempfile
import time
import warnings

import pytest

from pinball_decryptor.core import host_temp, pad_temp
from pinball_decryptor.core import space_keeper as sk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = 86400
_FUNCS = ("mkdtemp", "mkstemp", "TemporaryDirectory", "NamedTemporaryFile")

#: Calls whose prefix is a parameter: the names their callers pass.
_PASSED = {
    ("pinball_decryptor/core/elevated_flash.py", "prefix"):
        ("pad_flash_", "pad_read_", "pad_network_", "pad_remote_", "pad_jjp_usb_"),
    ("pinball_decryptor/core/root_session.py", "prefix"):
        ("pad_iso_", "spooky_iso_"),
    ("pinball_decryptor/plugins/stern/engine.py", "base"):
        ("spike2_", "spike2_grow_", "spike2_revert_"),
    ("tools/spike2_emu/mkmulticard.py", "prefix"): ("mkmulticard.",),
}


def _sources():
    for top in ("pinball_decryptor", "tools"):
        for root, dirs, files in os.walk(os.path.join(ROOT, top)):
            dirs[:] = [d for d in dirs
                       if d not in ("tests", "test", "proof", "__pycache__")]
            for f in files:
                if f.endswith(".py"):
                    p = os.path.join(root, f)
                    rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
                    try:
                        with open(p, encoding="utf-8") as fh,                                 warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            tree = ast.parse(fh.read())
                    except (SyntaxError, UnicodeDecodeError):
                        continue
                    yield rel, tree


def _consts(tree):
    out = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
    return out


def _lead(node, consts):
    """The literal a name starts with, or None when it cannot be read."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    if isinstance(node, ast.JoinedStr) and node.values \
            and isinstance(node.values[0], ast.Constant):
        return node.values[0].value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return _lead(node.left, consts)
    return None


def _fname(call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def _registered(prefix):
    return pad_temp.lookup(prefix + "x") is not None or \
        pad_temp.lookup(prefix) is not None


def test_every_temp_name_in_the_tree_is_registered():
    bad = []
    for rel, tree in _sources():
        consts = _consts(tree)
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and _fname(n).endswith(_FUNCS)):
                continue
            kw = {k.arg: k.value for k in n.keywords}
            d = kw.get("dir")
            if d is None and _fname(n).endswith("mkdtemp") and len(n.args) >= 3:
                d = n.args[2]
            if d is not None and "gettempdir" not in ast.unparse(d):
                continue                    # not the temp folder
            pre = kw.get("prefix")
            if pre is None and _fname(n).endswith("mkdtemp") and len(n.args) >= 2:
                pre = n.args[1]
            where = "%s:%d" % (rel, n.lineno)
            if pre is None:
                if rel.startswith("pinball_decryptor/"):
                    bad.append("%s %s() has no prefix: its tmp* leftover "
                               "cannot be told apart" % (where, _fname(n)))
                continue
            lead = _lead(pre, consts)
            if lead is None:
                passed = _PASSED.get((rel, ast.unparse(pre)))
                if passed is None:
                    bad.append("%s prefix %s cannot be read: list what callers "
                               "pass in _PASSED" % (where, ast.unparse(pre)))
                    continue
                names = passed
            else:
                if lead.startswith("/"):
                    continue                # an absolute Linux path
                names = (lead,)
            bad += ["%s %r is not in core/pad_temp.py NAMES" % (where, x)
                    for x in names if not _registered(x)]
    assert not bad, "\n".join(bad)


def test_every_fixed_temp_folder_is_registered():
    bad = []
    for rel, tree in _sources():
        consts = _consts(tree)
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and _fname(n) == "join"
                    and len(n.args) >= 2
                    and "gettempdir" in ast.unparse(n.args[0])):
                continue
            lead = _lead(n.args[1], consts)
            if lead and not _registered(lead):
                bad.append("%s:%d %r" % (rel, n.lineno, lead))
    assert not bad, "\n".join(bad)


def test_the_app_makes_its_temp_folders_through_pad_temp():
    """So the keeper knows who made them (a bare tempfile.mkdtemp is not)."""
    bad = []
    for rel, tree in _sources():
        if not rel.startswith("pinball_decryptor/") or rel.endswith("pad_temp.py"):
            continue
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "mkdtemp"
                    and ast.unparse(n.func.value) in ("tempfile", "_tf")
                    and not any(k.arg == "dir" for k in n.keywords)):
                bad.append("%s:%d" % (rel, n.lineno))
    assert not bad, "use pad_temp.mkdtemp: " + ", ".join(bad)


def test_lookup_longest_prefix_and_exact_names():
    assert pad_temp.lookup("cc_dcs_x").detail == "Cactus Canyon DCS scratch"
    assert pad_temp.lookup("cc_x").detail == "Cactus Canyon scratch"
    assert pad_temp.lookup("pad-game-code-x").detail == "game file code staging"
    assert pad_temp.lookup("pad-game-x").detail == "game file export"
    assert pad_temp.lookup("spike2_card_cache").kept
    assert not pad_temp.lookup("spike2_card_cache_x").kept   # just a spike2_
    assert pad_temp.lookup("pad_card_preview").child_days == 7
    mb = pad_temp.lookup("pinball_spike2_multiboot")      # PAD-1598: a cache, not scratch
    assert mb.kept and mb.child_days == 30
    assert pad_temp.tmp_writer("x.json.tmp.123") == 123 == pad_temp.tmp_writer("x.tmp123")
    assert pad_temp.lookup("someone_elses") is None
    for name in ("spike1_x", "pad-modes-x", "pad-scenes-x", "pad-audio-x",
                 "image_sound_selftest_x", "pinball_spike2_multiboot",
                 "pad_srcfind_x", "pad-film-cut-x"):
        assert pad_temp.lookup(name), name


def test_the_tests_temp_folder_is_not_the_real_one(tmp_path_factory):
    td = os.path.realpath(tempfile.gettempdir())
    base = os.path.realpath(str(tmp_path_factory.getbasetemp()))
    if sys.platform == "darwin":
        # conftest's short folder of the session's own there (a unix socket path caps at 104 bytes)
        assert os.path.dirname(td) == os.path.realpath("/tmp")
        assert os.path.basename(td).startswith("padt-")
    else:
        assert td.startswith(base)
    assert os.environ["TEMP"] == tempfile.gettempdir()


# ------------------------------------------------------------------ owners
@pytest.fixture
def temp(tmp_path, monkeypatch):
    d = tmp_path / "temp"
    d.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(d))
    return d


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _aged(path, secs):
    t = time.time() - secs
    for root, dirs, files in os.walk(path):
        for n in dirs + files:
            os.utime(os.path.join(root, n), (t, t))
    os.utime(path, (t, t))


def _fill(path, n=10):
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "f.bin"), "wb") as f:
        f.write(b"x" * n)


def test_mkdtemp_notes_this_process_and_the_owner_states(temp):
    d = pad_temp.mkdtemp(prefix="pad-scenes-")
    assert os.path.dirname(d) == str(temp)
    assert pad_temp.owner_state(os.path.basename(d)) == "alive"
    rec = os.path.join(pad_temp.owners_dir(), os.path.basename(d))
    with open(rec, "w") as f:
        json.dump({"pid": _dead_pid(), "started": None}, f)
    assert pad_temp.owner_state(os.path.basename(d)) == "dead"
    # the same pid running another program (started differs) is not ours -
    # where a start time can be read at all (Windows, /proc; not macOS)
    if pad_temp._started(os.getpid()) is not None:
        with open(rec, "w") as f:
            json.dump({"pid": os.getpid(), "started": 12345}, f)
        assert pad_temp.owner_state(os.path.basename(d)) == "dead"
    assert pad_temp.owner_state("pad-scenes-nobody") is None
    elsewhere = pad_temp.mkdtemp(prefix="pad-scenes-", dir=str(temp.parent))
    assert pad_temp.owner_state(os.path.basename(elsewhere)) is None


def test_keeper_leaves_a_running_makers_folder_takes_a_dead_ones_in_an_hour(temp):
    live = pad_temp.mkdtemp(prefix="spike2_King_Kong_")       # this process
    dead = pad_temp.mkdtemp(prefix="spike2_King_Kong_")
    pad_temp.mark_owner(dead, pid=_dead_pid())
    unknown = str(temp / "pad-modes-abc")
    young_dead = pad_temp.mkdtemp(prefix="pad-scenes-")
    pad_temp.mark_owner(young_dead, pid=_dead_pid())
    for d in (live, dead, unknown, young_dead):
        _fill(d)
    _aged(live, 3 * DAY)
    _aged(dead, 2 * 3600)
    _aged(unknown, 2 * 3600)              # a day not yet gone: stays
    _aged(young_dead, 600)                # an hour not yet gone: stays
    plan = sk.plan_host(host_temp.scan(include_empty=True), time.time())
    assert [p["path"] for p in plan] == [dead]
    _aged(unknown, 2 * DAY)
    plan = sk.plan_host(host_temp.scan(include_empty=True), time.time())
    assert sorted(p["path"] for p in plan) == sorted([dead, unknown])


def test_empty_leftovers_go_too_but_the_window_does_not_list_them(temp):
    d = temp / "spike2_grow_0a1b2c3d"
    d.mkdir()
    _aged(str(d), 2 * DAY)
    assert host_temp.scan() == []
    plan = sk.plan_host(host_temp.scan(include_empty=True), time.time())
    assert [os.path.basename(p["path"]) for p in plan] == ["spike2_grow_0a1b2c3d"]


def test_a_caches_unused_entries_age_out_the_cache_stays(temp):
    cache = temp / "spike2_card_cache"
    old, used = str(cache / "a"), str(cache / "b")
    for d in (old, used):
        _fill(d, 1 << 20)
    _aged(old, 31 * DAY)
    _aged(used, 31 * DAY)
    os.utime(used, None)                 # a hit touches the folder
    half_dead = str(cache / ("c.tmp%d" % _dead_pid()))
    half_live = str(cache / ("d.tmp%d" % os.getpid()))
    for d in (half_dead, half_live):
        _fill(d)
        _aged(d, 2 * 3600)
    t = time.time() - 40 * DAY
    os.utime(str(cache), (t, t))         # the cache folder alone
    prev = temp / "pad_card_preview" / "k1"
    _fill(str(prev))
    _aged(str(prev), 8 * DAY)
    plan = sk.plan_host(host_temp.scan(include_empty=True), time.time())
    got = sorted(p["path"] for p in plan)
    assert got == sorted([old, half_dead, str(prev)])
    assert all(host_temp._is_safe(p) for p in got)
    assert host_temp.delete(got) > 0
    assert os.path.isdir(cache) and os.path.isdir(used)
    assert not any(os.path.exists(p) for p in got)


def test_the_window_marks_and_never_deletes_an_in_use_folder(temp):
    d = pad_temp.mkdtemp(prefix="pad-audio-")
    _fill(d)
    e, = host_temp.scan()
    assert e["in_use"] and e["detail"].endswith("(in use)")
    assert host_temp.delete([d]) == 0 and os.path.isdir(d)
    pad_temp.mark_owner(d, pid=_dead_pid())
    assert host_temp.delete([d]) == 10 and not os.path.exists(d)
    assert not os.path.exists(os.path.join(pad_temp.owners_dir(),
                                           os.path.basename(d)))


def test_owner_notes_of_gone_folders_are_dropped(temp):
    d = pad_temp.mkdtemp(prefix="pad-fonts-")
    os.rmdir(d)
    assert pad_temp.prune_owners() == 1
    assert os.listdir(pad_temp.owners_dir()) == []


def test_the_owners_folder_is_never_listed_or_deleted(temp):
    pad_temp.mkdtemp(prefix="pad-fonts-")
    assert all(os.path.basename(e["path"]) != pad_temp.OWNERS
               for e in host_temp.scan(include_empty=True))
    assert not host_temp._is_safe(pad_temp.owners_dir())


def test_keeper_run_reports_before_after(temp, monkeypatch, tmp_path):
    monkeypatch.setenv("PAD_SPACE_STATE", str(tmp_path / "keeper.json"))
    for v in ("PAD_UI_CAPTURE", "PAD_UI_NO_RIG", "PAD_SPACE_KEEPER"):
        monkeypatch.delenv(v, raising=False)
    for name in ("pad-modes-1", "pad-scenes-2", "image_sound_selftest_3"):
        _fill(str(temp / name), 1 << 20)
        _aged(str(temp / name), 2 * DAY)
    _fill(pad_temp.mkdtemp(prefix="pad-scenes-"), 1 << 20)   # an open tab's
    rec = sk.tidy(force=True, wsl=False)
    assert rec["count"] == 3 and rec["freed"] == 3 << 20
    assert [os.path.basename(e["path"]) for e in host_temp.scan()][0] \
        .startswith("pad-scenes-")


# ------------------------------------------------------------- card previews
def test_card_previews_unused_for_a_week_go(temp):
    from pinball_decryptor.webui import card_preview as CP
    root = CP.cache_root()
    for k, age in (("old", 8 * DAY), ("new", DAY), ("shown", 30 * DAY)):
        _fill(os.path.join(root, k))
        _aged(os.path.join(root, k), age)
    assert CP.prune_cache(keep=("shown",)) == 1
    assert sorted(os.listdir(root)) == ["new", "shown"]
    CP.touch(os.path.join(root, "new"))
    assert CP.prune_cache(now=time.time() + 6 * DAY) == 1   # shown went
    assert os.listdir(root) == ["new"]
