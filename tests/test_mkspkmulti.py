"""tools/spooky_emu/mkspkmulti.py, the Spooky Pinball multi-boot builder (PAD-980).

Synthetic updates of a flat title (Scooby-Doo: the archive's root is uptest/), a nested one
(Evil Dead: uptest/ + assets/), a plain-tar one (Looney Tunes) and a signed one (Beetlejuice):
the plan, the update's shape the machine's own install needs (the launcher as main.x86_64,
pad/ beside it, b0 whole, each build's differences and deletions), the conf and spk.conf,
inspect, verify, inject, and what is refused.  The machine-side proof (the update installed
as the machine does, the launcher run, the menu, the chosen build in attract) is
tools/spooky_emu/machine_sim.sh.
"""
import io
import json
import os
import sys
import tarfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "tools", "spooky_emu"))
sys.path.insert(0, REPO)
import mkspkmulti as mk  # noqa: E402

LAUNCHER = os.path.join(REPO, "tools", "spike2_emu", "codeselect", "padselect_spk.sh")


def _tar(path, files, mode="w:gz"):
    with tarfile.open(path, mode) as tf:
        for rel, data in files.items():
            ti = tarfile.TarInfo(rel)
            ti.size = len(data)
            ti.mode = 0o755 if rel.endswith("main.x86_64") else 0o644
            tf.addfile(ti, io.BytesIO(data))
    return str(path)


def _members(path, work):
    u = mk.SpkUpdate(path)
    with tarfile.open(u.tar_path(str(work)), "r|*") as tf:
        out = {}
        for ti in tf:
            out[ti.name] = (ti, tf.extractfile(ti).read() if ti.isfile() else None)
        return out


@pytest.fixture
def sel(tmp_path):
    d = tmp_path / "sel"
    d.mkdir()
    (d / "spkselect").write_bytes(b"\x7fELF menu")
    (d / "spksw").write_bytes(b"\x7fELF buttons")
    (d / "padselect.sh").write_bytes(open(LAUNCHER, "rb").read())
    (d / "font.ttf").write_bytes(b"font")
    return str(d)


@pytest.fixture
def scooby(tmp_path):
    (tmp_path / "stock").mkdir()
    (tmp_path / "mod").mkdir()
    stock = _tar(tmp_path / "stock" / "v2025.12.01.09.scooby", {
        "main.x86_64": b"\x7fELF unity", "main_Data/a.assets": b"A" * 200, "main_Data/v.ogg": b"V" * 50,
        "_profile": b"profile", "lightshows/x.lightshow": b"L", "old.txt": b"only stock"})
    mod = _tar(tmp_path / "mod" / "v2025.12.01.09.scooby", {
        "main.x86_64": b"\x7fELF unity", "main_Data/a.assets": b"A" * 200, "main_Data/v.ogg": b"MINE" * 20,
        "_profile": b"profile", "lightshows/x.lightshow": b"L", "new.txt": b"only mine"})
    return stock, mod


def _build(stock, extras, out, sel, *args):
    argv = ["build", "--primary", stock]
    for e in extras:
        argv += ["--extra", e]
    rc = mk.main(argv + ["--out", out, "--selector-dir", sel, "--timeout", "12",
                         "--titles", "SCOOBY;MINE"] + list(args))
    assert rc == 0
    return os.path.join(out, os.path.basename(stock)) if os.path.isdir(out) else out


