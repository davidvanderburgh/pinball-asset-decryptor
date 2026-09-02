"""mkmulticard.py - the multi-image Spike 2 card builder (item 90), pure-python parts.

The bytes here were read off the stock 8G turtles_pro 1.59.0 card (the four MBR
entries and both EBR sectors) and the layout numbers off the same card and the
16G / 32G ones; the builder must regenerate them byte-identically before it is
allowed near a real image.  Everything below runs on Windows without WSL, dd or
debugfs: geometries are constructed, synthetic cards are a few MiB of random
bytes in tmp_path, and the ext4 injection (which needs debugfs) is exercised by
the tool's own `selftest` subcommand under WSL instead.
"""
import hashlib
import json
import os
import re
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


# ---- images.conf v2 (item 90 media): 6-field image lines + the global keys ---------------
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
    assert conf["media"] == [("art0.png", "", ""), ("art1.png", "anim1.gif", "music1.wav"), ("", "", "")]
    assert (conf["sound_move"], conf["sound_confirm"], conf["volume"], conf["mixer_volume"]) == ("move.wav", "confirm.wav", 35, 20)
    assert conf["media_dir"] == mk.MEDIA_DIR and conf["default"] == 1 and conf["timeout"] == 0
    assert mk.conf_media_names(conf) == ["anim1.gif", "art0.png", "art1.png", "confirm.wav", "move.wav", "music1.wav"]
    assert [mk.parse_device(d) for (d, _t, _s) in conf["images"]] == [(3, None), (7, "img1"), (7, "img2")]


def test_a_three_field_image_line_stays_valid_and_unknown_keys_are_ignored(mk):
    conf = mk.parse_images_conf("image=/dev/mmcblk0p3|STERN|stock\nimage=/dev/mmcblk0p7|TMNT 1987\n"
                                "default=1\ntimeout=15\nanim_fps=12\nfont=/x.ttf\n")
    assert conf["images"] == [("/dev/mmcblk0p3", "STERN", "stock"), ("/dev/mmcblk0p7", "TMNT 1987", "")]
    assert conf["media"] == [("", "", ""), ("", "", "")]
    assert conf["sound_move"] is None and conf["volume"] is None and conf["media_dir"] is None
    assert mk.conf_media_names(conf) == []
    # no media anywhere -> the 3-field form is what gets written, and no media= key
    text = mk.render_images_conf(["/dev/mmcblk0p3", "/dev/mmcblk0p7"], ["A", "B"], media=[None, ("", "", "")])
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    assert lines == ["image=/dev/mmcblk0p3|A|", "image=/dev/mmcblk0p7|B|", "default=0", "timeout=15"]


@pytest.mark.parametrize("bad", [
    "image=/dev/mmcblk0p3|A|a|art.png|anim.gif|music.wav|extra\n",           # 7 fields
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
    assert list(ms["files"]) == ["art0.png", "art1.png", "anim1.gif", "music1.wav", "move.wav", "confirm.wav"]
    assert ms["rows"] == [("art0.png", "", ""), ("art1.png", "anim1.gif", "music1.wav")]
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
    mk.synth_gif(str(many), 2, 2, 31)
    with pytest.raises(mk.Refused, match="31 frames"):
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
    with pytest.raises(mk.Refused, match="not 'parts' or 'multi'"):
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
    valpatch, _s, ext4 = mk._stern_plugins()
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
        state, writes, notes = mk.compute_bypass_writes(r, 2)
        assert state == "armed" and sum(len(b) for (_d, b) in writes) == 4 + 20 + 16, notes
        assert all(st * 512 <= d < (st + cnt) * 512 for (d, _b) in writes), "every write lands inside p3"
    assert mk.tree_state(STOCK_CARD, G and mk.Part(3, 0x83, st, cnt, STOCK_CARD, st, None), None)[0] == "armed"


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


@pytest.mark.parametrize("cmd", ["plan", "check-stock", "build", "inject", "inspect", "bypass", "verify", "selftest"])
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
                            written="2026-09-02T00:00:00Z")
    assert man["tool"] == "mkmulticard" and man["version"] == mk.VERSION
    assert man["written"] == "2026-09-02T00:00:00Z" and man["layout"] == "parts"
    assert (man["timeout"], man["default"]) == (20, 1)
    assert (man["volume"], man["mixer_volume"]) == (35, 20)
    assert (man["sound_move"], man["sound_confirm"]) == ("move.wav", "confirm.wav")
    assert man["images"] == [
        {"device": "/dev/mmcblk0p3", "source": os.path.abspath("/img/a.raw"), "title": "STERN 1.59.0",
         "subtitle": "Original Stern code", "art": "art0.png", "anim": None, "music": None},
        {"device": "/dev/mmcblk0p7", "source": os.path.abspath("/img/b.raw"), "title": "TMNT 1987",
         "subtitle": "1987 cartoon upscale", "art": "art1.png", "anim": "anim1.gif", "music": "music1.wav"}]
    # it is JSON, and exactly the keys contract A names
    d = json.loads(json.dumps(man))
    assert set(d) == {"tool", "version", "written", "layout", "images", "timeout", "default",
                      "volume", "mixer_volume", "sound_move", "sound_confirm"}
    # a card with no media at all: the fields are null, not absent
    plain = mk.build_manifest(plan, mk.parse_images_conf(_menu_conf(mk, plan)), None)
    assert [im["art"] for im in plain["images"]] == [None, None]
    assert plain["volume"] is None and plain["sound_move"] is None and plain["images"][0]["source"] is None


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
    [(name, mode, size)]}, `trees` {device: (validator state, title dir)}."""
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

    def state(card, part, sub):
        got = (trees or {}).get(mk.device_name(part.num, sub))
        if got is None:
            raise mk.Refused("no title directory with a game file in this tree")
        return got[0], got[1], got[1] + "/game"

    monkeypatch.setattr(mk, "debugfs_cat", cat)
    monkeypatch.setattr(mk, "debugfs_ls", ls)
    monkeypatch.setattr(mk, "tree_state", state)


def _loaded_card(mk, tmp_path, monkeypatch, with_build=True, with_media_json=True, sources=None):
    out, srcs, plan = _synth_card(mk, tmp_path)
    conf = mk.render_images_conf(plan.devices(), ["STERN 1.59.0", "TMNT 1987"],
                                 ["Original Stern code", "1987 cartoon upscale"], 1, 20,
                                 mk.SELECT_DIR + "/font.ttf",
                                 media=[("art0.png", "", ""), ("art1.png", "anim1.gif", "music1.wav")],
                                 sound_move="move.wav", sound_confirm="confirm.wav", volume=35)
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
    _fake_p2(mk, monkeypatch, files, dirs,
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
                        "has_build_json", "selector", "warnings"}
    assert json.loads(json.dumps(rep))["images"][1]["title"] == "TMNT 1987"
    # --media-out gives back a directory that IS a --media-dir again
    d = tmp_path / "loaded"
    assert sorted(p.name for p in d.iterdir()) == ["anim1.gif", "art0.png", "art1.png", "confirm.wav",
                                                   "media.json", "move.wav", "music1.wav"]
    assert (d / "art0.png").read_bytes() == b"png-zero"
    assert json.loads((d / "media.json").read_bytes())["images"][1]["anim_source"] == "auto@20:2:8"
    assert rep["media_out"]["files"] == 7


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
