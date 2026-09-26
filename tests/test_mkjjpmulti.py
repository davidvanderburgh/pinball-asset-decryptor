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


RUNGAME_CASES = ("#!/bin/dash\nexport JJPEDIR='/jjpe/gen1'\n. $JJPEDIR/setenv.sh\n$JJPEDIR/scripts/runonce.sh\n"
                 "while true\ndo\n  $GAMEDIR/game\n  result=\"$?\"\n  case \"$result\" in\n"
                 "    42) # net img or delta update\n        reboot\n        sleep 99 ;;\n"
                 "    43) # settings restore - need to restart the game\n        ;;\n"
                 "    68) # maintenance reboot (hostname set)\n        reboot\n        sleep 99 ;;\n"
                 "    69) # maintenance reboot\n        $jimage 5000 $graphics/JJP_logo_message.png \\\n"
                 "            \"MAINTENANCE REBOOT\" \"Please wait ...\"\n        reboot\n        sleep 99 ;;\n"
                 "  esac\ndone\n")


def test_maintenance_reboots_tell_the_hook_first(mj):
    """David, 2026-09-14: the menu must not show twice after a fresh install.  The game
    exits 68/69 and rungame.sh reboots; the builder's second patch calls the hook with
    --maintenance-reboot right before those reboots (and not before the update reboot),
    idempotently, and strip_hook takes it back out."""
    hooked = mj.hook_rungame(RUNGAME_CASES)
    lines = hooked.split("\n")
    at = [i for i, ln in enumerate(lines) if ln.strip() == mj.MAINT_CALL]
    assert len(at) == 2 and all(lines[i + 1].strip() == "reboot" for i in at)
    assert all(lines[i].startswith("        [") for i in at)              # indented like the reboot
    assert lines[lines.index("    42) # net img or delta update") + 1].strip() == "reboot"
    assert lines[lines.index("    68) # maintenance reboot (hostname set)") + 1].strip() == mj.MAINT_CALL
    assert mj.hook_rungame(hooked) == hooked
    assert mj.strip_hook(hooked) == RUNGAME_CASES
    assert mj.hook_line_count(hooked) == 1 and hooked.count(mj.HOOK_LINES[2]) == 3   # whole lines, not substrings
    assert mj.mark_maintenance_reboots(RUNGAME) == RUNGAME                # no such cases: untouched
    assert "--maintenance-reboot" in mj.MAINT_CALL and mj.MAINT_CALL.startswith("[ -x ")


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
    for bad in ("3", "3.8", "64.0", "x.1", "3.0,", "3.0,3.4,3.5", "3.0,x.1"):
        with pytest.raises(mj.Refused):
            mj.check_key_pos("key_plus", bad)
    # two places for one button: the GNR's lockdown-bar Action button is a second START
    # (David, 2026-09-14 evening) - written, parsed and carried as one value
    assert mj.check_key_pos("key_start", "3.0, 3.4") == "3.0,3.4"
    two = mj.render_images_conf(["rootA", "rootB"], ["A", "B"], ["", ""], 0, 15, None, [], None, None, 20,
                                keys={"key_start": "3.0,3.4"})
    assert "key_start=3.0,3.4\n" in two
    assert mj.parse_images_conf(two)["keys"] == {"key_start": "3.0,3.4"}
    assert p.parse_args(["--key-start", "3.0,3.4"]).key_start == "3.0,3.4"


def test_the_machine_log_and_learn_are_off_by_default(mj):
    """2026-09-14: the GNR's menu came up silent and the selector's bounded log went on
    the machine by default; 2026-09-15, everything working, David asked for the logs off.
    --machine-log puts it back; --learn (learn=1, the hook's --learn) implies it and is
    carried by an inject."""
    import argparse
    p = argparse.ArgumentParser()
    mj._add_conf_flags(p)
    assert p.parse_args([]).debug_log is False and p.parse_args([]).learn is False
    assert p.parse_args(["--machine-log"]).debug_log is True
    assert p.parse_args(["--no-machine-log"]).debug_log is False
    assert p.parse_args(["--debug-log"]).debug_log is True     # the old spelling still works
    assert p.parse_args(["--learn"]).learn is True
    quiet = mj.conf_for_args(["rootA", "rootB"], argparse.Namespace(), default_titles=["A", "B"])
    assert "log=" not in quiet and "learn=" not in quiet
    loud = mj.conf_for_args(["rootA", "rootB"], argparse.Namespace(learn=True), default_titles=["A", "B"])
    assert "learn=1\n" in loud and "log=/jjpe/temp/jjpselect.log\n" in loud
    parsed = mj.parse_images_conf(loud)
    assert parsed["learn"] == "1"
    carried = mj.conf_for_args(["rootA", "rootB"], argparse.Namespace(), existing=parsed, default_titles=["A", "B"])
    assert "learn=1\n" in carried and "log=" in carried


