"""PAD-1325: editions on a Spike 3 multi-boot card.

A Spike 2 card of editions (PAD-495) is a multi-boot card whose images are Writes of one game, each
with EDITION in its operator menu; the boot program reads the setting off the machine's settings
store and boots that image with no menu. On Spike 3 the three pieces are:

- the Spike 3 Write grows EDITION into the 64-bit game program's menu (:mod:`.spike3_menu`, on the
  page that lists CUSTOM MESSAGE: Attract Mode) and puts the program on the card whole;
- the card builder (tools/spike3_emu/mks3multi.py ``--editions``) checks every image carries it and
  writes ``edition=/data/nv/<title>/NVM|<key>|<n>`` into images.conf;
- the menu (s3select, codeselect's nvm.c) reads a Spike 3 store, whose header is bigger than Spike
  2's (its section table is u64 at 0xa8, and its adjustments start 8 bytes past 336 + 40 * audits).

The real programs are the Spike 3 library cards' (skipped when the library is not on this machine);
the store reader is compiled from nvm.c when this machine has a C compiler.
"""
import hashlib
import os
import shutil
import struct
import subprocess
import sys
from types import SimpleNamespace

import pytest

from pinball_decryptor.plugins.stern import editions as Ed
from pinball_decryptor.plugins.stern import menu_settings as MS
from pinball_decryptor.plugins.stern import spike3_menu as S3M

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODESELECT = os.path.join(ROOT, "tools", "spike2_emu", "codeselect")
sys.path.insert(0, os.path.join(ROOT, "tools", "spike3_emu"))
import mks3multi as M3  # noqa: E402

LIBRARY = r"D:\Pinball\images\Stern\spike3"
CARDS = {
    "star_wars_elg": "star_wars_elg-1_10_0_spike3.Release.64G.sdcard-secure.raw",
    "fallout_le_081": "fallout_le-0_81_0_spike3.Release.64G.sdcard-secure.raw",
    "fallout_le": "fallout_le-0_82_0_spike3.Release.64G.sdcard-secure.raw",
    "transformers_mtmte_le": "transformers_mtmte_le-0_96_0_spike3.Release.64G.sdcard-secure.raw",
    "pokemon_le": "pokemon_le-0_82_0.Release.64G.sdcard-secure.raw",
}
_CACHE = {}
NAMES = ["Standard", "Dark Side"]


def program(key):
    if key in _CACHE:
        return _CACHE[key]
    path = os.path.join(LIBRARY, CARDS[key])
    if not os.path.isfile(path):
        pytest.skip("no Spike 3 library card for %s (%s)" % (key, path))
    from pinball_decryptor.plugins.stern import title_reader as TR
    _CACHE[key] = TR.game_program(path)
    return _CACHE[key]


# ---- the settings store the menu reads -------------------------------------------------------
def _store(wide, records, n_audits=3):
    """A settings store in Spike 2's layout (*wide* False) or Spike 3's, holding *records*
    ``[(caption, value)]`` as its adjustments."""
    head = 336 if wide else 208
    adj = head + 40 * n_audits
    if wide:
        adj += 8          # measured: ELG's adjustments start 8 bytes past its audits' end
    buf = bytearray(adj + 44 * len(records) + 64)
    buf[0:4] = b"MAP0"
    struct.pack_into("<HH", buf, 0x3c, n_audits, len(records))
    if wide:
        struct.pack_into("<QQ", buf, 0xa8, head, adj)
    else:
        struct.pack_into("<II", buf, 0x7c, head, adj)
    for k, (cap, v) in enumerate(records):
        o = adj + 44 * k
        buf[o:o + 20] = hashlib.sha1(cap.encode()).digest()
        struct.pack_into("<6I", buf, o + 20, 0, 0, 1, k, v, 0xFF - (v & 0xFF))
    return bytes(buf)


_DRIVER = r'''
#include <stdio.h>
#include "nvm.h"
int main(int argc, char **argv)
{
    unsigned char key[20]; char why[400] = "", from[400] = ""; int v = -1;
    if (argc != 3 || nvm_parse_key(argv[2], key)) return 2;
    if (nvm_read_value(argv[1], key, &v, from, sizeof from, why, sizeof why)) { printf("NO %s\n", why); return 1; }
    printf("%d\n", v);
    return 0;
}
'''


@pytest.fixture(scope="module")
def nvread(tmp_path_factory):
    cc = shutil.which("cc") or shutil.which("gcc")
    if os.name == "nt" or not cc:
        pytest.skip("no C compiler to build codeselect's nvm.c")
    d = tmp_path_factory.mktemp("nvm")
    (d / "drv.c").write_text(_DRIVER)
    exe = d / "nvread"
    subprocess.run([cc, "-O1", "-I", CODESELECT, "-o", str(exe), str(d / "drv.c"),
                    os.path.join(CODESELECT, "nvm.c")], check=True)

    def read(store_bytes, caption):
        sd = d / ("s%d" % len(list(d.iterdir())))
        sd.mkdir()
        (sd / "00000002").write_bytes(b"MAP0 an older generation")
        (sd / "00000003").write_bytes(store_bytes)
        (sd / "00000003.crc32").write_bytes(b"\0\0\0\0")
        r = subprocess.run([str(exe), str(sd), hashlib.sha1(caption.encode()).hexdigest()],
                           capture_output=True, text=True)
        return r.stdout.strip()
    return read


