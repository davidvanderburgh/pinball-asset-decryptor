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
    assert "unreachable" not in capsys.readouterr().out
    assert mk.main(["plan", "--primary", A, "--extra", B, "--extra", C]) == 2
    err = capsys.readouterr().err
    assert "/dev/mmcblk0p8" in err and "CONFIG_MMC_BLOCK_MINORS=8" in err and "--allow-unreachable" in err
    assert mk.main(["plan", "--primary", A, "--extra", B, "--extra", C, "--allow-unreachable"]) == 0
    assert "p8 unreachable on the machine" in capsys.readouterr().out
    # build refuses BEFORE a byte is written
    out = tmp_path / "multi.img"
    assert mk.main(["build", "--primary", A, "--extra", B, "--extra", C, "--out", str(out), "--no-inject"]) == 2
    assert "p7 is the last partition" in capsys.readouterr().err
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


@pytest.mark.parametrize("cmd", ["plan", "check-stock", "build", "inject", "verify", "selftest"])
def test_every_subcommand_has_help(mk, cmd, capsys):
    with pytest.raises(SystemExit) as e:
        mk.main([cmd, "--help"])
    assert e.value.code == 0
    assert "usage:" in capsys.readouterr().out


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
    plan = mk.make_plan(A, [B, C])
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
