"""tools/dp_emu/mkdpmulti.py, The Big Lebowski multi-boot builder (PAD-853).

Synthetic TBL update zips (a stock version, a delta mod over it, a whole build): the plan,
the zip's shape the machine's own USB update and Version Select need (ONE <V>/ folder named
for the file, digits and dots, a launcher as its start, an empty database/), the builds'
files with their modes, the conf and builds.txt, inspect, verify, inject, and what is
refused.  The machine-side proof (the zip unzipped as the USB update does, the launcher run,
the menu on an X server, the chosen build in attract) is tools/dp_emu/machine_sim.sh.
"""
import json
import os
import stat
import sys
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "tools", "dp_emu"))
import mkdpmulti as md  # noqa: E402
from mkmulticard import Refused  # noqa: E402


def _zip(path, version, files, delta=None):
    with zipfile.ZipFile(path, "w") as z:
        for rel, data in files.items():
            zi = zipfile.ZipInfo("%s/%s" % (version, rel))
            zi.create_system = 3
            zi.external_attr = (stat.S_IFREG | (0o755 if rel == "start" else 0o644)) << 16
            z.writestr(zi, data)
        if delta is not None:
            z.writestr("%s/delta" % version, delta)
    return str(path)


@pytest.fixture
def inputs(tmp_path):
    stock = _zip(tmp_path / "TBL-v1.15.zip", "1.15", {"start": b"#!stock", "assets/a.png": b"A" * 100},
                 delta="1.10,1.11,1.12,1.13")
    mod = _zip(tmp_path / "My mod.zip", "1.15", {"start": b"#!stock", "assets/a.png": b"MOD" * 50},
               delta="1.13,1.15")
    whole = _zip(tmp_path / "TBL-v1.10.zip", "1.10", {"start": b"#!old", "lib.so.1": b"L"})
    sel = tmp_path / "sel"
    sel.mkdir()
    (sel / "dpselect").write_bytes(b"\x7fELF menu")
    (sel / "dpprocsw").write_bytes(b"\x7fELF buttons")
    (sel / "padselect.sh").write_bytes(
        open(os.path.join(REPO, "tools", "spike2_emu", "codeselect", "padselect_dp.sh"), "rb").read())
    (sel / "font.ttf").write_bytes(b"font")
    return {"stock": stock, "mod": mod, "whole": whole, "sel": str(sel), "dir": tmp_path}


def _build(inputs, *extra_args, version="9.1234"):
    out = str(inputs["dir"] / ("TBL-v%s.zip" % version))
    rc = md.main(["build", "--primary", inputs["stock"], "--extra", inputs["mod"], "--extra", inputs["whole"],
                  "--version", version, "--out", out, "--selector-dir", inputs["sel"], "--timeout", "12",
                  "--titles", "STOCK;MINE;OLD"] + list(extra_args))
    assert rc == 0
    return out


def test_tbl_zip_reads_version_and_delta(inputs):
    z = md.TblZip(inputs["mod"])
    assert (z.version, z.delta, z.whole, z.has_start) == ("1.15", ["1.13", "1.15"], False, True)
    w = md.TblZip(inputs["whole"])
    assert w.whole and w.version == "1.10"


def test_default_version_is_short_digits_and_dots():
    v = md.default_v(now=1_800_000_000)
    assert md.VERSION_RE.match(v) and v.startswith("9.") and len(v) + 1 <= md.NAME_MAX


def test_plan(inputs, capsys):
    assert md.main(["plan", "--primary", inputs["stock"], "--extra", inputs["mod"], "--version", "9.1234"]) == 0
    out = capsys.readouterr().out
    assert "image-size 0 1.15 0 " in out
    assert "image-size 1 9.12341 " in out
    assert "fat32: fits" in out and "zip-size " in out and "fits USB 8G stick size" in out
    assert "select 9.1234 in Version Select" in out


