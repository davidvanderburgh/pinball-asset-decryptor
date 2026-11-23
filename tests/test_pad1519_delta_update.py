"""PAD-1519: updates from the changed files alone.

David: "Can we do automatic delta updates?  so instead of replacing all the
files, we just do the new ones?"  A release publishes a file list and a pack
(installer/make_delta.py); an installed copy builds the next version from
its own files and fetches the rest (core/update_delta.py), and the setup
exe is only the fallback.
"""

import gzip
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time

import pytest

from pinball_decryptor.core import update_delta as ud
from pinball_decryptor.core import update_slots as us
from pinball_decryptor.core import updater
from tests.test_pad1024_background_update import (  # noqa: F401,F811
    WIN, _banner, _installer, _ready, _tree, _until, slots, staged)
from tests.webui_harness import web_app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "owner/pad"


def _md():
    spec = importlib.util.spec_from_file_location(
        "make_delta", os.path.join(ROOT, "installer", "make_delta.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


md = _md()


# ---------------------------------------------------------------- helpers
def _write(root, files):
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
    return root


def _sources(root):
    out = {}
    for dirpath, _d, names in os.walk(root):
        for n in names:
            full = os.path.join(dirpath, n)
            out[os.path.relpath(full, root).replace("\\", "/")] = full
    return out


class _Resp:
    def __init__(self, data, status):
        self._data, self._pos, self.status = data, 0, status

    def read(self, n=-1):
        end = len(self._data) if n is None or n < 0 else self._pos + n
        chunk = self._data[self._pos:end]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Releases:
    """GitHub's release downloads: ``<tag>/<name>`` files under a folder,
    served with Range, every request recorded."""

    def __init__(self, folder):
        self.folder, self.requests = folder, []
        self.ignore_range = False

    def path(self, tag, name=None):
        return os.path.join(self.folder, tag, name) if name else \
            os.path.join(self.folder, tag)

    def __call__(self, req, timeout=None):
        m = re.match(r"https://github\.com/%s/releases/download/([^/]+)/(.+)$"
                     % re.escape(REPO), req.full_url)
        assert m, req.full_url
        rng = req.get_header("Range")
        self.requests.append((m.group(1), m.group(2), rng))
        try:
            with open(self.path(m.group(1), m.group(2)), "rb") as f:
                data = f.read()
        except OSError:
            raise OSError("HTTP 404")
        if rng and not self.ignore_range:
            a, b = map(int, re.match(r"bytes=(\d+)-(\d+)", rng).groups())
            return _Resp(data[a:b + 1], 206)
        return _Resp(data, 200)


def _release(rel, version, tree, previous=None):
    """Build *tree*'s delta assets as release v*version*; the manifest."""
    name = "Pinball_Asset_Decryptor_v%s_Windows" % version
    prev = md.read_manifest(previous) if previous else None
    mpath, _ppath, stats = md.build(
        _sources(tree), version, rel.path("v" + version), name,
        previous=prev, repo=REPO,
        reachable=lambda url: md._reachable(url, rel), log=lambda *a: None)
    return mpath, stats


def _asset(mpath, version):
    with open(mpath, "rb") as f:
        raw = f.read()
    return {"name": os.path.basename(mpath),
            "url": "https://github.com/%s/releases/download/v%s/%s"
                   % (REPO, version, os.path.basename(mpath)),
            "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


BIG = os.urandom(300_000)           # does not compress: stored as it is

V1 = {"pinball_decryptor/__init__.py": '__version__ = "1.0.0"\n',
      "pinball_decryptor/app.py": "print('one')\n" * 50,
      "pinball_decryptor/core/keep.py": "KEEP = 1\n",
      "pinball_decryptor/core/gone.py": "GONE = 1\n",
      "python/python.exe": b"MZ python",
      "python/pythonw.exe": b"MZ pythonw",
      "python/big.dll": BIG,
      "python/Lib/site-packages/lib/mod.py": "A = 1\n",
      "python/Lib/site-packages/lib/same.py": "S = 1\n",
      "launcher.vbs": "vbs", "Pinball Asset Decryptor.pyw": "pyw",
      "tools/a.sh": "echo a\n", "tools/twin.sh": "echo a\n"}
V2 = dict(V1, **{
    "pinball_decryptor/__init__.py": '__version__ = "2.0.0"\n',
    "pinball_decryptor/app.py": "print('two')\n" * 50,
    "pinball_decryptor/core/new.py": "NEW = 1\n",
    "pinball_decryptor/core/new_twin.py": "NEW = 1\n",
    "python/Lib/site-packages/lib/mod.py": "A = 2\n"})
del V2["pinball_decryptor/core/gone.py"]


@pytest.fixture
def two(tmp_path):
    """Releases 1.0.0 and 2.0.0 on a stand-in GitHub, and an install of
    1.0.0 with compiled files, as the setup exe leaves it."""
    rel = _Releases(str(tmp_path / "releases"))
    t1 = _write(tmp_path / "t1", V1)
    t2 = _write(tmp_path / "t2", V2)
    m1, s1 = _release(rel, "1.0.0", t1)
    m2, s2 = _release(rel, "2.0.0", t2, previous=m1)
    app = _write(tmp_path / "PAD", V1)
    _write(app, {
        "unins000.exe": "u",
        "pinball_decryptor/core/__pycache__/keep.cpython-312.pyc": "kc",
        "pinball_decryptor/__pycache__/app.cpython-312.pyc": "stale",
        "python/Lib/site-packages/lib/__pycache__/same.cpython-312.pyc": "sc",
        "python/Lib/site-packages/lib/__pycache__/mod.cpython-312.pyc": "old",
        "python/Lib/site-packages/userpkg/f.py": "mine"})
    return {"rel": rel, "m1": m1, "m2": m2, "s1": s1, "s2": s2,
            "app": app, "t2": t2}


def _tree_of(root):
    return {k: open(v, "rb").read() for k, v in _sources(root).items()}


# ------------------------------------------------------ installer/make_delta
def test_the_file_list_is_read_from_the_installers_own_files_section(tmp_path):
    """The real pinball_decryptor.iss, whole: every entry is one this reader
    models (an unknown flag would stop the release's delta assets), and its
    wildcards and Excludes are applied as Inno applies them."""
    py = _write(tmp_path / "py", {"python.exe": "x", "Lib/a.py": "x",
                                  "Lib/__pycache__/a.cpython-312.pyc": "x",
                                  "Lib/__pycache__/orphan.cpython-312.pyc":
                                      "x"})
    files = md.iss_files(defines={"ProjectDir": ROOT, "PythonDir": str(py)})
    assert "pinball_decryptor/__init__.py" in files
    assert "pinball_decryptor/core/update_delta.py" in files
    assert "launcher.vbs" in files and "LICENSE" in files
    assert "stern-spike-3/tools/luks_otp.py" in files
    assert "tools/rigboard.sh" in files
    assert files["python/Lib/a.py"] == os.path.join(str(py), "Lib", "a.py")
    # Excludes: no compiled files from the project, no rig pictures or
    # logs - but the icons folder's own entry brings its .png back
    for rel in files:
        if not rel.startswith("python/"):
            assert "__pycache__" not in rel and not rel.endswith(".pyc"), rel
    rig = [r for r in files if r.startswith("tools/spike2_emu/")]
    assert rig and not any(r.endswith((".log", ".raw", ".dis")) for r in rig)
    png = [r for r in rig if r.endswith(".png")]
    assert png and all(r.startswith("tools/spike2_emu/icons/") for r in png)
    assert not any(r.startswith(("tools/spike2_emu/games/",
                                 "tools/spike2_emu/shots/")) for r in rig)
    # the build's python is shipped as it is, but a .pyc beside its source
    # is not listed: it differs on every build
    kept = md.drop_compiled(files)
    assert "python/Lib/__pycache__/a.cpython-312.pyc" not in kept
    assert "python/Lib/__pycache__/orphan.cpython-312.pyc" in kept
    assert "python/Lib/a.py" in kept


@pytest.mark.parametrize("line, says", [
    ('Source: "a.txt"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist',
     "unknown [Files] flag"),
    ('Source: "a.txt"; DestDir: "{app}"; Check: SomeCheck',
     "unknown [Files] parameter"),
    ('Source: "a.txt"; DestDir: "{sys}"', "DestDir outside"),
    ('Source: "nothing*.zip"; DestDir: "{app}"', "matches no file"),
])
def test_an_entry_the_reader_does_not_model_stops_it(tmp_path, line, says):
    (tmp_path / "a.txt").write_text("a")
    iss = tmp_path / "x.iss"
    iss.write_text("[Setup]\nAppName=x\n[Files]\n; comment\n%s\n[Run]\n"
                   % line)
    with pytest.raises(md.IssError, match=re.escape(says)):
        md.iss_files(str(iss))


def test_excludes_follow_innos_rules(tmp_path):
    _write(tmp_path, {"src/a.py": "", "src/a.log": "", "src/sub/b.py": "",
                      "src/sub/games/deep/x.bin": "", "src/games/y.bin": "",
                      "src/top.txt": "", "src/sub/top.txt": "",
                      "src/sub/__pycache__/b.pyc": ""})
    iss = tmp_path / "x.iss"
    iss.write_text(
        '[Files]\nSource: "src\\*"; DestDir: "{app}\\d"; \\\n'
        '    Flags: recursesubdirs ignoreversion; \\\n'
        '    Excludes: "__pycache__\\*,*.LOG,games\\*,\\top.txt"\n')
    assert sorted(md.iss_files(str(iss))) == [
        "d/a.py", "d/sub/b.py", "d/sub/top.txt"]


def test_a_releases_pack_holds_only_what_is_new(two):
    """The first release packs every file; the next one only the files no
    earlier pack has, and its file list points at the earlier pack for the
    rest - the upload on the release's critical path stays small."""
    assert two["s1"]["new_files"] == two["s1"]["files"] == len(V1)
    m2 = md.read_manifest(two["m2"])
    assert [p["tag"] for p in m2["packs"]] == ["v2.0.0", "v1.0.0"]
    new = sorted(r[0] for r in m2["files"] if r[3] == 0)
    assert new == ["pinball_decryptor/__init__.py",
                   "pinball_decryptor/app.py",
                   "pinball_decryptor/core/new.py",
                   "pinball_decryptor/core/new_twin.py",
                   "python/Lib/site-packages/lib/mod.py"]
    pack2 = os.path.getsize(two["rel"].path(
        "v2.0.0", "Pinball_Asset_Decryptor_v2.0.0_Windows.delta.pack"))
    assert pack2 < 1000 < len(BIG)
    assert pack2 == two["s2"]["pack_bytes"]
    # two files with the same bytes are one blob
    twins = [r for r in m2["files"] if r[0].startswith(
        "pinball_decryptor/core/new")]
    assert twins[0][2:] == twins[1][2:]


def test_a_yanked_releases_files_are_packed_again(two, tmp_path):
    """A pack that can no longer be downloaded (its release was deleted) is
    noticed at build time, and the next release carries those files itself."""
    os.unlink(two["rel"].path(
        "v1.0.0", "Pinball_Asset_Decryptor_v1.0.0_Windows.delta.pack"))
    said = []
    name = "Pinball_Asset_Decryptor_v3.0.0_Windows"
    mpath, _p, stats = md.build(
        _sources(two["t2"]), "3.0.0", two["rel"].path("v3.0.0"), name,
        previous=md.read_manifest(two["m2"]), repo=REPO,
        reachable=lambda url: md._reachable(url, two["rel"]),
        log=said.append)
    m3 = md.read_manifest(mpath)
    assert [p["tag"] for p in m3["packs"]] == ["v3.0.0", "v2.0.0"]
    assert any("v1.0.0 is gone" in s for s in said)
    by = {r[0]: r for r in m3["files"]}
    assert by["python/big.dll"][3] == 0                 # packed again
    assert by["pinball_decryptor/app.py"][3] == 1       # still in v2's pack


def test_verify_compares_an_installed_folder_with_the_file_list(two,
                                                                tmp_path):
    """The release workflow's tripwire: what the real setup exe installed
    against the file list.  Compiled files and the uninstaller are not the
    list's business; a missing, extra or different file is."""
    m2 = md.read_manifest(two["m2"])
    inst = _write(tmp_path / "inst", V2)
    _write(inst, {"unins000.exe": "u", ".pad_staged.json": "{}",
                  "pinball_decryptor/__pycache__/app.cpython-312.pyc": "c"})
    assert md.verify(str(inst), m2) == []
    (inst / "tools" / "a.sh").write_text("echo changed\n")
    (inst / "tools" / "extra.sh").write_text("x")
    os.unlink(inst / "python" / "big.dll")
    assert md.verify(str(inst), m2) == [
        "differs from the manifest: tools/a.sh",
        "installed but not in the manifest: tools/extra.sh",
        "in the manifest but not installed: python/big.dll"]


def test_the_command_line_builds_and_checks(two, tmp_path, capsys):
    out = tmp_path / "out"
    exe = out / "Pinball_Asset_Decryptor_v9.9.9_Windows.exe"
    proj = _write(tmp_path / "proj", {
        "pinball_decryptor/__init__.py": '__version__ = "9.9.9"\n',
        "installer/a.txt": "a"})
    iss = proj / "installer" / "x.iss"
    iss.write_text('[Files]\nSource: "{#ProjectDir}\\pinball_decryptor\\*"; '
                   'DestDir: "{app}\\pinball_decryptor"; '
                   'Flags: recursesubdirs ignoreversion\n')
    args = ["--project-dir", str(proj), "--iss", str(iss), "--out", str(out)]
    assert md.main(args + ["--installer", str(exe)]) == 0
    assert "1 files" in capsys.readouterr().out
    mpath = out / "Pinball_Asset_Decryptor_v9.9.9_Windows.delta.json.gz"
    assert (out / "Pinball_Asset_Decryptor_v9.9.9_Windows.delta.pack").exists()
    assert md.main(["--verify", str(proj), "--manifest", str(mpath)]) == 1
    assert "DOES NOT MATCH" in capsys.readouterr().out      # installer/…
    inst = _write(tmp_path / "i", {
        "pinball_decryptor/__init__.py": '__version__ = "9.9.9"\n'})
    assert md.main(["--verify", str(inst), "--manifest", str(mpath)]) == 0
    # the wrong version's installer is refused, not misnamed
    other = out / "Pinball_Asset_Decryptor_v1.0.0_Windows.exe"
    assert md.main(args + ["--installer", str(other)]) == 2


# ------------------------------------------------------- core/update_delta
def _build(two, target, **kw):
    manifest = ud.fetch_manifest(_asset(two["m2"], "2.0.0"), "2.0.0",
                                 two["rel"])
    two["rel"].requests.clear()
    return ud.build_tree(manifest, str(two["app"]), str(target),
                         opener=two["rel"], repo=REPO, **kw)


def test_the_new_version_is_built_from_the_install_and_the_changes(two,
                                                                   tmp_path):
    """v1.0.0 installed, v2.0.0 released: the unchanged files are copied
    from the install, the changed ones fetched from v2.0.0's pack, and what
    comes out is the release's tree, file for file."""
    nxt = tmp_path / "PAD.next"
    took = _build(two, nxt)
    got = _tree_of(nxt)
    pyc = {k: v for k, v in got.items() if k.endswith(".pyc")}
    plain = {k: v for k, v in got.items() if not k.endswith(".pyc")}
    assert plain == {k: (v if isinstance(v, bytes) else v.encode())
                     for k, v in V2.items()}
    assert md.verify(str(nxt), md.read_manifest(two["m2"])) == []
    assert took["changed"] == [
        "pinball_decryptor/__init__.py", "pinball_decryptor/app.py",
        "pinball_decryptor/core/new.py", "pinball_decryptor/core/new_twin.py",
        "python/Lib/site-packages/lib/mod.py"]
    assert took["copied"] == len(V2) - 5 and took["fetched"] == 5
    # only v2.0.0's small pack was touched, in one ranged request - never
    # the 300 KB dll's pack, never a whole file
    reqs = two["rel"].requests
    assert len(reqs) == 1 and reqs[0][0] == "v2.0.0" and reqs[0][2]
    assert took["fetched_bytes"] < 1000
    # compiled files: kept for the unchanged sources, never for a changed
    # one (the stale app.pyc and mod.pyc are not carried)
    assert sorted(pyc) == [
        "pinball_decryptor/core/__pycache__/keep.cpython-312.pyc",
        "python/Lib/site-packages/lib/__pycache__/same.cpython-312.pyc"]
    # an unchanged file keeps its timestamp, so its .pyc stays valid
    rel = "pinball_decryptor/core/keep.py"
    assert (os.stat(nxt / rel).st_mtime_ns
            == os.stat(two["app"] / rel).st_mtime_ns)
    assert not [n for n in got if n.endswith(".part")]


def test_a_damaged_or_missing_installed_file_is_fetched(two, tmp_path):
    """Whatever the install has is checked by hash, not trusted: a file
    edited or deleted since comes from the packs like a changed one - here
    from the EARLIER release's pack, which still holds it."""
    (two["app"] / "tools" / "a.sh").write_text("tampered\n")
    os.unlink(two["app"] / "python" / "big.dll")
    nxt = tmp_path / "PAD.next"
    took = _build(two, nxt)
    assert (nxt / "tools" / "a.sh").read_bytes() == b"echo a\n"
    assert (nxt / "python" / "big.dll").read_bytes() == BIG
    assert "python/big.dll" in took["changed"]
    assert {r[0] for r in two["rel"].requests} == {"v1.0.0", "v2.0.0"}
    assert md.verify(str(nxt), md.read_manifest(two["m2"])) == []


def test_a_pack_that_does_not_match_the_file_list_is_refused(two, tmp_path):
    pack = two["rel"].path(
        "v2.0.0", "Pinball_Asset_Decryptor_v2.0.0_Windows.delta.pack")
    data = bytearray(open(pack, "rb").read())
    data[len(data) // 2] ^= 0xFF
    open(pack, "wb").write(bytes(data))
    nxt = tmp_path / "PAD.next"
    with pytest.raises(ud.DeltaUnavailable, match="could not be downloaded"):
        _build(two, nxt)
    assert not [n for n in _sources(nxt) if n.endswith(".part")]
    # each range was tried again before giving up
    assert len(two["rel"].requests) == ud.FETCH_TRIES


def test_a_gone_pack_or_a_server_without_ranges_is_the_installers_turn(
        two, tmp_path):
    two["rel"].ignore_range = True
    with pytest.raises(ud.DeltaUnavailable, match="ignored the range"):
        _build(two, tmp_path / "a.next")
    two["rel"].ignore_range = False
    os.unlink(two["rel"].path(
        "v2.0.0", "Pinball_Asset_Decryptor_v2.0.0_Windows.delta.pack"))
    with pytest.raises(ud.DeltaUnavailable, match="could not be downloaded"):
        _build(two, tmp_path / "b.next")


def test_more_to_fetch_than_the_installer_is_not_worth_it(two, tmp_path):
    os.unlink(two["app"] / "python" / "big.dll")
    with pytest.raises(ud.DeltaUnavailable, match="no smaller than"):
        _build(two, tmp_path / "PAD.next", max_download=100_000)
    assert two["rel"].requests == []            # decided before any fetch


def test_a_cancel_stops_it(two, tmp_path):
    with pytest.raises(InterruptedError):
        _build(two, tmp_path / "PAD.next", cancel_cb=lambda: True)


def test_progress_is_the_copy_then_the_download(two, tmp_path):
    seen = []
    _build(two, tmp_path / "PAD.next",
           progress_cb=lambda *a: seen.append(a))
    assert ("copy", len(V2), len(V2)) in seen
    downloads = [s for s in seen if s[0] == "download"]
    assert downloads[0][1] == 0 and downloads[-1][1] == downloads[-1][2] > 0


def test_ranges_close_together_share_a_request():
    blobs = [(0, 10), (10, 10), (20 + ud.MERGE_GAP, 5),
             (21 + 2 * ud.MERGE_GAP + 5, 5)]
    assert ud.plan_spans(list(reversed(blobs))) == [
        [(0, 10), (10, 10), (20 + ud.MERGE_GAP, 5)],
        [(21 + 2 * ud.MERGE_GAP + 5, 5)]]
    big = [(0, ud.MAX_SPAN - 1), (ud.MAX_SPAN - 1, 10)]
    assert ud.plan_spans(big) == [[big[0]], [big[1]]]


def _manifest(**over):
    data = {"format": 1, "version": "2.0.0",
            "packs": [{"tag": "v2.0.0", "name": "x.delta.pack"}],
            "files": [["a/b.py", 3, "0" * 64, 0, 0, 3, 0]]}
    data.update(over)
    return gzip.compress(json.dumps(data).encode())


@pytest.mark.parametrize("path", [
    "../evil.py", "a/../../evil.py", "/abs.py", "C:/abs.py", "a\\b.py",
    "a//b.py", "a/./b.py", "nul", "a/con.txt", "a/b.py.", "a/ b.py", "",
    "a/b?.py", "a:b"])
def test_a_file_list_cannot_name_a_path_outside_the_folder(path):
    with pytest.raises(ud.DeltaUnavailable, match="bad entry"):
        ud.parse_manifest(_manifest(
            files=[[path, 3, "0" * 64, 0, 0, 3, 0]]), "2.0.0")


@pytest.mark.parametrize("over, says", [
    ({"version": "3.0.0"}, "is for v3.0.0"),
    ({"format": 2}, "format"),
    ({"files": []}, "empty"),
    ({"packs": [{"tag": "v2.0.0", "name": "evil.exe"}]}, "not a release"),
    ({"packs": [{"tag": "../../other/repo", "name": "x.delta.pack"}]},
     "not a release"),
    ({"packs": [{"tag": "v2.0.0", "name": "a/b.delta.pack"}]},
     "not a release"),
    ({"files": [["a.py", 3, "0" * 64, 5, 0, 3, 0]]}, "bad entry"),
    ({"files": [["a.py", 3, "xyz", 0, 0, 3, 0]]}, "bad entry"),
    ({"files": [["a.py", -3, "0" * 64, 0, 0, 3, 0]]}, "bad entry"),
    ({"files": [["a.py", 3, "0" * 64, 0, 0, 3, 0],
                ["A.PY", 3, "0" * 64, 0, 0, 3, 0]]}, "twice"),
])
def test_a_file_list_that_is_not_ours_is_refused(over, says):
    with pytest.raises(ud.DeltaUnavailable, match=says):
        ud.parse_manifest(_manifest(**over), "2.0.0")
    with pytest.raises(ud.DeltaUnavailable, match="unreadable"):
        ud.parse_manifest(b"\x1f\x8bnot gzip", "2.0.0")


def test_the_file_list_is_only_used_with_its_published_digest(two):
    asset = _asset(two["m2"], "2.0.0")
    assert ud.fetch_manifest(asset, "2.0.0", two["rel"])["version"] == "2.0.0"
    with pytest.raises(ud.DeltaUnavailable, match="integrity"):
        ud.fetch_manifest(dict(asset, sha256="0" * 64), "2.0.0", two["rel"])
    with pytest.raises(ud.DeltaUnavailable, match="could not be downloaded"):
        ud.fetch_manifest(dict(asset, url=asset["url"] + "x"), "2.0.0",
                          two["rel"])
    name = WIN % "2.0.0"
    rows = [{"name": name, "browser_download_url": "u"},
            {"name": name[:-4] + ".delta.json.gz", "digest": "sha256:" +
             "a" * 64, "browser_download_url": "m", "size": 5},
            {"name": name[:-4] + ".delta.pack", "browser_download_url": "p"}]
    picked = updater._pick_installer_asset(rows, platform="win32")
    assert picked["name"] == name                    # still the setup exe
    assert picked["delta"] == {"name": rows[1]["name"], "url": "m",
                               "size": 5, "sha256": "a" * 64}
    rows[1].pop("digest")                            # unverifiable: unused
    assert updater._pick_installer_asset(rows, platform="win32")[
        "delta"] is None
    assert updater._pick_installer_asset(rows[:1], platform="win32")[
        "delta"] is None
    # the other platforms' picks are as they were
    assert "delta" not in (updater._pick_installer_asset(
        [{"name": "x_Linux_x86_64.AppImage", "browser_download_url": "u"}],
        platform="linux", machine="x86_64"))


def test_compile_args_are_the_installers_plus_the_changed_library_sources(
        tmp_path):
    lst = tmp_path / "c.lst"
    args = ud.compile_args(r"C:\PAD.next", [
        "pinball_decryptor/app.py", "python/Lib/site-packages/lib/mod.py",
        "python/big.dll"], str(lst))
    assert args[:6] == [os.path.join(r"C:\PAD.next", "python", "python.exe"),
                        "-m", "compileall", "-q", "-j", "0"]
    assert args[6:] == ["-i", str(lst),
                        os.path.join(r"C:\PAD.next", "pinball_decryptor")]
    assert lst.read_text().split() == [os.path.join(
        r"C:\PAD.next", "python", "Lib", "site-packages", "lib", "mod.py")]
    assert "-i" not in ud.compile_args("x", ["pinball_decryptor/app.py"],
                                       str(tmp_path / "none.lst"))
    assert not (tmp_path / "none.lst").exists()


# --------------------------------------------------- update_slots: staging
class _Run:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, b"", b"")


def _fill_from(two, took=None):
    def fill(target, progress):
        manifest = ud.fetch_manifest(_asset(two["m2"], "2.0.0"), "2.0.0",
                                     two["rel"])
        got = ud.build_tree(manifest, str(two["app"]), target,
                            opener=two["rel"], repo=REPO,
                            progress_cb=lambda s, d, t: s == "copy"
                            and progress(d * 100 // t))
        if took is not None:
            took.update(got)
        return ["compile", "it"]
    return fill


def test_staging_from_changes_ends_like_the_installers(two):
    """The folder is filled from the install and the packs; what follows is
    what follows the setup exe: the layout check, the compile, what the
    user's install has that a fresh one lacks, the marker."""
    run, pcts = _Run(), []
    ok, carried = us.stage_delta_install(
        _fill_from(two), str(two["app"]), "2.0.0", run=run,
        progress_cb=pcts.append)
    assert ok
    assert sorted(carried) == [
        os.path.join("python", "Lib", "site-packages", "userpkg"),
        "unins000.exe"]
    nxt = us.next_dir(str(two["app"]))
    assert us.staged_install_ok(str(two["app"]), "2.0.0")
    assert json.load(open(os.path.join(nxt, us.MARKER))) == {
        "version": "2.0.0", "setup": None, "delta": True}
    assert os.path.isfile(os.path.join(
        nxt, "python", "Lib", "site-packages", "userpkg", "f.py"))
    # the Users grant goes on the EMPTY python folder, before anything is
    # written under it (every file then inherits it); no walk of the
    # finished tree
    assert [c[0][0].lower().endswith("icacls.exe") for c in run.calls] == [
        True, False]
    grant = run.calls[0][0]
    assert grant[1:] == [os.path.join(nxt, "python"), "/grant",
                         "*S-1-5-32-545:(OI)(CI)RX", "/C", "/Q"]
    assert "/T" not in grant
    assert run.calls[1][0] == ["compile", "it"]
    assert run.calls[1][1]["cwd"] == nxt
    assert pcts[0] == 0 and pcts[-1] == 100 and pcts == sorted(pcts)


@pytest.mark.parametrize("problem", ["raises", "wrong version", "cancel"])
def test_a_failed_delta_stage_leaves_nothing(two, problem):
    app = str(two["app"])

    def fill(target, progress):
        os.makedirs(os.path.join(target, "pinball_decryptor"))
        if problem == "raises":
            raise ud.DeltaUnavailable("the pack is gone")
        if problem == "cancel":
            raise InterruptedError("update canceled")
        _tree(two["app"].parent / "PAD.next", "1.5.0")
        return None
    if problem == "raises":
        with pytest.raises(ud.DeltaUnavailable):
            us.stage_delta_install(fill, app, "2.0.0", run=_Run())
    elif problem == "cancel":
        with pytest.raises(InterruptedError):
            us.stage_delta_install(fill, app, "2.0.0", run=_Run())
    else:
        assert us.stage_delta_install(fill, app, "2.0.0", run=_Run()) == (
            False, "the new install is v1.5.0, not v2.0.0")
    assert not os.path.exists(us.next_dir(app))
    assert us.tree_version(app) == "1.0.0"          # the install untouched


@pytest.mark.skipif(sys.platform != "win32", reason="the bundled Python")
def test_the_compile_step_really_compiles_only_what_changed(two):
    """Through a real Python standing in for the bundled one: the changed
    modules get their .pyc, the unchanged one keeps the one it had."""
    app = str(two["app"])
    nxt = us.next_dir(app)
    took = {}
    fill = _fill_from(two, took)

    def _fill(target, progress):
        fill(target, progress)
        cmd = ud.compile_args(target, took["changed"],
                              os.path.join(target, "c.lst"))
        return [sys.executable] + cmd[1:]
    ok, _ = us.stage_delta_install(_fill, app, "2.0.0")
    assert ok
    tag = sys.implementation.cache_tag
    pkg = os.path.join(nxt, "pinball_decryptor")
    assert os.path.isfile(os.path.join(pkg, "__pycache__",
                                       "app.%s.pyc" % tag))
    assert os.path.isfile(os.path.join(pkg, "core", "__pycache__",
                                       "new.%s.pyc" % tag))
    assert os.path.isfile(os.path.join(
        nxt, "python", "Lib", "site-packages", "lib", "__pycache__",
        "mod.%s.pyc" % tag))
    assert open(os.path.join(pkg, "core", "__pycache__",
                             "keep.cpython-312.pyc")).read() == "kc"


# ------------------------------------------------- the swap with no setup
def test_swap_script_without_a_setup_brings_the_app_back():
    text = us.swap_script(r"C:\PAD", "2.0.0", None, 7, r"C:\l.log",
                          failed_note=r"C:\t\failed.txt")
    fall = text[text.index("function Fallback"):text.index("Say 'waiting")]
    assert "starting the version in place again" in fall
    assert "Set-Content -LiteralPath 'C:\\t\\failed.txt' -Value '2.0.0'" in fall
    assert "launcher.vbs" in fall and "if ($true -and" in fall
    quiet = us.swap_script(r"C:\PAD", "2.0.0", None, 7, r"C:\l.log",
                           launch=False)
    assert "if ($false -and" in quiet
    # a swap that works clears an earlier failure's note
    done = text[text.index("Say 'swapped in"):]
    assert "Remove-Item -LiteralPath 'C:\\t\\failed.txt'" in done


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell")
def test_a_swap_that_cannot_be_done_notes_the_version(tmp_path):
    """The real helper with nothing staged and no setup exe to fall back
    on: the version in place is left alone and the failure noted, so the
    app fetches that version's installer next time."""
    app = _tree(tmp_path / "PAD", "1.0.0")
    log, note = tmp_path / "swap.log", tmp_path / "failed.txt"
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    ok, _ = us.start_swap(str(app), "2.0.0", None, pid=gone.pid,
                          launch=False, register=False, log_path=str(log),
                          failed_note=str(note))
    assert ok
    end = time.time() + 60
    while time.time() < end and not note.exists():
        time.sleep(0.2)
    assert us.swap_failed_version(str(note)) == "2.0.0"
    assert "starting the version in place again" in log.read_text(
        encoding="utf-8-sig")
    assert us.tree_version(str(app)) == "1.0.0"
    assert us.swap_failed_version(str(tmp_path / "none.txt")) is None


# ------------------------------------------------------------ app: the flow
@pytest.fixture
def delta(tmp_path, slots, two, monkeypatch):
    """An installed v1.0.0 whose release feed offers v2.0.0 with its file
    list, on the stand-in GitHub; the setup-exe route only records."""
    from pinball_decryptor.core import net
    app_dir = str(two["app"])
    monkeypatch.setattr(us, "installed_app_dir", lambda *a, **k: app_dir)
    monkeypatch.setattr(net, "urlopen", two["rel"])
    monkeypatch.setattr(ud, "GITHUB_REPO", REPO)
    monkeypatch.setattr(ud.build_tree, "__kwdefaults__",
                        dict(ud.build_tree.__kwdefaults__, repo=REPO))
    monkeypatch.setattr(ud.pack_url, "__defaults__", (REPO,))
    monkeypatch.setattr(us, "swap_failed_note_path",
                        lambda: str(tmp_path / "failed.txt"))
    runs = _Run()
    monkeypatch.setattr(us.subprocess, "run", runs)
    two["rel"].requests.clear()         # the build's own look at the packs
    inst = _installer(name=WIN % "2.0.0", size=5_000_000,
                      delta=_asset(two["m2"], "2.0.0"))
    # slots itself, not a copy: its counters are read live
    slots.update(two=two, installer=inst, app_dir=app_dir, runs=runs,
                 note=tmp_path / "failed.txt")
    return slots


def _log(w):
    return [e["text"] for e in w.window.log_history()]


def test_an_update_is_made_from_the_changed_files_without_the_installer(
        tmp_path, delta):
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.app._offer_update, "2.0.0", "u", delta["installer"])
        assert _until(w, lambda: _ready(w)), _log(w)
        # no setup exe was downloaded or run
        assert delta["downloads"] == [] and delta["stages"] == []
        assert us.staged_install_ok(delta["app_dir"], "2.0.0")
        nxt = us.next_dir(delta["app_dir"])
        assert md.verify(nxt, md.read_manifest(delta["two"]["m2"])) == [
            "installed but not in the manifest: "
            "python/Lib/site-packages/userpkg/f.py"]
        assert not os.path.exists(os.path.join(nxt, ".pad_compile.lst"))
        texts = _log(w)
        assert any("Downloading v2.0.0 in the background" in t for t in texts)
        said = [t for t in texts if "Update v2.0.0 is installed" in t]
        assert said and re.search(
            r"\(5 changed files, 0\.0 MB downloaded instead of the 5\.0 MB "
            r"installer, ready in \d+ s\) - press Restart", said[0]), said
        assert not any("can't be made" in t for t in texts)
        # Restart to update is the same swap, with no setup exe to hand it
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: delta["closed"])
        assert delta["swaps"] == [(delta["app_dir"], "2.0.0", str(
            delta["dir"] / (WIN % "2.0.0")))]
        assert delta["launched"] == []


@pytest.mark.parametrize("why", ["no pack", "bad list", "too much",
                                 "swap failed before"])
def test_anything_in_the_way_is_the_installers_turn(tmp_path, delta, why):
    """A release whose pack is gone, a file list that fails its check, more
    to fetch than the installer, a swap that failed last time: the setup
    exe is downloaded and staged as before, and the log says why."""
    rel = delta["two"]["rel"]
    inst = delta["installer"]
    if why == "no pack":
        os.unlink(rel.path(
            "v2.0.0", "Pinball_Asset_Decryptor_v2.0.0_Windows.delta.pack"))
        says = "could not be downloaded"
    elif why == "bad list":
        inst["delta"] = dict(inst["delta"], sha256="0" * 64)
        says = "integrity check"
    elif why == "too much":
        inst["size"] = 10
        says = "no smaller than the installer"
    else:
        # the copy that would not swap in is still staged: it is not
        # reused without the setup exe the swap falls back on
        delta["note"].write_text("2.0.0\n", encoding="utf-8-sig")
        nxt = _tree(tmp_path / "PAD.next", "2.0.0")
        (nxt / us.MARKER).write_text('{"version": "2.0.0"}',
                                     encoding="utf-8")
        says = "did not work last time"
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.app._offer_update, "2.0.0", "u", inst)
        assert _until(w, lambda: _ready(w)), _log(w)
        dest = str(delta["dir"] / (WIN % "2.0.0"))
        assert delta["downloads"] == [dest]
        assert delta["stages"] == ([] if why == "swap failed before" else
                                   [(dest, delta["app_dir"], "2.0.0")])
        texts = _log(w)
        said = [t for t in texts if "can't be made from the changed files "
                "alone" in t]
        assert said and says in said[0], texts
        assert "downloading its installer instead" in said[0]
        assert any("Update v2.0.0 is installed - press" in t for t in texts)
        # Restart to update then has the setup exe to hand the swap
        w.call("ui.banner_action", "update", "install")
        assert _until(w, lambda: delta["closed"])
        assert delta["swaps"] == [(delta["app_dir"], "2.0.0", dest)]


def test_a_release_without_a_file_list_updates_as_before(tmp_path, delta):
    inst = dict(delta["installer"], delta=None)
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.app._offer_update, "2.0.0", "u", inst)
        assert _until(w, lambda: _ready(w))
        assert len(delta["downloads"]) == 1 and len(delta["stages"]) == 1
        assert delta["two"]["rel"].requests == []
        assert not any("changed files" in t for t in _log(w))


def test_one_already_made_is_not_made_again(tmp_path, delta):
    """The app was closed with the update ready and not restarted into:
    the next run finds it and fetches nothing."""
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.app._offer_update, "2.0.0", "u", delta["installer"])
        assert _until(w, lambda: _ready(w))
    delta["two"]["rel"].requests.clear()
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.app._offer_update, "2.0.0", "u", delta["installer"])
        assert _until(w, lambda: _ready(w))
        assert delta["two"]["rel"].requests == []
        assert delta["downloads"] == []
        assert any("Update v2.0.0 is installed (it was ready already)" in t
                   for t in _log(w))