@pytest.mark.parametrize("wide", [False, True], ids=["spike2", "spike3"])
def test_the_menu_reads_edition_off_either_store(nvread, wide):
    store = _store(wide, [("MASTER VOLUME SETTING", 40), ("EDITION", 2), ("CUSTOM MESSAGE", 1)], n_audits=231)
    assert nvread(store, "EDITION") == "2"
    assert nvread(store, "MASTER VOLUME SETTING") == "40"
    assert nvread(store, "HANDICAP").startswith("NO ")


def test_a_spike3_store_is_not_where_spike2s_rule_puts_it():
    # the layout this ticket reads: Star Wars ELG 1.10's store, 231 audits -> adjustments at 9584,
    # where 208 + 231 * 40 = 9448 lands 136 bytes short (measured off the emulator's slot)
    store = _store(True, [("EDITION", 1)], n_audits=231)
    assert struct.unpack_from("<QQ", store, 0xa8) == (336, 9584)
    assert 208 + 231 * 40 == 9448


# ---- the page EDITION goes on, per game ------------------------------------------------------
@pytest.mark.parametrize("key", ["star_wars_elg", "fallout_le_081", "fallout_le", "transformers_mtmte_le"])
def test_edition_goes_on_the_attract_mode_page_by_its_name(key):
    # PAD-1324's lookup: the page by its name (Fallout has two Attract Mode pages: the system's first)
    from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable
    _g, _v, elf = program(key)
    t = AdjustmentTable(elf, wide_ok=True)
    num = MS.wide_category(t, MS.EDITION)
    assert MS.wide_category_names(t)[num].strip().lower() == "attract mode"


def test_music_modes_and_edition_grow_together():
    # the modes' hook runs the music modes' grown copy (game.pad) in the card's program's place, so
    # that copy carries EDITION too: one grow, one category table, both rows read back
    from pinball_decryptor.plugins.stern import spike3_music
    _g, _v, elf = program("star_wars_elg")
    modes = SimpleNamespace(count=2, menu_names=lambda: ["Stock", "Rock"])
    setting, grown = spike3_music.menu_program(elf, modes, [(MS.EDITION, 2, NAMES)])
    assert setting.key == MS.MUSIC_MODE and not MS.check(grown, setting)
    ed = Ed.in_program(grown)
    assert ed is not None and ed["values"] == 2 and ed["help"] == "1 = Standard, 2 = Dark Side"
    # and with no extra rows it is the music modes' program as before
    setting2, alone = spike3_music.menu_program(elf, modes)
    assert not MS.check(alone, setting2) and Ed.in_program(alone) is None


# ---- which Spike 3 builds take it -------------------------------------------------------------
def test_spike3_build_keys_and_refusals():
    assert Ed.spike3_key("fallout_le", "0.82.0") == "fallout_le-0.82"
    assert Ed.spike3_key("star_wars_elg", "1.10") == "star_wars_elg-1.10"
    for game, ver in (("star_wars_elg", "1.10.0"), ("fallout_le", "0.81.0"), ("fallout_le", "0.82.0"),
                      ("transformers_mtmte_le", "0.96.0")):
        assert Ed.spike3_refusal(game, ver) == ""
    assert "uses every setting EDITION could take" in Ed.spike3_refusal("pokemon_le", "0.82.0")
    assert "not offered on" in Ed.spike3_refusal("some_new_title", "0.10.0")
    assert Ed.spike3_refusal("", "") == Ed.NO_TITLE


@pytest.mark.parametrize("key", ["star_wars_elg", "fallout_le_081", "fallout_le", "transformers_mtmte_le"])
def test_the_write_grows_edition_onto_attract_mode(key):
    game, _version, elf = program(key)
    assert Ed.in_program(elf) is None                           # the stock program has none
    out, settings, refused = S3M.grow(elf, [(MS.EDITION, 2, NAMES)])
    assert not refused and [s.key for s in settings] == [MS.EDITION]
    s = settings[0]
    assert s.category == 16 and s.where == "Adjustments > Machine Settings > Attract Mode"
    assert len(out) > len(elf)                                  # the grown menu table's segment
    got = Ed.in_program(out)
    assert got == {"values": 2, "help": "1 = Standard, 2 = Dark Side", "id": s.id}
    # a second Write of the same project leaves the program as it is
    again, s2, _r = S3M.grow(out, [(MS.EDITION, 2, NAMES)])
    assert again == out and s2[0].id == s.id