def test_build_shape(inputs):
    out = _build(inputs)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert {n.split("/")[0] for n in names} == {"9.1234"}
        info = {i.filename: i for i in z.infolist()}
        start = info["9.1234/start"]
        assert start.create_system == 3 and (start.external_attr >> 16) & 0o777 == 0o755
        assert z.read("9.1234/start").startswith(b"#!/bin/bash")
        assert "9.1234/database/" in names
        assert (info["9.1234/pad/dpselect"].external_attr >> 16) & 0o777 == 0o755
        conf = z.read("9.1234/pad/images.conf").decode()
        assert "image=1.15|STOCK|" in conf and "image=9.12341|MINE|" in conf and "image=9.12342|OLD|" in conf
        assert "timeout=12" in conf
        builds = z.read("9.1234/pad/builds.txt").decode().splitlines()
        assert "9.12341 1.13,1.15 b1" in builds and "9.12342 - b2" in builds
        assert z.read("9.1234/pad/b1/assets/a.png") == b"MOD" * 50
        assert (info["9.1234/pad/b2/start"].external_attr >> 16) & 0o777 == 0o755
        assert not any(n.startswith("9.1234/pad/b0") for n in names)    # the stock travels not
        man = json.loads(z.read("9.1234/pad/build.json"))
        assert man["multiboot_version"] == "9.1234" and man["images"][1]["folder"] == "9.12341"


def test_inspect_and_verify(inputs, capsys):
    out = _build(inputs)
    rep = md.inspect_zip(out)
    assert [im["device"] for im in rep["images"]] == ["1.15", "9.12341", "9.12342"]
    assert rep["hook"] and rep["timeout"] == 12 and rep["builds"] == {"b1": 3, "b2": 2}    # b1: start, a.png, delta
    assert md.main(["verify", "--zip", out]) == 0


def test_verify_refuses_a_renamed_file(inputs):
    out = _build(inputs)
    other = str(inputs["dir"] / "renamed.zip")
    os.rename(out, other)
    assert md.main(["verify", "--zip", other]) == 1


def test_inject_rewrites_the_menu_and_keeps_the_builds(inputs):
    out = _build(inputs)
    assert md.main(["inject", "--zip", out, "--titles", "A;B;C", "--timeout", "30"]) == 0
    with zipfile.ZipFile(out) as z:
        conf = z.read("9.1234/pad/images.conf").decode()
        assert "image=9.12341|B|" in conf and "timeout=30" in conf
        assert z.read("9.1234/pad/b1/assets/a.png") == b"MOD" * 50
        assert z.read("9.1234/start").startswith(b"#!/bin/bash")
    assert md.main(["verify", "--zip", out]) == 0


def test_out_is_named_for_the_version(inputs):
    rc = md.main(["build", "--primary", inputs["stock"], "--extra", inputs["mod"], "--version", "9.4321",
                  "--out", str(inputs["dir"] / "whatever.zip"), "--selector-dir", inputs["sel"]])
    assert rc == 0 and os.path.isfile(str(inputs["dir"] / "TBL-v9.4321.zip"))


@pytest.mark.parametrize("version,why", [("9.12345", "characters"), ("v9", "digits and dots")])
def test_bad_versions_refused(inputs, version, why):
    with pytest.raises(Refused, match=why):
        md.check_v(version, 2)


def test_refusals(inputs, tmp_path):
    with pytest.raises(Refused, match="at least two images"):
        md._inputs(type("A", (), {"primary": inputs["stock"], "extra": [], "version": "9.1"})())
    with pytest.raises(Refused, match="the multi-boot's own"):
        md._inputs(type("A", (), {"primary": inputs["stock"], "extra": [inputs["mod"]], "version": "1.15"})())
    bad = _zip(tmp_path / "two.zip", "1.15", {"start": b"x"})
    with zipfile.ZipFile(bad, "a") as z:
        z.writestr("other/x", b"x")
    with pytest.raises(Refused, match="ONE <version>/ folder"):
        md.TblZip(bad)
    nostart = _zip(tmp_path / "TBL-v1.0.zip", "1.0", {"assets/x": b"x"})
    with pytest.raises(Refused, match="no program"):
        md._inputs(type("A", (), {"primary": inputs["stock"], "extra": [nostart], "version": "9.1"})())
