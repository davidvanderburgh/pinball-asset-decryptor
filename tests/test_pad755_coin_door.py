"""A Home Edition's coin door (PAD-755): plugins.stern.coin_door, the Defaults
tab's Coin door box and the build step that writes it.

The synthetic program carries what the module reads - the switch devices with
their link bytes, the dedicated-switch handler table and the name cells - in
the shapes Jurassic Park The Pin 1.05 and Pro 1.16 have them.  The handler
hunt (an ARM code walk) is stood in for there and proven on the real builds
below, which run where the card library is (David's PC), with the emulator
proof in the ticket: the Home Editions put up 48V DISABLED / CLOSE COIN DOOR
when the door opens once linked, and ignore the door as they ship.
"""
import json
import os
import struct

import pytest

from pinball_decryptor.plugins.stern import coin_door as C

TEXT_VA, TEXT_SIZE = 0x8000, 0x1000
DATA_VA = 0x100000
HANDLER = 0x8200
SELECT_FN = 0x8100


class _Builder:
    def __init__(self):
        self.data = bytearray()

    def here(self):
        return DATA_VA + len(self.data)

    def align(self):
        while len(self.data) % 4:
            self.data.append(0)

    def string(self, s):
        self.align()
        va = self.here()
        self.data += s.encode("latin1") + b"\0"
        return va

    def words(self, *ws):
        self.align()
        va = self.here()
        self.data += struct.pack("<%dI" % len(ws), *ws)
        return va

    def cell(self, s):
        sva = self.string(s)
        return self.words(sva, sva, sva, sva, sva)


def _elf(home=True, select_link=0x98, key=C.INTERLOCK_KEY, half=False):
    """A program shaped like JP The Pin (*home*) or JP Pro."""
    b = _Builder()
    b.words(0xDEADBEEF)                          # nothing sits at DATA_VA
    door_cell = b.cell("Coin Door Power Interlock")
    sel_cell = b.cell("Service Select")
    rec_sel_cell = b.cell("SELECT")
    rec20_cell = b.cell("DEDICATED SW. #20" if home else "COIN DOOR INTERLOCK")
    filler_cell = b.cell("NOT USED")
    # devices: [0, link, name, cell] - the link byte 8 bytes before the cell
    link = 0 if home else (0x80 | 20)
    if half:
        link = 0x80 | 20
    b.words(0, link, 0, door_cell)
    b.words(0, select_link, 0, sel_cell)
    # the handler table, records 1..25
    table = b.here()
    for n in range(1, 26):
        if n == 24:
            b.words(SELECT_FN, 8, rec_sel_cell, 0x0FFF1F80, 0x32, 0x007D0005,
                    (1 << 24) | (n << 16) | 0x4D, 1)
        elif n == 20 and home:
            b.words(0, 0, rec20_cell, 0x04000000, 0x32, key, (n << 16) | 0x4D, 0)
        elif n == 20:
            b.words(HANDLER, 0, rec20_cell, 0x0FFF1F80, 0x32, key,
                    (1 << 24) | (n << 16) | 0x4D, 1)
        else:
            b.words(0, 0, filler_cell, 0, 0x70, 0x005E0005, (n << 16) | 0x4D, 0)
    b.align()
    # ELF: header, two program headers, .text then .data
    phoff, ph = 0x34, 32
    text_off = 0x1000
    data_off = text_off + TEXT_SIZE
    hdr = bytearray(text_off)
    hdr[:4] = b"\x7fELF"
    hdr[4], hdr[5] = 1, 1
    struct.pack_into("<I", hdr, 0x1C, phoff)
    struct.pack_into("<HH", hdr, 0x2A, ph, 2)
    struct.pack_into("<8I", hdr, phoff, 1, text_off, TEXT_VA, TEXT_VA,
                     TEXT_SIZE, TEXT_SIZE, 5, 0x1000)
    struct.pack_into("<8I", hdr, phoff + ph, 1, data_off, DATA_VA, DATA_VA,
                     len(b.data), len(b.data), 6, 0x1000)
    return bytes(hdr) + bytes(TEXT_SIZE) + bytes(b.data), table


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.setattr(C, "_handler", lambda _elf, _table: HANDLER)


