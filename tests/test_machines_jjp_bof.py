"""My machines for JJP and BoF (PAD-787): their card printers (a JJP
full-install ISO's volume ID, a BoF ``.fun``'s first tar member decrypted in
Python), their support-page parsers, the per-title pages of the daily check,
a Write's revision, and both makers' rows on the real web app.

The ``.fun`` and ISO here are built in Python (an OpenPGP symmetric file as
gpg writes one; an ISO 9660 primary volume descriptor), so everything runs
anywhere; the real library files are read too when they are on this
computer.
"""

import io
import json
import os
import tarfile
import time
import zlib

import pytest

from pinball_decryptor.core import code_watch, lineage, machines
from pinball_decryptor.plugins.bof import fun_head
from pinball_decryptor.plugins.bof import machine_info as bof
from pinball_decryptor.plugins.jjp import machine_info as jjp

JJP_LIB = r"D:\Pinball\images\JJP"
BOF_LIB = r"D:\Pinball\images\BoF"

# JJP's support page as it spells its downloads (US and EU mirrors of one
# ISO, the delta zip beside it); BoF's as a Dropbox link with an HTML-escaped
# query.  One stub page carries both, as the screenshot rig's does.
STUB_PAGE = """<html>
<a href="https://marketing.jerseyjackpinball.com/sonic/Sonic-v00.951.iso">Download</a>
<a href="https://downloadseu.jerseyjackpinball.com/sonic/Sonic-v00.951.iso">Download</a>
<a href="https://marketing.jerseyjackpinball.com/gnr/gnr_update-v03.03.zip">Download</a>
<a href="https://www.dropbox.com/scl/fi/ql75j/BOF_WMH_20261001.zip?rlkey=x&#038;dl=0">DOWNLOAD</a>
</html>"""


# ------------------------------------------------------------ test files
def _len(n):
    if n < 192:
        return bytes([n])
    if n < 8384:
        n -= 192
        return bytes([(n >> 8) + 192, n & 0xFF])
    return b"\xff" + n.to_bytes(4, "big")


def _packet(tag, body, partial=False):
    """A new-format packet; *partial* splits the body into 1 KiB partial
    chunks as gpg does for a stream."""
    head = bytes([0xC0 | tag])
    if not partial:
        return head + _len(len(body)) + body
    out = bytearray(head)
    while len(body) > 1024:
        out += b"\xea" + body[:1024]          # 2**10, partial
        body = body[1024:]
    return bytes(out + _len(len(body)) + body)


def _encrypt(plain, passphrase, compress=True):
    """*plain* as ``gpg --symmetric`` writes it: SKESK v4 (AES-256, S2K
    type 3), SEIPD v1 over an (optionally compressed) literal packet."""
    from Crypto.Cipher import AES
    s2k = bytes([3, 10]) + b"saltsalt" + bytes([0x10])
    key = fun_head._s2k_key(s2k, passphrase.encode(), 32)
    inner = _packet(11, b"b\x00\x00\x00\x00\x00" + plain, partial=True)
    if compress:
        inner = _packet(8, b"\x02" + zlib.compress(inner), partial=True)
    prefix = os.urandom(16)
    clear = prefix + prefix[-2:] + inner
    enc = AES.new(key, AES.MODE_CFB, iv=b"\0" * 16,
                  segment_size=128).encrypt(clear)
    return _packet(3, bytes([4, 9]) + s2k) + _packet(18, b"\x01" + enc,
                                                    partial=True)


def _tar_gz(first, mtime=1777487101, size=50000):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        ti = tarfile.TarInfo(first)
        ti.size, ti.mtime = size, mtime
        t.addfile(ti, io.BytesIO(os.urandom(size)))
        ti = tarfile.TarInfo("md5")
        ti.size = 3
        t.addfile(ti, io.BytesIO(b"abc"))
    return buf.getvalue()


def make_fun(path, first="GDHarvest_not_harvest_20260429.x86_64",
             passphrase="winchesterkey", **kw):
    data = _encrypt(_tar_gz(first, **kw), passphrase)
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


