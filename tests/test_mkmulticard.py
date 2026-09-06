"""mkmulticard.py - the multi-image Spike 2 card builder (item 90), pure-python parts.

The bytes here were read off the stock 8G turtles_pro 1.59.0 card (the four MBR
entries and both EBR sectors) and the layout numbers off the same card and the
16G / 32G ones; the builder must regenerate them byte-identically before it is
allowed near a real image.  Everything below runs on Windows without WSL, dd or
debugfs: geometries are constructed, synthetic cards are a few MiB of random
bytes in tmp_path, and the ext4 injection (which needs debugfs) is exercised by
the tool's own `selftest` subcommand under WSL instead.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isfile(os.path.join(RIG, "mkmulticard.py")),
                                reason="mkmulticard.py not present")


@pytest.fixture()
def mk():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import mkmulticard
    return mkmulticard


# ---- the stock 8G turtles_pro 1.59.0 card, byte for byte ----------------------------------
STOCK_8G_SIZE = 7861174272                       # 15353856 sectors
STOCK_8G_PRIM = [(1, 0x0C, 8192, 16384), (2, 0x83, 24576, 688128),
                 (3, 0x83, 712704, 13402110), (4, 0x0F, 14114816, 1239038)]
STOCK_8G_EXT = (14114816, 1239038)
STOCK_8G_LOGICAL = [(14114816, 0x83, 14116864, 147454),      # EBR1 -> p5 (data)
                    (14264318, 0x83, 14264320, 1089534)]     # EBR2 -> p6 (dump)
STOCK_8G_MBR_ENTRIES = (
    "000001400c0320bf0020000000400000"     # p1  FAT   CHS 64/0/1..191/3/32  LBA 8192 x16384
    "000001c08303e0ff0060000000800a00"     # p2  Linux LBA 24576 x688128
    "0003e0ff8303e0ff00e00a00fe7fcc00"     # p3  Linux LBA 712704 x13402110
    "0003e0ff0f03e0ff0060d700fee71200")    # p4  ext   LBA 14114816 x1239038
STOCK_8G_EBR1 = ("00" * 0x1BE
                 + "0003e0ff8303e0ff00080000fe3f0200"    # p5: rel 2048 x147454
                 + "0003e0ff0503e0fffe47020000a01000"    # link: rel 149502 (from ext base) x1089536
                 + "00" * 32 + "55aa")
STOCK_8G_EBR2 = ("00" * 0x1BE
                 + "0003e0ff8303e0ff02000000fe9f1000"    # p6: rel 2 x1089534
                 + "00" * 48 + "55aa")
GAMES_8G = 13402110                              # an 8G image's games partition, in sectors


def stock_8g(mk, size=STOCK_8G_SIZE):
    mbr = bytearray(512)
    mbr[:8] = b"\xfa\xb8\x00\x10\x8e\xd0\xbc\x00"      # the first bootstrap bytes, as on the card
    mbr[0x1B8:0x1BC] = bytes.fromhex("8fb04d0c")        # disk id 0c4db08f, little-endian
    mbr[0x1BE:0x1FE] = bytes.fromhex(STOCK_8G_MBR_ENTRIES)
    mbr[510:512] = b"\x55\xaa"
    return mk.Geometry(size, bytes(mbr), STOCK_8G_PRIM, STOCK_8G_EXT, STOCK_8G_LOGICAL,
                       {14114816: bytes.fromhex(STOCK_8G_EBR1), 14264318: bytes.fromhex(STOCK_8G_EBR2)},
                       path="turtles_pro-1_59_0.Release.8G.sdcard.raw")


def extra_8g(mk, name):
    """An extra image only contributes its p3; give it the stock shape anyway."""
    g = stock_8g(mk)
    g.path = name
    return g


# ============================================================================ table bytes
def test_stock_mbr_entries_are_regenerated_byte_identically(mk):
    """The four entries of the stock card, from the geometry alone: the CHS convention
    (4 heads x 32 sectors, capped at 03 e0 ff), the LBAs and the counts."""
    plan = mk.Plan(stock_8g(mk), [])
    assert mk.mbr_entries(plan).hex() == STOCK_8G_MBR_ENTRIES
    sector = mk.mbr_sector(plan)
    assert sector[:0x1BE] == stock_8g(mk).mbr[:0x1BE], "bootstrap + disk id come from the template"
    assert sector[510:] == b"\x55\xaa"


def test_stock_ebr_chain_is_regenerated_byte_identically(mk):
    """Both EBR sectors: the logical's entry relative to its EBR, the 0x05 link relative
    to the extended base, everything else zero, 55aa."""
    plan = mk.Plan(stock_8g(mk), [])
    assert mk.ebr_sector(plan, 0).hex() == STOCK_8G_EBR1
    assert mk.ebr_sector(plan, 1).hex() == STOCK_8G_EBR2


def test_stock_plan_reproduces_the_image_size(mk):
    plan = mk.Plan(stock_8g(mk), [])
    assert plan.total == STOCK_8G_SIZE // 512 == 15353856
    assert plan.table()[:4] == STOCK_8G_PRIM
    assert plan.table()[4:] == [(5, 0x83, 14116864, 147454), (6, 0x83, 14264320, 1089534)]
    assert stock_8g(mk).shape_issues() == []


@pytest.mark.parametrize("lba,expect", [
    (8192, "000140"), (24575, "0320bf"), (24576, "0001c0"), (712703, "03e0ff"), (14114816, "03e0ff"),
])
def test_chs_bytes(mk, lba, expect):
    assert mk.chs(lba).hex() == expect


# ============================================================================ the layout
def test_two_image_plan_puts_p7_at_15353856(mk):
    """stock + one 8G extra: the numbers recorded for the TMNT pair."""
    plan = mk.Plan(stock_8g(mk), [extra_8g(mk, "b.raw")], "a.raw", ["b.raw"])
    p7 = plan.logs[2]
    assert (p7.num, p7.ptype, p7.start, p7.count, p7.ebr) == (7, 0x83, 15353856, GAMES_8G, 15353854)
    assert (p7.src, p7.src_start) == ("b.raw", 712704)
    assert (plan.ext_base, plan.ext_count) == (14114816, 14641150)
    assert plan.total == 28755968
    assert plan.total_bytes == 14_723_055_616
    fits = plan.fits()
    assert fits["8G"] < 0 and fits["16G"] == 771_751_936 and fits["32G"] > 0
    assert plan.devices() == ["/dev/mmcblk0p3", "/dev/mmcblk0p7"]
    assert plan.table()[:3] == STOCK_8G_PRIM[:3]
    assert plan.table()[3] == (4, 0x0F, 14114816, 14641150)
    assert plan.table()[4:] == [(5, 0x83, 14116864, 147454), (6, 0x83, 14264320, 1089534), (7, 0x83, 15353856, GAMES_8G)]


def test_two_image_ebr_chain(mk):
    """EBR1 is unchanged; EBR2 gains the link to EBR3; EBR3 carries p7 and no link."""
    plan = mk.Plan(stock_8g(mk), [extra_8g(mk, "b.raw")])
    assert mk.ebr_sector(plan, 0).hex() == STOCK_8G_EBR1
    ebr2 = mk.ebr_sector(plan, 1)
    assert ebr2[0x1BE:0x1CE].hex() == "0003e0ff8303e0ff02000000fe9f1000"
    link = ebr2[0x1CE:0x1DE]
    assert link[4] == 0x05
    assert int.from_bytes(link[8:12], "little") == 15353854 - 14114816 == 1239038
    assert int.from_bytes(link[12:16], "little") == 28755966 - 15353854 == 13402112
    ebr3 = mk.ebr_sector(plan, 2)
    e1 = ebr3[0x1BE:0x1CE]
    assert e1[4] == 0x83
    assert int.from_bytes(e1[8:12], "little") == 2
    assert int.from_bytes(e1[12:16], "little") == GAMES_8G
    assert ebr3[0x1CE:0x1FE] == bytes(48) and ebr3[510:] == b"\x55\xaa" and ebr3[:0x1BE] == bytes(0x1BE)
    # the MBR's p4 is the grown container: LBA 14114816 x 14641150 (0xdf67fe)
    assert mk.mbr_entries(plan)[48:].hex() == "0003e0ff0f03e0ff0060d700fe67df00"
    assert mk.mbr_entries(plan)[:48].hex() == STOCK_8G_MBR_ENTRIES[:96]


@pytest.mark.parametrize("n_extra,p_last,total_bytes,fit16,fit32", [
    (2, (8, 28755968, 28755966), 21_584_936_960, False, True),
    (3, (9, 42158080, 42158078), 28_446_818_304, False, True),
])
def test_three_and_four_image_plans(mk, n_extra, p_last, total_bytes, fit16, fit32):
    """The arithmetic past p7 still holds - and the plan names p8/p9 as unreachable and refuses:
    the card's kernel (CONFIG_MMC_BLOCK_MINORS=8) allocates minors for p1..p7 only, so a third
    image on /dev/mmcblk0p8 can never be mounted on the machine."""
    plan = mk.Plan(stock_8g(mk), [extra_8g(mk, "x%d.raw" % i) for i in range(n_extra)])
    last = plan.logs[-1]
    assert (last.num, last.start, last.ebr) == p_last
    assert plan.total_bytes == total_bytes
    assert (plan.fits()["16G"] >= 0, plan.fits()["32G"] >= 0) == (fit16, fit32)
    assert len(plan.images) == n_extra + 1
    beyond = list(range(8, 8 + n_extra - 1))
    assert [p.num for p in plan.unreachable()] == beyond
    assert plan.unreachable_note() == "/".join("p%d" % n for n in beyond) + " unreachable on the machine"
    with pytest.raises(mk.Refused, match="p7 is the last partition"):
        mk.check_reachable(plan)
    assert mk.check_reachable(plan, allow=True) is plan


def test_two_images_are_reachable_and_the_printout_says_when_more_are_not(mk, capsys):
    two = mk.Plan(stock_8g(mk), [extra_8g(mk, "b.raw")], "a.raw", ["b.raw"])
    assert two.unreachable() == [] and two.unreachable_note() == ""
    assert mk.check_reachable(two) is two
    mk.print_plan(two)
    assert "unreachable" not in capsys.readouterr().out
    three = mk.Plan(stock_8g(mk), [extra_8g(mk, "b.raw"), extra_8g(mk, "c.raw")], "a.raw", ["b.raw", "c.raw"])
    mk.print_plan(three)
    out = capsys.readouterr().out
    assert "fits Stern 32G" in out
    # the images line, each of the three fits lines, and the warning
    assert out.count("p8 unreachable on the machine") >= 5
    assert "CONFIG_MMC_BLOCK_MINORS=8" in out


def test_plan_and_build_refuse_a_third_image_unless_told(mk, tmp_path, capsys):
    A = mk.make_synthetic_card(str(tmp_path / "A.img"), "A", 0x0A0A0A0A)
    B = mk.make_synthetic_card(str(tmp_path / "B.img"), "B", 0x0B0B0B0B)
    C = mk.make_synthetic_card(str(tmp_path / "C.img"), "C", 0x0C0C0C0C)
    assert mk.main(["plan", "--primary", A, "--extra", B]) == 0
    out = capsys.readouterr().out
    assert "unreachable" not in out and "layout: parts" in out, "auto = parts for one extra"
    assert mk.main(["plan", "--primary", A, "--extra", B, "--extra", C, "--layout", "parts"]) == 2
    err = capsys.readouterr().err
    assert "/dev/mmcblk0p8" in err and "CONFIG_MMC_BLOCK_MINORS=8" in err and "--allow-unreachable" in err
    assert mk.main(["plan", "--primary", A, "--extra", B, "--extra", C, "--layout", "parts", "--allow-unreachable"]) == 0
    assert "p8 unreachable on the machine" in capsys.readouterr().out
    # build refuses BEFORE a byte is written
    out = tmp_path / "multi.img"
    assert mk.main(["build", "--primary", A, "--extra", B, "--extra", C, "--out", str(out), "--no-inject", "--layout", "parts"]) == 2
    assert "p7 is the last partition" in capsys.readouterr().err
    assert not out.exists()
    # two extras with no --layout = the multi layout, which sizes p7 from the extras' superblocks -
    # random bytes have none, and that is refused before a byte is written too
    assert mk.main(["build", "--primary", A, "--extra", B, "--extra", C, "--out", str(out), "--no-inject"]) == 2
    assert "no ext4 superblock" in capsys.readouterr().err
    assert not out.exists()


def test_plan_refuses_a_primary_without_a_logical_chain(mk):
    g = stock_8g(mk)
    g.logical = []
    with pytest.raises(mk.Refused):
        mk.Plan(g, [])


# ============================================================================ the hook
# Stern's lines 322-330 (game:326 is 'pkill boot_display ' WITH a trailing space - built by
# concatenation so no editor can strip it off a physical line end).
STOCK_TAIL = ("#================================\n"
              "# try to launch an application at $GAMES_PATH/game.  this will be a link to the game so\n"
              "# that this script doesn't need to change.  redirect stderr messages to log file.\n"
              "\n"
              "pkill boot_display" + " \n"
              "\n"
              "if [ -f $GAMES_PATH/game ]; then\n"
              "\techo \"starting conagent...\"\n"
              "\t/etc/init.d/conagent_monitor $GAMES_PATH/conagent < $CONSOLE_INPUT > $CONSOLE_LOG 2>&1 &\n")


def test_hook_lands_between_pkill_and_the_if(mk):
    hooked = mk.hook_game_script(STOCK_TAIL)
    orig = STOCK_TAIL.split("\n")
    new = hooked.split("\n")
    i = orig.index("pkill boot_display ")
    assert new[:i + 1] == orig[:i + 1], "nothing before the anchor changes"
    assert new[i + 1:i + 1 + len(mk.HOOK_LINES)] == mk.HOOK_LINES
    assert new[i + 1 + len(mk.HOOK_LINES):] == orig[i + 1:], "nothing after it changes"
    assert new[i + 1 + len(mk.HOOK_LINES) + 1] == "if [ -f $GAMES_PATH/game ]; then"
    assert mk.HOOK_LINES == [
        "",
        "# codeselect: boot-time code selector (item 90) - runs the menu and remounts /games",
        "if [ -x /usr/local/codeselect/select.sh ]; then",
        "\t/usr/local/codeselect/select.sh",
        "fi",
    ]
    assert mk.has_hook(hooked) and not mk.has_hook(STOCK_TAIL)


def test_hook_is_idempotent_and_reversible(mk):
    once = mk.hook_game_script(STOCK_TAIL)
    assert mk.hook_game_script(once) == once
    assert mk.strip_hook(once) == STOCK_TAIL
    assert mk.strip_hook(STOCK_TAIL) == STOCK_TAIL
    assert mk.hook_game_script(STOCK_TAIL.encode()) == once, "bytes in, text out"


@pytest.mark.parametrize("mutate,why", [
    (lambda s: s.replace("pkill boot_display \n", "pkill boot_display\n"), "no trailing space"),
    (lambda s: s.replace("pkill boot_display \n", "pkill boot_display \npkill boot_display \n"), "two anchors"),
    (lambda s: s.replace("if [ -f $GAMES_PATH/game ]; then", "if [ -f /games/game ]; then"), "if line missing"),
    (lambda s: s.replace("pkill boot_display \n\n", "pkill boot_display \n\nsleep 1\n"), "something in between"),
    (lambda s: s.replace("pkill boot_display \n\nif", "if"), "if before pkill's gap"),
])
def test_hook_refuses_an_unexpected_script(mk, mutate, why):
    with pytest.raises(mk.Refused):
        mk.hook_game_script(mutate(STOCK_TAIL))


# ============================================================================ images.conf
def test_images_conf_round_trips(mk):
    text = mk.render_images_conf(["/dev/mmcblk0p3", "/dev/mmcblk0p7"], ["STERN 1.59.0", "TMNT 1987"],
                                 ["Original Stern code", "1987 cartoon upscale (1.59.0)"], 0, 15,
                                 "/usr/local/codeselect/font.ttf")
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    assert lines == ["image=/dev/mmcblk0p3|STERN 1.59.0|Original Stern code",
                     "image=/dev/mmcblk0p7|TMNT 1987|1987 cartoon upscale (1.59.0)",
                     "default=0", "timeout=15", "font=/usr/local/codeselect/font.ttf"]
    conf = mk.parse_images_conf(text)
    assert conf["images"] == [("/dev/mmcblk0p3", "STERN 1.59.0", "Original Stern code"),
                              ("/dev/mmcblk0p7", "TMNT 1987", "1987 cartoon upscale (1.59.0)")]
    assert (conf["default"], conf["timeout"], conf["font"]) == (0, 15, "/usr/local/codeselect/font.ttf")


def test_images_conf_defaults_and_refusals(mk):
    text = mk.render_images_conf(["/dev/mmcblk0p3", "/dev/mmcblk0p7", "/dev/mmcblk0p8"], ["only one"])
    conf = mk.parse_images_conf(text)
    assert [t for (_d, t, _s) in conf["images"]] == ["only one", "image 1", "image 2"]
    assert all(s == "" for (_d, _t, s) in conf["images"])
    assert conf["font"] is None and conf["timeout"] == 15
    with pytest.raises(mk.Refused):
        mk.render_images_conf(["/dev/mmcblk0p3"], ["a|b"])
    with pytest.raises(mk.Refused):
        mk.render_images_conf(["/dev/mmcblk0p3"], default=1)
    with pytest.raises(mk.Refused):
        mk.render_images_conf(["/dev/mmcblk0p3"], ["a", "b"])
    with pytest.raises(mk.Refused):
        mk.render_images_conf(["/dev/mmcblk0p3"], timeout=-1)


def test_the_card_log_is_a_development_switch_the_app_never_sets(mk):
    """The selector's log on the card (/dump/log/codeselect.log) exists only on a card built or
    injected with --debug-log: the plain render carries no log= line (the hook then passes no
    --log and the menu writes nothing to /dump, boot after boot), the flag writes exactly one,
    parse hands it back as debug_log, and conf_for_plan never carries a card's old log= through
    - so the app's inject, which never passes the flag, turns a development card's log off."""
    import argparse
    devs = ["/dev/mmcblk0p3", "/dev/mmcblk0p7"]
    plain = mk.render_images_conf(devs, ["A", "B"])
    assert not [l for l in plain.splitlines() if l.startswith("log")]
    assert mk.parse_images_conf(plain)["debug_log"] is None
    debug = mk.render_images_conf(devs, ["A", "B"], debug_log=True)
    assert [l for l in debug.splitlines() if l.startswith("log")] == ["log=" + mk.CARD_LOG]
    assert mk.CARD_LOG == "/dump/log/codeselect.log"
    assert mk.parse_images_conf(debug)["debug_log"] == mk.CARD_LOG
    # the flag is on build's and inject's shared conf flags, off by default
    ap = argparse.ArgumentParser()
    mk._add_conf_flags(ap)
    assert ap.parse_args([]).debug_log is False
    assert ap.parse_args(["--debug-log"]).debug_log is True
    # an inject without the flag over a card that has the line: the line goes
    plan = _two_image_plan(mk)
    on_card = mk.parse_images_conf(mk.render_images_conf(plan.devices(), ["A", "B"], debug_log=True))
    assert on_card["debug_log"] == mk.CARD_LOG
    args = argparse.Namespace(titles="A;B", subtitles="", timeout=9, default=0, debug_log=False)
    text = mk.conf_for_plan(plan, args, existing=on_card)
    assert not [l for l in text.splitlines() if l.startswith("log")]
    assert mk.parse_images_conf(text)["debug_log"] is None
    # ...and with it, the line comes back
    args.debug_log = True
    text = mk.conf_for_plan(plan, args, existing=on_card)
    assert mk.parse_images_conf(text)["debug_log"] == mk.CARD_LOG


# ---- images.conf v2 (item 90 media): the image lines + the global keys -------------------
def test_images_conf_v2_round_trips_media_and_the_keys(mk):
    text = mk.render_images_conf(["/dev/mmcblk0p3", "/dev/mmcblk0p7:img1", "p7:img2"], ["A", "B", "C"], ["a", "", "c"], 1, 0, None,
                                 media=[("art0.png", "", ""), ("art1.png", "anim1.gif", "music1.wav"), None],
                                 sound_move="move.wav", sound_confirm="confirm.wav", volume=35, mixer_volume=20)
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    assert lines == ["image=/dev/mmcblk0p3|A|a|art0.png||",
                     "image=/dev/mmcblk0p7:img1|B||art1.png|anim1.gif|music1.wav",
                     "image=p7:img2|C|c|||",
                     "default=1", "timeout=0", "sound_move=move.wav", "sound_confirm=confirm.wav",
                     "volume=35", "mixer_volume=20", "media=/usr/local/codeselect/media"]
    conf = mk.parse_images_conf(text)
    assert conf["images"] == [("/dev/mmcblk0p3", "A", "a"), ("/dev/mmcblk0p7:img1", "B", ""), ("p7:img2", "C", "c")]
    assert conf["media"] == [("art0.png", "", "", ""),
                             ("art1.png", "anim1.gif", "music1.wav", ""), ("", "", "", "")]
    assert (conf["sound_move"], conf["sound_confirm"], conf["volume"], conf["mixer_volume"]) == ("move.wav", "confirm.wav", 35, 20)
    assert conf["media_dir"] == mk.MEDIA_DIR and conf["default"] == 1 and conf["timeout"] == 0
    assert mk.conf_media_names(conf) == ["anim1.gif", "art0.png", "art1.png", "confirm.wav", "move.wav", "music1.wav"]
    assert [mk.parse_device(d) for (d, _t, _s) in conf["images"]] == [(3, None), (7, "img1"), (7, "img2")]


def test_a_three_field_image_line_stays_valid_and_unknown_keys_are_ignored(mk):
    conf = mk.parse_images_conf("image=/dev/mmcblk0p3|STERN|stock\nimage=/dev/mmcblk0p7|TMNT 1987\n"
                                "default=1\ntimeout=15\nanim_fps=12\nfont=/x.ttf\n")
    assert conf["images"] == [("/dev/mmcblk0p3", "STERN", "stock"), ("/dev/mmcblk0p7", "TMNT 1987", "")]
    assert conf["media"] == [("", "", "", ""), ("", "", "", "")]
    assert conf["sound_move"] is None and conf["volume"] is None and conf["media_dir"] is None
    assert mk.conf_media_names(conf) == []
    # no media anywhere -> the 3-field form is what gets written, and no media= key
    text = mk.render_images_conf(["/dev/mmcblk0p3", "/dev/mmcblk0p7"], ["A", "B"], media=[None, ("", "", "")])
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    assert lines == ["image=/dev/mmcblk0p3|A|", "image=/dev/mmcblk0p7|B|", "default=0", "timeout=15"]


def test_an_image_can_name_its_own_confirm_sound(mk):
    """The seventh field: the sound that plays when THAT image is chosen.  It is written only
    when some image has one - a menu where every image uses the menu-wide sound is byte for byte
    the file this tool wrote before the field existed - and an image without one leaves it
    empty, which is how the selector is told to fall back."""
    text = mk.render_images_conf(
        ["/dev/mmcblk0p3", "/dev/mmcblk0p7"], ["A", "B"], ["a", "b"],
        media=[("art0.png", "", "", ""), ("art1.png", "", "", "confirm1.wav")],
        sound_confirm="confirm.wav")
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    assert lines[:2] == ["image=/dev/mmcblk0p3|A|a|art0.png|||",
                         "image=/dev/mmcblk0p7|B|b|art1.png|||confirm1.wav"]
    conf = mk.parse_images_conf(text)
    assert conf["media"] == [("art0.png", "", "", ""), ("art1.png", "", "", "confirm1.wav")]
    # the per-image sound is staged like any other media name, so it is in the set to copy
    assert mk.conf_media_names(conf) == ["art0.png", "art1.png", "confirm.wav", "confirm1.wav"]


def test_a_media_row_from_before_the_confirm_field_is_still_accepted(mk):
    """Three-tuples are what every caller wrote until this field existed; they are widened, not
    refused, and they still produce the 6-field line."""
    text = mk.render_images_conf(["/dev/mmcblk0p3"], ["A"], media=[("art0.png", "", "")])
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    assert lines[0] == "image=/dev/mmcblk0p3|A||art0.png||"
    assert mk.parse_images_conf(text)["media"] == [("art0.png", "", "", "")]


@pytest.mark.parametrize("bad", [
    "image=/dev/mmcblk0p3|A|a|art.png|anim.gif|music.wav|c.wav|extra\n",     # 8 fields
    "image=/dev/mmcblk0p3|A|a|art|anim.gif|../x.wav\n",                        # a slash in a media name
    "image=/dev/mmcblk0p3|A|a|art:png||\n",                                    # a colon in a media name
    "image=/dev/mmcblk0p7:img1:x|A|a\n",                                       # two colons in the device
    "image=/dev/mmcblk0p7:|A|a\n",                                             # an empty subdirectory
    "image=/dev/sda7|A|a\n",                                                   # not a Spike device
    "image=/dev/mmcblk0p3|A|a\nvolume=101\n",
    "image=/dev/mmcblk0p3|A|a\nmixer_volume=64\n",
    "image=/dev/mmcblk0p3|A|a\nsound_move=a|b.wav\n",
    "".join("image=/dev/mmcblk0p%d|x|y\n" % i for i in range(17)),            # 17 images
])
def test_parse_refuses_pipe_and_colon_misuse(mk, bad):
    with pytest.raises(mk.Refused):
        mk.parse_images_conf(bad)


def test_render_refuses_bad_media_and_devices(mk):
    with pytest.raises(mk.Refused, match="plain media file name"):
        mk.render_images_conf(["/dev/mmcblk0p3"], media=[("a|b.png", "", "")])
    with pytest.raises(mk.Refused, match="plain media file name"):
        mk.render_images_conf(["/dev/mmcblk0p3"], sound_move="dir/x.wav")
    with pytest.raises(mk.Refused, match="not /dev/mmcblk0pN"):
        mk.render_images_conf(["/dev/mmcblk0p7:img1:x"])
    with pytest.raises(mk.Refused, match="outside 0..100"):
        mk.render_images_conf(["/dev/mmcblk0p3"], volume=101)
    with pytest.raises(mk.Refused, match="at most 16"):
        mk.render_images_conf(["/dev/mmcblk0p%d" % i for i in range(17)])
    with pytest.raises(mk.Refused, match="media rows"):
        mk.render_images_conf(["/dev/mmcblk0p3"], media=[None, None])


# ---- the media checks (pure python, synthetic files) ----------------------------------------
def test_media_checks_accept_the_synthetic_set_and_refuse_the_wrong_shapes(mk, tmp_path, monkeypatch):
    d = str(tmp_path / "media")
    mk.synth_media_dir(d, 2)
    ms = mk.plan_media(d, 2)
    assert list(ms["files"]) == ["art0.png", "art1.png", "anim1.gif", "music1.wav", "confirm1.wav",
                                "move.wav", "confirm.wav"]
    assert ms["rows"] == [("art0.png", "", "", ""),
                          ("art1.png", "anim1.gif", "music1.wav", "confirm1.wav")]
    assert (ms["sound_move"], ms["sound_confirm"], ms["volume"], ms["mixer_volume"]) == ("move.wav", "confirm.wav", 40, None)
    assert ms["kinds"]["anim1.gif"] == "gif 4x3 2 frames" and ms["kinds"]["move.wav"] == "wav 44100 Hz 1 ch"
    assert ms["kinds"]["art0.png"] == "png 4x3"
    assert "wrong_rate.wav" not in ms["files"], "only referenced files are staged"
    # the wrong shapes, one at a time
    with pytest.raises(mk.Refused, match="48000 Hz"):
        mk.check_media_file(os.path.join(d, "wrong_rate.wav"), "wav")
    with pytest.raises(mk.Refused, match="must be a PNG"):
        mk.check_media_file(os.path.join(d, "move.wav"), "art")
    with pytest.raises(mk.Refused, match="must be an animated GIF"):
        mk.check_media_file(os.path.join(d, "art0.png"), "anim")
    with pytest.raises(mk.Refused, match="does not exist"):
        mk.check_media_file(os.path.join(d, "nope.png"), "art")
    big = tmp_path / "media" / "big.png"
    mk.synth_png(str(big), 1361, 8)
    with pytest.raises(mk.Refused, match="larger than the 1360x768 panel"):
        mk.check_media_file(str(big), "art")
    wide = tmp_path / "media" / "wide.gif"
    mk.synth_gif(str(wide), 513, 2, 1)
    with pytest.raises(mk.Refused, match="over 512x288"):
        mk.check_media_file(str(wide), "anim")
    many = tmp_path / "media" / "many.gif"
    mk.synth_gif(str(many), 2, 2, mk.GIF_MAX_FRAMES + 1)
    with pytest.raises(mk.Refused, match="%d frames" % (mk.GIF_MAX_FRAMES + 1)):
        mk.check_media_file(str(many), "anim")
    monkeypatch.setattr(mk, "MEDIA_BUDGET", 100)
    with pytest.raises(mk.Refused, match="over the 100 byte budget"):
        mk.plan_media(d, 2)
    monkeypatch.setattr(mk, "GIF_MAX_BYTES", 10)
    with pytest.raises(mk.Refused, match="over the 10 byte cap"):
        mk.check_media_file(os.path.join(d, "anim1.gif"), "anim")


def test_media_manifest_refusals(mk, tmp_path):
    d = str(tmp_path / "m")
    with pytest.raises(mk.Refused, match="not a directory"):
        mk.plan_media(d, 1)
    os.makedirs(d)
    with pytest.raises(mk.Refused, match="media.json"):
        mk.plan_media(d, 1)
    man = tmp_path / "m" / "media.json"
    man.write_text("{not json")
    with pytest.raises(mk.Refused, match="not JSON"):
        mk.plan_media(d, 1)
    man.write_text('{"images": [{"art": "a.png"}]}')
    with pytest.raises(mk.Refused, match="does not exist"):
        mk.plan_media(d, 1)
    man.write_text('{"images": [{"art": "a.png"}, {}]}')
    with pytest.raises(mk.Refused, match="lists 2 images; the card holds 1"):
        mk.plan_media(d, 1)
    man.write_text('{"images": [{"art": ["a.png"]}]}')
    with pytest.raises(mk.Refused, match="file name or null"):
        mk.plan_media(d, 1)
    man.write_text('{"images": [{}], "volume": 200}')
    with pytest.raises(mk.Refused, match="outside 0..100"):
        mk.plan_media(d, 1)
    man.write_text('{"images": [{}], "sound_move": "a b.wav"}')
    with pytest.raises(mk.Refused, match="plain media file name"):
        mk.plan_media(d, 1)


def test_wav_png_gif_sniffers(mk, tmp_path):
    assert mk.png_info(b"GIF89a") is None and mk.gif_info(b"\x89PNG") is None and mk.wav_info(b"RIFX") is None
    p = str(tmp_path / "x.png")
    mk.synth_png(p, 7, 5)
    assert mk.png_info(open(p, "rb").read()) == (7, 5)
    g = str(tmp_path / "x.gif")
    mk.synth_gif(g, 6, 2, 3)
    assert mk.gif_info(open(g, "rb").read()) == (6, 2, 3)
    w = str(tmp_path / "x.wav")
    mk.synth_wav(w, rate=22050, ch=1)
    assert mk.wav_info(open(w, "rb").read()) == (1, 1, 22050, 16)
    # a Logic-style export: JUNK before fmt
    data = open(w, "rb").read()
    junk = b"JUNK" + (28).to_bytes(4, "little") + bytes(28)
    logic = data[:12] + junk + data[12:]
    assert mk.wav_info(logic) == (1, 1, 22050, 16)


def test_inject_commands_replace_an_existing_media_directory(mk):
    """debugfs's rm cannot take a directory: the children go first, then rmdir, then a fresh
    mkdir + 040755 root:root when media is staged; an untouched media dir stays."""
    items = [("/s/codeselect", "/usr/local/codeselect/codeselect", 0o755),
             ("/s/media/art0.png", "/usr/local/codeselect/media/art0.png", 0o644),
             ("/s/game", "/etc/init.d/game", 0o755)]
    cmds = mk.inject_commands(items, ["codeselect", "images.conf"], {}, existing_media=["old.png", "old.wav"])
    assert cmds[:6] == ['rm "/usr/local/codeselect/codeselect"', 'rm "/usr/local/codeselect/images.conf"',
                        'rm "/usr/local/codeselect/media/old.png"', 'rm "/usr/local/codeselect/media/old.wav"',
                        'rmdir "/usr/local/codeselect/media"', 'rm "/etc/init.d/game"']
    assert cmds[6] == 'mkdir "/usr/local/codeselect/media"'
    assert cmds.index('mkdir "/usr/local/codeselect/media"') < cmds.index('write "/s/media/art0.png" "/usr/local/codeselect/media/art0.png"')
    assert 'set_inode_field "/usr/local/codeselect/media" mode 040755' in cmds
    assert 'set_inode_field "/usr/local/codeselect/media" uid 0' in cmds
    assert 'set_inode_field "/usr/local/codeselect/media/art0.png" mode 0100644' in cmds
    # no media staged and none to replace: exactly the old script shape
    plain = [items[0], items[2]]
    cmds = mk.inject_commands(plain, ["codeselect"], {})
    assert cmds[:2] == ['rm "/usr/local/codeselect/codeselect"', 'rm "/etc/init.d/game"']
    assert not [c for c in cmds if "media" in c]
    # media staged into a card with no media dir yet
    cmds = mk.inject_commands(items, None, {})
    assert cmds[:3] == ['mkdir "/usr/local/codeselect"', 'rm "/etc/init.d/game"', 'mkdir "/usr/local/codeselect/media"']


# ---- the multi layout (pure python parts) --------------------------------------------------
def _fake_ext4(path, blocks, free, log_bs=2, sixty_four=False, offset=0):
    """Just enough superblock for ext_used_bytes: magic, counts, block size."""
    sb = bytearray(1024)
    sb[0x38:0x3A] = (0xEF53).to_bytes(2, "little")
    sb[0x4:0x8] = (blocks & 0xffffffff).to_bytes(4, "little")
    sb[0xC:0x10] = (free & 0xffffffff).to_bytes(4, "little")
    sb[0x18:0x1C] = log_bs.to_bytes(4, "little")
    if sixty_four:
        sb[0x60:0x64] = (0x80).to_bytes(4, "little")
        sb[0x150:0x154] = (blocks >> 32).to_bytes(4, "little")
        sb[0x158:0x15C] = (free >> 32).to_bytes(4, "little")
    with open(path, "r+b" if os.path.exists(path) else "wb") as f:
        f.seek(offset + 1024)
        f.write(sb)


def test_multi_size_is_used_bytes_plus_slack_and_headroom_rounded_to_a_mib(mk, tmp_path):
    p = str(tmp_path / "x.img")
    _fake_ext4(p, 1675263, 760265)                     # the stock 8G p3: 4 KiB blocks
    used, total = mk.ext_used_bytes(p, 0)
    assert (used, total) == ((1675263 - 760265) * 4096, 1675263 * 4096)
    sectors = mk.multi_size_sectors(used)
    size = sectors * 512
    assert size % (1 << 20) == 0
    assert size >= used * 1.10 + (256 << 20) and size < used * 1.10 + (257 << 20)
    q = str(tmp_path / "y.img")
    _fake_ext4(q, (1 << 32) + 10, 5, sixty_four=True)
    assert mk.ext_used_bytes(q, 0)[1] == ((1 << 32) + 10) * 4096
    with pytest.raises(mk.Refused, match="no ext4 superblock"):
        mk.ext_used_bytes(str(tmp_path / "A.img"), 0) if (tmp_path / "A.img").exists() else mk.ext_used_bytes(q, 4096)


def test_multi_plan_puts_every_extra_inside_one_p7(mk, tmp_path):
    """Three extras: one logical p7 sized from their superblocks, devices p7:img1..img3, never
    p8, nothing unreachable; the table is p1..p7."""
    extras = []
    for i in range(3):
        p = str(tmp_path / ("x%d.raw" % i))
        with open(p, "wb") as f:
            f.truncate(STOCK_8G_SIZE)
        _fake_ext4(p, 1675263, 760265, offset=712704 * 512)
        extras.append(p)
    plan = mk.Plan(stock_8g(mk), [extra_8g(mk, x) for x in extras], "a.raw", extras, "multi")
    assert plan.layout == "multi" and plan.multi_subdirs == ["img1", "img2", "img3"]
    assert plan.devices() == ["/dev/mmcblk0p3", "/dev/mmcblk0p7:img1", "/dev/mmcblk0p7:img2", "/dev/mmcblk0p7:img3"]
    assert [p.num for p in plan.logs] == [5, 6, 7] and plan.unreachable() == [] and mk.check_reachable(plan) is plan
    p7 = plan.multi_part
    assert (p7.num, p7.ptype, p7.start, p7.ebr, p7.src, p7.src_start) == (7, 0x83, 15353856, 15353854, None, 0)
    used = 3 * (1675263 - 760265) * 4096
    assert plan.multi_used == used and p7.count == mk.multi_size_sectors(used)
    assert plan.table()[-1] == (7, 0x83, 15353856, p7.count)
    assert plan.total == 15353856 + p7.count + 2
    assert [(p.num, s) for (p, s) in plan.trees] == [(3, None), (7, "img1"), (7, "img2"), (7, "img3")]
    assert plan.images == [plan.prims[2], p7]
    # the same plan with the built p7 image as its source
    with_src = plan.with_multi_src("/tmp/p7.img")
    assert with_src.multi_part.src == "/tmp/p7.img" and with_src.table() == plan.table() and with_src.multi_used == used
    # and a card-derived plan (size + subdirs given) needs no extras
    back = mk.Plan(stock_8g(mk), [], "card.raw", [], "multi", multi_sectors=p7.count, multi_subdirs=["img1", "img2", "img3"])
    assert back.table() == plan.table() and back.devices() == plan.devices() and back.multi_used is None
    assert mk.resolve_layout("auto", 1) == "parts" and mk.resolve_layout("auto", 2) == "multi"
    with pytest.raises(mk.Refused):
        mk.resolve_layout("bogus", 1)
    with pytest.raises(mk.Refused, match="not 'parts', 'multi' or 'store'"):
        mk.Plan(stock_8g(mk), [], layout="auto")


def test_print_plan_describes_the_multi_partition(mk, tmp_path, capsys):
    p = str(tmp_path / "x.raw")
    with open(p, "wb") as f:
        f.truncate(STOCK_8G_SIZE)
    _fake_ext4(p, 1675263, 760265, offset=712704 * 512)
    plan = mk.Plan(stock_8g(mk), [extra_8g(mk, p), extra_8g(mk, p)], "a.raw", [p, p], "multi")
    mk.print_plan(plan)
    out = capsys.readouterr().out
    assert "layout: multi" in out and "multi ext4: img1=x.raw, img2=x.raw" in out
    assert "p7 (multi layout): 2 trees img1/img2" in out and "+ 10% + 256 MiB" in out
    assert "images: 0=/dev/mmcblk0p3, 1=/dev/mmcblk0p7:img1, 2=/dev/mmcblk0p7:img2" in out
    assert "unreachable" not in out


def test_device_names_and_titles(mk):
    assert mk.device_name(7, "img2") == "/dev/mmcblk0p7:img2" and mk.device_name(3) == "/dev/mmcblk0p3"
    assert mk.parse_device("p7:img2") == (7, "img2") and mk.parse_device("/dev/mmcblk0p3") == (3, None)
    for bad in ("p7:", "p7:a:b", "/dev/mmcblk0p", "mmcblk0p3", "p7:img 2", ""):
        with pytest.raises(mk.Refused):
            mk.parse_device(bad)


def test_bypass_words_and_states(mk):
    assert mk.bypass_words("bypassed") == "validator: bypassed"
    assert mk.bypass_words("absent") == "validator: none on this build"
    assert "ARMED" in mk.bypass_words("armed") and "UNLOCATED" in mk.bypass_words("unlocated")
    assert mk.bypass_state(b"not an elf at all") == "absent"


#: The stock turtles_pro 1.59.0 image, wherever this machine keeps it: the repo's images/
#: junction (absent in a worktree), David's library on D:, or the same through WSL.
_STOCK_NAME = os.path.join("Stern", "spike2", "turtles_pro-1_59_0.Release.8G.sdcard.raw")
STOCK_CARD = next((p for p in (
    os.path.join(os.path.dirname(RIG.rstrip(os.sep)), "..", "images", _STOCK_NAME),
    os.path.join("D:\\Pinball\\images", _STOCK_NAME),
    os.path.join("/mnt/d/Pinball/images", _STOCK_NAME)) if os.path.isfile(p)), "")


@pytest.mark.skipif(not os.path.isfile(STOCK_CARD), reason="the stock turtles_pro 1.59 card is not on this machine")
def test_the_stock_card_validator_is_located_and_reported_armed(mk):
    """Read-only, one 6.4 MB file out of the library image: the locator finds validation_exec
    in the stock game and the tree reads as ARMED (the bypass has something to do)."""
    valpatch, _s, ext4, _adj = mk._stern_plugins()
    G = mk.Geometry.from_file(STOCK_CARD)
    _t, st, cnt = G.part(3)
    with open(STOCK_CARD, "rb") as f:
        r = ext4.Ext4Reader(f, st * 512, cnt * 512)
        title, gpath, _gi, gnode = mk.tree_game(r, 2)
        assert (title, gpath) == ("turtles_pro", "turtles_pro/game")
        elf = r.read_file_bytes(gnode)
        assert valpatch.find_validation_exec(elf) is not None
        assert mk.bypass_state(elf) == "armed"
        assert mk.tree_sidx(r, 2)[0] == "spk/index/turtles_pro-1_59_0.sidx"
        state, writes, notes, digests = mk.compute_bypass_writes(r, 2)
        # bx lr on the tick + mov r0,#0 on the grade restore (item 98) + the two .sidx digests
        assert state == "armed" and sum(len(b) for (_d, b) in writes) == 4 + 4 + 20 + 16, notes
        assert all(st * 512 <= d < (st + cnt) * 512 for (d, _b) in writes), "every write lands inside p3"
        # the digests the record will hold are the bytes those raw writes LEAVE on the card:
        # reconstruct both files through the same extents the writes were mapped through
        assert digests["game_path"] == gpath and digests["sidx_path"] == "spk/index/turtles_pro-1_59_0.sidx"
        _s2, snode = mk.tree_sidx(r, 2)
        assert digests["game"] == hashlib.sha256(_after_disk_writes(r, gnode, writes)).hexdigest()
        assert digests["sidx"] == hashlib.sha256(_after_disk_writes(r, snode, writes)).hexdigest()
        assert digests["game"] != hashlib.sha256(elf).hexdigest(), "the record must not hold the source's game"
    assert mk.tree_state(STOCK_CARD, G and mk.Part(3, 0x83, st, cnt, STOCK_CARD, st, None), None)[0] == "armed"


def _after_disk_writes(reader, node, writes):
    """A file's bytes with every raw (disk offset, bytes) write that lands inside it applied -
    what the card holds once bypass_card has written them.  The extent map is the reader's own,
    so this is an independent path to the digests compute_bypass_writes reports."""
    data = bytearray(reader.read_file_bytes(node))
    spans, off = [], 0
    for disk, n in reader.disk_ranges(node, 0, len(data)):
        spans.append((disk, disk + n, off))
        off += n
    for d, b in writes:
        for ds, de, fo in spans:
            if ds <= d < de:
                assert d + len(b) <= de, "a write straddles two extents"
                data[fo + (d - ds):fo + (d - ds) + len(b)] = b
                break
    return bytes(data)


def test_default_title_strips_the_card_suffixes(mk):
    assert mk.default_title("/x/turtles_pro-1_59_0.Release.8G.sdcard.raw") == "turtles_pro-1_59_0.Release"
    assert mk.default_title("turtles_pro-1_59_0.1987-upscaled.8G.sdcard.raw") == "turtles_pro-1_59_0.1987-upscaled"
    assert mk.default_title("multi.img") == "multi"
    assert mk.split_list("STERN 1.59.0; TMNT 1987") == ["STERN 1.59.0", "TMNT 1987"]
    assert mk.split_list(None) == []


# ============================================================================ output safety
def test_output_path_refusals(mk, tmp_path):
    src = tmp_path / "a.raw"
    src.write_bytes(b"x")
    out = tmp_path / "out.img"
    assert mk.check_output_path(str(out), [str(src)]) == str(out)
    for bad in ("/mnt/d/Pinball/images/Stern/spike2/x.raw", "/mnt/d/Pinball/images", "/MNT/D/PINBALL/IMAGES/x.raw",
                r"D:\Pinball\images\Stern\x.raw", "D:/Pinball/images/x.raw"):
        with pytest.raises(mk.Refused, match="card library"):
            mk.check_output_path(bad, [])
    assert mk.check_output_path("/mnt/d/Pinball/imagesX/x.raw", []) == "/mnt/d/Pinball/imagesX/x.raw"
    with pytest.raises(mk.Refused, match="also an input"):
        mk.check_output_path(str(src), [str(src)])
    with pytest.raises(mk.Refused, match="also an input"):
        mk.check_output_path(str(tmp_path / "." / "a.raw"), [str(src)])
    with pytest.raises(mk.Refused, match="also an input"):
        mk.check_output_path(str(src), [str(src)], force=True)
    out.write_bytes(b"old")
    with pytest.raises(mk.Refused, match="--force"):
        mk.check_output_path(str(out), [str(src)])
    assert mk.check_output_path(str(out), [str(src)], force=True) == str(out)
    with pytest.raises(mk.Refused, match="directory"):
        mk.check_output_path(str(tmp_path), [])
    with pytest.raises(mk.Refused, match="does not exist"):
        mk.check_output_path(str(tmp_path / "missing.img"), [], must_exist=True)
    assert mk.check_output_path(str(out), [], must_exist=True) == str(out)
    with pytest.raises(mk.Refused):
        mk.check_output_path("", [])


def test_the_library_refusal_follows_symlinks_and_junctions(mk, tmp_path, monkeypatch):
    """The repo's own images/ is a link into D:\\Pinball\\images - the card library - so a
    prefix test on the SPELLED path let `images/x.raw` straight through.  Links are resolved
    (an output that does not exist yet through its parent)."""
    lib = tmp_path / "Pinball" / "images"
    lib.mkdir(parents=True)
    link = tmp_path / "repo" / "images"
    link.parent.mkdir()
    try:
        os.symlink(str(lib), str(link), target_is_directory=True)
    except (OSError, NotImplementedError) as e:
        pytest.skip("cannot create a symlink here: %s" % e)
    monkeypatch.setattr(mk, "FORBIDDEN_OUTPUT_PREFIXES", (str(lib),))
    with pytest.raises(mk.Refused, match="card library"):
        mk.check_output_path(str(link / "x.raw"), [])                   # not there yet: the parent resolves
    (lib / "y.raw").write_bytes(b"y")
    with pytest.raises(mk.Refused, match="card library"):
        mk.check_output_path(str(link / "y.raw"), [], force=True)       # exists: resolved itself
    with pytest.raises(mk.Refused, match="card library"):
        mk.check_output_path(str(link / "deeper" / "z.raw"), [])        # a new directory under the link
    # ...and a linked INPUT names the same file as its target (outside the library, where
    # the library rule would fire first)
    real = tmp_path / "real"
    real.mkdir()
    (real / "y.raw").write_bytes(b"y")
    alias = tmp_path / "alias"
    os.symlink(str(real), str(alias), target_is_directory=True)
    with pytest.raises(mk.Refused, match="also an input"):
        mk.check_output_path(str(alias / "y.raw"), [str(real / "y.raw")], force=True)
    assert mk.check_output_path(str(alias / "new.raw"), [str(real / "y.raw")]) == str(alias / "new.raw")
    assert mk.check_output_path(str(tmp_path / "elsewhere.raw"), []) == str(tmp_path / "elsewhere.raw")


def test_debugfs_commands_quote_a_staged_path_with_a_space(mk):
    """debugfs parses its script with libss: `write /tmp/my stage/x /usr/local/x` is three
    words.  A card under 'D:\\Pinball\\TMNT 1987\\multi' stages exactly there."""
    items = [("/tmp/my stage/codeselect", "/usr/local/codeselect/codeselect", 0o755),
             ("/tmp/my stage/game", "/etc/init.d/game", 0o755)]
    cmds = mk.inject_commands(items, None, {"mtime": 1234, "atime": 1})
    assert cmds[:2] == ['mkdir "/usr/local/codeselect"', 'rm "/etc/init.d/game"']
    assert 'write "/tmp/my stage/codeselect" "/usr/local/codeselect/codeselect"' in cmds
    assert 'write "/tmp/my stage/game" "/etc/init.d/game"' in cmds
    assert 'set_inode_field "/usr/local/codeselect/codeselect" mode 0100755' in cmds
    assert 'set_inode_field "/etc/init.d/game" mtime @1234' in cmds
    assert 'set_inode_field "/etc/init.d/game" atime @1' in cmds
    assert not [c for c in cmds if re.search(r'(^|\s)/', c)], "a bare (unquoted) path in %r" % cmds
    # an existing selector directory: its entries go first, by quoted path
    cmds = mk.inject_commands(items, ["codeselect", "old.ttf"], {})
    assert cmds[:3] == ['rm "/usr/local/codeselect/codeselect"', 'rm "/usr/local/codeselect/old.ttf"',
                        'rm "/etc/init.d/game"']
    assert mk.dq("/plain") == '"/plain"'
    with pytest.raises(mk.Refused):
        mk.dq('a"b')


def test_p2_sidecar_records_the_whole_range_and_sees_a_flipped_byte(mk, tmp_path):
    """verify cannot compare p2 to its source (it is patched), so without the sidecar a p2
    corrupted outside the injected files passed."""
    A = mk.make_synthetic_card(str(tmp_path / "A.img"), "A", 0x0A0A0A0A)
    p2_off, p2_len = 10240 * 512, 2048 * 512
    assert mk.p2_range(A) == (p2_off, p2_len)
    assert mk.read_p2_sidecar(A) is None and mk.check_p2_sidecar(A)[0] is None
    h = mk.write_p2_sidecar(A)
    side = tmp_path / "A.img.p2.md5"
    assert mk.p2_sidecar_path(A) == str(side) and side.is_file()
    assert side.read_text().split() == [h, "p2", "@%d+%d" % (p2_off, p2_len)]
    assert h == mk.md5_range(A, p2_off, p2_len)
    assert mk.read_p2_sidecar(A) == h and mk.check_p2_sidecar(A) == (h, h)

    def flip(off):
        with open(A, "r+b") as f:
            f.seek(off)
            b = f.read(1)
            f.seek(off)
            f.write(bytes([b[0] ^ 1]))

    flip(p2_off + p2_len - 1)                          # p2's last byte
    want, got = mk.check_p2_sidecar(A)
    assert want == h and got != h
    flip(p2_off + p2_len - 1)                          # back
    flip(p2_off + p2_len)                              # p3's first byte: not p2's business
    assert mk.check_p2_sidecar(A) == (h, h)
    side.write_text("garbage\n")
    with pytest.raises(mk.Refused, match="sidecar"):
        mk.read_p2_sidecar(A)


def test_build_cli_refuses_before_reading_anything(mk, tmp_path, capsys):
    """The output check runs before the inputs are even opened: a refused path never
    gets as far as a truncate."""
    rc = mk.main(["build", "--primary", str(tmp_path / "nope.raw"), "--out",
                  "/mnt/d/Pinball/images/Stern/spike2/turtles_pro-1_59_0.Release.8G.sdcard.raw",
                  "--selector-dir", str(tmp_path)])
    assert rc == 2
    assert "card library" in capsys.readouterr().err
    rc = mk.main(["build", "--primary", str(tmp_path / "nope.raw"), "--out", str(tmp_path / "nope.raw"),
                  "--selector-dir", str(tmp_path)])
    assert rc == 2
    assert not (tmp_path / "nope.raw").exists()


@pytest.mark.parametrize("cmd", ["plan", "check-stock", "build", "inject", "inspect", "bypass", "verify", "selftest",
                                 "update"])
def test_every_subcommand_has_help(mk, cmd, capsys):
    with pytest.raises(SystemExit) as e:
        mk.main([cmd, "--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "usage:" in out
    if cmd in ("build", "inject"):
        assert "--media-dir" in out and "--volume" in out and "--mixer-volume" in out
    if cmd == "build":
        assert "--layout" in out and "--bypass-validation" in out and "--workdir" in out
    if cmd == "bypass":
        assert "--card" in out and "--dry-run" in out
    if cmd == "inject":
        assert "--primary" in out and "--extra" in out       # provenance for build.json
    if cmd == "inspect":
        assert "--card" in out and "--json" in out and "--media-out" in out


def test_sidecars_are_per_partition_and_stale_ones_are_dropped(mk, tmp_path):
    A = mk.make_synthetic_card(str(tmp_path / "A.img"), "A", 0x0A0A0A0A)
    assert mk.sidecar_path(A, 7) == A + ".p7.md5" and mk.p2_sidecar_path(A) == A + ".p2.md5"
    h3 = mk.write_part_sidecar(A, 3)
    assert (tmp_path / "A.img.p3.md5").read_text().split() == [h3, "p3", "@%d+%d" % (12288 * 512, 2046 * 512)]
    assert mk.read_part_sidecar(A, 3) == h3 and mk.check_part_sidecar(A, 3) == (h3, h3)
    assert mk.read_part_sidecar(A, 7) is None
    with pytest.raises(mk.Refused, match="not Linux"):
        mk.write_part_sidecar(A, 1)
    mk.write_p2_sidecar(A)
    mk.drop_stale_sidecars(A, keep=(2,))
    assert (tmp_path / "A.img.p2.md5").is_file() and not (tmp_path / "A.img.p3.md5").exists()


# ============================================================================ synthetic end to end (pure python)
def test_synthetic_cards_build_and_parse_back(mk, tmp_path):
    """Three 10 MiB stock-shaped cards of random bytes -> one 12 MiB card; every range md5-equal
    to its source, the table parses back (own parser), the bootstrap is verbatim, and the
    synthetic primary passes check-stock's byte comparison."""
    A = mk.make_synthetic_card(str(tmp_path / "A.img"), "A", 0x0A0A0A0A)
    B = mk.make_synthetic_card(str(tmp_path / "B.img"), "B", 0x0B0B0B0B)
    C = mk.make_synthetic_card(str(tmp_path / "C.img"), "C", 0x0C0C0C0C)
    ga = mk.Geometry.from_file(A)
    assert ga.part(1) == (0x0C, 8192, 2048) and ga.part(6) == (0x83, 18432, 2046)
    assert ga.logical[1][0] == 18430 and ga.sectors == 20480
    assert mk.check_stock(A)
    plan = mk.make_plan(A, [B, C], "parts")
    assert plan.layout == "parts" and plan.trees == [(p, None) for p in plan.images]
    assert [(p.num, p.start, p.count, p.ebr) for p in plan.logs] == [
        (5, 16384, 2046, 14336), (6, 18432, 2046, 18430), (7, 20480, 2046, 20478), (8, 22528, 2046, 22526)]
    assert plan.total == 24576 and plan.ext_count == 24574 - 14336
    out = str(tmp_path / "multi.img")
    mk.build_image(plan, out)
    assert os.path.getsize(out) == 12 << 20
    got = mk.Geometry.from_file(out)
    table = [(n, t, st, cnt) for (n, t, st, cnt) in got.prim] + \
            [(5 + i, t, st, cnt) for i, (_e, t, st, cnt) in enumerate(got.logical)]
    assert table == plan.table()
    for p in plan.prims + plan.logs:
        assert mk.md5_range(p.src, p.src_start * 512, p.count * 512) == mk.md5_range(out, p.start * 512, p.count * 512), p
    with open(out, "rb") as f:
        mbr = f.read(512)
    assert mbr[:0x1BE] == ga.mbr[:0x1BE]
    assert mk.md5_range(A, 512, 8191 * 512) == mk.md5_range(out, 512, 8191 * 512)
    # p7 and p8 are B's and C's p3, not A's
    assert mk.md5_range(out, 20480 * 512, 2046 * 512) == mk.md5_range(B, 12288 * 512, 2046 * 512)
    assert mk.md5_range(out, 22528 * 512, 2046 * 512) == mk.md5_range(C, 12288 * 512, 2046 * 512)
    # and the EBR sectors are exactly the writer's
    with open(out, "rb") as f:
        for i, p in enumerate(plan.logs):
            f.seek(p.ebr * 512)
            assert f.read(512) == mk.ebr_sector(plan, i), "EBR for p%d" % p.num
    # a card built from itself: plan_from_card sees the two extra images
    back = mk.plan_from_card(out)
    assert [p.num for p in back.images] == [3, 7, 8]
    assert back.total == plan.total and back.table() == plan.table()