def test_flat_title_layout(tmp_path, scooby, sel):
    stock, mod = scooby
    out = tmp_path / "multi"
    out.mkdir()
    path = _build(stock, [mod], str(out), sel)
    assert os.path.basename(path) == "v2025.12.01.09.scooby"
    m = _members(path, tmp_path)
    # the machine's install wants main.x86_64 at the root: the launcher
    ti, data = m["main.x86_64"]
    assert data.startswith(b"#!") and b"multi-boot launcher" in data and ti.mode & 0o111
    # b0 whole, laid out as on the machine (uptest/...)
    assert m["pad/b0/uptest/main_Data/v.ogg"][1] == b"V" * 50
    assert m["pad/b0/uptest/old.txt"][1] == b"only stock"
    assert m["pad/b0/uptest/main.x86_64"][0].mode & 0o111
    # build 1: only what differs, and what it lacks
    d1 = {n for n in m if n.startswith("pad/d1/") and m[n][0].isfile()}
    assert d1 == {"pad/d1/uptest/main_Data/v.ogg", "pad/d1/uptest/new.txt"}
    assert m["pad/d1.removed"][1] == b"uptest/old.txt\n"
    assert b"b1 d1" in m["pad/builds.txt"][1]
    spk = m["pad/spk.conf"][1].decode()
    assert "board=warden" in spk and "L=86" in spk and "R=80" in spk and "S=87" in spk
    assert "root=" not in spk
    conf = m["pad/images.conf"][1].decode()
    assert "image=b0|SCOOBY|" in conf and "image=b1|MINE|" in conf and "timeout=12" in conf
    for f in ("spkselect", "spksw", "font.ttf"):
        assert "pad/" + f in m
    assert mk.main(["verify", "--zip", path]) == 0
    rep = mk.inspect_update(path)
    assert rep["game"] == "Scooby-Doo" and rep["hook"] and [i["device"] for i in rep["images"]] == ["b0", "b1"]


def test_nested_title_roots(tmp_path, sel):
    for d in ("a", "b"):
        (tmp_path / d).mkdir()
    files = {"uptest/main.x86_64": b"\x7fELF", "uptest/main_Data/x": b"X", "assets/video/a.webm": b"W" * 10,
             "version.txt": b"2026.07.15"}
    stock = _tar(tmp_path / "a" / "2026.07.15.ed", files)
    mod = _tar(tmp_path / "b" / "2026.07.15.ed", dict(files, **{"assets/video/a.webm": b"MY VIDEO"}))
    out = tmp_path / "multi"
    out.mkdir()
    path = _build(stock, [mod], str(out), sel)
    m = _members(path, tmp_path)
    # the install wants uptest/main.x86_64; everything of ours sits in uptest/pad
    assert b"multi-boot launcher" in m["uptest/main.x86_64"][1]
    assert m["uptest/pad/b0/assets/video/a.webm"][1] == b"W" * 10
    assert m["uptest/pad/d1/assets/video/a.webm"][1] == b"MY VIDEO"
    assert not [n for n in m if n.startswith("assets")], "no assets/ of ours: the install would wipe the stock ones"
    spk = m["uptest/pad/spk.conf"][1].decode()
    assert "root=assets /game/code/assets" in spk and "config" not in spk
    assert mk.main(["verify", "--zip", path]) == 0


def test_looney_plain_tar_and_pinotaur_table():
    assert mk.TITLES["halloween_78"]["board"] == "pinotaur" and mk.TITLES["halloween_78"]["sw"] == (81, 80, 87)
    assert dict(mk.TITLES["texas_chainsaw"]["roots"]) == {"assets": "/game/code/assets",
                                                          "config": "/game/code/config"}


def test_looney_stays_plain_tar(tmp_path, sel):
    for d in ("a", "b"):
        (tmp_path / d).mkdir()
    stock = _tar(tmp_path / "a" / "2025.10.08.looney", {"main.x86_64": b"\x7fELF godot" * 10,
                                                        "version.txt": b"2025_10_08"}, mode="w")
    mod = _tar(tmp_path / "b" / "2025.10.08.looney", {"main.x86_64": b"\x7fELF mine" * 10,
                                                      "version.txt": b"2025_10_08"}, mode="w")
    out = tmp_path / "multi"
    out.mkdir()
    path = _build(stock, [mod], str(out), sel)
    with open(path, "rb") as f:
        assert f.read(2) != b"\x1f\x8b", "a .looney is a plain tar"
    m = _members(path, tmp_path)
    assert set(n for n in m if n.startswith("pad/d1/") and m[n][0].isfile()) == {"pad/d1/uptest/main.x86_64"}
    assert mk.main(["verify", "--zip", path]) == 0