def mkc_text_sizes():
    """The two words images.conf's text_size= takes, from the shared module the JJP
    builder imports them through (PAD-183)."""
    import mkmulticard
    return mkmulticard.TEXT_SIZES


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
    # THE TEXT SIZE (PAD-183): the same key the Stern builder writes, and the same
    # silence when nobody asked - the menu draws at one size either way
    assert "text_size" not in text and p["text_size"] is None and "text_size" in mj.CONF_KEYS
    for word in mkc_text_sizes():
        again = mj.render_images_conf(["rootA", "rootB"], ["a", "b"], text_size=word)
        assert "text_size=%s" % word in again.splitlines()
        assert mj.parse_images_conf(again)["text_size"] == word
    with pytest.raises(mj.Refused):
        mj.render_images_conf(["rootA", "rootB"], ["a", "b"], text_size="enormous")
    # ...and an install's own word rides through an inject that does not name one
    old = mj.parse_images_conf(mj.render_images_conf(["rootA", "rootB"], ["a", "b"], text_size="per-card"))
    a = argparse.Namespace(titles=None, subtitles=None, timeout=None, default=None, volume=None,
                           heading=None, theme=None, color=None, conf=None, jjp_update=None,
                           debug_log=False)
    assert mj.parse_images_conf(mj.conf_for_args(mj.DEVICES, a, existing=old))["text_size"] == "per-card"


def test_the_two_lines_under_the_cards_are_the_stern_builder_s_keys(mj):
    """PAD-190: counter= and countdown_word= are the same keys the Stern builder
    writes, validated by the same shared functions, and neither is written until
    somebody asks - a JJP install that says nothing draws the counter line and says
    'starting', exactly as a card does."""
    import mkmulticard
    bare = mj.render_images_conf(["rootA", "rootB"], ["a", "b"])
    p = mj.parse_images_conf(bare)
    assert "counter" not in bare and "countdown_word" not in bare
    assert p["counter"] is None and p["countdown_word"] is None
    assert "counter" in mj.CONF_KEYS and "countdown_word" in mj.CONF_KEYS
    for word in mkmulticard.COUNTERS:
        text = mj.render_images_conf(["rootA", "rootB"], ["a", "b"], counter=word)
        assert "counter=%s" % word in text.splitlines()
        assert mj.parse_images_conf(text)["counter"] == word
    for word in ("Launching", ""):
        text = mj.render_images_conf(["rootA", "rootB"], ["a", "b"],
                                     countdown_word=word)
        assert "countdown_word=%s" % word in text.splitlines()
        assert mj.parse_images_conf(text)["countdown_word"] == word
    with pytest.raises(mj.Refused):
        mj.render_images_conf(["rootA", "rootB"], ["a", "b"], counter="hidden")
    # ...and an install's own answers ride through an inject that names neither
    old = mj.parse_images_conf(mj.render_images_conf(
        ["rootA", "rootB"], ["a", "b"], counter="off", countdown_word="Booting"))
    a = argparse.Namespace(titles=None, subtitles=None, timeout=None, default=None,
                           volume=None, heading=None, theme=None, color=None,
                           conf=None, jjp_update=None, debug_log=False)
    back = mj.parse_images_conf(mj.conf_for_args(mj.DEVICES, a, existing=old))
    assert back["counter"] == "off" and back["countdown_word"] == "Booting"