def test_a_build_with_no_spare_setting_is_refused_with_its_reason():
    _g, _v, elf = program("pokemon_le")
    out, settings, refused = S3M.grow(elf, [(MS.EDITION, 2, NAMES)])
    assert out == elf and not settings
    assert "not a setting it says it no longer uses" in refused[MS.EDITION]


# ---- the card builder ---------------------------------------------------------------------------
def test_edition_contract_from_written_programs():
    _g, _v, elf = program("star_wars_elg")
    grown, _s, _r = S3M.grow(elf, [(MS.EDITION, 2, NAMES)])
    rel = "star_wars_elg/game"
    ed = M3.edition_contract([("a.raw", rel, "1.10.0", grown), ("b.raw", rel, "1.10.0", grown)])
    assert ed == {"store": "/data/nv/star_wars_elg/NVM", "key": Ed.NVM_KEY, "values": 2}
    assert Ed.NVM_KEY == hashlib.sha1(b"EDITION").hexdigest()
    with pytest.raises(M3.Refused, match="has no EDITION in its menu"):
        M3.edition_contract([("a.raw", rel, "1.10.0", grown), ("b.raw", rel, "1.10.0", elf)])
    three, _s, _r = S3M.grow(elf, [(MS.EDITION, 3, NAMES + ["Light Side"])])
    with pytest.raises(M3.Refused, match="offers 3 editions and the card has 2"):
        M3.edition_contract([("a.raw", rel, "1.10.0", three), ("b.raw", rel, "1.10.0", three)])
    other, _s, _r = S3M.grow(elf, [(MS.EDITION, 2, ["Standard", "Rebel"])])
    with pytest.raises(M3.Refused, match="names the editions"):
        M3.edition_contract([("a.raw", rel, "1.10.0", grown), ("b.raw", rel, "1.10.0", other)])
    with pytest.raises(M3.Refused, match="one game at one version"):
        M3.edition_contract([("a.raw", rel, "1.10.0", grown), ("b.raw", rel, "1.11.0", grown)])
    with pytest.raises(M3.Refused, match="two images or more"):
        M3.edition_contract([("a.raw", rel, "1.10.0", grown)])


def test_images_conf_edition_line_round_trips():
    ed = {"store": "/data/nv/fallout_le/NVM", "key": Ed.NVM_KEY, "values": 3}
    text = "default=0\nimage=img0|A|\nimage=img1|B|\nimage=img2|C|\n"
    got = M3.with_edition(text, ed)
    assert got.endswith("edition=/data/nv/fallout_le/NVM|%s|3\n" % Ed.NVM_KEY)
    assert M3.conf_edition(got) == ed
    assert M3.with_edition(M3.with_edition(got, ed), ed) == got          # never twice
    assert M3.conf_edition(M3.with_edition(got, None)) is None
    assert "edition" not in M3.with_edition(got, None)


def test_the_program_is_found_behind_a_modes_hook():
    assert M3._program_rel("star_wars_elg/game", lambda: "") == "star_wars_elg/game"
    assert M3._program_rel("/games/fallout_le/game", lambda: "") == "fallout_le/game"
    assert M3._program_rel("pad/padmode/padmode.sh", lambda: "/games/star_wars_elg/game\n") == \
        "star_wars_elg/game"


def test_the_tab_passes_editions_on_spike3():
    from pinball_decryptor.webui import multiboot_core as mt
    from pinball_decryptor.webui import spike3_key
    from pinball_decryptor.webui.multiboot_backend import S3
    from pinball_decryptor.webui.multiboot_core import ImageRow, MultibootForm
    assert S3.editions
    old = spike3_key.find_keyfile
    spike3_key.find_keyfile = lambda *a, **k: "C:/k.json"
    try:
        rows = [ImageRow(path="D:/a_spike3.raw", title="A"), ImageRow(path="D:/b_spike3.raw", title="B")]
        on = MultibootForm(images=rows, out="D:/m.raw", platform="s3", editions=True)
        off = MultibootForm(images=rows, out="D:/m.raw", platform="s3")
        assert "--editions" in mt.build_args(on) and "--no-editions" in mt.build_args(off)
        assert "--editions" in mt.inject_args(on, "D:/m.raw")
        assert "--no-editions" in mt.inject_args(off, "D:/m.raw")
        assert mt.menu_summary(on).startswith("no menu: the game's EDITION setting picks")
    finally:
        spike3_key.find_keyfile = old


def test_the_builder_takes_the_flags():
    import argparse
    ap = argparse.ArgumentParser()
    M3._add_conf_flags(ap)
    a = ap.parse_args(["--editions"])
    assert a.editions and not a.no_editions
    assert ap.parse_args(["--no-editions"]).no_editions


def test_the_spike3_family_census_no_longer_leaves_editions_out():
    from pinball_decryptor.plugins.stern import spike3_modes as SM
    assert "editions" not in SM.FAMILY_LEFT_OUT