def test_beetlejuice_signed_round_trip(tmp_path, sel):
    for d in ("a", "b"):
        (tmp_path / d).mkdir()
    from pinball_decryptor.plugins.spooky import gpg
    raw = []
    for d, v in (("a", b"stock"), ("b", b"mine")):
        t = _tar(tmp_path / d / "x.tar.gz", {"main.x86_64": b"\x7fELF", "main_Data/v": v})
        p = str(tmp_path / d / "v2026.09.15.11.beetlejuice")
        gpg.sign_beetlejuice(t, p)
        raw.append(p)
    out = tmp_path / "multi"
    out.mkdir()
    path = _build(raw[0], [raw[1]], str(out), sel, "--cache-dir", str(tmp_path / "cache"))
    m = _members(path, tmp_path)
    assert m["pad/d1/uptest/main_Data/v"][1] == b"mine" and b"multi-boot launcher" in m["main.x86_64"][1]


def test_inject_rewrites_the_menu_keeps_the_builds(tmp_path, scooby, sel):
    stock, mod = scooby
    out = tmp_path / "multi"
    out.mkdir()
    path = _build(stock, [mod], str(out), sel)
    assert mk.main(["inject", "--zip", path, "--titles", "NEW;NAMES", "--timeout", "5"]) == 0
    m = _members(path, tmp_path)
    conf = m["pad/images.conf"][1].decode()
    assert "image=b0|NEW|" in conf and "timeout=5" in conf
    assert m["pad/d1/uptest/main_Data/v.ogg"][1] == b"MINE" * 20
    assert m["pad/b0/uptest/old.txt"][1] == b"only stock"
    assert len([n for n in m if n == "pad/images.conf"]) == 1
    assert mk.main(["verify", "--zip", path]) == 0


def test_plan(tmp_path, scooby, capsys):
    stock, mod = scooby
    assert mk.main(["plan", "--primary", stock, "--extra", mod]) == 0
    text = capsys.readouterr().out
    assert "image-size 1 b1" in text and "upd-size" in text and "fits USB 8G stick size" in text
    assert "1 changed" not in text and "2 changed, 1 removed" in text


def test_refusals(tmp_path, scooby, sel):
    stock, mod = scooby
    (tmp_path / "e").mkdir()
    ed = _tar(tmp_path / "e" / "2026.07.15.ed", {"uptest/main.x86_64": b"x"})
    assert mk.main(["build", "--primary", stock, "--extra", ed, "--out", str(tmp_path), "--selector-dir", sel]) == 2
    assert mk.main(["build", "--primary", stock, "--out", str(tmp_path), "--selector-dir", sel]) == 2
    (tmp_path / "n").mkdir()
    noprog = _tar(tmp_path / "n" / "v1.scooby", {"main_Data/x": b"x"})
    assert mk.main(["build", "--primary", stock, "--extra", noprog, "--out", str(tmp_path),
                    "--selector-dir", sel]) == 2
    # the output keeps the primary's name, and never over the primary itself
    assert mk.main(["build", "--primary", stock, "--extra", mod, "--out", str(tmp_path / "other.scooby"),
                    "--selector-dir", sel]) == 2
    assert mk.main(["build", "--primary", stock, "--extra", mod, "--out", stock, "--selector-dir", sel]) == 2
    # a multi-boot is not an image
    out = tmp_path / "multi"
    out.mkdir()
    path = _build(stock, [mod], str(out), sel)
    assert mk.main(["build", "--primary", stock, "--extra", path, "--out", str(tmp_path / "multi2"),
                    "--selector-dir", sel]) == 2
    json.dumps(mk.inspect_update(path))


def test_a_second_plan_reads_the_kept_member_lists(tmp_path, scooby, monkeypatch):
    stock, mod = scooby
    monkeypatch.setattr(mk, "INDEX_CACHE", str(tmp_path / "idx"))
    assert mk.main(["plan", "--primary", stock, "--extra", mod]) == 0
    assert len(os.listdir(tmp_path / "idx")) == 2
    opened = []
    real = tarfile.open
    monkeypatch.setattr(tarfile, "open", lambda *a, **k: opened.append(a) or real(*a, **k))
    assert mk.main(["plan", "--primary", stock, "--extra", mod]) == 0
    assert opened == [], "the plan read an update again instead of its kept list"