def test_copy_range_skips_zero_chunks_and_keeps_data(mk, tmp_path):
    src = tmp_path / "src.bin"
    data = b"\x00" * (9 << 20) + b"Q" * 1000 + b"\x00" * 5000
    src.write_bytes(data)
    out = tmp_path / "out.bin"
    with open(out, "wb") as f:
        f.truncate(len(data) + 4096)
    mk.copy_range(str(src), 0, str(out), 4096, len(data), progress=None)
    assert out.read_bytes() == b"\x00" * 4096 + data
    assert hashlib.md5(out.read_bytes()[4096:]).hexdigest() == mk.md5_range(str(src), 0, len(data))


# ============================================================ the JSON sidecars (item 90: load a card back)
def _two_image_plan(mk):
    return mk.Plan(stock_8g(mk), [extra_8g(mk, "b.raw")], "a.raw", ["b.raw"])


def _menu_conf(mk, plan, **kw):
    kw.setdefault("titles", ["STERN 1.59.0", "TMNT 1987"])
    kw.setdefault("subtitles", ["Original Stern code", "1987 cartoon upscale"])
    kw.setdefault("default", 1)
    kw.setdefault("timeout", 20)
    return mk.render_images_conf(plan.devices(), **kw)


def test_build_manifest_records_the_menu_and_where_each_image_came_from(mk):
    """build.json holds what images.conf holds PLUS the one thing it cannot: the .raw each
    image was built from."""
    plan = _two_image_plan(mk)
    text = _menu_conf(mk, plan, media=[("art0.png", "", ""), ("art1.png", "anim1.gif", "music1.wav")],
                      sound_move="move.wav", sound_confirm="confirm.wav", volume=35, mixer_volume=20)
    man = mk.build_manifest(plan, mk.parse_images_conf(text), ["/img/a.raw", "/img/b.raw"],
                            written="2026-09-02T00:00:00Z", versions=[
                                {"device": "/dev/mmcblk0p3", "title": "turtles_pro",
                                 "version": "1.59.0", "node_fw_version": "1.33.0"},
                                {"device": "/dev/mmcblk0p7", "title": "turtles_pro",
                                 "version": "1.58.0", "node_fw_version": "1.19.0"}])
    assert man["tool"] == "mkmulticard" and man["version"] == mk.VERSION
    assert man["written"] == "2026-09-02T00:00:00Z" and man["layout"] == "parts"
    assert (man["timeout"], man["default"]) == (20, 1)
    assert (man["volume"], man["mixer_volume"]) == (35, 20)
    assert (man["sound_move"], man["sound_confirm"]) == ("move.wav", "confirm.wav")
    assert man["images"] == [
        {"device": "/dev/mmcblk0p3", "source": os.path.abspath("/img/a.raw"), "title": "STERN 1.59.0",
         "subtitle": "Original Stern code", "art": "art0.png", "anim": None, "music": None,
         "confirm": None,
         "title_dir": "turtles_pro", "version": "1.59.0", "node_fw_version": "1.33.0"},
        {"device": "/dev/mmcblk0p7", "source": os.path.abspath("/img/b.raw"), "title": "TMNT 1987",
         "subtitle": "1987 cartoon upscale", "art": "art1.png", "anim": "anim1.gif", "music": "music1.wav",
         "confirm": None,
         "title_dir": "turtles_pro", "version": "1.58.0", "node_fw_version": "1.19.0"}]
    # it is JSON, and exactly the keys contract A names
    d = json.loads(json.dumps(man))
    assert set(d) == {"tool", "version", "written", "layout", "images", "timeout", "default",
                      "volume", "machine_volume", "mixer_volume", "sound_move", "sound_confirm", "theme",
                      "colors"}
    # a card with no media at all: the fields are null, not absent
    plain = mk.build_manifest(plan, mk.parse_images_conf(_menu_conf(mk, plan)), None)
    assert [im["art"] for im in plain["images"]] == [None, None]
    assert plain["volume"] is None and plain["sound_move"] is None and plain["images"][0]["source"] is None
    # ...and so are the version fields when no version was read
    assert [im["version"] for im in plain["images"]] == [None, None]