def test_the_instructions_line_is_the_stern_builder_s_key(mj):
    """PAD-190 round 2: footer= is the same key, validated by the same shared
    function, with the same three answers - and a JJP install that says nothing
    still draws the selector's own line."""
    bare = mj.render_images_conf(["rootA", "rootB"], ["a", "b"])
    assert "footer" not in bare
    assert mj.parse_images_conf(bare)["footer"] is None
    assert "footer" in mj.CONF_KEYS
    for text in ("FLIPPERS choose    START boots", ""):
        conf = mj.render_images_conf(["rootA", "rootB"], ["a", "b"], footer=text)
        assert "footer=%s" % text in conf.splitlines()
        assert mj.parse_images_conf(conf)["footer"] == text
    with pytest.raises(mj.Refused):
        mj.render_images_conf(["rootA", "rootB"], ["a", "b"],
                              footer="two" + chr(10) + "lines")
    old = mj.parse_images_conf(mj.render_images_conf(
        ["rootA", "rootB"], ["a", "b"], footer="FLIPPERS choose"))
    a = argparse.Namespace(titles=None, subtitles=None, timeout=None, default=None,
                           volume=None, heading=None, theme=None, color=None,
                           conf=None, jjp_update=None, debug_log=False)
    assert mj.parse_images_conf(mj.conf_for_args(
        mj.DEVICES, a, existing=old))["footer"] == "FLIPPERS choose"
    own = argparse.Namespace(**dict(vars(a), footer_own=True))
    assert mj.parse_images_conf(mj.conf_for_args(
        mj.DEVICES, own, existing=old))["footer"] is None


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
    """Item 120 / PAD-219: a JJP machine plays the menu through amplifiers it keeps at
    full, so the conf always says a level (the default when none is given) and the cap,
    and the builder refuses past it.  The scale is 0-100 like Stern's (the selector's
    JJP build plays 100 at 30% of the samples); it was 0-40 with 20 the default."""
    bare = mj.parse_images_conf(mj.render_images_conf(["rootA", "rootB"], ["a", "b"]))
    assert bare["volume"] == mj.VOLUME_DEFAULT == 50
    assert bare["volume_max"] == mj.VOLUME_MAX == 100
    assert mj.parse_images_conf(mj.render_images_conf(["rootA", "rootB"], ["a", "b"], volume=100))["volume"] == 100
    with pytest.raises(mj.Refused):
        mj.render_images_conf(["rootA", "rootB"], ["a", "b"], volume=101)
    assert "volume_max" in mj.CONF_KEYS


def test_conf_for_args_keeps_an_existing_menus_volume(mj, capsys):
    """An install's volume=50 (loud on the old 0-40 scale, where the builder used to bring
    it down to 40) is a middling level on the 0-100 scale and is kept as it stands."""
    old = mj.parse_images_conf("image=rootA|a|\nimage=rootB|b|\nvolume=50\n")
    a = argparse.Namespace(titles=None, subtitles=None, timeout=None, default=None, volume=None, heading=None,
                           theme=None, color=None, conf=None, jjp_update=None, debug_log=False)
    p = mj.parse_images_conf(mj.conf_for_args(mj.DEVICES, a, existing=old))
    assert p["volume"] == 50 and p["volume_max"] == 100
    said = capsys.readouterr()
    assert "above the JJP cap" not in said.out + said.err
    a.volume = 101                                # asked for above the cap outright: refused
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
    assert argv[argv.index("--volume") + 1] == "50"      # the default is 50 of 100 (PAD-219)
    assert argv[argv.index("--peak-dbfs") + 1] == "-3"
    a.volume = 101
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


