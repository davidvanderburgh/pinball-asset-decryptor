"""PAD-1630: a card the Mac's container SEES but cannot READ.

Dustin's Iron Maiden LE card was there in the container (``[ -f ]`` true,
the share check passed) and read as no card at all, so ensureselect.sh said
"no MBR signature - not a card image?", the guest filesystem was never
unpacked, the menu program could not compile, and the size check and the
Build failed - and the Log then blamed a folder that was mounted.

The container here is a stand-in: ``docker exec ... python3 -c <head>`` runs
the module's own head reader on this PC, against the host path each
container path names, and a "blocked" folder reads empty the way Dustin's
did.  ``cp -c`` is a plain copy.
"""

import os
import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.webui import multiboot_docker as D
from pinball_decryptor.webui import multiboot_core as mt

MBR = bytes(446) + bytes(range(64)) + b"\x55\xaa"


@pytest.fixture
def mac(monkeypatch, tmp_path):
    monkeypatch.setattr(mt.sys, "platform", "darwin")
    monkeypatch.setattr(D.sys, "platform", "darwin")
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(D, "cache_root", lambda: str(cache).replace("\\", "/"))
    monkeypatch.setattr(D, "_CLONES", {})
    monkeypatch.setattr(D, "_READ_OK", {})
    monkeypatch.setattr(D, "_UNREADABLE_SAID", set())
    state = {"blocked": set(), "execs": 0, "clone": True, "clones": 0}

    def host_of(cpath):
        if cpath.startswith("/host"):
            return cpath[len("/host"):]     # a C:/... path on this PC
        return D.host_from_container(cpath)

    def fake_docker(args, timeout=30):
        assert args[:4] == ["exec", D.CONTAINER, "python3", "-c"], args
        state["execs"] += 1
        out = []
        for cp in args[5:]:
            hp = host_of(cp)
            if any(hp.startswith(b + "/") for b in state["blocked"]):
                out.append("OK 0 ")          # what Dustin's container read
                continue
            r = subprocess.run([sys.executable, "-c", args[4], hp],
                               capture_output=True, text=True)
            out.append(r.stdout.strip())
        return subprocess.CompletedProcess(args, 0, "\n".join(out) + "\n", "")

    def fake_clone(src, dst):
        if not state["clone"]:
            return False
        state["clones"] += 1
        shutil.copyfile(src, dst)
        return True

    monkeypatch.setattr(D, "_docker", fake_docker)
    monkeypatch.setattr(D, "_clonefile", fake_clone)
    return state


def _card(tmp_path, folder, name="iron_maiden_le-1_18_0.Release.8G.sdcard.raw"):
    d = tmp_path / folder
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_bytes(MBR + b"\x01" * 4096)
    return str(p).replace("\\", "/"), str(d).replace("\\", "/")


def test_a_card_the_container_reads_is_left_alone(mac, tmp_path):
    card, _ = _card(tmp_path, "Cards")
    D.settle_reads([card])
    assert D._CLONES == {} and mac["clones"] == 0
    D.settle_reads([card])
    assert mac["execs"] == 1, "a card read once is not asked about again"


def test_a_card_the_container_reads_empty_is_read_through_a_clone(mac, tmp_path):
    """Dustin's case: the clone in the cache is what every step reads."""
    card, folder = _card(tmp_path, "Documents")
    mac["blocked"].add(folder)
    said = []
    D.settle_reads([card], log=said.append)
    assert card in D._CLONES
    clone = D._CLONES[card][1]
    assert clone.replace("\\", "/").startswith(D.cache_root() + "/readable/")
    assert os.path.basename(clone) == os.path.basename(card)
    with open(clone, "rb") as f:
        assert f.read(512) == MBR
    assert len(said) == 1 and "reads as empty there" in said[0]
    assert "clone" in said[0]

    # the ensureselect step the tab built names the card; it runs on the clone
    line = ("cd /tmp/repo && PAD_ROOT=~/spike2root bash "
            "tools/spike2_emu/ensureselect.sh %s" % mt._q(mt.wsl(card)))
    argv = D.remap_argv(D.exec_argv(line))
    assert D.container_path(clone) in argv[-1]
    assert mt.wsl(card) not in argv[-1]
    # ...and a base card + edits folder too
    edits = mt.wsl(card) + mt.EDITS_JOIN + "/host/x/edits"
    assert D.remap_argv(["docker", "exec", "c", "bash", "-lc",
                         "tool --primary " + edits])[-1] == (
        "tool --primary " + D.container_path(clone) + mt.EDITS_JOIN
        + "/host/x/edits")
    # a longer name that only starts the same is not the card
    other = "tool " + mt.wsl(card) + ".bak"
    assert D.remap_argv(["docker", "exec", "c", "bash", "-lc", other])[-1] \
        == other