def make_iso(path, volume="Sonic-v00.926", body=b""):
    pvd = bytearray(2048)
    pvd[0], pvd[1:6], pvd[6] = 1, b"CD001", 1
    pvd[40:72] = volume.encode().ljust(32)
    with open(path, "wb") as f:
        f.write(b"\0" * 32768 + bytes(pvd) + (body or os.urandom(200000)))
    return str(path)


@pytest.fixture
def print_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(lineage, "PRINT_CACHE", str(tmp_path / "prints.json"))
    import pinball_decryptor.plugins.jjp.manufacturer  # noqa: F401  registers
    import pinball_decryptor.plugins.bof.manufacturer  # noqa: F401
    return tmp_path


# ------------------------------------------------------------------- JJP
def test_jjp_builds_compare_as_jjp_writes_them():
    assert jjp.version_of("00", "95") > jjp.version_of("00", "926")
    assert jjp.version_of("00", "951") > jjp.version_of("00", "926")
    assert jjp.version_of("03", "10") > jjp.version_of("03", "03")
    assert jjp.version_of("01", "00") > jjp.version_of("00", "951")
    assert jjp.version_words(jjp.version_of("00", "951")) == "0.951"
    assert jjp.version_words(jjp.version_of("03", "03")) == "3.03"
    assert jjp.version_words(jjp.version_of("01", "26")) == "1.26"


def test_jjp_page_and_titles():
    assert jjp.parse_support_page(STUB_PAGE) == {"sonic": jjp.version_of("00", "951")}
    from pinball_decryptor.plugins.jjp.games import GAME_DB
    names = {g["display"] for g in GAME_DB.values()}
    for key in jjp.PAGES:                    # every title has its real name
        assert jjp.release_info(key + "-v01.00")["title"] in names
    rel = jjp.release_info("GunsNRoses-v03.03")
    assert (rel["key"], rel["build"], rel["title"]) == \
        ("gunsnroses", "3.03", "Guns N' Roses")
    assert jjp.release_info("not an iso") is None


def test_jjp_iso_print(tmp_path, monkeypatch):
    iso = make_iso(tmp_path / "renamed.iso")
    a = jjp.iso_print(iso)
    assert a["sidx"] == "Sonic-v00.926" and a["manufacturer"] == "jjp"
    assert a == jjp.iso_print(iso)                         # the same file again
    assert not a["official"] and a["label"] == "Sonic the Hedgehog 0.926"
    monkeypatch.setitem(jjp.STOCK, "Sonic-v00.926", a["print"])
    assert jjp.iso_print(iso)["official"]
    # a rebuild of it prints apart
    assert jjp.iso_print(make_iso(tmp_path / "b.iso"))["print"] != a["print"]
    # a release PAD has no record of; not an ISO; not JJP's volume ID
    assert jjp.iso_print(make_iso(tmp_path / "c.iso", "Sonic-v00.999"))["label"] == ""
    junk = tmp_path / "junk.iso"
    junk.write_bytes(b"x" * 40000)
    assert jjp.iso_print(str(junk)) is None
    assert jjp.iso_print(make_iso(tmp_path / "d.iso", "UBUNTU 24.04")) is None


# ------------------------------------------------------------------- BoF
def test_fun_head_reads_the_first_member(tmp_path):
    p = make_fun(tmp_path / "winchester.fun")
    assert fun_head.first_member(p, "winchesterkey")[0] == \
        "GDHarvest_not_harvest_20260429.x86_64"
    with pytest.raises(fun_head.FunHeadError):
        fun_head.first_member(p, "funkey")                 # wrong passphrase
    # gpg without compression, too
    raw = tmp_path / "raw.fun"
    raw.write_bytes(_encrypt(_tar_gz("update/"), "funkey", compress=False))
    assert fun_head.first_member(str(raw), "funkey")[0].startswith("update")


def test_build_dates():
    import datetime
    d = datetime.date
    assert fun_head.build_date("GDHarvest_not_harvest_20260429.x86_64", 0) == d(2026, 4, 29)
    assert fun_head.build_date("GDHarvest_202600513.x86_64", 0) == d(2026, 5, 13)
    assert fun_head.build_date("._GDCraze_linux_20260130.x86_64", 0) == d(2026, 1, 30)
    # Labyrinth: the first member is a folder; its date is the build's
    assert fun_head.build_date("update", 1769786856) == d(2026, 1, 30)