# ============================================================================ install (a disk)
GNR_INSTALLER_LINES = """#!/bin/bash
lib_path="/jjp/lib"
sgdisk_backup30="${lib_path}/backup.sgdisk1"
sgdisk_backup60="${lib_path}/backup.sgdisk2"
sgdisk_backup120="${lib_path}/backup.sgdisk3"

FS_UUID_EFI="DD8B8D65"
FS_UUID_BOOT="61af91e2-2fcf-4434-8508-4d1aaf8d2c59"
FS_UUID_ROOTA="d8223f69-d29a-474f-a837-0a11dccc27f2"
FS_UUID_ROOTB="e1a1fecc-e0a1-4daa-9c51-9a8fbd2c2f87"
FS_UUID_PERMA="3930f288-dba6-4e1a-ab3d-5a23b73aae76"
FS_UUID_PERMB="bb26c099-d746-457e-abcc-dad19f55c7ab"
FS_UUID_TEMP="76695bac-6f28-4546-8fad-d3b121016394"
min_disk_size_gib="111"
elif [[ "$disk_size" -lt $(( $min_disk_size_gib * 1024 * 1024 * 1024 )) ]]
then
    jjp_error "Storage device $dest_disk not large enough"
fi
PART_EFI="${dest_disk}${part_prefix}1"
PART_BOOT="${dest_disk}${part_prefix}2"
PART_ROOTA="${dest_disk}${part_prefix}3"
PART_ROOTB="${dest_disk}${part_prefix}5"
PART_PERMA="${dest_disk}${part_prefix}4"
PART_PERMB="${dest_disk}${part_prefix}6"
PART_TEMP="${dest_disk}${part_prefix}7"
if [[ "$compatible" != "true" ]]
then
    # choose the partition table to use
    backup_to_use="$sgdisk_backup120"
    if [[ "$disk_size" -lt $((55 * 1024 * 1024 * 1024)) ]]
    then
        backup_to_use="$sgdisk_backup30"
    elif [[ "$disk_size" -lt $((111 * 1024 * 1024 * 1024)) ]]
    then
        backup_to_use="$sgdisk_backup60"
    fi
    sgdisk -Z "$dest_disk" &> /dev/null
    sgdisk --load-backup="$backup_to_use" "$dest_disk" &> /dev/null
fi
restore_partition "$PART_EFI"   "sda1.vfat-ptcl-img" "$FS_UUID_EFI"
restore_partition "$PART_BOOT"  "sda2.ext4-ptcl-img" "$FS_UUID_BOOT"
restore_partition "$PART_ROOTA" "sda3.ext4-ptcl-img" "$FS_UUID_ROOTA"
restore_partition "$PART_ROOTB" "sda5.ext4-ptcl-img" "$FS_UUID_ROOTB"

if [[ "$compatible" != "true" ]]
then
    restore_partition "$PART_PERMA" "sda4.ext4-ptcl-img" "$FS_UUID_PERMA"
    restore_partition "$PART_PERMB" "sda4.ext4-ptcl-img" "$FS_UUID_PERMB"
else
    :
fi
mkfs.ext4 -F "$PART_TEMP" &> /dev/null
e2fsck -f -y "$PART_TEMP" &> /dev/null
tune2fs "$PART_TEMP" -f -U "$FS_UUID_TEMP" &> /dev/null
halt -f
"""


def test_parse_installer_reads_the_gnr_installer(mj):
    """The lines `install` runs are the installer's own: seven slots, the UUIDs grub and
    fstab expect, three templates by size, the six restores in order (a pad_install.sh
    puts sda5 in root B), the temp partition."""
    ins = mj.parse_installer(GNR_INSTALLER_LINES)
    assert ins["parts"] == {"EFI": 1, "BOOT": 2, "ROOTA": 3, "ROOTB": 5, "PERMA": 4, "PERMB": 6, "TEMP": 7}
    assert ins["uuids"]["ROOTA"] == "d8223f69-d29a-474f-a837-0a11dccc27f2"
    assert ins["uuids"]["EFI"] == "DD8B8D65"
    assert ins["templates"] == {"30": "backup.sgdisk1", "60": "backup.sgdisk2", "120": "backup.sgdisk3"}
    assert ins["choices"] == [(55, "30"), (111, "60")] and ins["default"] == "120"
    assert [r[0] for r in ins["restores"]] == ["EFI", "BOOT", "ROOTA", "ROOTB", "PERMA", "PERMB"]
    assert ins["restores"][3] == ("ROOTB", "sda5.ext4-ptcl-img", "ROOTB")
    assert ins["min_disk_gib"] == 111
    # the stock installer: root B from sda3
    stock = mj.parse_installer(GNR_INSTALLER_LINES.replace('"sda5.ext4-ptcl-img"', '"sda3.ext4-ptcl-img"'))
    assert stock["restores"][3] == ("ROOTB", "sda3.ext4-ptcl-img", "ROOTB")


def test_parse_installer_reads_the_fake_installer_the_same_way(mj):
    fake = mj.parse_installer(mj.FAKE_INSTALLER)
    real = mj.parse_installer(GNR_INSTALLER_LINES)
    assert fake["parts"] == real["parts"] and fake["uuids"] == real["uuids"] and fake["templates"] == real["templates"]
    assert fake["choices"] == real["choices"] and fake["default"] == real["default"]
    assert [r[0] for r in fake["restores"]] == [r[0] for r in real["restores"]]
    assert mj.FAKE_UUIDS == real["uuids"]