# ------------------------------------------------------- the release's CI
def test_the_release_attaches_the_delta_assets_before_the_setup_exe():
    """The app offers a release the moment its setup exe is up, so the file
    list must be there by then - and its step may never fail the build."""
    yaml = pytest.importorskip("yaml")
    with open(os.path.join(ROOT, ".github", "workflows", "release.yml"),
              encoding="utf-8") as f:
        wf = yaml.safe_load(f)
    steps = wf["jobs"]["build-windows"]["steps"]
    names = [s.get("name") for s in steps]
    d, exe = (names.index("Build and attach delta-update assets"),
              names.index("Attach to release"))
    assert names.index("Build installer") < d < exe
    assert steps[d]["continue-on-error"] is True
    assert steps[d]["timeout-minutes"] <= 6
    assert "build_delta_assets.sh" in steps[d]["run"]
    check = wf["jobs"]["check-delta"]
    assert check["needs"] == "build-windows"
    run = check["steps"][-1]["run"]
    assert "/STAGED=2" in run and "make_delta.py --verify" in run
    assert run.count("gh release delete-asset") == 2
    with open(os.path.join(ROOT, ".github", "scripts",
                           "build_delta_assets.sh"), encoding="utf-8") as f:
        sh = f.read()
    assert "\r" not in sh
    # the pack goes up before the file list: the list is what the app
    # acts on
    assert sh.index('"$TAG" "$pack"') < sh.index('"$TAG" "$list"')