def test_an_inject_with_no_sources_carries_the_previous_provenance_through(mk):
    """The rule that keeps a menu edit from destroying a card's history: an inject given no
    --primary/--extra reads the card's build.json and keeps its 'source' values, BY DEVICE."""
    plan = _two_image_plan(mk)
    conf = mk.parse_images_conf(_menu_conf(mk, plan))
    on_card = mk.build_manifest(plan, conf, None)
    for im, p in zip(on_card["images"], ["/mnt/d/Pinball/a.raw", "/mnt/d/Pinball/b.raw"]):
        im["source"] = p                                  # as a Linux-built card spells them
    again = mk.build_manifest(plan, conf, None, existing=on_card)
    assert [im["source"] for im in again["images"]] == ["/mnt/d/Pinball/a.raw", "/mnt/d/Pinball/b.raw"]
    # a carried path is used VERBATIM - re-absolutising a /mnt/d path on Windows would mangle it
    assert again["images"][0]["source"] == "/mnt/d/Pinball/a.raw"
    # one path given replaces just that image; the other is still carried
    mixed = mk.build_manifest(plan, conf, ["", "/new/b.raw"], existing=on_card)
    assert [im["source"] for im in mixed["images"]] == ["/mnt/d/Pinball/a.raw", os.path.abspath("/new/b.raw")]
    # the menu can change freely: the sources follow the DEVICE, not the title
    renamed = mk.parse_images_conf(_menu_conf(mk, plan, titles=["swapped", "names"]))
    assert [im["source"] for im in mk.build_manifest(plan, renamed, None, existing=on_card)["images"]] \
        == ["/mnt/d/Pinball/a.raw", "/mnt/d/Pinball/b.raw"]
    # an image the old manifest never knew has no source (and does not steal another's)
    three = mk.Plan(stock_8g(mk), [extra_8g(mk, "b.raw"), extra_8g(mk, "c.raw")], "a.raw", ["b.raw", "c.raw"])
    grown = mk.build_manifest(three, mk.parse_images_conf(
        mk.render_images_conf(three.devices(), ["A", "B", "C"])), None, existing=on_card)
    assert [im["source"] for im in grown["images"]] == ["/mnt/d/Pinball/a.raw", "/mnt/d/Pinball/b.raw", None]


