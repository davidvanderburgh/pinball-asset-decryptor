"""mkjjpmulti.py - the JJP multi-boot install ISO builder (item 116), pure-python parts.

Everything here runs on Windows without WSL, xorriso or partclone: the conf
writer/parser, the hook and installer patches, the boot-config redirect, the
version gate, the plan's arithmetic over hand-built IsoInfo objects and the
build.json shape.  The ISO work (restore, stage, partclone, xorriso) is
exercised by the tool's own `selftest` subcommand under WSL as root, and the
real GNR pair by the item's rig run.
"""
import argparse
import json
import os
import sys

import pytest

JJP_EMU = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "jjp_emu")

pytestmark = pytest.mark.skipif(not os.path.isfile(os.path.join(JJP_EMU, "mkjjpmulti.py")),
                                reason="mkjjpmulti.py not present")


@pytest.fixture()
def mj():
    if JJP_EMU not in sys.path:
        sys.path.insert(0, JJP_EMU)
    import mkjjpmulti
    return mkjjpmulti


# ============================================================================ names + slugs
def test_iso_slug_is_padpaths_jjp_slug(mj):
    assert mj.iso_slug("D:/Pinball/images/JJP/GunsNRoses-v03.03.iso") == "GunsNRoses-v03.03"
    assert mj.iso_slug("/mnt/d/x/CHAKAs_LOTLJ_V1.0_GNR_LE_3.03.ISO") == "CHAKAs_LOTLJ_V1.0_GNR_LE_3.03"
    assert mj.iso_slug("weird name (1).iso") == "weird_name__1"
    assert mj.cache_base("x/GunsNRoses-v03.03.iso") == os.path.join("/var/tmp", "jjp_GunsNRoses-v03.03")
    assert mj.cache_base("x/a.iso", "/tmp/c") == os.path.join("/tmp/c", "jjp_a")


def test_default_title_from_the_iso_name(mj):
    assert mj.default_title("CHAKAs_LOTLJ_V1.0_GNR_LE_3.03.iso") == "CHAKAs LOTLJ V1.0 GNR LE 3.03"
    assert mj.default_title("/x/GunsNRoses-v03.03.ISO") == "GunsNRoses-v03.03"
    assert mj.default_title("") == "image"


# ============================================================================ joliet (item 119)
def _vds(path, joliet):
    s = 2048
    b = bytearray(s * 19)
    for i, kind, esc in ((16, 1, b""), (17, 2, b"%/E"), (18, 255, b"")) if joliet else \
            ((16, 1, b""), (17, 255, b"")):
        o = i * s
        b[o] = kind
        b[o + 1:o + 6] = b"CD001"
        b[o + 6] = 1
        if esc:
            b[o + 88:o + 91] = esc
    path.write_bytes(bytes(b))
    return str(path)


def test_iso_has_joliet_reads_the_descriptors(mj, tmp_path):
    assert mj.iso_has_joliet(_vds(tmp_path / "j.iso", True)) is True
    assert mj.iso_has_joliet(_vds(tmp_path / "n.iso", False)) is False
    junk = tmp_path / "junk.iso"
    junk.write_bytes(b"\0" * 2048 * 17)
    assert mj.iso_has_joliet(str(junk)) is None


def test_the_output_iso_asks_xorriso_for_joliet(mj, tmp_path, monkeypatch):
    """xorriso writes only Rock Ridge unless told, and Windows reads Joliet: the
    GNR multi-boot stick carried SDA3_EXT4_PTCL_IMG_GZ.AA names without it."""
    out = tmp_path / "out.iso"
    seen = []

    class Proc:
        stdout = iter([b"xorriso : UPDATE : 50% done\n"])

        def wait(self):
            out.write_bytes(b"iso")
            return 0
    monkeypatch.setattr(mj, "need_tools", lambda *a: None)
    monkeypatch.setattr(mj, "iso_has_boot", lambda iso: True)
    monkeypatch.setattr(mj.subprocess, "Popen", lambda argv, **k: (seen.append(argv), Proc())[1])
    mj.xorriso_build("in.iso", str(out), [], [], [], [])
    argv = seen[0]
    assert argv[argv.index("-joliet") + 1] == "on"
    assert argv[argv.index("-boot_image") + 1:argv.index("-boot_image") + 3] == ["any", "replay"]