def test_bof_page_and_print(tmp_path, monkeypatch):
    assert bof.parse_code_page(STUB_PAGE) == {"winchester": (2026, 10, 1)}
    assert bof.parse_code_page(
        'href="https://www.dropbox.com/x/BOF_LAB_20260130.zip?dl=0"'
        'href="https://www.dropbox.com/x/BOF_DUNE_20260513.zip?dl=0"'
        'href="https://www.dropbox.com/x/BOF_JOVI_20261014.zip?dl=0"') == {
        "labyrinth": (2026, 1, 30), "dune": (2026, 5, 13),
        "bonjovi": (2026, 10, 14)}
    p = make_fun(tmp_path / "winchester.fun")
    a = bof.fun_print(p)
    assert a["sidx"] == "winchester-2026.04.29" and a["manufacturer"] == "bof"
    assert a["label"] == "Winchester Mystery House 2026.04.29" and not a["official"]
    monkeypatch.setitem(bof.STOCK, "winchester-2026.04.29", a["print"])
    assert bof.fun_print(p)["official"]
    rel = bof.release_info(a["sidx"])
    assert (rel["title"], rel["build"]) == ("Winchester Mystery House", "2026.04.29")
    junk = tmp_path / "x.raw"
    junk.write_bytes(b"0")
    assert bof.fun_print(str(junk)) is None