def test_selector_manifests_writes_build_json_always_and_media_json_verbatim(mk, tmp_path):
    plan = _two_image_plan(mk)
    text = _menu_conf(mk, plan)
    d = tmp_path / "media set"
    d.mkdir()
    raw = b'{ "images" : [ {"art": "a.png", "art_source": "auto@20:2:8"} ], "volume":41 }'
    (d / "media.json").write_bytes(raw)
    mans = mk.selector_manifests(plan, text, str(d), ["/x/a.raw", "/x/b.raw"])
    assert list(mans) == ["build.json", "media.json"]
    assert mans["media.json"] == raw, "the manifest selectmedia wrote goes on the card verbatim"
    assert json.loads(mans["build.json"])["images"][0]["title"] == "STERN 1.59.0"
    # no --media-dir: the card's own media.json is carried through byte for byte
    carried = mk.selector_manifests(plan, text, None, None, existing_media=raw)
    assert carried["media.json"] == raw
    # neither: build.json alone (a card with no media carries no media.json)
    assert list(mk.selector_manifests(plan, text)) == ["build.json"]


def test_stage_selector_puts_the_sidecars_beside_images_conf_never_in_media(mk, tmp_path):
    """They are not media: they must never land in the directory the selector scans."""
    sel = tmp_path / "sel"
    sel.mkdir()
    (sel / "codeselect").write_bytes(b"#!/bin/sh\nexit 0\n")
    (sel / "select.sh").write_bytes(b"#!/bin/sh\nexit 0\n")
    art = tmp_path / "art0.png"
    art.write_bytes(b"not really a png")
    stage = tmp_path / "stage"
    stage.mkdir()
    items = mk.stage_selector(str(sel), str(stage), "image=/dev/mmcblk0p3|A|\ndefault=0\ntimeout=1\n",
                              "#!/bin/sh\n", {"art0.png": str(art)},
                              {"build.json": '{"tool": "mkmulticard"}\n', "media.json": b'{"images": []}'})
    cards = [c for (_s, c, _m) in items]
    modes = {c: m for (_s, c, m) in items}
    assert mk.SELECT_DIR + "/build.json" in cards and mk.SELECT_DIR + "/media.json" in cards
    assert modes[mk.SELECT_DIR + "/build.json"] == 0o644 and modes[mk.SELECT_DIR + "/media.json"] == 0o644
    assert [c for c in cards if c.startswith(mk.MEDIA_DIR + "/")] == [mk.MEDIA_DIR + "/art0.png"]
    assert (stage / "media.json").read_bytes() == b'{"images": []}'          # bytes stay bytes
    assert not (stage / "media" / "media.json").exists()
    with pytest.raises(mk.Refused):
        mk.stage_selector(str(sel), str(stage), "x\n", "#!/bin/sh\n", None, {"notes.json": "{}"})