def test_pick_template_is_the_installers_size_ladder(mj):
    ins = mj.parse_installer(GNR_INSTALLER_LINES)
    assert mj.pick_template(ins, 30 * 1000 ** 3) == "backup.sgdisk1"
    assert mj.pick_template(ins, 60 * 1000 ** 3) == "backup.sgdisk2"
    assert mj.pick_template(ins, (111 << 30) - 1) == "backup.sgdisk2"
    assert mj.pick_template(ins, 111 << 30) == "backup.sgdisk3"
    assert mj.pick_template(ins, 120 * 1000 ** 3) == "backup.sgdisk3"
    assert mj.pick_template(ins, 2 * 1000 ** 4) == "backup.sgdisk3"


def test_part_dev_follows_the_installers_prefix_rule(mj):
    assert mj.part_dev("/dev/sda", 3) == "/dev/sda3"
    assert mj.part_dev("/dev/nvme0n1", 5) == "/dev/nvme0n1p5"
    assert mj.part_dev("/dev/loop7", 1) == "/dev/loop7p1"


@pytest.mark.parametrize("drop, why", [
    ('PART_TEMP="${dest_disk}${part_prefix}7"\n', "PART_TEMP"),
    ('FS_UUID_ROOTB="e1a1fecc-e0a1-4daa-9c51-9a8fbd2c2f87"\n', "FS_UUID_ROOTB"),
    ('mkfs.ext4 -F "$PART_TEMP" &> /dev/null\n', "mkfs"),
    ('sgdisk_backup120="${lib_path}/backup.sgdisk3"\n', "sgdisk_backup120"),
    ('min_disk_size_gib="111"\n', "min_disk_size_gib"),
])
def test_an_installer_missing_a_line_is_refused_not_guessed(mj, drop, why):
    text = GNR_INSTALLER_LINES.replace(drop, "")
    assert drop not in text
    with pytest.raises(mj.Refused) as e:
        mj.parse_installer(text)
    assert why in str(e.value) and "not run blind" in str(e.value)


def test_a_slot_restored_twice_is_refused(mj):
    text = GNR_INSTALLER_LINES.replace('restore_partition "$PART_PERMB" "sda4.ext4-ptcl-img" "$FS_UUID_PERMB"',
                                       'restore_partition "$PART_PERMA" "sda4.ext4-ptcl-img" "$FS_UUID_PERMA"')
    with pytest.raises(mj.Refused) as e:
        mj.parse_installer(text)
    assert "restored twice" in str(e.value)


def test_the_install_command_is_wired_and_needs_root(mj, capsys):
    """The CLI reaches install_disk, whose first act is the root check - so on this side of
    WSL it exits 2 with the refusal and touches nothing."""
    rc = mj.main(["install", "--iso", "x.iso", "--disk", "/dev/sdz", "--yes"])
    out = capsys.readouterr()
    assert rc == 2
    assert "needs root" in out.out + out.err