# ------------------------------------------------------ per-title pages
class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_check_reads_only_the_owners_titles_pages(tmp_path, monkeypatch):
    from pinball_decryptor.core import config
    monkeypatch.setattr(config, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.delenv(code_watch.ENV_URL, raising=False)
    import pinball_decryptor.plugins.jjp.manufacturer  # noqa: F401
    seen = []

    def opener(req, timeout):
        seen.append(req.full_url)
        if "wonka" in req.full_url:
            raise OSError("offline")
        return _Resp(STUB_PAGE.encode())

    assert code_watch.page_url("jjp", "sonic") == jjp.PAGES["sonic"]
    assert code_watch.page_url("jjp", "nobody") == jjp.SUPPORT_PAGE
    assert code_watch.due("jjp", now=1000, keys={"sonic"})
    st = code_watch.check("jjp", opener=opener, now=1000, keys={"sonic"})
    assert seen == [jjp.PAGES["sonic"]] and st["ok"]
    assert code_watch.newest("jjp", "sonic") == jjp.version_of("00", "951")
    assert not code_watch.due("jjp", now=2000, keys={"sonic"})
    # a machine of another title added since: its page is due today
    assert code_watch.due("jjp", now=2000, keys={"sonic", "wonka"})
    st = code_watch.check("jjp", opener=opener, now=2000,
                          keys={"sonic", "wonka"})
    assert not st["ok"] and "offline" in st["error"]
    assert code_watch.newest("jjp", "sonic") == jjp.version_of("00", "951")
    # the stub stands in for every page
    monkeypatch.setenv(code_watch.ENV_URL, "http://127.0.0.1:1/stub")
    assert code_watch.page_url("jjp", "sonic") == "http://127.0.0.1:1/stub"
    assert code_watch._urls("jjp", {"sonic", "wonka"}) == ["http://127.0.0.1:1/stub"]


# ------------------------------------------------------- a Write's revision
def test_a_jjp_write_is_a_revision(tmp_path, print_cache):
    orig = make_iso(tmp_path / "Sonic-v00.926.iso")
    built = make_iso(tmp_path / "Sonic-v00.926_modified.iso")
    proj = tmp_path / "Sonic mods"
    proj.mkdir()
    lineage.note_extract(str(proj), "Sonic-v00.926.iso",
                         lineage.card_print(orig, measure=True))
    said = []
    entry = lineage.note_built(orig, str(proj), built,
                               lambda t, lvl: said.append(t))
    assert entry["rev"] == 1 and said and "rev 1" in said[0]
    m = {"print": lineage.card_print(built)["print"]}
    found = machines.projects_for(m, [str(proj)])
    assert machines.card_words(m, found[0][1]) == "PAD build, rev 1"


def test_both_writes_record_their_revision(tmp_path, print_cache):
    """The JJP and BoF Write wrappers note the file they built in the
    project's lineage before they report done."""
    from pinball_decryptor.plugins.bof.manufacturer import BOFManufacturer
    from pinball_decryptor.plugins.jjp.manufacturer import JJPManufacturer
    noop = lambda *a, **k: None                           # noqa: E731
    cases = []
    proj = tmp_path / "jjp"
    proj.mkdir()
    orig = make_iso(tmp_path / "Sonic-v00.926.iso")
    built = make_iso(proj / "Sonic-v00.926_modified.iso")
    cases.append((JJPManufacturer(), orig, proj, str(tmp_path / "out.iso"),
                  built))
    proj = tmp_path / "bof"
    proj.mkdir()
    orig = make_fun(tmp_path / "winchester.fun")
    out = str(tmp_path / "out" / "winchester.fun")
    os.makedirs(os.path.dirname(out))
    cases.append((BOFManufacturer(), orig, proj, out, None))
    for mfr, orig, proj, out, produced in cases:
        lineage.note_extract(str(proj), os.path.basename(orig),
                             lineage.card_print(orig, measure=True))
        seen = {}
        w = mfr.make_write_pipeline(
            orig, str(proj), out, log_cb=noop, phase_cb=noop,
            progress_cb=noop,
            done_cb=lambda ok, summary: seen.update(ok=ok))
        if produced is None:
            make_fun(out)                         # what the Write wrote
            w._done(True, "built")
        else:
            w._intercept_done(True, "built")
        lin = lineage.read_lineage(str(proj))
        assert seen["ok"] and [r["rev"] for r in lin["revs"]] == [1], mfr.key
        assert lin["revs"][0]["print"] == lineage.card_print(out)["print"]


# ----------------------------------------------------- on the real web app
def _until(w, pred, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return False


def _rows(w):
    return (w.state("shellx").get("machines") or {}).get("rows") or []


def test_jjp_and_bof_machines_on_the_picker(tmp_path, monkeypatch, print_cache):
    from tests.webui_harness import web_app
    from pinball_decryptor.core import project_file
    iso = make_iso(tmp_path / "Sonic-v00.926.iso")
    fun = make_fun(tmp_path / "winchester.fun")
    proj = tmp_path / "Sonic mods"
    proj.mkdir()
    lineage.note_extract(str(proj), "Sonic-v00.926.iso",
                         lineage.card_print(iso, measure=True))
    project_file.save(project_file.anchor_path(str(proj)),
                      manufacturer_key="jjp", paths={"extract_input": iso},
                      extract_options={}, stock_image=iso)
    import http.server
    import threading
    got = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):                                  # noqa: N802
            got.append(self.path)
            body = STUB_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv(code_watch.ENV_URL, "http://127.0.0.1:%d/support/"
                       % srv.server_address[1])
    try:
        with web_app(tmp_path, settings={"projects": [
                {"folder": str(proj), "manufacturer": "jjp",
                 "last_opened": ""}]}) as w:
            w.answers.append("Game room Sonic")
            sonic = w.call("shellx.machines_add", iso)
            assert w.asked[-1]["initial"] == "Sonic the Hedgehog"
            wmh = w.call("shellx.machines_add", fun, "Winchester")
            assert sonic and wmh
            # opt-in: with the box never ticked no maker's site is read
            assert _until(w, lambda: len(_rows(w)) == 2)
            _until(w, lambda: False, timeout=1.5)
            m = w.state("shellx")["machines"]
            assert got == [] and m["watch"] is False
            assert not any(r["newer"] for r in _rows(w))
            assert "off: PAD reads no maker's site" in m["watch_text"]
            assert not w.call("shellx.machines_check_now")
            assert got == []
            # ticked: the pages are read
            assert w.call("shellx.machines_set_watch", True)
            ok = _until(w, lambda: len(_rows(w)) == 2
                        and all(r["newer"] for r in _rows(w)))
            assert ok, (json.dumps(_rows(w), indent=1), got,
                        w.state("shellx")["machines"]["watch_text"])
            rows = {r["id"]: r for r in _rows(w)}
            r = rows[sonic]
            assert (r["mfr"], r["maker"], r["title"], r["build"], r["newer"],
                    r["noun"], r["transfer"]) == \
                ("jjp", "JJP", "Sonic the Hedgehog", "0.926", "0.951",
                 "install ISO", False)
            assert r["lineage"] == "Modified card"    # not JJP's own 0.926
            assert os.path.normcase(r["project"]) == os.path.normcase(str(proj))
            r = rows[wmh]
            assert (r["mfr"], r["maker"], r["title"], r["build"], r["newer"],
                    r["noun"]) == \
                ("bof", "Barrels of Fun", "Winchester Mystery House",
                 "2026.04.29", "2026.10.01", "update file")
            text = w.state("shellx")["machines"]["watch_text"]
            assert "Barrels of Fun's code-update pages and JJP's support " \
                   "pages checked at" in text
            toasts = [t["text"] for t in w.state("shell")["toasts"]]
            assert any("JJP has Sonic the Hedgehog 0.951 out; Game room "
                       "Sonic runs 0.926" in t for t in toasts)
            assert any("Barrels of Fun has Winchester Mystery House "
                       "2026.10.01 out" in t for t in toasts)
            # Mod Pack: the project open on the Mod Pack tab; no transfer
            # fields for a maker without one
            assert w.call("shellx.machines_transfer", sonic)
            assert _until(w, lambda: w.state("shell").get("tab") == "modpack")
            assert os.path.normcase(w.app._project_folder()) == \
                os.path.normcase(str(proj))
            # Change card refuses another maker's file
            w.answers.append("ok")
            assert not w.call("shellx.machines_rebind", sonic, fun)
            assert "JJP machine" in w.asked[-1]["message"]
    finally:
        srv.shutdown()


# ------------------------------------------------- the real library files
_REAL_JJP = ["EltonJohn-v02.03.iso", "Godfather-v02.03.iso",
             "GunsNRoses-v03.03.iso", "HarryPotter-v01.26.iso",
             "Pirates-v01.01.iso", "Sonic-v00.925.iso", "Sonic-v00.926.iso",
             "Wonka-v03.03.iso"]


@pytest.mark.skipif(not os.path.isdir(JJP_LIB), reason="no JJP library here")
@pytest.mark.parametrize("name", _REAL_JJP)
def test_every_library_iso_is_stock(name):
    path = os.path.join(JJP_LIB, name)
    if not os.path.isfile(path):
        pytest.skip("not in the library")
    a = jjp.iso_print(path)
    assert a["sidx"] == name[:-4] and a["official"]


@pytest.mark.skipif(not os.path.isfile(os.path.join(
    JJP_LIB, "CHAKAs_LOTLJ_V1.0_GNR_LE_3.03.iso")), reason="no mod ISO here")
def test_a_modded_iso_is_modified():
    a = jjp.iso_print(os.path.join(JJP_LIB, "CHAKAs_LOTLJ_V1.0_GNR_LE_3.03.iso"))
    assert a["sidx"] == "GunsNRoses-v03.03" and not a["official"] and a["label"]


@pytest.mark.skipif(not os.path.isdir(BOF_LIB), reason="no BoF library here")
@pytest.mark.parametrize("name,sidx,official", [
    ("lab.fun", "labyrinth-2026.01.30", True),
    ("dune.fun", "dune-2026.05.13", True),
    ("winchester.fun", "winchester-2026.04.29", True),
    (os.path.join("winchester 5-27", "winchester.fun"), "winchester-2026.05.27", True),
    ("bon-jovi_2026.10.01.fun", "bonjovi-2026.10.01", True),
    (os.path.join("Labyrinth (Sarah mod)", "lab.fun"), "labyrinth-2026.01.30", False),
])
def test_every_library_fun(name, sidx, official):
    path = os.path.join(BOF_LIB, name)
    if not os.path.isfile(path):
        pytest.skip("not in the library")
    a = bof.fun_print(path)
    assert (a["sidx"], a["official"]) == (sidx, official)