def test_inject_commands_remove_and_rewrite_the_sidecars(mk):
    items = [("/s/images.conf", "/usr/local/codeselect/images.conf", 0o644),
             ("/s/build.json", "/usr/local/codeselect/build.json", 0o644),
             ("/s/media.json", "/usr/local/codeselect/media.json", 0o644),
             ("/s/game", "/etc/init.d/game", 0o755)]
    cmds = mk.inject_commands(items, ["images.conf", "build.json", "media.json"], {})
    for name in ("build.json", "media.json"):
        rm = 'rm "/usr/local/codeselect/%s"' % name
        write = 'write "/s/%s" "/usr/local/codeselect/%s"' % (name, name)
        assert rm in cmds and write in cmds and cmds.index(rm) < cmds.index(write)
        assert 'set_inode_field "/usr/local/codeselect/%s" mode 0100644' % name in cmds
    assert not [c for c in cmds if "/codeselect/media/" in c]   # never inside the media directory


def test_parse_manifest_degrades_on_a_broken_sidecar(mk):
    warns = []
    assert mk.parse_manifest(None, "build.json", warns) is None and warns == []
    assert mk.parse_manifest(b'{"a": 1}', "build.json", warns) == {"a": 1}
    assert mk.parse_manifest(b"not json at all", "build.json", warns) is None
    assert mk.parse_manifest(b'["a list"]', "media.json", warns) is None
    assert len(warns) == 2 and "build.json" in warns[0] and "media.json" in warns[1]
    with pytest.raises(mk.Refused):
        mk.parse_manifest(b"{", "build.json")


# ============================================================ inspect (item 90: contract B)
REG, DIRM = 0o100644, 0o040755


def _synth_card(mk, tmp_path, n_extra=1):
    """A real (pure-python) multi card plus its sources; the ext4 side is faked below."""
    srcs = [mk.make_synthetic_card(str(tmp_path / ("S%d.img" % i)), "S%d" % i, 0x0A0B0C00 + i)
            for i in range(n_extra + 1)]
    plan = mk.make_plan(srcs[0], srcs[1:], "parts")
    out = str(tmp_path / "multi.img")
    mk.build_image(plan, out)
    return out, srcs, plan


def _fake_p2(mk, monkeypatch, files, dirs, trees=None):
    """Stand in for the debugfs read layer: `files` {card path: bytes}, `dirs` {dir path:
    [(name, mode, size)]}, `trees` {device: (validator state, title dir[, version, node fw])}."""
    monkeypatch.setattr(mk, "need_tools", lambda *a: None)
    monkeypatch.setattr(mk, "debugfs_exists", lambda ref, p: p in files or p in dirs)

    def cat(ref, p):
        if p not in files:
            raise mk.Refused("no such file %s" % p)
        return files[p]

    def ls(ref, p):
        if p not in dirs:
            raise mk.Refused("no such directory %s" % p)
        return [(100 + i, mode, 0, 0, name, size) for i, (name, mode, size) in enumerate(dirs[p])]

    def tree(card, part, sub=None):
        got = (trees or {}).get(mk.device_name(part.num, sub))
        if got is None:
            raise mk.Refused("no title directory with a game file in this tree")
        state, title = got[0], got[1]
        ver = got[2] if len(got) > 2 else None
        fw = got[3] if len(got) > 3 else None
        rec = mk._unread_tree(mk.device_name(part.num, sub), "synthetic")
        rec.update([("title", title), ("game_path", title + "/game"), ("bypass", state),
                    ("version", ver), ("version_source", "spk index + game ELF" if ver else None),
                    ("sidx", "%s-%s.sidx" % (title, (ver or "").replace(".", "_")) if ver else None),
                    ("sidx_version", ver), ("elf_version", ver.rsplit(".", 1)[0] if ver else None),
                    ("node_fw", ["pinnode-LPC1313-%s.hex" % (fw or "").replace(".", "_")] if fw else []),
                    ("node_fw_version", fw), ("node_fw_digest", fw), ("notes", [])])
        return rec

    monkeypatch.setattr(mk, "debugfs_cat", cat)
    monkeypatch.setattr(mk, "debugfs_ls", ls)
    monkeypatch.setattr(mk, "read_tree", tree)


def _loaded_card(mk, tmp_path, monkeypatch, with_build=True, with_media_json=True, sources=None,
                 trees=None, theme=None, colors=None):
    out, srcs, plan = _synth_card(mk, tmp_path)
    conf = mk.render_images_conf(plan.devices(), ["STERN 1.59.0", "TMNT 1987"],
                                 ["Original Stern code", "1987 cartoon upscale"], 1, 20,
                                 mk.SELECT_DIR + "/font.ttf",
                                 media=[("art0.png", "", ""), ("art1.png", "anim1.gif", "music1.wav")],
                                 sound_move="move.wav", sound_confirm="confirm.wav", volume=35,
                                 theme=theme, colors=colors)
    media_json = json.dumps({"images": [{"art": "art0.png", "anim": None, "music": None,
                                         "art_source": "auto@20", "anim_source": None},
                                        {"art": "art1.png", "anim": "anim1.gif", "music": "music1.wav",
                                         "art_source": "/x/clip.mov@21", "anim_source": "auto@20:2:8"}],
                             "sound_move": "move.wav", "sound_confirm": "confirm.wav",
                             "volume": 35}, indent=2).encode()
    mans = mk.selector_manifests(plan, conf, None, srcs if sources is None else sources)
    files = {mk.SELECT_DIR + "/images.conf": conf.encode(),
             mk.SELECT_DIR + "/codeselect": b"\x7fELF..codeselect 2.1 - Spike 2 boot-time code selector\n",
             mk.SELECT_DIR + "/select.sh": b"#!/bin/sh\n",
             mk.MEDIA_DIR + "/art0.png": b"png-zero",
             mk.MEDIA_DIR + "/art1.png": b"png-one",
             mk.MEDIA_DIR + "/anim1.gif": b"gif-one",
             mk.MEDIA_DIR + "/music1.wav": b"wav-one",
             mk.MEDIA_DIR + "/move.wav": b"mv",
             mk.MEDIA_DIR + "/confirm.wav": b"ok"}
    sel_dir = [("codeselect", REG, len(files[mk.SELECT_DIR + "/codeselect"])), ("select.sh", REG, 10),
               ("images.conf", REG, len(conf)), ("media", DIRM, 4096)]
    if with_build:
        files[mk.SELECT_DIR + "/build.json"] = mans["build.json"].encode()
        sel_dir.append(("build.json", REG, len(mans["build.json"])))
    if with_media_json:
        files[mk.SELECT_DIR + "/media.json"] = media_json
        sel_dir.append(("media.json", REG, len(media_json)))
    dirs = {mk.SELECT_DIR: sel_dir,
            mk.MEDIA_DIR: [(n.rsplit("/", 1)[1], REG, len(b))
                           for n, b in files.items() if n.startswith(mk.MEDIA_DIR + "/")]}
    _fake_p2(mk, monkeypatch, files, dirs, trees or
             {"/dev/mmcblk0p3": ("armed", "turtles_pro"), "/dev/mmcblk0p7": ("bypassed", "turtles_pro")})
    return out, srcs, plan


def test_inspect_reads_back_every_field_a_loader_needs(mk, tmp_path, monkeypatch):
    out, srcs, _plan = _loaded_card(mk, tmp_path, monkeypatch)
    rep = mk.inspect_card(out, str(tmp_path / "loaded"))
    assert rep["card"] == os.path.abspath(out) and rep["size"] == os.path.getsize(out)
    assert rep["layout"] == "parts"
    assert [p["num"] for p in rep["partitions"]] == [1, 2, 3, 4, 5, 6, 7]
    assert [(im["index"], im["device"]) for im in rep["images"]] == [(0, "/dev/mmcblk0p3"), (1, "/dev/mmcblk0p7")]
    assert [im["title"] for im in rep["images"]] == ["STERN 1.59.0", "TMNT 1987"]
    assert [im["subtitle"] for im in rep["images"]] == ["Original Stern code", "1987 cartoon upscale"]
    assert [(im["art"], im["anim"], im["music"]) for im in rep["images"]] == [
        ("art0.png", None, None), ("art1.png", "anim1.gif", "music1.wav")]
    assert [(im["art_source"], im["anim_source"]) for im in rep["images"]] == [
        ("auto@20", None), ("/x/clip.mov@21", "auto@20:2:8")]
    assert [im["source"] for im in rep["images"]] == [os.path.abspath(s) for s in srcs]
    assert [im["source_exists"] for im in rep["images"]] == [True, True]
    assert [im["title_dir"] for im in rep["images"]] == ["turtles_pro", "turtles_pro"]
    assert [im["bypass"] for im in rep["images"]] == ["armed", "bypassed"]
    assert (rep["timeout"], rep["default"], rep["volume"], rep["mixer_volume"]) == (20, 1, 35, None)
    assert (rep["sound_move"], rep["sound_confirm"]) == ("move.wav", "confirm.wav")
    assert rep["font"] == mk.SELECT_DIR + "/font.ttf" and rep["media_dir"] == mk.MEDIA_DIR
    assert rep["theme"] is None and rep["colors"] == {}          # no theme key: the selector's default
    assert sorted(m["name"] for m in rep["media"]) == ["anim1.gif", "art0.png", "art1.png", "confirm.wav",
                                                       "move.wav", "music1.wav"]
    assert [m for m in rep["media"] if m["name"] == "art0.png"][0]["bytes"] == len(b"png-zero")
    assert rep["has_build_json"] and rep["has_media_json"]
    assert rep["build"]["tool"] == "mkmulticard" and rep["build"]["version"] == mk.VERSION
    assert rep["selector"]["version"] == "2.1" and rep["selector"]["bytes"] > 0
    assert rep["warnings"] == []
    # every key contract B names, and the whole report is JSON
    assert set(rep) >= {"card", "size", "layout", "partitions", "images", "timeout", "default", "volume",
                        "mixer_volume", "sound_move", "sound_confirm", "font", "media", "has_media_json",
                        "has_build_json", "selector", "warnings", "theme", "colors"}
    assert json.loads(json.dumps(rep))["images"][1]["title"] == "TMNT 1987"
    # --media-out gives back a directory that IS a --media-dir again
    d = tmp_path / "loaded"
    assert sorted(p.name for p in d.iterdir()) == ["anim1.gif", "art0.png", "art1.png", "confirm.wav",
                                                   "media.json", "move.wav", "music1.wav"]
    assert (d / "art0.png").read_bytes() == b"png-zero"
    assert json.loads((d / "media.json").read_bytes())["images"][1]["anim_source"] == "auto@20:2:8"
    assert rep["media_out"]["files"] == 7


def test_inspect_reads_the_theme_back(mk, tmp_path, monkeypatch, capsys):
    """theme= and the colour overrides come back as the card spells them - a loader puts them in
    its Theme picker - and the human table says them too."""
    out, _srcs, _plan = _loaded_card(mk, tmp_path, monkeypatch, theme="custom",
                                     colors={"frame_hl": "#00FF00", "background": "102030"})
    rep = mk.inspect_card(out, str(tmp_path / "loaded"))
    assert rep["theme"] == "custom"
    assert rep["colors"] == {"background": "102030", "frame_hl": "00ff00"}
    mk.print_inspect(rep)
    table = capsys.readouterr().out
    assert "theme      custom color_background=102030 color_frame_hl=00ff00" in table
    # ...and build.json carried them too, so an inject with no flags writes them back
    build = json.loads(mk.selector_manifests(_plan_of(mk, rep), mk.render_images_conf(
        [im["device"] for im in rep["images"]], theme="slate"), None, None)["build.json"])
    assert build["theme"] == "slate" and build["colors"] == {}


