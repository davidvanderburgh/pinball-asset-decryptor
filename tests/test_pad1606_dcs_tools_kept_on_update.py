"""PAD-1606: antivirus programs flag the bundled DCSExplorer.exe /
DCSEncoder.exe by mistake (PAD-1391), and what they catch is a freshly
written copy.  Every update staged the new version in a new folder and
wrote both tools into it again, so users switched their scanner off to
update.  Now an update leaves the copy already installed alone: the new
folder gets a hard link to the same file (no new file is written), and an
install over the top keeps an existing copy.
"""
import os
import re

import pytest

from pinball_decryptor.core import update_delta as ud
from pinball_decryptor.core import update_slots as us
from tests.test_pad1519_delta_update import (  # noqa: F401
    REPO, ROOT, V1, V2, _Releases, _asset, _release, _write, md)

EXPLORER = "pinball_decryptor/plugins/williams/vendor/DCSExplorer.exe"
ENCODER = "pinball_decryptor/plugins/williams/vendor/DCSEncoder.exe"
TOOLS = {EXPLORER: b"MZ explorer" * 100, ENCODER: b"MZ encoder" * 100}
ISS = os.path.join(ROOT, "installer", "pinball_decryptor.iss")


def test_the_kept_files_are_the_bundled_dcs_tools():
    assert set(ud.KEEP_AS_INSTALLED) == {EXPLORER, ENCODER}
    for rel in ud.KEEP_AS_INSTALLED:
        assert os.path.isfile(os.path.join(ROOT, *rel.split("/"))), rel


@pytest.fixture
def two_with_tools(tmp_path):
    """Releases 1.0.0 and 2.0.0 that both ship the DCS tools unchanged, and
    an install of 1.0.0."""
    rel = _Releases(str(tmp_path / "releases"))
    v1, v2 = dict(V1, **TOOLS), dict(V2, **TOOLS)
    m1, _ = _release(rel, "1.0.0", _write(tmp_path / "t1", v1))
    m2, _ = _release(rel, "2.0.0", _write(tmp_path / "t2", v2), previous=m1)
    app = _write(tmp_path / "PAD", v1)
    return {"rel": rel, "m2": m2, "app": app}


def _build(two, target):
    manifest = ud.fetch_manifest(_asset(two["m2"], "2.0.0"), "2.0.0",
                                 two["rel"])
    two["rel"].requests.clear()
    return ud.build_tree(manifest, str(two["app"]), str(target),
                         opener=two["rel"], repo=REPO)


def test_an_update_links_the_installed_tools_instead_of_writing_them(
        two_with_tools, tmp_path):
    nxt = tmp_path / "PAD.next"
    took = _build(two_with_tools, nxt)
    for rel, data in TOOLS.items():
        new, old = nxt / rel, two_with_tools["app"] / rel
        # the very same file on disk, under a second name: nothing written
        assert os.path.samefile(new, old), rel
        assert new.read_bytes() == data
        assert rel not in took["changed"]
    # the rest of the tree is still copied as before, not linked
    keep = "pinball_decryptor/core/keep.py"
    assert not os.path.samefile(nxt / keep, two_with_tools["app"] / keep)
    assert md.verify(str(nxt), md.read_manifest(two_with_tools["m2"])) == []
    # the swap retires the old folder; the tool lives on in the new one
    import shutil
    shutil.rmtree(two_with_tools["app"])
    assert (nxt / EXPLORER).read_bytes() == TOOLS[EXPLORER]


def test_a_tool_the_install_lost_comes_from_the_pack(two_with_tools,
                                                     tmp_path):
    """Quarantined (gone) or not the listed file: fetched like any other."""
    os.unlink(two_with_tools["app"] / EXPLORER)
    (two_with_tools["app"] / ENCODER).write_bytes(b"MZ other")
    nxt = tmp_path / "PAD.next"
    took = _build(two_with_tools, nxt)
    assert EXPLORER in took["changed"] and ENCODER in took["changed"]
    assert (nxt / EXPLORER).read_bytes() == TOOLS[EXPLORER]
    assert (nxt / ENCODER).read_bytes() == TOOLS[ENCODER]
    assert not os.path.samefile(nxt / ENCODER,
                                two_with_tools["app"] / ENCODER)


def test_where_links_fail_the_tool_is_copied(two_with_tools, tmp_path,
                                             monkeypatch):
    def _no_link(*a):
        raise OSError(1, "no links here")
    monkeypatch.setattr(os, "link", _no_link)
    nxt = tmp_path / "PAD.next"
    _build(two_with_tools, nxt)
    assert (nxt / EXPLORER).read_bytes() == TOOLS[EXPLORER]


def test_the_staged_installers_skipped_tools_are_linked_in(tmp_path):
    """The setup exe's staged install leaves the tools out when the running
    install has them (KeptAsInstalled); carry_over links them in."""
    app = _write(tmp_path / "PAD", dict(TOOLS, **{"launcher.vbs": "v"}))
    new = _write(tmp_path / "PAD.next", {"launcher.vbs": "v"})
    carried = us.carry_over(str(app), str(new))
    for rel in TOOLS:
        assert os.path.samefile(new / rel, app / rel)
        assert rel.replace("/", os.sep) in carried


def test_a_tool_the_staged_install_wrote_is_left_as_it_is(tmp_path):
    """The running install lacked it, so the setup exe wrote it: kept."""
    app = _write(tmp_path / "PAD", {EXPLORER: b"MZ old"})
    new = _write(tmp_path / "PAD.next", {EXPLORER: b"MZ new"})
    assert us.carry_over(str(app), str(new)) == []
    assert (new / EXPLORER).read_bytes() == b"MZ new"
    assert not (new / ENCODER).exists()


def _iss():
    with open(ISS, encoding="utf-8-sig") as f:
        return f.read()


def test_the_installer_writes_the_tools_only_when_they_are_not_there():
    text = _iss()
    files = md._files_section(text)
    package = [l for l in files
               if 'DestDir: "{app}\\pinball_decryptor";' in l]
    assert len(package) == 1
    excl = md._Excludes(md._iss_params(package[0])["excludes"])
    for rel in TOOLS:
        name = rel.split("/")[-1]
        assert excl.match(rel.split("/", 1)[1].replace("/", "\\")), name
        own = [md._iss_params(l) for l in files
               if l.split(";")[0].endswith(name + '"')]
        assert len(own) == 1, name
        assert "onlyifdoesntexist" in own[0]["flags"].split()
        assert own[0]["check"] == "KeptAsInstalled('%s')" % rel.replace(
            "/", "\\")
        # uninstall still removes a copy that came in as a link
        assert re.search(r'Type: files; Name: "\{app\}\\%s"'
                         % re.escape(rel.replace("/", "\\")), text), name
    # the staged-install check looks beside <app>.next for <app>
    body = text[text.index("function KeptAsInstalled"):]
    body = body[:body.index("end;\n\n") if "end;\n\n" in body else 600]
    assert "IsStaged()" in body and "'.next'" in body
    assert ".next" == us.NEXT_SUFFIX


def test_the_release_file_list_still_holds_the_tools_once(tmp_path):
    py = _write(tmp_path / "py", {"python.exe": "x"})
    files = md.iss_files(ISS, {"ProjectDir": ROOT, "PythonDir": str(py)})
    for rel in TOOLS:
        assert rel in files
        assert os.path.samefile(files[rel],
                                os.path.join(ROOT, *rel.split("/")))