def test_version_info_parses_jjps_file(mj):
    text = ("###\n# Copyright (c) 2025 Jersey Jack Pinball\n###\nTitle: Guns N Roses\nName: GunsNRoses\n"
            "Version: 03.03\nType: iso\nDisksize: 111\nOS: Ubuntu 21.10\nDate: 2025-03-26\n")
    v = mj.read_version_info(text)
    assert v["Title"] == "Guns N Roses" and v["Name"] == "GunsNRoses" and v["Version"] == "03.03"
    assert v["Disksize"] == "111"
    assert mj.read_version_info(None) == {}


def test_piece_names(mj):
    assert mj.parse_piece_name("sda3.ext4-ptcl-img.gz.aa") == ("sda3", "ext4", "aa")
    assert mj.parse_piece_name("sda1.vfat-ptcl-img.gz.aa") == ("sda1", "vfat", "aa")
    assert mj.parse_piece_name("sda5.ext4-ptcl-img.gz.ag") == ("sda5", "ext4", "ag")
    assert mj.parse_piece_name("parts") is None
    assert mj.parse_piece_name("sda3.ext4-ptcl-img.gz.aa.md5") is None


# ============================================================================ the hook
RUNGAME = ("#!/bin/dash\nexport JJPEDIR='/jjpe/gen1'\n. $JJPEDIR/setenv.sh\nexport GAMEDIR=$JJPEDIR/$GAMENAME\n"
           "chmod +x $JJPEDIR/scripts/runonce.sh\n$JJPEDIR/scripts/runonce.sh\nwhile true\ndo\n  $GAMEDIR/game\ndone\n")


def test_hook_lands_after_runonce_and_strips_back(mj):
    hooked = mj.hook_rungame(RUNGAME)
    assert mj.has_hook(hooked) and not mj.has_hook(RUNGAME)
    lines = hooked.split("\n")
    i = lines.index("$JJPEDIR/scripts/runonce.sh")
    assert lines[i + 1:i + 1 + len(mj.HOOK_LINES)] == mj.HOOK_LINES
    assert lines[i + 1 + len(mj.HOOK_LINES)] == "while true"
    assert mj.hook_rungame(hooked) == hooked                       # idempotent
    assert mj.strip_hook(hooked) == RUNGAME
    assert mj.strip_hook(RUNGAME) == RUNGAME


def test_hook_line_is_executed_not_sourced(mj):
    # an `exit` in a sourced file would take rungame.sh down and loop jjp.service (item 115)
    assert mj.HOOK_LINES[-1] == "[ -x $JJPEDIR/scripts/padselect.sh ] && $JJPEDIR/scripts/padselect.sh"
    assert ". $JJPEDIR" not in mj.HOOK_LINES[-1]


def test_hook_refuses_an_unknown_rungame(mj):
    with pytest.raises(mj.Refused):
        mj.hook_rungame("#!/bin/dash\n$GAMEDIR/game\n")
    with pytest.raises(mj.Refused):
        mj.hook_rungame(RUNGAME + "$JJPEDIR/scripts/runonce.sh\n")     # two anchors


# ============================================================================ the installer
INSTALLER = """#!/bin/bash
################################################################################
# Copyright (c) 2025 Jersey Jack Pinball
################################################################################
lib_path="/jjp/lib"
function check_image {
    pieces="$medium_path/home/partimag/img/$2.gz.a?"
}
check_image "EFI"  "sda1.vfat-ptcl-img"
check_image "BOOT" "sda2.ext4-ptcl-img"
check_image "ROOT" "sda3.ext4-ptcl-img"
check_image "PERM" "sda4.ext4-ptcl-img"
restore_partition "$PART_EFI"   "sda1.vfat-ptcl-img" "$FS_UUID_EFI"
restore_partition "$PART_BOOT"  "sda2.ext4-ptcl-img" "$FS_UUID_BOOT"
restore_partition "$PART_ROOTA" "sda3.ext4-ptcl-img" "$FS_UUID_ROOTA"
restore_partition "$PART_ROOTB" "sda3.ext4-ptcl-img" "$FS_UUID_ROOTB"
halt -f
"""