def _plan_of(mk, rep):
    """A plan-shaped stand-in for build_manifest: only .layout is read."""
    class P(object):
        layout = rep["layout"]
    return P()


def test_the_themes_file_is_the_one_definition(mk):
    """codeselect/themes.json, read as is: fourteen roles, a label for each, a default that
    exists, a handful of built-ins each naming every role as RRGGBB - and the selector's own
    generator accepts the same file, which is what its build compiles in."""
    th = mk.boot_themes()
    assert th["default"] == "midnight"
    assert th["roles"][0] == "background" and th["roles"][-1] == "countdown" and len(th["roles"]) == 14
    assert mk.theme_names() == ["midnight", "arcade", "neon", "emerald", "slate", "daylight"]
    assert set(th["labels"]) == set(th["roles"])
    for t in th["themes"]:
        assert set(t["colors"]) == set(th["roles"])
        assert all(re.match(r"^[0-9a-f]{6}$", v) for v in t["colors"].values()), t["name"]
        assert t["title"] and t["about"]
    assert mk.theme_colors("midnight")["background"] == "0b0e13"     # the look before themes existed
    assert mk.theme_colors("midnight")["frame_hl"] == "ffc42d"
    assert mk.theme_colors("custom") is None and mk.theme_colors("nosuch") is None
    gen = os.path.join(os.path.dirname(mk.THEMES_JSON), "gen_themes.py")
    header = subprocess.run([sys.executable, gen, mk.THEMES_JSON, "-"], check=True,
                            capture_output=True, text=True).stdout
    assert "#define TH_N 14" in header and "#define THEME_COUNT 6" in header
    assert '#define THEME_DEFAULT "midnight"' in header
    assert "TH_BACKGROUND," in header and "TH_COUNTDOWN\n" in header
    assert '{ "daylight", { 0xf2f0ea,' in header


def test_images_conf_carries_a_theme_and_its_colours(mk):
    """theme= after the other keys; color_<role>= lines in the roles' order, lower case, no '#';
    both read back; nothing written when nothing was asked for; a typo refused where it is
    typed, and a card's unknown name or bad colour tolerated where it is read (the selector
    tolerates them too)."""
    devs = ["/dev/mmcblk0p3", "/dev/mmcblk0p7"]
    text = mk.render_images_conf(devs, ["A", "B"], theme="Slate")
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    assert lines == ["image=/dev/mmcblk0p3|A|", "image=/dev/mmcblk0p7|B|", "default=0", "timeout=15",
                     "theme=slate"]
    text = mk.render_images_conf(devs, ["A", "B"], theme="custom",
                                 colors={"countdown": "#00FF00", "background": "102030"})
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    assert lines[-3:] == ["theme=custom", "color_background=102030", "color_countdown=00ff00"]
    conf = mk.parse_images_conf(text)
    assert conf["theme"] == "custom" and conf["colors"] == {"background": "102030", "countdown": "00ff00"}
    # colours on a built-in are legal too (the selector puts them on top of it)
    text = mk.render_images_conf(devs, ["A", "B"], theme="neon", colors={"frame_hl": "ffffff"})
    assert "theme=neon\ncolor_frame_hl=ffffff\n" in text
    # nothing asked for: no key, and the parser says so
    plain = mk.render_images_conf(devs, ["A", "B"])
    assert "theme" not in plain and "color_" not in plain
    assert mk.parse_images_conf(plain)["theme"] is None and mk.parse_images_conf(plain)["colors"] == {}
    # build.json carries both
    man = mk.build_manifest(None, mk.parse_images_conf(text), None)
    assert (man["theme"], man["colors"]) == ("neon", {"frame_hl": "ffffff"})
    # a typo is refused where it is typed...
    for bad in ({"theme": "nosuch"}, {"colors": {"countdown": "zzz"}}, {"colors": {"nosuchrole": "ffffff"}},
                {"colors": {"countdown": "#12345"}}):
        with pytest.raises(mk.Refused):
            mk.render_images_conf(devs, ["A", "B"], **bad)
    # ...and tolerated where it is read: the name kept for inspect to show, the bad colours dropped
    conf = mk.parse_images_conf("image=/dev/mmcblk0p3|A|\ntheme=NoSuch\ncolor_countdown=zzz\n"
                                "color_nosuchrole=ffffff\ncolor_frame_hl=#ABCDEF\n")
    assert conf["theme"] == "nosuch" and conf["colors"] == {"frame_hl": "abcdef"}
    assert mk.parse_color_flags(["frame_hl=abcdef", "countdown = 00ff00 "]) == {"frame_hl": "abcdef",
                                                                                "countdown": "00ff00"}
    with pytest.raises(mk.Refused):
        mk.parse_color_flags(["frame_hl"])


def test_conf_for_plan_takes_the_theme_from_the_flags_else_the_card(mk):
    plan = _two_image_plan(mk)
    ex = mk.parse_images_conf(_menu_conf(mk, plan, theme="custom", colors={"countdown": "00ff00"}))
    # no flags: the card's own theme and colours ride through
    text = mk.conf_for_plan(plan, argparse.Namespace(), existing=ex)
    assert "theme=custom\ncolor_countdown=00ff00\n" in text
    # --theme alone: the whole answer - the old overrides go
    text = mk.conf_for_plan(plan, argparse.Namespace(theme="arcade"), existing=ex)
    assert text.endswith("theme=arcade\n") and "color_" not in text
    # --color alone: on top of the card's theme
    text = mk.conf_for_plan(plan, argparse.Namespace(color=["frame_hl=ffffff"]), existing=ex)
    assert text.endswith("theme=custom\ncolor_frame_hl=ffffff\n")
    # a card whose theme this build does not know: noted, the default written
    odd = dict(ex, theme="nosuch")
    text = mk.conf_for_plan(plan, argparse.Namespace(), existing=odd)
    assert "theme=" not in text
    # a typo in the flag is refused
    with pytest.raises(mk.Refused):
        mk.conf_for_plan(plan, argparse.Namespace(theme="nosuch"), existing=ex)


def test_inspect_degrades_when_the_card_carries_no_json_sidecars(mk, tmp_path, monkeypatch):
    """A card built before the sidecars existed (David's v1 card) still loads: the menu is read
    off images.conf, the unknown fields are null, and the report SAYS what is missing."""
    out, _srcs, _plan = _loaded_card(mk, tmp_path, monkeypatch, with_build=False, with_media_json=False)
    rep = mk.inspect_card(out)
    assert rep["has_build_json"] is False and rep["has_media_json"] is False and rep["build"] is None
    assert [im["source"] for im in rep["images"]] == [None, None]
    assert [im["source_exists"] for im in rep["images"]] == [False, False]
    assert [im["art_source"] for im in rep["images"]] == [None, None]
    assert [im["title"] for im in rep["images"]] == ["STERN 1.59.0", "TMNT 1987"]   # the menu still loads
    assert [im["art"] for im in rep["images"]] == ["art0.png", "art1.png"]
    assert [im["bypass"] for im in rep["images"]] == ["armed", "bypassed"]
    assert any("build.json" in w for w in rep["warnings"]) and any("media.json" in w for w in rep["warnings"])
    assert rep["media_out"] is None
    # extracting into a directory that already holds an EARLIER load's media.json says so: this
    # card carries none, and re-injecting from that directory would stage the wrong set
    d = tmp_path / "stale"
    d.mkdir()
    (d / "media.json").write_bytes(b'{"images": []}')
    rep = mk.inspect_card(out, str(d))
    assert any("EARLIER load" in w for w in rep["warnings"])
    assert (d / "art0.png").read_bytes() == b"png-zero"        # the files still come out


def test_inspect_says_when_a_source_is_not_on_this_machine(mk, tmp_path, monkeypatch):
    out, _srcs, _plan = _loaded_card(mk, tmp_path, monkeypatch,
                                     sources=["/mnt/d/Pinball/gone.raw", "/mnt/d/Pinball/also_gone.raw"])
    rep = mk.inspect_card(out)
    assert [im["source_exists"] for im in rep["images"]] == [False, False]
    assert [im["source"] for im in rep["images"]] != [None, None]
    assert len([w for w in rep["warnings"] if "not on this machine" in w]) == 2


def test_inspect_reads_a_multi_layout_cards_subdirectory_devices(mk, tmp_path, monkeypatch):
    out, srcs, _plan = _synth_card(mk, tmp_path)
    monkeypatch.setattr(mk, "multi_subdirs_on", lambda card, part_num=7: ["img1", "img2"])
    plan = mk.plan_from_card(out)
    devs = ["/dev/mmcblk0p3", "/dev/mmcblk0p7:img1", "/dev/mmcblk0p7:img2"]
    assert plan.layout == "multi" and plan.devices() == devs
    conf = mk.render_images_conf(devs, ["A", "B", "C"], ["", "", ""], 0, 15)
    mans = mk.selector_manifests(plan, conf, None, list(srcs) + ["/x/c.raw"])
    files = {mk.SELECT_DIR + "/images.conf": conf.encode(),
             mk.SELECT_DIR + "/build.json": mans["build.json"].encode(),
             mk.SELECT_DIR + "/codeselect": b"codeselect 2.1 - Spike 2 boot-time code selector"}
    dirs = {mk.SELECT_DIR: [("codeselect", REG, 46), ("select.sh", REG, 10),
                            ("images.conf", REG, len(conf)), ("build.json", REG, len(mans["build.json"]))]}
    _fake_p2(mk, monkeypatch, files, dirs, {d: ("bypassed", "turtles_pro") for d in devs})
    rep = mk.inspect_card(out)
    assert rep["layout"] == "multi"
    assert [im["device"] for im in rep["images"]] == devs
    assert [im["bypass"] for im in rep["images"]] == ["bypassed"] * 3
    assert [im["title_dir"] for im in rep["images"]] == ["turtles_pro"] * 3
    assert json.loads(mans["build.json"])["layout"] == "multi"
    assert rep["media"] == [] and rep["has_media_json"] is False


def test_inspect_refuses_what_is_not_a_multi_boot_card(mk, tmp_path, monkeypatch):
    out, _srcs, _plan = _synth_card(mk, tmp_path)
    # a Spike 2 card with no selector installed (a stock card)
    _fake_p2(mk, monkeypatch, {}, {})
    with pytest.raises(mk.Refused) as e:
        mk.inspect_card(out)
    assert "no boot selector" in str(e.value)
    # the directory is there but holds no menu
    _fake_p2(mk, monkeypatch, {}, {mk.SELECT_DIR: [("codeselect", REG, 4)]})
    with pytest.raises(mk.Refused) as e:
        mk.inspect_card(out)
    assert "images.conf" in str(e.value)
    # not a card at all
    junk = tmp_path / "junk.raw"
    junk.write_bytes(b"\x00" * 4096)
    with pytest.raises(mk.Refused):
        mk.inspect_card(str(junk))