def test_the_clone_is_made_once_and_again_when_the_card_changes(mac, tmp_path):
    card, folder = _card(tmp_path, "Downloads")
    mac["blocked"].add(folder)
    D.settle_reads([card])
    D.settle_reads([card])
    assert mac["clones"] == 1
    with open(card, "ab") as f:
        f.write(b"\x02" * 512)              # rebuilt: size and date change
    D.settle_reads([card])
    assert mac["clones"] == 2
    assert os.path.getsize(D._CLONES[card][1]) == os.path.getsize(card)


def test_no_clone_stops_the_run_with_what_to_do(mac, tmp_path):
    """Another volume: cp -c refuses, and an 8 GB copy is never made."""
    card, folder = _card(tmp_path, "Desktop")
    mac["blocked"].add(folder)
    mac["clone"] = False
    with pytest.raises(D.Unreadable) as exc:
        D.settle_reads([card])
    msg = str(exc.value)
    assert os.path.basename(card) in msg and "reads as empty there" in msg
    assert "Privacy & Security" in msg and "Files and Folders" in msg
    assert D._CLONES == {}
    assert not os.listdir(os.path.join(D.cache_root(), "readable"))


def test_a_preview_says_it_once_and_never_raises(mac, tmp_path, monkeypatch):
    card, folder = _card(tmp_path, "Desktop")
    mac["blocked"].add(folder)
    mac["clone"] = False
    said = []
    for _ in range(3):
        D.settle_reads_quietly([card], said.append)
    assert len(said) == 1 and "cannot read what is in it" in said[0]


def test_a_file_the_mac_cannot_read_or_a_missing_output_is_left_alone(mac,
                                                                      tmp_path):
    D.settle_reads([str(tmp_path / "nope.raw"), "", "~/spike2root/x",
                    D.cache_root() + "/repo/x"])
    assert mac["execs"] == 0


def test_dustins_log_no_longer_blames_a_mounted_folder(mac):
    """The /host/ card on one line and the compiler's missing stdio.h on
    another is no folder missing from the container."""
    raw = "\n".join([
        "[rootfs] card   : /host/Users/d/Pinball/iron_maiden_le.raw",
        "/host/Users/d/Pinball/iron_maiden_le.raw no MBR signature - not a "
        "card image?",
        "codeselect.c:35:10: fatal error: stdio.h: No such file or directory",
    ])
    assert mt.container_note(raw) == ""
    assert "mounted yet" in mt.container_note(
        "mkmulticard.py: REFUSED: /host/Users/me/a.raw: No such file or "
        "directory")


def test_the_panel_reads_its_cards_and_media_never_its_output(mac, tmp_path):
    a, folder = _card(tmp_path, "Cards", "a.raw")
    b, _ = _card(tmp_path, "Cards", "b.raw")
    edits = tmp_path / "edits"
    edits.mkdir()
    (edits / mt.editsource().MANIFEST).write_text("{}")
    form = mt.MultibootForm(
        images=[mt.ImageRow(path=a + mt.EDITS_JOIN + str(edits)),
                mt.ImageRow(path=b)],
        out=b)
    panel = mt.MultibootPanel.__new__(mt.MultibootPanel)
    panel.form = lambda: form
    reads = [r.replace("\\", "/") for r in panel._read_paths()]
    assert a in reads
    assert b not in reads