def _rec(elf_bytes, table, n):
    e = C._Elf(elf_bytes)
    return struct.unpack_from("<8I", elf_bytes, e.off(table + 32 * (n - 1)))


# ------------------------------------------------------------- reading
def test_a_pro_reads_as_fitted():
    elf, _t = _elf(home=False)
    assert C.plan(elf) == {"state": C.FITTED, "handler": HANDLER}


def test_a_home_edition_reads_as_missing_with_what_to_write(handler):
    elf, table = _elf(home=True)
    p = C.plan(elf, table=object())
    assert p["state"] == C.MISSING
    assert p["record_va"] == table + 32 * 19
    assert p["handler"] == HANDLER
    # the mask and board come from the build's own live SELECT record
    assert p["mask"] == 0x0FFF1F80 and p["board"] == 1
    assert p["flags"] == (1 << 24) | (20 << 16) | 0x4D


@pytest.mark.parametrize("kw", [
    {"select_link": 0x97},           # Service Select names another record
    {"select_link": 0x18},           # ...or isn't linked at all
    {"key": 0x00780005},             # record 20 is not the door's switch
    {"half": True},                  # linked device, empty record: unknown
])
def test_anything_unexpected_offers_nothing(handler, kw):
    elf, _t = _elf(home=True, **kw)
    assert C.plan(elf, table=object()) is None


def test_no_handler_found_offers_nothing(monkeypatch):
    monkeypatch.setattr(C, "_handler", lambda _elf, _table: None)
    elf, _t = _elf(home=True)
    assert C.plan(elf, table=object()) is None


def test_not_an_elf_offers_nothing():
    assert C.plan(b"nope" * 100) is None


# ------------------------------------------------------------- writing
def test_the_patch_writes_the_pros_link_and_nothing_else(handler):
    elf, table = _elf(home=True)
    p = C.plan(elf, table=object())
    out = C.patched_bytes(elf, p)
    assert len(out) == len(elf)
    e = C._Elf(elf)
    changed = [i for i in range(len(elf)) if elf[i] != out[i]]
    link_off = e.off(p["link_va"])
    rec_off = e.off(p["record_va"])
    allowed = {link_off} | set(range(rec_off, rec_off + 4)) \
        | set(range(rec_off + 12, rec_off + 16)) \
        | set(range(rec_off + 24, rec_off + 32))
    assert changed and set(changed) <= allowed
    assert out[link_off] == 0x94
    assert _rec(out, table, 20) == (HANDLER, 0, _rec(elf, table, 20)[2],
                                    0x0FFF1F80, 0x32, C.INTERLOCK_KEY,
                                    0x0114004D, 1)
    assert C.plan(out) == {"state": C.FITTED, "handler": HANDLER}


def test_a_fitted_build_is_not_patched():
    elf, _t = _elf(home=False)
    with pytest.raises(ValueError):
        C.patched_bytes(elf, C.plan(elf))


def test_the_build_step_patches_or_says_why_not(handler):
    from pinball_decryptor.plugins.stern.explorer import CardImage
    home, _t = _elf(home=True)
    pro, _t = _elf(home=False)
    logs = []
    log = lambda text, level="info": logs.append((level, text))   # noqa: E731
    out = CardImage._with_coin_door(object(), home, log)
    assert C.plan(out)["state"] == C.FITTED
    assert logs[-1][0] == "info" and "48V DISABLED" in logs[-1][1]
    assert CardImage._with_coin_door(object(), pro, log) == pro
    assert "already uses its coin door" in logs[-1][1]
    assert CardImage._with_coin_door(object(), b"x" * 64, log) == b"x" * 64
    assert logs[-1][0] == "warning"