def test_installer_patch_is_exactly_the_two_root_b_lines(mj):
    out = mj.patch_installer(INSTALLER)
    d = [ln for ln in mj.installer_diff(INSTALLER, out) if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    assert d == ["+" + x for x in mj.PAD_HEADER] + ["+" + mj.CHECK_ROOTB_LINE, "-" + mj.RESTORE_B_STOCK, "+" + mj.RESTORE_B_PAD]
    lines = out.split("\n")
    assert lines[0] == "#!/bin/bash"                                # the shebang stays first
    assert lines[1:1 + len(mj.PAD_HEADER)] == mj.PAD_HEADER
    i = lines.index(mj.CHECK_ROOT_LINE)
    assert lines[i + 1] == mj.CHECK_ROOTB_LINE
    assert 'restore_partition "$PART_ROOTA" "sda3.ext4-ptcl-img" "$FS_UUID_ROOTA"' in lines
    assert mj.RESTORE_B_STOCK not in lines and mj.RESTORE_B_PAD in lines
    assert mj.patch_installer(out) == out                           # idempotent


def test_installer_patch_keeps_indentation(mj):
    text = INSTALLER.replace('check_image "ROOT" "sda3.ext4-ptcl-img"', '    check_image "ROOT" "sda3.ext4-ptcl-img"')
    text = text.replace(mj.RESTORE_B_STOCK, "\t" + mj.RESTORE_B_STOCK)
    out = mj.patch_installer(text).split("\n")
    assert "    " + mj.CHECK_ROOTB_LINE in out
    assert "\t" + mj.RESTORE_B_PAD in out


def test_installer_patch_refuses_an_unknown_installer(mj):
    with pytest.raises(mj.Refused):
        mj.patch_installer(INSTALLER.replace(mj.RESTORE_B_STOCK, "restore_partition x"))
    with pytest.raises(mj.Refused):
        mj.patch_installer(INSTALLER + mj.RESTORE_B_STOCK + "\n")    # two of them


def test_cfg_redirect_is_a_bash_command_line(mj):
    cfg = "label x\n  append initrd=/live/initrd.img boot=live " + mj.OCS_STOCK + " ocs_live_batch=yes\n"
    out = mj.patch_cfg(cfg)
    assert mj.OCS_STOCK not in out and mj.OCS_PAD in out
    # Clonezilla evals the string, the medium is the stick: no exec bit and no squashfs repack needed
    assert mj.OCS_PAD == 'ocs_live_run="bash /lib/live/mount/medium/jjp/pad_install.sh"'
    assert mj.patch_cfg(out) == out
    with pytest.raises(mj.Refused):
        mj.patch_cfg("label x\n  append boot=live\n")


# ============================================================================ images.conf
def test_key_positions_are_written_parsed_and_carried(mj):
    """David's GNR headphone-kit rocker sits at byte 3 bits 6/5 (the menu's --learn line,
    2026-09-14): --key-plus / --key-minus write key_plus=/key_minus=, an inject carries
    them, a bad position is refused before anything is built."""
    import argparse
    text = mj.render_images_conf(["rootA", "rootB"], ["A", "B"], ["", ""], 0, 15, None, [], None, None, 20,
                                 keys={"key_plus": "3.6", "key_minus": "3.5"})
    assert "key_plus=3.6\n" in text and "key_minus=3.5\n" in text and "key_left=" not in text
    parsed = mj.parse_images_conf(text)
    assert parsed["keys"] == {"key_plus": "3.6", "key_minus": "3.5"}
    carried = mj.conf_for_args(["rootA", "rootB"], argparse.Namespace(), existing=parsed, default_titles=["A", "B"])
    assert "key_plus=3.6\n" in carried and "key_minus=3.5\n" in carried
    swapped = mj.conf_for_args(["rootA", "rootB"], argparse.Namespace(key_plus="3.5", key_minus="3.6"),
                               existing=parsed, default_titles=["A", "B"])
    assert "key_plus=3.5\n" in swapped and "key_minus=3.6\n" in swapped
    p = argparse.ArgumentParser()
    mj._add_conf_flags(p)
    assert p.parse_args(["--key-plus", "3.6"]).key_plus == "3.6"
    import pytest
    for bad in ("3", "3.8", "64.0", "x.1"):
        with pytest.raises(mj.Refused):
            mj.check_key_pos("key_plus", bad)


def test_the_machine_log_is_on_by_default(mj):
    """2026-09-14: the GNR's menu came up silent and nothing on the machine could say
    why.  The selector's bounded log now goes on the machine unless asked not to;
    JJP's own dumplogs.sh copies /jjpe/temp/*.log* to a stick."""
    import argparse
    p = argparse.ArgumentParser()
    mj._add_conf_flags(p)
    assert p.parse_args([]).debug_log is True
    assert p.parse_args(["--no-machine-log"]).debug_log is False
    assert p.parse_args(["--debug-log"]).debug_log is True     # the old spelling still works


def test_conf_round_trip_with_jjp_devices_and_policy(mj):
    text = mj.render_images_conf(["rootA", "rootB"], ["GUNS N' ROSES 3.03", "CHAKA'S LOTLJ"], ["Stock", "Retheme"],
                                 default=1, timeout=20, font="/jjpe/gen1/padselect/font.ttf",
                                 media=[("art0.png", "", "music0.wav", ""), ("art1.png", "anim1.gif", "", "confirm1.wav")],
                                 sound_move="move.wav", sound_confirm="confirm.wav", volume=40, theme="midnight",
                                 colors={"background": "102030"}, heading="PICK ONE", jjp_update="allow", debug_log=True)
    p = mj.parse_images_conf(text)
    assert p["images"] == [("rootA", "GUNS N' ROSES 3.03", "Stock"), ("rootB", "CHAKA'S LOTLJ", "Retheme")]
    assert p["media"] == [("art0.png", "", "music0.wav", ""), ("art1.png", "anim1.gif", "", "confirm1.wav")]
    assert p["default"] == 1 and p["timeout"] == 20 and p["volume"] == 40
    assert p["heading"] == "PICK ONE" and p["font"] == "/jjpe/gen1/padselect/font.ttf"
    assert p["sound_move"] == "move.wav" and p["sound_confirm"] == "confirm.wav"
    assert p["media_dir"] == mj.MEDIA_DIR and p["theme"] == "midnight" and p["colors"] == {"background": "102030"}
    assert p["jjp_update"] == "allow" and p["log"] == mj.JJP_CARD_LOG
    assert "image=rootB|CHAKA'S LOTLJ|Retheme|art1.png|anim1.gif||confirm1.wav" in text.splitlines()


def test_conf_is_as_narrow_as_it_needs_to_be(mj):
    bare = mj.render_images_conf(["rootA", "rootB"], ["a", "b"])
    keys = [ln.split("=", 1)[0] for ln in bare.splitlines() if ln and not ln.startswith("#")]
    assert "image=rootA|a|" in bare.splitlines() and "image=rootB|b|" in bare.splitlines()
    assert "media" not in keys and "font" not in keys and "log" not in keys
    assert "jjp_update=refuse" in bare.splitlines()                  # the policy is always spelled out
    six = mj.render_images_conf(["rootA", "rootB"], ["a", "b"], media=[("art0.png", "", "", ""), ("", "", "", "")])
    assert "image=rootA|a||art0.png||" in six.splitlines()
    assert "image=rootB|b||||" in six.splitlines()
    assert "media=/jjpe/gen1/padselect/media" in six.splitlines()


def test_conf_refusals(mj):
    with pytest.raises(mj.Refused):
        mj.render_images_conf(["/dev/mmcblk0p3", "rootB"], ["a", "b"])   # Stern's token
    with pytest.raises(mj.Refused):
        mj.render_images_conf(["rootA", "rootB"], ["a|b", "c"])
    with pytest.raises(mj.Refused):
        mj.render_images_conf(["rootA", "rootB"], ["a", "b"], default=2)
    with pytest.raises(mj.Refused):
        mj.render_images_conf(["rootA", "rootB"], ["a", "b"], jjp_update="maybe")
    with pytest.raises(mj.Refused):
        mj.render_images_conf(["rootA", "rootB"], ["a", "b"], media=[("../x.png", "", "", "")])
    with pytest.raises(mj.Refused):
        mj.parse_images_conf("default=0\n")
    with pytest.raises(mj.Refused):
        mj.parse_images_conf("image=p3|a|b\n")
    assert mj.parse_device("rootB:img2") == ("B", "img2")


def test_conf_volume_is_quiet_and_capped_for_a_jjp_machine(mj):
    """Item 120: a JJP machine plays the menu through amplifiers it keeps at full, so the
    conf always says a level (the quiet default when none is given) and the cap, and the
    builder refuses past it."""
    bare = mj.parse_images_conf(mj.render_images_conf(["rootA", "rootB"], ["a", "b"]))
    assert bare["volume"] == mj.VOLUME_DEFAULT == 20
    assert bare["volume_max"] == mj.VOLUME_MAX == 40
    assert mj.parse_images_conf(mj.render_images_conf(["rootA", "rootB"], ["a", "b"], volume=40))["volume"] == 40
    with pytest.raises(mj.Refused):
        mj.render_images_conf(["rootA", "rootB"], ["a", "b"], volume=41)
    assert "volume_max" in mj.CONF_KEYS


def test_conf_for_args_brings_an_old_loud_menu_under_the_cap(mj, capsys):
    old = mj.parse_images_conf("image=rootA|a|\nimage=rootB|b|\nvolume=50\n")      # a pre-120 install
    a = argparse.Namespace(titles=None, subtitles=None, timeout=None, default=None, volume=None, heading=None,
                           theme=None, color=None, conf=None, jjp_update=None, debug_log=False)
    p = mj.parse_images_conf(mj.conf_for_args(mj.DEVICES, a, existing=old))
    assert p["volume"] == 40 and p["volume_max"] == 40
    said = capsys.readouterr()
    assert "above the JJP cap" in said.out + said.err
    a.volume = 50                                 # asked for outright: refused, not quietly cut
    with pytest.raises(mj.Refused):
        mj.conf_for_args(mj.DEVICES, a, existing=old)


def test_media_step_levels_every_sound_and_caps_the_volume(mj, monkeypatch, tmp_path):
    import selectmedia
    seen = []

    def fake_main(argv):
        seen.append(list(argv))
        return 0

    monkeypatch.setattr(selectmedia, "main", fake_main)
    a = argparse.Namespace(primary="a.iso", extra=["b.iso"], out=str(tmp_path / "m"), art=["0=none", "1=none"],
                           anim=[], music=[], sound_move="synth", sound_confirm=None, volume=None, size=None,
                           visual_only=False, work=None, cache_dir=None)
    assert mj.cmd_media(a) == 0
    argv = seen[-1]
    assert argv[argv.index("--volume") + 1] == "20"
    assert argv[argv.index("--peak-dbfs") + 1] == "-3"
    a.volume = 41
    with pytest.raises(mj.Refused):
        mj.cmd_media(a)


def test_conf_for_args_carries_an_existing_menu_through(mj):
    old = mj.parse_images_conf(mj.render_images_conf(["rootA", "rootB"], ["Old0", "Old1"], ["s0", "s1"], default=1,
                                                     timeout=30, theme="midnight", heading="H", jjp_update="allow",
                                                     media=[("art0.png", "", "", ""), ("art1.png", "anim1.gif", "", "")],
                                                     sound_move="move.wav", volume=33))
    a = argparse.Namespace(titles="New0;New1", subtitles=None, timeout=None, default=None, volume=None, heading=None,
                           theme=None, color=None, conf=None, jjp_update=None, debug_log=False)
    p = mj.parse_images_conf(mj.conf_for_args(mj.DEVICES, a, existing=old))
    assert [t for _d, t, _s in p["images"]] == ["New0", "New1"]
    assert [s for _d, _t, s in p["images"]] == ["s0", "s1"]
    assert p["default"] == 1 and p["timeout"] == 30 and p["theme"] == "midnight" and p["heading"] == "H"
    assert p["jjp_update"] == "allow" and p["media"][1] == ("art1.png", "anim1.gif", "", "")
    assert p["sound_move"] == "move.wav" and p["volume"] == 33 and p["log"] is None
    # no existing conf: the defaults and the given titles
    b = argparse.Namespace(titles=None, subtitles=None, timeout=None, default=None, volume=None, heading=None,
                           theme=None, color=None, conf=None, jjp_update=None, debug_log=False)
    q = mj.parse_images_conf(mj.conf_for_args(mj.DEVICES, b, default_titles=["Guns N Roses 03.03", "Chaka"]))
    assert [t for _d, t, _s in q["images"]] == ["Guns N Roses 03.03", "Chaka"]
    assert q["default"] == 0 and q["timeout"] == 15 and q["jjp_update"] == "refuse"


def test_conf_verbatim_must_name_the_same_devices(mj, tmp_path):
    good = tmp_path / "good.conf"
    good.write_text(mj.render_images_conf(["rootA", "rootB"], ["a", "b"]))
    a = argparse.Namespace(conf=str(good))
    assert mj.conf_for_args(mj.DEVICES, a) == good.read_text()
    bad = tmp_path / "bad.conf"
    bad.write_text(mj.render_images_conf(["rootA"], ["a"]))
    with pytest.raises(mj.Refused):
        mj.conf_for_args(mj.DEVICES, argparse.Namespace(conf=str(bad)))


# ============================================================================ the gate + the plan
def _info(mj, path, name="GunsNRoses", version="03.03", pieces=(1000000000, 797331236), overhead=600000000):
    info = mj.IsoInfo(path)
    info.version = {"Title": "Guns N Roses", "Name": name, "Version": version}
    info.pieces = {"sda3": [("sda3.ext4-ptcl-img.gz.a" + chr(ord("a") + i), s) for i, s in enumerate(pieces)],
                   "sda1": [("sda1.vfat-ptcl-img.gz.aa", 2358904)]}
    info.files = [(mj.PARTIMAG + "/" + n, s) for n, s in info.pieces["sda3"] + info.pieces["sda1"]] + \
                 [("/live/filesystem.squashfs", overhead - 2358904)]
    info.has_squashfs = True
    return info


def _ident(sha="c4672be7", fl="e92e8bcb", name="GunsNRoses", used=7685017600):
    return {"gamename": name, "game_sha256": sha * 8, "fldat_sha256": fl * 8, "used_bytes": used}


def test_same_version_gate_passes_a_retheme_and_refuses_a_version(mj):
    infos = [_info(mj, "stock.iso"), _info(mj, "chaka.iso")]
    assert mj.check_same_version(infos, [_ident(), _ident(used=8391864320)]) == []
    with pytest.raises(mj.Refused) as e:
        mj.check_same_version([_info(mj, "a.iso"), _info(mj, "b.iso", version="03.04")], [_ident(), _ident()])
    assert "03.04" in str(e.value) and "--allow-version-mismatch" in str(e.value)
    with pytest.raises(mj.Refused) as e:
        mj.check_same_version(infos, [_ident(), _ident(sha="deadbeef")])
    assert "game binary differs" in str(e.value)
    with pytest.raises(mj.Refused) as e:
        mj.check_same_version(infos, [_ident(), _ident(fl="00000000")])
    assert "fl.dat differs" in str(e.value)
    why = mj.check_same_version(infos, [_ident(), _ident(name="Wonka")], allow=True)
    assert len(why) == 1 and "GAMENAME" in why[0]


def test_iso_info_helpers(mj):
    info = _info(mj, "stock.iso")
    assert info.piece_bytes("sda3") == 1797331236
    assert info.split_size() == 1000000000
    assert info.overhead_bytes() == 600000000                     # everything but the root pieces
    one = _info(mj, "small.iso", pieces=(500000,))
    assert one.split_size() == mj.SPLIT_DEFAULT                   # a lone piece proves nothing
    info.check_stock_shape()
    bad = _info(mj, "x.iso")
    bad.has_squashfs = False
    with pytest.raises(mj.Refused):
        bad.check_stock_shape()


def test_plan_math_and_stick_fit(mj, monkeypatch):
    infos = {"stock.iso": _info(mj, "stock.iso", pieces=(1000000000,) * 5 + (797331236,)),
             "chaka.iso": _info(mj, "chaka.iso", pieces=(1000000000,) * 6 + (518261539,))}
    monkeypatch.setattr(mj, "iso_info", lambda iso, mnt=None: infos[os.path.basename(iso)])
    monkeypatch.setattr(mj, "cached_root_raw", lambda *a, **k: None)
    plan = mj.make_plan("stock.iso", ["chaka.iso"])
    c0, c1 = 5797331236, 6518261539
    assert plan["image_bytes"][1] == c1
    assert plan["image_bytes"][0] == int(c0 * 1.01) + 1000000
    assert plan["overhead"] == 600000000 + 2000000
    assert plan["total"] == sum(plan["image_bytes"]) + plan["overhead"]
    assert plan["fits"]["8G"][0] is False and plan["fits"]["16G"][0] is True
    assert plan["fits"]["16G"][1] == mj.USB_SIZES["16G"] - plan["total"]
    assert plan["idents"] == [None, None]
    with pytest.raises(mj.Refused):
        mj.make_plan("stock.iso", [])
    with pytest.raises(mj.Refused):
        mj.make_plan("stock.iso", ["chaka.iso", "chaka.iso"])


def test_plan_prints_the_protocol_rows(mj, monkeypatch, capsys):
    infos = {"stock.iso": _info(mj, "stock.iso"), "chaka.iso": _info(mj, "chaka.iso")}
    monkeypatch.setattr(mj, "iso_info", lambda iso, mnt=None: infos[os.path.basename(iso)])
    monkeypatch.setattr(mj, "cached_root_raw", lambda *a, **k: None)
    mj.print_plan(mj.make_plan("stock.iso", ["chaka.iso"]))
    out = capsys.readouterr().out.splitlines()
    assert any(ln.startswith("image-size 0 rootA ") for ln in out)
    assert any(ln.startswith("image-size 1 rootB 1797331236 ") for ln in out)
    assert any(ln.startswith("image-size overhead ") for ln in out)
    assert any(ln.startswith("iso-size ") for ln in out)
    assert any(ln.startswith("fits USB 8G stick size ") and ln.endswith(")") for ln in out)
    assert any(ln.startswith("version 0 rootA GunsNRoses 03.03 ") for ln in out)
    assert "stick: 8G" in out


# ============================================================================ build.json
def test_build_manifest_shape_and_carry_through(mj):
    conf = mj.parse_images_conf(mj.render_images_conf(["rootA", "rootB"], ["a", "b"], ["s", "t"],
                                                      media=[("art0.png", "", "", ""), ("", "anim1.gif", "", "")]))
    infos = [_info(mj, "/x/stock.iso"), _info(mj, "/x/chaka.iso")]
    m = mj.build_manifest(conf, ["/x/stock.iso", "/x/chaka.iso"], infos, [_ident(), _ident(used=8391864320)],
                          staged={"/jjpe/gen1/padselect/jjpselect": "ab" * 32}, split_size=1000000000,
                          installer={"stock_sha256": "1", "pad_sha256": "2", "diff": []}, written="2026-09-13T00:00:00Z")
    assert m["tool"] == "mkjjpmulti" and m["layout"] == "jjp-ab" and m["split_size"] == 1000000000
    assert [im["device"] for im in m["images"]] == ["rootA", "rootB"]
    assert m["images"][1]["anim"] == "anim1.gif" and m["images"][0]["art"] == "art0.png" and m["images"][0]["anim"] is None
    assert m["images"][1]["used_bytes"] == 8391864320 and m["images"][1]["pieces"] == 2
    assert m["images"][0]["source"] == os.path.abspath("/x/stock.iso")
    assert m["images"][0]["name"] == "GunsNRoses" and m["images"][0]["game_version"] == "03.03"
    assert m["staged"] == {"/jjpe/gen1/padselect/jjpselect": "ab" * 32}
    assert m["jjp_update"] == "refuse"
    json.dumps(m)
    # an inject: no new info for image 1 -> its record is carried from the old manifest by device
    conf2 = mj.parse_images_conf(mj.render_images_conf(["rootA", "rootB"], ["a2", "b2"]))
    m2 = mj.build_manifest(conf2, [None, None], [infos[0], None], [_ident(), None], existing=m)
    assert m2["images"][1]["source"] == os.path.abspath("/x/chaka.iso") and m2["images"][1]["used_bytes"] == 8391864320
    assert m2["images"][1]["title"] == "b2" and m2["split_size"] == 1000000000 and m2["installer"]["pad_sha256"] == "2"
    assert mj.parse_manifest(b"{not json", "build.json", []) is None
    assert mj.parse_manifest(json.dumps(m).encode(), "build.json")["tool"] == "mkjjpmulti"


def test_selector_files_and_paths(mj):
    assert list(mj.SELECTOR_FILES) == ["jjpselect", "padselect.sh", "font.ttf"]
    assert mj.PADSELECT_DIR == "/jjpe/gen1/padselect" and mj.HOOK_PATH == "/jjpe/gen1/scripts/padselect.sh"
    assert mj.ROOTB_PIECE == "sda5.ext4-ptcl-img" and mj.PAD_INSTALLER == "/jjp/pad_install.sh"
    assert mj.CFG_FILES == ("/syslinux/syslinux.cfg", "/boot/grub/grub.cfg")