def test_inspect_cli_prints_one_json_object_and_exits_2_on_a_refusal(mk, tmp_path, monkeypatch, capsys):
    out, srcs, _plan = _loaded_card(mk, tmp_path, monkeypatch)
    capsys.readouterr()                                   # drop what building the card printed
    assert mk.main(["inspect", "--card", out, "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["card"] == os.path.abspath(out)
    assert [im["source"] for im in rep["images"]] == [os.path.abspath(s) for s in srcs]
    assert mk.main(["inspect", "--card", out]) == 0
    table = capsys.readouterr().out
    assert "STERN 1.59.0" in table and "validator=armed" in table and "codeselect 2.1" in table
    assert mk.main(["inspect", "--card", str(tmp_path / "nope.raw")]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_extract_card_media_writes_a_media_dir_and_refuses_the_card_library(mk, tmp_path, monkeypatch):
    files = {mk.MEDIA_DIR + "/art0.png": b"png", mk.MEDIA_DIR + "/move.wav": b"wav"}
    _fake_p2(mk, monkeypatch, files, {})
    d = tmp_path / "out"
    written, skipped = mk.extract_card_media("ref", str(d), ["art0.png", "move.wav", "../escape"], b"{}")
    assert written == ["art0.png", "move.wav", "media.json"] and skipped == ["../escape"]
    assert (d / "art0.png").read_bytes() == b"png" and (d / "media.json").read_bytes() == b"{}"
    assert not (tmp_path / "escape").exists()
    monkeypatch.setattr(mk, "FORBIDDEN_OUTPUT_PREFIXES", (str(tmp_path / "library"),))
    with pytest.raises(mk.Refused):
        mk.extract_card_media("ref", str(tmp_path / "library" / "media"), [], None)


# ============================================ game code versions (item 90: the same-version gate)
def _vrec(mk, i, version="1.59.0", title="turtles_pro", fw="1.33.0", fwnames=None, notes=()):
    """One read_tree-shaped record, as plan_identities / card_identities hand them to the gate."""
    names = fwnames if fwnames is not None else (
        ["pinnode-LPC1313-%s.hex" % fw.replace(".", "_")] if fw else [])
    return {"index": i, "device": mk.device_name(3 if i == 0 else 6 + i), "title": title,
            "version": version, "version_source": "spk index + game ELF" if version else None,
            "node_fw": names, "node_fw_version": fw,
            "node_fw_digest": mk._fw_digest(names), "notes": list(notes)}


def test_the_game_elf_identity_record_is_located_and_decoded(mk):
    """The version is a uint16 - high byte major, low byte minor - after a run of pointers to
    the game code, the model name(s), the release date and (usually) the title directory."""
    elf = mk.synth_game_elf("turtles_pro", "1.59.0", model="TMNT PRO", code="TMT",
                            date="AUGUST 25, 2019")
    rec = mk.game_identity(elf, "turtles_pro")
    assert rec["version"] == "1.59" and rec["raw"] == (1 << 8) | 59
    assert rec["name"] == "TMNT PRO" and rec["date"] == "AUGUST 25, 2019"
    assert rec["title_dir"] == "turtles_pro"
    assert rec["strings"] == ["TMT", "TMNT PRO", "AUGUST 25, 2019", "turtles_pro"]
    # it is found without being told the title directory too (the date anchors it)
    assert mk.game_identity(elf)["version"] == "1.59"


@pytest.mark.parametrize("kw,version,raw", [
    # every shape the 31 stock cards showed, and the numbers read off them
    ({"version": "1.58.0"}, "1.58", 314),
    ({"version": "0.96", "title_dir": "king_kong_le", "model": "KING KONG LE", "code": "SKK",
      "date": "Mar 31 2026"}, "0.96", 96),                          # __DATE__, two spaces, 0.x
    ({"version": "1.13", "with_title": False, "model": "GODZILLA LE",
      "code": "GODZILLA: 70TH ANNIVERSARY", "date": "Oct  6 2025"}, "1.13", 269),  # no title dir
    ({"version": "1.06", "hi": 0x22}, "1.06", 262),                 # junk above the uint16
    ({"version": "1.13", "extra_names": ("I4", "I3", "I9", "I0"), "date": "JUL. 5, 2019",
      "with_title": False}, "1.13", 269),                           # 'Mmm. D, YYYY', six codes
    ({"version": "1.30", "date": "APR. 20, 2016"}, "1.30", 286),
])
def test_the_identity_record_is_read_in_every_shape_the_library_showed(mk, kw, version, raw):
    rec = mk.game_identity(mk.synth_game_elf(**kw), kw.get("title_dir", "turtles_pro"))
    assert (rec["version"], rec["raw"]) == (version, raw)


def test_the_identity_locator_says_nothing_rather_than_guessing(mk):
    """No ELF, no record, and no run that holds a date or the title directory -> None.  A wrong
    version is worse than no version: the gate reports UNKNOWN instead."""
    assert mk.game_identity(b"not an elf at all") is None
    assert mk.game_identity(b"") is None
    # a record whose strings are neither a date nor the title directory is not this record
    elf = mk.synth_game_elf("turtles_pro", "1.59.0", date="not a date", with_title=False)
    assert mk.game_identity(elf, "turtles_pro") is None


def test_sidx_and_node_firmware_names_carry_the_versions(mk):
    m = mk.SIDX_NAME_RE.match("turtles_pro-1_59_0.sidx")
    assert (m.group("pkg"), mk.version_text(m.group("ver"))) == ("turtles_pro", "1.59.0")
    assert mk.SIDX_NAME_RE.match("turtles_pro.sidx") is None        # the bare symlink: no version
    m = mk.NODE_FW_RE.match("coil4node-LPC1112_101-1_33_0.hex")
    assert (m.group("base"), mk.version_text(m.group("ver"))) == ("coil4node-LPC1112_101", "1.33.0")
    assert mk.NODE_FW_RE.match("image.bin") is None
    assert mk.version_text(None) is None


def test_the_gate_is_silent_when_every_image_is_the_same_code(mk):
    recs = [_vrec(mk, 0), _vrec(mk, 1)]
    found = mk.check_versions(recs)                                  # does not raise
    assert all(v is None for v in found.values())
    assert mk.version_findings(recs)["version_mismatch"] is None


def test_the_gate_names_the_version_the_title_and_the_node_firmware(mk):
    found = mk.version_findings([_vrec(mk, 0), _vrec(mk, 1, version="1.58.0", fw="1.19.0")])
    assert "GAME CODE VERSION" in found["version_mismatch"]
    assert "1.59.0" in found["version_mismatch"] and "1.58.0" in found["version_mismatch"]
    assert found["title_mismatch"] is None
    assert "NODE BOARD FIRMWARE" in found["node_fw_mismatch"]
    assert "reflash the node boards" in found["node_fw_mismatch"]
    assert "image 0 carries pinnode-LPC1313-1_33_0.hex" in found["node_fw_mismatch"]  # WHICH
    assert "image 1 carries pinnode-LPC1313-1_19_0.hex" in found["node_fw_mismatch"]  # files
    # two images that ship the SAME set are named together, never as "only its own"
    three = mk.version_findings([_vrec(mk, 0), _vrec(mk, 1), _vrec(mk, 2, fw="1.19.0")])
    assert "images 0, 1 carry pinnode-LPC1313-1_33_0.hex" in three["node_fw_mismatch"]
    assert "image 2 carries pinnode-LPC1313-1_19_0.hex" in three["node_fw_mismatch"]
    # a different TITLE is the larger warning, and it is folded into version_mismatch so a
    # reader that shows only that key never misses it
    both = mk.version_findings([_vrec(mk, 0), _vrec(mk, 1, title="godzilla_le", version="1.13.0")])
    assert "DIFFERENT TITLES" in both["title_mismatch"]
    assert "settings, audits and high scores are stored per title" in both["title_mismatch"]
    assert both["title_mismatch"] in both["version_mismatch"]


def test_the_node_firmware_check_stands_on_its_own(mk):
    """Same title, same game code version, different node firmware: still refused, and the
    refusal is about the node boards alone."""
    recs = [_vrec(mk, 0), _vrec(mk, 1, fw="1.19.0")]
    found = mk.version_findings(recs)
    assert found["version_mismatch"] is None and found["node_fw_mismatch"]
    with pytest.raises(mk.Refused) as e:
        mk.check_versions(recs)
    assert "NODE BOARD FIRMWARE" in str(e.value) and "GAME CODE VERSION" not in str(e.value)
    assert "--allow-version-mismatch" in str(e.value)                # one flag covers all three


def test_the_refusal_says_what_it_costs_and_how_to_override(mk):
    recs = [_vrec(mk, 0), _vrec(mk, 1, version="1.58.0", fw="1.19.0")]
    with pytest.raises(mk.Refused) as e:
        mk.check_versions(recs)
    msg = str(e.value)
    assert "MENU CAPTION" in msg and "compiled default" in msg      # what does NOT break...
    assert "RENAMED" in msg and "THREE generations" in msg          # ...and what does
    assert "REFLASH the node boards" in msg
    assert "THE FIX is to give every image on the card the same game code version" in msg
    assert "--allow-version-mismatch" in msg
    assert "image 0 " in msg and "1.59.0" in msg and "1.58.0" in msg
    # the override returns the findings instead of raising - nothing is hidden, it just proceeds
    found = mk.check_versions(recs, allow=True)
    assert found["version_mismatch"] and found["node_fw_mismatch"]


def test_an_unreadable_tree_is_reported_not_guessed(mk):
    """A tree the reader could not open is its OWN finding; it never fabricates a mismatch
    against the tree that did read."""
    recs = [_vrec(mk, 0), _vrec(mk, 1, title=None, version=None, fw=None,
                                notes=["this tree could not be read"])]
    found = mk.version_findings(recs)
    assert found["version_mismatch"] is None                        # one version is not a mismatch
    assert found["node_fw_mismatch"] is None and found["title_mismatch"] is None
    assert "did not say what game code" in found["unknown_version"]
    assert "this tree could not be read" in found["unknown_version"]
    mk.check_versions(recs)                                         # and it does not refuse
    # a tree that DID read but carries no node firmware at all is a real difference, and said so
    half = mk.version_findings([_vrec(mk, 0), _vrec(mk, 1, fw=None)])
    assert "no node firmware" in half["node_fw_mismatch"]


def test_print_version_table_has_one_line_per_image(mk, capsys):
    mk.print_version_table([_vrec(mk, 0), _vrec(mk, 1, version="1.58.0", fw="1.19.0")])
    out = capsys.readouterr().out
    assert "game code versions" in out
    assert "/dev/mmcblk0p3         turtles_pro              1.59.0" in out
    assert "/dev/mmcblk0p7         turtles_pro              1.58.0" in out
    assert "1.33.0 (1 hex)" in out and "1.19.0 (1 hex)" in out
    assert out.count("WARNING:") == 2                               # version + node firmware
    mk.print_version_table([_vrec(mk, 0), _vrec(mk, 1)])
    assert "WARNING:" not in capsys.readouterr().out


def test_build_refuses_a_version_mismatch_before_it_writes_anything(mk, tmp_path, monkeypatch, capsys):
    """The whole point of the gate: --out must not exist when the tool says no."""
    A = mk.make_synthetic_card(str(tmp_path / "A.img"), "A", 0x0A0A0A0A)
    B = mk.make_synthetic_card(str(tmp_path / "B.img"), "B", 0x0B0B0B0B)
    sel = tmp_path / "sel"
    sel.mkdir()
    (sel / "codeselect").write_bytes(b"#!/bin/sh\n")
    (sel / "select.sh").write_bytes(b"#!/bin/sh\n")
    out = tmp_path / "multi.img"
    monkeypatch.setattr(mk, "plan_identities", lambda plan, progress=mk.say: [
        _vrec(mk, 0), _vrec(mk, 1, version="1.58.0", fw="1.19.0")])
    argv = ["build", "--primary", A, "--extra", B, "--out", str(out), "--selector-dir", str(sel)]
    assert mk.main(argv) == 2
    assert not out.exists(), "the gate must refuse before a byte of --out is written"
    err = capsys.readouterr().err
    assert "GAME CODE VERSION" in err and "--allow-version-mismatch" in err


def test_inspect_reports_each_images_version_and_the_mismatch_sentences(mk, tmp_path, monkeypatch, capsys):
    out, _srcs, _plan = _loaded_card(
        mk, tmp_path, monkeypatch,
        trees={"/dev/mmcblk0p3": ("armed", "turtles_pro", "1.59.0", "1.33.0"),
               "/dev/mmcblk0p7": ("bypassed", "turtles_pro", "1.58.0", "1.19.0")})
    rep = mk.inspect_card(out)
    assert [im["version"] for im in rep["images"]] == ["1.59.0", "1.58.0"]
    assert [im["version_source"] for im in rep["images"]] == ["spk index + game ELF"] * 2
    assert [im["sidx"] for im in rep["images"]] == ["turtles_pro-1_59_0.sidx", "turtles_pro-1_58_0.sidx"]
    assert [im["elf_version"] for im in rep["images"]] == ["1.59", "1.58"]
    assert [im["node_fw_version"] for im in rep["images"]] == ["1.33.0", "1.19.0"]
    assert rep["version_mismatch"] and rep["node_fw_mismatch"]
    assert rep["title_mismatch"] is None and rep["unknown_version"] is None
    # and the JSON a GUI reads carries the ready-made sentences
    d = json.loads(json.dumps(rep))
    assert "GAME CODE VERSION" in d["version_mismatch"]
    mk.print_inspect(rep)
    table = capsys.readouterr().out
    assert "game code=1.59.0" in table and "node firmware=1.19.0" in table
    assert "VERSION WARNING:" in table


def test_inspect_is_silent_about_versions_when_the_images_match(mk, tmp_path, monkeypatch, capsys):
    out, _srcs, _plan = _loaded_card(
        mk, tmp_path, monkeypatch,
        trees={"/dev/mmcblk0p3": ("armed", "turtles_pro", "1.59.0", "1.33.0"),
               "/dev/mmcblk0p7": ("bypassed", "turtles_pro", "1.59.0", "1.33.0")})
    rep = mk.inspect_card(out)
    assert rep["version_mismatch"] is None and rep["node_fw_mismatch"] is None
    mk.print_inspect(rep)
    assert "VERSION WARNING:" not in capsys.readouterr().out


def test_build_json_carries_a_recorded_version_through_an_inject(mk):
    """An inject reads nothing off the trees, so the versions the build recorded must survive
    it BY DEVICE - exactly as the source paths do."""
    plan = _two_image_plan(mk)
    conf = mk.parse_images_conf(_menu_conf(mk, plan))
    built = mk.build_manifest(plan, conf, ["/img/a.raw", "/img/b.raw"], versions=[
        _vrec(mk, 0), _vrec(mk, 1, version="1.58.0", fw="1.19.0")])
    assert [im["version"] for im in built["images"]] == ["1.59.0", "1.58.0"]
    again = mk.build_manifest(plan, conf, None, existing=built)
    assert [im["version"] for im in again["images"]] == ["1.59.0", "1.58.0"]
    assert [im["title_dir"] for im in again["images"]] == ["turtles_pro", "turtles_pro"]
    assert [im["node_fw_version"] for im in again["images"]] == ["1.33.0", "1.19.0"]


@pytest.mark.skipif(not os.path.isfile(STOCK_CARD), reason="the stock turtles_pro 1.59 card is not on this machine")
def test_the_stock_card_reads_1_59_0_from_both_sources(mk):
    """The real thing, read-only: the package name and the game ELF's own record AGREE."""
    rec = mk.read_tree(STOCK_CARD, mk.source_part(STOCK_CARD))
    assert rec["title"] == "turtles_pro"
    assert (rec["version"], rec["version_source"]) == ("1.59.0", "spk index + game ELF")
    assert rec["sidx"] == "turtles_pro-1_59_0.sidx" and rec["sidx_version"] == "1.59.0"
    assert rec["elf_version"] == "1.59" and rec["elf_name"] == "TMNT PRO"
    assert rec["node_fw_version"] == "1.33.0" and len(rec["node_fw"]) == 17
    assert rec["notes"] == [] and rec["bypass"] == "armed"


def test_the_selftests_check_recorder_names_the_line_that_failed(mk, capsys):
    """`ok &= <expr>` used to fail silently: the run ended in FAIL and the
    only way to find the check was to swap older copies of the file in and
    bisect.  That happened once; one line of output saves the next one."""
    ok = mk.Checks()
    ok &= True
    ok &= 1 == 1
    assert bool(ok) and not ok.failed
    assert capsys.readouterr().out == ""
    # the line the failing check is ON is the one it must name
    line = sys._getframe().f_lineno + 1
    ok &= False
    out = capsys.readouterr().out
    assert not bool(ok)
    assert ok.failed == [line]
    assert "CHECK FAILED at test_mkmulticard.py:%d" % line in out
    # ...and it stays failed, however many pass afterwards
    ok &= True
    assert not bool(ok)
    assert "PASS" if ok else "FAIL" == "FAIL"


# ---- the machine's own volume: volume=machine + machine_volume= (David, 2026-09-03) ---------
def test_images_conf_can_follow_the_machines_own_volume(mk):
    """volume=machine + machine_volume=<store>|<key>|<factory>: what the selector reads to play
    at the MASTER VOLUME SETTING the owner set (David: 'it should follow the set volume of the
    actual machine')."""
    import hashlib
    assert mk.MACHINE_VOLUME_KEY == hashlib.sha1(b"MASTER VOLUME SETTING").hexdigest()
    mv = {"store": "/data/nv/turtles_pro/NVM", "key": mk.MACHINE_VOLUME_KEY, "default": 18}
    text = mk.render_images_conf(["/dev/mmcblk0p3", "/dev/mmcblk0p7"], ["A", "B"], volume=35, machine_volume=mv)
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    assert "volume=machine" in lines and "volume=35" not in lines
    assert "machine_volume=/data/nv/turtles_pro/NVM|73fa9f7f0223dfa965f070fa2d0d49ed0efaec62|18" in lines
    conf = mk.parse_images_conf(text)
    assert conf["volume"] == "machine"
    assert conf["machine_volume"] == {"store": "/data/nv/turtles_pro/NVM", "key": mk.MACHINE_VOLUME_KEY,
                                      "default": 18}
    # no store known (the title could not be read) and no factory level: the fields are empty
    text = mk.render_images_conf(["/dev/mmcblk0p3"],
                                 machine_volume={"store": None, "key": mk.MACHINE_VOLUME_KEY, "default": None})
    assert "machine_volume=|%s|" % mk.MACHINE_VOLUME_KEY in text
    assert mk.parse_images_conf(text)["machine_volume"] == {"store": None, "key": mk.MACHINE_VOLUME_KEY,
                                                             "default": None}
    # a number is still a number, the key must be a SHA1 and the factory level 0-63
    plain = mk.parse_images_conf("image=p3|A|a\nvolume=40\n")
    assert plain["volume"] == 40 and plain["machine_volume"] is None
    with pytest.raises(mk.Refused):
        mk.render_images_conf(["/dev/mmcblk0p3"], machine_volume={"store": "/x", "key": "nope", "default": 1})
    with pytest.raises(mk.Refused):
        mk.parse_images_conf("image=p3|A|a\nmachine_volume=/x|%s|64\n" % mk.MACHINE_VOLUME_KEY)


def test_conf_for_plan_keeps_a_machine_following_card_and_the_flag_reads_the_title(mk, tmp_path, monkeypatch):
    from types import SimpleNamespace
    _out, _srcs, plan = _loaded_card(mk, tmp_path, monkeypatch)
    ex = mk.parse_images_conf("image=/dev/mmcblk0p3|A|a\nimage=/dev/mmcblk0p7|B|b\nvolume=machine\n"
                              "machine_volume=/data/nv/turtles_pro/NVM|%s|18\n" % mk.MACHINE_VOLUME_KEY)
    # no flags: a card that follows its machine keeps doing so, byte for byte
    text = mk.conf_for_plan(plan, SimpleNamespace(), existing=ex)
    assert "volume=machine" in text
    assert "machine_volume=/data/nv/turtles_pro/NVM|%s|18" % mk.MACHINE_VOLUME_KEY in text
    # --volume N takes it off the machine's setting...
    text = mk.conf_for_plan(plan, SimpleNamespace(volume=40), existing=ex)
    assert "volume=40" in text and "machine" not in text
    # ...and --machine-volume puts it on: here the fixture's card has no readable games tree, so
    # there is no store and no factory level, the usual key stands, and nothing raised
    text = mk.conf_for_plan(plan, SimpleNamespace(machine_volume=True, volume=40), existing=ex)
    assert "volume=machine" in text and "volume=40" not in text
    assert "machine_volume=|%s|" % mk.MACHINE_VOLUME_KEY in text
    mv = mk.machine_volume_for(str(tmp_path / "nowhere.raw"), None)
    assert mv["store"] is None and mv["default"] is None and mv["key"] == mk.MACHINE_VOLUME_KEY
    assert mv["notes"] and "could not be read" in mv["notes"][0]


# ---- the work meter and what each image costs --------------------------------------------
def test_image_costs_add_up_to_the_card(mk, tmp_path, capsys):
    """Every game's own bytes, plus what the card spends on itself, IS the
    image - so the size strip's bands can never quietly leave one out."""
    A = mk.make_synthetic_card(str(tmp_path / "A.img"), "A", 0x0A0A0A0A)
    B = mk.make_synthetic_card(str(tmp_path / "B.img"), "B", 0x0B0B0B0B)
    plan = mk.make_plan(A, [B], "parts")
    rows, overhead = mk.image_costs(plan)
    assert [r[0] for r in rows] == [0, 1]
    assert [r[1] for r in rows] == ["/dev/mmcblk0p3", "/dev/mmcblk0p7"]
    assert [r[3] for r in rows] == [A, B]
    room = mk.plan_room(plan)
    assert sum(r[2] for r in rows) + room + overhead == plan.total_bytes
    assert overhead > 0
    assert room == 0, "a synthetic card has no superblock to read a free count off"
    # ...and the plan prints them, one line each, under a word the version
    # table cannot be mistaken for - the room for updates (item 93) under one too
    mk.print_plan(plan)
    out = capsys.readouterr().out
    assert "image-size 0 /dev/mmcblk0p3 %d %s" % (rows[0][2], "A.img") in out
    assert "image-size free %d " % room in out
    assert "image-size overhead %d " % overhead in out


def test_the_multi_layout_costs_each_game_its_own_used_bytes(mk, tmp_path,
                                                             monkeypatch):
    """Inside the shared p7 an image costs what its tree USES, not a whole
    partition - which is the only number that answers 'which one do I drop'.

    The used bytes come off a real ext4 superblock, which needs mke2fs; the
    arithmetic on top of them is what this pins, so the two trees are given
    sizes rather than made."""
    A = mk.make_synthetic_card(str(tmp_path / "A.img"), "A", 0x0A0A0A0A)
    B = mk.make_synthetic_card(str(tmp_path / "B.img"), "B", 0x0B0B0B0B)
    C = mk.make_synthetic_card(str(tmp_path / "C.img"), "C", 0x0C0C0C0C)
    used = {B: 3_000_000_000, C: 4_000_000_000}
    monkeypatch.setattr(mk, "ext_used_bytes",
                        lambda path, off: (used[path], used[path] * 2))
    plan = mk.make_plan(A, [B, C], "multi")
    assert plan.multi_each == [3_000_000_000, 4_000_000_000]
    assert plan.multi_used == 7_000_000_000
    rows, overhead = mk.image_costs(plan)
    assert [r[1] for r in rows] == ["/dev/mmcblk0p3", "/dev/mmcblk0p7:img1",
                                    "/dev/mmcblk0p7:img2"]
    assert [r[2] for r in rows[1:]] == plan.multi_each
    room = mk.plan_room(plan)
    assert sum(r[2] for r in rows) + room + overhead == plan.total_bytes
    # p7's slack is ROOM FOR UPDATES (item 93), not any one game's cost and not
    # the card's overhead
    assert room >= plan.multi_part.count * mk.SECTOR - plan.multi_used
    assert overhead > 0


def test_build_work_bytes_counts_the_extraction_and_the_copy(mk, tmp_path,
                                                             monkeypatch):
    A = mk.make_synthetic_card(str(tmp_path / "A.img"), "A", 0x0A0A0A0A)
    B = mk.make_synthetic_card(str(tmp_path / "B.img"), "B", 0x0B0B0B0B)
    monkeypatch.setattr(mk, "ext_used_bytes",
                        lambda path, off: (2_000_000_000, 4_000_000_000))
    parts = mk.make_plan(A, [B], "parts")
    ranges = mk.PRE_P1 * mk.SECTOR + sum(
        p.count * mk.SECTOR for p in parts.prims + parts.logs)
    assert mk.build_work_bytes(parts) == ranges
    # the multi layout also reads every tree OUT and writes it back IN
    multi = mk.make_plan(A, [B], "multi")
    assert mk.build_work_bytes(multi) - 2 * multi.multi_used == \
        mk.PRE_P1 * mk.SECTOR + sum(p.count * mk.SECTOR
                                    for p in multi.prims + multi.logs)


def test_the_meter_never_goes_backwards_or_past_the_total(mk, capsys):
    """The one property a progress bar has to have.  A child that writes more
    than its budget (metadata) and a step that ends early are both normal;
    neither may move the number the wrong way."""
    m = mk.Progress()
    assert m.on is False and m.at == 0
    m.start(1000, "start")
    assert m.on and m.at == 0
    m.step("first", 400)
    m.sample(100)
    assert m.at == 100
    m.sample(50)                        # a late sample from behind: ignored
    assert m.at == 100
    m.sample(4000)                      # ...and one past the budget: capped
    assert m.at == 400
    m.step("second", 400)               # the first banks in full
    assert m.at == 400
    m.add(100)
    assert m.at == 500
    m.step("third", 10 ** 9)            # a budget bigger than the whole run
    m.sample(10 ** 9)
    assert m.at == 1000                 # ...still cannot pass the total
    m.finish()
    assert m.at == 1000
    lines = [l for l in capsys.readouterr().out.splitlines()
             if l.startswith("[card] progress")]
    assert lines and lines[-1].startswith("[card] progress 1000/1000 100.0%")
    seen = [int(l.split()[2].split("/")[0]) for l in lines]
    assert seen == sorted(seen)


def test_an_idle_meter_prints_nothing(mk, capsys):
    """Every subcommand but build leaves it idle, and an idle meter must not
    add a line to output the GUI parses for something else."""
    m = mk.Progress()
    m.step("nothing", 10)
    m.add(5)
    m.sample(5)
    m.finish()
    assert capsys.readouterr().out == ""


def test_run_metered_hands_back_what_the_child_said(mk):
    rc, out, err = mk.run_metered(
        [sys.executable, "-c",
         "import sys; sys.stdout.write('hi'); sys.stderr.write('bye'); "
         "raise SystemExit(3)"], None, tick=0.01)
    assert (rc, out, err) == (3, b"hi", b"bye")


def test_proc_written_is_absent_rather_than_wrong(mk):
    """It reads /proc/<pid>/io, which is Linux's.  Everywhere else it says it
    does not know - and the meter then just has no live count, which is the
    one honest fallback."""
    assert mk.proc_written(-1) is None
    got = mk.proc_written(os.getpid())
    if sys.platform == "win32":
        assert got is None
    else:
        assert got is None or got >= 0


def test_inspect_hands_over_the_sources_that_made_the_sounds(mk):
    """media.json has recorded them since the sounds learned to re-render;
    the report used to drop them, which left a loader comparing a card's
    FILE NAME against a SOURCE and concluding "stale" every time."""
    src = mk.inspect_card.__doc__ or ""
    text = open(os.path.join(RIG, "mkmulticard.py"), encoding="utf-8").read()
    # the per-image music source, beside the three already carried
    assert '("music_source", m.get("music_source"))' in text
    # ...and the menu's two, off media.json rather than the conf (the conf
    # only ever knew the file name that landed)
    assert '("sound_move_source", (media_man or {}).get("sound_move_source"))'         in text
    assert ('("sound_confirm_source", '
            '(media_man or {}).get("sound_confirm_source"))') in text


# ============================================================================ the store layout (item 95)
def test_store_plan_grows_p3_and_relays_p5_p6_after_it(mk):
    """--layout store: the primary's p3 grown to the given sectors, the extras as trees INSIDE
    it (p3:img1...), p5/p6 re-laid at the first aligned sectors after it, no p7 - and with the
    stock p3 size the plan reproduces the stock table exactly."""
    g = stock_8g(mk)
    _t, s3, c3 = g.part(3)
    same = mk.Plan(g, [extra_8g(mk, "x.raw")], "a.raw", ["x.raw"], "store")
    assert same.layout == "store" and same.prims[2].count == c3 and same.store_src_count == c3
    assert same.table() == mk.Plan(g, []).table()
    assert same.devices() == ["/dev/mmcblk0p3", "/dev/mmcblk0p3:img1"]
    assert [(p.num, s) for (p, s) in same.trees] == [(3, None), (3, "img1")] and same.multi_part is None
    grown = mk.Plan(g, [extra_8g(mk, "x.raw"), extra_8g(mk, "y.raw")], "a.raw", ["x.raw", "y.raw"], "store",
                    store_sectors=c3 + 4096000)
    p3 = grown.prims[2]
    assert (p3.num, p3.start, p3.count, p3.src, p3.src_start) == (3, s3, c3 + 4096000, "a.raw", s3)
    assert grown.ext_base == mk.align_up(s3 + p3.count)
    p5, p6 = grown.logs
    assert p5.ebr == grown.ext_base and p5.start == mk.align_up(grown.ext_base + 1)
    assert p6.ebr == p5.start + p5.count and p6.start == mk.align_up(p6.ebr + 1)
    assert [(p.num, p.count, p.src_start) for p in (p5, p6)] == [
        (5, g.part(5)[2], g.part(5)[1]), (6, g.part(6)[2], g.part(6)[1])]
    assert grown.total == p6.start + p6.count + mk.TAIL and grown.unreachable() == []
    assert grown.table()[3] == (4, 0x0F, grown.ext_base, grown.ext_count) and grown.images == [p3]
    assert grown.store_subdirs == ["img1", "img2"] and grown.devices()[-1] == "/dev/mmcblk0p3:img2"
    with pytest.raises(mk.Refused):
        mk.Plan(g, [], "a.raw", [], "store", store_sectors=c3 - 1)
    assert mk.resolve_layout("store", 1) == "store" and mk.resolve_layout("auto", 5) == "multi"
    assert "store" in mk.LAYOUTS and mk.STORE_SIZES == ("content", "8G", "16G", "32G")
    assert mk.store_sectors_for_class(g, [], "a.raw", [], [], "8G") == c3       # the stock card IS the 8G class


def test_store_sectors_for_class_fills_the_stern_image_size(mk):
    g = stock_8g(mk)
    for cls in ("8G", "16G", "32G"):
        cnt = mk.store_sectors_for_class(g, [], "a.raw", [], [], cls)
        plan = mk.Plan(g, [], "a.raw", [], "store", store_sectors=cnt)
        assert plan.total_bytes <= mk.STERN_SIZES[cls] and cnt >= g.part(3)[2]
        bigger = mk.Plan(g, [], "a.raw", [], "store", store_sectors=cnt + mk.ALIGN)
        assert bigger.total_bytes > mk.STERN_SIZES[cls]


def test_store_plan_costs_are_the_unique_bytes_and_the_shared_row(mk, capsys):
    g = stock_8g(mk)
    plan = mk.Plan(g, [extra_8g(mk, "x.raw")], "a.raw", ["x.raw"], "store", store_sectors=g.part(3)[2] + 2048 * 100)
    plan.store_unique = [3000000000, 1000000000]
    plan.store_shared = 2500000000
    plan.store_meta = 100000000
    rows, over = mk.image_costs(plan)
    assert [(i, d, n) for i, d, n, _s in rows] == [(0, "/dev/mmcblk0p3", 3000000000), (1, "/dev/mmcblk0p3:img1", 1000000000)]
    room = mk.plan_room(plan)
    assert room == plan.prims[2].count * 512 - 4000000000 - 100000000
    assert sum(n for _i, _d, n, _s in rows) + room + over == plan.total_bytes
    mk.print_plan(plan)
    out = capsys.readouterr().out
    assert "layout: store" in out and "image-size shared 2500000000" in out
    assert "p3 (store layout): 2 trees /, img1 inside the primary" in out and "image-size free %d" % room in out
    assert "image-size 1 /dev/mmcblk0p3:img1 1000000000 x.raw" in out


def test_the_store_plan_names_each_image_to_the_meter_as_it_hashes_it(mk, monkeypatch):
    """The compact plan hashes every image the first time (20-30 s for two on David's
    machine) and used to say nothing meanwhile; now the tool's meter is told which image is
    being read, so the app's size strip can show the name and the percentage."""
    seen = []

    class Meter:
        def step(self, stage, budget=0):
            seen.append(("step", stage))

        def add(self, n):
            seen.append(("add", n))
    monkeypatch.setattr(mk, "source_tree", lambda path, cache_dir=None, progress=None: (
        seen.append(("hash", os.path.basename(path))) or ("man:" + path, "hashed")))
    mans = mk.measure_sources(["/x/a.raw", "/x/b.raw"], None, Meter())
    assert mans == ["man:/x/a.raw", "man:/x/b.raw"]
    assert seen == [("step", "measuring a.raw"), ("hash", "a.raw"),
                    ("step", "measuring b.raw"), ("hash", "b.raw")]
    # without a meter nothing is said, and the budget is the sources' used bytes -
    # a source that cannot be read counts nothing (the plan says why, not this)
    seen.clear()
    assert mk.measure_sources(["/x/a.raw"], None, None) == ["man:/x/a.raw"]
    assert seen == [("hash", "a.raw")]

    class G:
        @staticmethod
        def part(n):
            return (0x83, 712704, 13402110)
    monkeypatch.setattr(mk.Geometry, "from_file", staticmethod(
        lambda path: G() if path != "/x/none.raw" else (_ for _ in ()).throw(OSError(path))))
    monkeypatch.setattr(mk, "_used_bytes_or_none", lambda path, off: {
        "/x/a.raw": 3000, "/x/b.raw": None}[path] if off == 712704 * 512 else None)
    assert mk.measure_total(["/x/a.raw", "/x/b.raw", "/x/none.raw"]) == 3000


# ---- item 98: the three validator states the tool tells apart ----------------------------
def test_bypass_state_tells_a_half_bypass_from_a_whole_one(mk, monkeypatch):
    """A tick already at bx lr whose grade restore is still live is 'half': the bypass
    has to be re-applied to finish it (item 98)."""
    import pinball_decryptor.plugins.stern.valpatch as vp
    elf = bytearray(b"\0" * 64)
    monkeypatch.setattr(vp, "find_validation_exec", lambda e: 0)
    monkeypatch.setattr(vp, "find_grade_restore", lambda e: 32)
    assert mk.bypass_state(bytes(elf)) == "armed"
    elf[0:4] = vp._BX_LR
    assert mk.bypass_state(bytes(elf)) == "half"
    elf[32:36] = vp._MOV_R0_0
    assert mk.bypass_state(bytes(elf)) == "bypassed"
    monkeypatch.setattr(vp, "find_grade_restore", lambda e: None)
    assert mk.bypass_state(bytes(elf)) == "bypassed"
    assert "HALF" in mk.bypass_words("half")