# ------------------------------------------------------ the Defaults tab
def _staged(folder):
    p = os.path.join(str(folder), ".staged_changes.json")
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _load(w, project, coin):
    svc = w.window.service("defaults")
    w.run(lambda: w.window.write_assets_var.set(str(project)))
    res = ("ok", object(), 3, "/game", [], "C:/card.raw", None, [], None,
           coin)
    w.run(lambda: svc._apply_result(res))
    return svc


def test_the_box_shows_only_on_a_build_it_can_fit(tmp_path):
    from tests.webui_harness import web_app
    project = tmp_path / "proj"
    project.mkdir()
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _load(w, project, {"state": C.FITTED, "handler": 1})
        assert w.state("defaults")["coin_offer"] is False
        assert w.call("defaults.coin_door_set", True) is False
        assert "coin_door" not in _staged(project)
        _load(w, project, None)
        assert w.state("defaults")["coin_offer"] is False
        _load(w, project, {"state": C.MISSING})
        st = w.state("defaults")
        assert st["coin_offer"] is True and st["coin_fitted"] is False


def test_ticking_it_stages_for_the_build_and_reset_clears_it(tmp_path):
    from tests.webui_harness import web_app
    project = tmp_path / "proj"
    project.mkdir()
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        svc = _load(w, project, {"state": C.MISSING})
        assert w.call("defaults.coin_door_set", True) is True
        assert _staged(project)["coin_door"] == "fitted"
        assert w.state("defaults")["coin_fitted"] is True
        assert svc.staged_coin_door(str(project)) is True
        assert w.window.staged_coin_door(str(project)) is True
        # a reload of the same project keeps it ticked
        _load(w, project, {"state": C.MISSING})
        assert w.state("defaults")["coin_fitted"] is True
        assert w.call("defaults.coin_door_set", False) is True
        assert "coin_door" not in _staged(project)
        assert w.state("defaults")["coin_fitted"] is False
        w.call("defaults.coin_door_set", True)
        w.call("defaults.reset")
        assert "coin_door" not in _staged(project)
        assert w.state("defaults")["coin_fitted"] is False


def test_packs_and_transfers_carry_it():
    from pinball_decryptor.core import mod_transfer, modpack
    assert "coin_door" in modpack._EXTRA_SCALARS
    assert "coin_door" in mod_transfer._TOGGLE_KEYS


# ------------------------------------------------------ the real builds
_LIB = "D:/Pinball/images/Stern/spike2"
_CARDS = {
    "jp_pin": "jurassic_park_the_pin-1_05_0.Release.8G.sdcard.raw",
    "sw_home": "star_wars_elg-1_10_0_spike2.Release.8G.sdcard.raw",
    "jp_pro": "jurassic_park_pro-1_16_0.Release.8G.sdcard.raw",
}


def _real(key):
    path = os.path.join(_LIB, _CARDS[key])
    if not os.path.isfile(path):
        pytest.skip("the card library is not on this machine")
    from pinball_decryptor.plugins.stern.explorer import CardImage
    with CardImage(path) as c:
        table, part, fw = c.adjustment_table()
        return c.read_firmware(part, fw), table


@pytest.mark.parametrize("key,handler_va,record_va,link_va", [
    ("jp_pin", 0x1B890C, 0x58BC50, 0x5856CC),
    ("sw_home", 0xCFEF4, 0x57E06C, 0x57522C),
])
def test_the_home_editions_are_found_and_fitted(key, handler_va, record_va,
                                                 link_va):
    elf, table = _real(key)
    p = C.plan(elf, table)
    assert (p["state"], p["handler"], p["record_va"], p["link_va"]) == (
        C.MISSING, handler_va, record_va, link_va)
    out = C.patched_bytes(elf, p)
    assert C.plan(out, table)["state"] == C.FITTED


def test_a_pros_own_handler_is_the_one_the_hunt_finds():
    """The hunt, checked against a build whose record 20 names its handler
    (all 31 fitted builds in the library agreed, 2026-10-26)."""
    elf, table = _real("jp_pro")
    p = C.plan(elf, table)
    assert p == {"state": C.FITTED, "handler": 0x3AA298}
    assert C._handler(elf, table) == 0x3AA298