@pytest.fixture
def h78um(tmp_path):
    """synthetic Ultraman (the stock) and Halloween updates, GPG-packed as the machines take them"""
    from pinball_decryptor.plugins.spooky import games, gpg
    out = {}
    for key, name, fmt in (("um", "code_UM.pkg", "um_pkg"), ("h78", "code_H78.pkg", "h78_pkg")):
        (tmp_path / key).mkdir()
        t = _tar(tmp_path / key / "x.tar.gz", {
            "uptest/main.x86_64": b"\x7fELF " + key.encode(), "uptest/main_Data/a": key.encode() * 10,
            "uptest/main_Data/same": b"S", "assets/v.webm": key.encode(),
            "config/default_highscores.config": key.encode() + b" defaults"})
        p = str(tmp_path / key / name)
        gpg.encrypt_gpg_symmetric(t, p, games.GPG_PASSPHRASES[fmt])
        out[key] = p
    return out


def test_halloween_and_ultraman_share_one_machine(tmp_path, h78um, sel, capsys):
    """PAD-997: Ultraman is Halloween's code base on the same board and wiring, so the two
    mix; the launcher is told each build's game, and which /game files each keeps its own."""
    um, h78 = h78um["um"], h78um["h78"]
    assert mk.main(["plan", "--primary", um, "--extra", h78, "--cache-dir", str(tmp_path / "cache")]) == 0
    assert "== games: Ultraman + Halloween on one machine" in capsys.readouterr().out
    out = tmp_path / "multi"
    out.mkdir()
    rc = mk.main(["build", "--primary", um, "--extra", h78, "--out", str(out), "--selector-dir", sel,
                  "--cache-dir", str(tmp_path / "cache")])
    assert rc == 0
    path = str(out / "code_UM.pkg")
    m = _members(path, tmp_path)
    assert m["uptest/pad/d1/uptest/main_Data/a"][1] == b"h78" * 10
    assert "uptest/pad/d1/uptest/main_Data/same" not in m, "an identical file travels once"
    spk = m["uptest/pad/spk.conf"][1].decode()
    for line in ("board=pinotaur", "title=b0 ultraman", "title=b1 halloween_78", "own=*.config *.json",
                 "seed=highscores.config config/default_highscores.config"):
        assert line in spk.splitlines(), line
    conf = m["uptest/pad/images.conf"][1].decode()
    assert "image=b0|ULTRAMAN|" in conf and "image=b1|HALLOWEEN|" in conf, "each card names its own game"
    man = json.loads(m["uptest/pad/build.json"][1])
    assert [i["game"] for i in man["images"]] == ["Ultraman", "Halloween"]
    assert mk.main(["verify", "--zip", path]) == 0
    # a new menu keeps the launcher told which game each build is
    assert mk.main(["inject", "--zip", path, "--titles", "UM;H78"]) == 0
    m = _members(path, tmp_path)
    assert "title=b1 halloween_78" in m["uptest/pad/spk.conf"][1].decode()
    assert "image=b1|H78|" in m["uptest/pad/images.conf"][1].decode()


def test_one_game_writes_no_game_lines(tmp_path, scooby, sel):
    stock, mod = scooby
    out = tmp_path / "multi"
    out.mkdir()
    m = _members(_build(stock, [mod], str(out), sel), tmp_path)
    assert "title=" not in m["pad/spk.conf"][1].decode() and "own=" not in m["pad/spk.conf"][1].decode()
    assert mk.keys_of_conf("title=b0 a\ntitle=b1 b\n") == ["a", "b"] and mk.keys_of_conf("title=b1 b\n") == []


def test_other_games_still_refused(tmp_path, h78um, scooby, sel):
    stock, _mod = scooby
    assert mk.main(["plan", "--primary", h78um["um"], "--extra", stock]) == 2
    assert mk.TITLES["scooby_doo"]["family"] == "scooby_doo"