# ============================================================================ the GPT by hand
def test_a_backup_round_trips_and_lays_out_to_the_disk_like_sgdisk(mj, tmp_path):
    """An sgdisk-shaped backup (MBR + header + 128 entries) parses, its entries read back with
    their GUIDs, and on a disk of another size the layout moves the backup header to the last
    sector and the last usable sector 34 from the end - what --load-backup does."""
    parts = [(mj.GPT_TYPE_EFI, 94 * 2048), (mj.GPT_TYPE_LINUX, 250 * 2048), (mj.GPT_TYPE_LINUX, 4 * 1024 * 2048)]
    total = 5 * 1000 ** 3 // 512
    data = mj.make_gpt_backup(parts, total, disk_guid="F8F0C24F-3358-4267-81DA-B737B45AB104")
    assert len(data) == mj.GPT_BACKUP_SIZE == 17920
    mbr, h, entries = mj.parse_gpt_backup(data)
    assert h["guid"] == mj.uuid.UUID("F8F0C24F-3358-4267-81DA-B737B45AB104").bytes_le
    used = mj.gpt_entries(entries)
    assert [(e["num"], e["first"], e["last"], e["type"]) for e in used] == [
        (1, 2048, 2048 + 94 * 2048 - 1, mj.GPT_TYPE_EFI),
        (2, 2048 + 94 * 2048, 2048 + 344 * 2048 - 1, mj.GPT_TYPE_LINUX),
        (3, 2048 + 344 * 2048, 2048 + 344 * 2048 + 4 * 1024 * 2048 - 1, mj.GPT_TYPE_LINUX)]
    assert len({e["guid"] for e in used}) == 3
    assert mj.gpt_rows(entries) == {e["num"]: (e["first"], e["last"]) for e in used}
    # a bigger disk: the same entries, the backup at ITS end
    bigger = 8 * 1000 ** 3 // 512
    layout = mj.gpt_layout(mbr, h, entries, bigger)
    lbas = [lba for lba, _d in layout]
    assert lbas == [0, 1, 2, bigger - 33, bigger - 1]
    primary = mj.parse_gpt_header(layout[1][1])
    backup = mj.parse_gpt_header(layout[4][1])
    assert (primary["my"], primary["alt"], primary["first"], primary["last"], primary["elba"]) == (1, bigger - 1, 34, bigger - 34, 2)
    assert (backup["my"], backup["alt"], backup["elba"]) == (bigger - 1, 1, bigger - 33)
    assert primary["guid"] == backup["guid"] == h["guid"]
    # the protective MBR spans the whole (bigger) disk
    pm = layout[0][1]
    assert pm[0x1BE + 4] == 0xEE and mj.struct.unpack_from("<II", pm, 0x1BE + 8) == (1, bigger - 1)
    # a disk too small for the entries is refused before anything is written
    with pytest.raises(mj.Refused):
        mj.gpt_layout(mbr, h, entries, 3 * 1000 ** 3 // 512)


def test_write_gpt_onto_a_file_reads_back_exactly(mj, tmp_path):
    """The self-test's road: the template onto a plain file, read back CRC-checked, entry for
    entry the template's; the old table zeroed first."""
    tpl = tmp_path / "backup.sgdisk3"
    parts = [(mj.GPT_TYPE_EFI, 94 * 2048), (mj.GPT_TYPE_LINUX, 250 * 2048), (mj.GPT_TYPE_LINUX, 100 * 2048)]
    tpl.write_bytes(mj.make_gpt_backup(parts, 500 * 2048))
    disk = tmp_path / "disk.raw"
    with open(disk, "wb") as f:
        f.truncate(600 * 2048 * 512)
    written = mj.write_gpt(str(disk), str(tpl))
    assert [e["num"] for e in written] == [1, 2, 3]
    h, entries = mj.read_gpt(str(disk))
    _mbr, th, tentries = mj.parse_gpt_backup(tpl.read_bytes())
    assert entries == tentries and h["guid"] == th["guid"]
    assert h["alt"] == 600 * 2048 - 1 and h["last"] == 600 * 2048 - 34
    assert mj.template_rows(str(tpl)) == mj.gpt_rows(entries)
    # a corrupted header is a refusal, not a guess
    with open(disk, "r+b") as f:
        f.seek(512 + 40)
        f.write(b"\xff")
    with pytest.raises(mj.Refused):
        mj.read_gpt(str(disk))


def test_a_real_shaped_backup_is_parsed_not_guessed(mj):
    with pytest.raises(mj.Refused):
        mj.parse_gpt_backup(b"\0" * 100)
    with pytest.raises(mj.Refused):
        mj.parse_gpt_backup(b"\0" * mj.GPT_BACKUP_SIZE)


# ============================================================================ install: the modes
def _ns(mj, **kw):
    import argparse
    base = dict(iso="x.iso", disk="/dev/sdz", yes=True, no_verify=False, workdir=None, menu_only=False, image=None,
                from_iso=None, allow_version_mismatch=False, cache_dir=None)
    base.update(kw)
    return argparse.Namespace(**base)


def test_install_modes_full_menu_image(mj):
    assert mj.install_args_check(_ns(mj)) == "full"
    assert mj.install_args_check(_ns(mj, menu_only=True)) == "menu"
    assert mj.install_args_check(_ns(mj, image=1, from_iso="new.iso")) == "image"
    assert mj.install_args_check(_ns(mj, image=0, from_iso="new.iso")) == "image"


@pytest.mark.parametrize("kw, why", [
    (dict(menu_only=True, image=1, from_iso="y.iso"), "two different writes"),
    (dict(image=1), "go together"),
    (dict(from_iso="y.iso"), "go together"),
    (dict(image=2, from_iso="y.iso"), "0 (root A) or 1 (root B)"),
])
def test_a_mixed_or_half_mode_is_refused_before_anything_runs(mj, kw, why):
    with pytest.raises(mj.Refused) as e:
        mj.install_args_check(_ns(mj, **kw))
    assert why in str(e.value)


def test_the_cli_refuses_a_mixed_mode_before_the_root_check(mj, capsys):
    rc = mj.main(["install", "--iso", "x.iso", "--disk", "/dev/sdz", "--menu-only", "--image", "1", "--from", "y.iso", "--yes"])
    out = capsys.readouterr()
    assert rc == 2 and "two different writes" in out.out + out.err
    rc = mj.main(["install", "--iso", "x.iso", "--disk", "/dev/sdz", "--menu-only", "--yes"])
    out = capsys.readouterr()
    assert rc == 2 and "needs root" in out.out + out.err


def test_root_manifest_bytes_drop_the_staged_map_only(mj):
    import collections
    import json
    man = collections.OrderedDict([("tool", "t"), ("images", [{"device": "rootA"}]), ("staged", {"/a": "x"}), ("layout", "jjp-ab")])
    out = mj.root_manifest_bytes(man)
    back = json.loads(out.decode("utf-8"))
    assert "staged" not in back and list(back) == ["tool", "images", "layout"]
    assert out.endswith(b"\n")
    # the same manifest without the map gives the same bytes: what `build` staged into the root
    man2 = collections.OrderedDict((k, v) for k, v in man.items() if k != "staged")
    assert mj.root_manifest_bytes(man2) == out


def test_gate_root_pair_names_what_differs(mj):
    class _Info:
        path, name, game_version = "/x/new.iso", "GunsNRoses", "03.04"
    rec_other = {"name": "GunsNRoses", "game_version": "03.03"}
    same = {"gamename": "GunsNRoses", "game_sha256": "a" * 64, "fldat_sha256": "b" * 64}
    with pytest.raises(mj.Refused) as e:
        mj.gate_root_pair(_Info(), rec_other, same, dict(same), 1, False)
    assert "03.04" in str(e.value) and "03.03" in str(e.value) and "--allow-version-mismatch" in str(e.value)
    _Info.game_version = "03.03"
    assert mj.gate_root_pair(_Info(), rec_other, same, dict(same), 1, False) == []
    other = dict(same, game_sha256="c" * 64)
    with pytest.raises(mj.Refused) as e:
        mj.gate_root_pair(_Info(), rec_other, same, other, 1, False)
    assert "game binary differs" in str(e.value)
    assert mj.gate_root_pair(_Info(), rec_other, same, other, 1, True)



# ============================================================================ restore cache (PAD-218)
def test_a_torn_cached_root_is_restored_again_not_trusted(mj, tmp_path, monkeypatch):
    """A cancelled restore that kept running once left a half-written sda3.raw in the
    cache, and every build copied it and refused "no GAMENAME ... not a JJP root"."""
    base = tmp_path / "jjp_Sonic-v00.940"
    base.mkdir()
    raw = base / "sda3.raw"
    raw.write_bytes(b"torn")
    restored = []

    def restore(pieces, dest, meter=None, label="sda3"):
        restored.append(dest)
        with open(dest, "wb") as f:
            f.write(b"whole")
    monkeypatch.setattr(mj, "restore_pieces", restore)
    monkeypatch.setattr(mj, "piece_paths", lambda mnt, info, part: [])
    monkeypatch.setattr(mj, "root_identity",
                        lambda r: {"gamename": "Sonic"} if open(r, "rb").read() == b"whole"
                        else (_ for _ in ()).throw(mj.Refused("%s: no GAMENAME" % r)))

    class Info:
        def piece_bytes(self, part):
            return 1
    iso = str(tmp_path / "Sonic-v00.940.iso")
    # a lookup that cannot restore hands back what is there (plan, the budget)
    assert mj.cached_root_raw(iso, str(tmp_path)) == str(raw)
    assert restored == []
    # one that can restore throws the torn one away and restores it
    assert mj.cached_root_raw(iso, str(tmp_path), "/mnt", Info()) == str(raw)
    assert restored == [str(raw)] and raw.read_bytes() == b"whole"
    # and a whole one is trusted as it is
    assert mj.cached_root_raw(iso, str(tmp_path), "/mnt", Info()) == str(raw)
    assert len(restored) == 1
