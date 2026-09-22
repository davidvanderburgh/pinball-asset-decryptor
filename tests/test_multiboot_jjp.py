"""Multi-boot tab, the JJP backend (item 118): the same tab builds a Jersey
Jack multi-boot install ISO through tools/jjp_emu/mkjjpmulti.py.

Pure, like the Stern half of tests/test_multiboot_tab.py: what is asserted is
the argv each step would run, the images.conf the preview draws from, what
the plan's rows parse to and what the size strip would say.  Nothing here
reaches WSL, and the Stern default is asserted alongside so the seam can be
seen to leave the old argv alone.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.gui import multiboot_docker as mac_docker
from pinball_decryptor.gui import multiboot_tab as mt
from pinball_decryptor.gui.multiboot_backend import JJP, STERN, backend_for
from pinball_decryptor.gui.multiboot_tab import (ImageRow, MultibootForm, wsl)

ISO0 = "D:/Pinball/images/JJP/GunsNRoses-v03.03.iso"          # forward slashes: read on Linux CI too
ISO1 = "D:/Pinball/images/JJP/CHAKAs_LOTLJ_V1.0_GNR_LE_3.03.iso"
OUT = "D:/Pinball/multi/GunsNRoses-v03.03.multi.iso"


def jjp_form(**kw):
    rows = [ImageRow(path=ISO0, title="GUNS N' ROSES 3.03", subtitle="Stock"),
            ImageRow(path=ISO1, title="CHAKA'S LOTLJ", subtitle="Retheme")]
    base = dict(images=rows, out=OUT, platform="jjp", timeout=15, default=0,
                volume=50, heading="SELECT GAME CODE")
    base.update(kw)
    return MultibootForm(**base)


def root_head():
    """What a root step's argv begins with on THIS platform.  THREE answers.

    macOS is the third and it is not a sudo at all.  The host has no losetup,
    no ext4 and no partclone, so PAD-192 gave the tab a Linux the way Windows
    already had one, and that container's own user is root.  The container is
    NAMED here on purpose: the JJP plugin runs a privileged container on a Mac
    too (its Alpine ``jjp-decryptor-worker``, for Direct-SSD work), and these
    steps must not drift into it - see the test below for why they cannot.
    """
    if sys.platform == "darwin":
        return ["docker", "exec", mac_docker.CONTAINER]
    return ["sudo", "-n"]


# ---------------------------------------------------------------------------- the backend
def test_backend_lookup_and_defaults():
    assert backend_for("jjp") is JJP and backend_for("stern") is STERN
    assert backend_for(None) is STERN and backend_for(jjp_form()) is JJP
    assert backend_for(MultibootForm()) is STERN            # a form that never says
    assert backend_for(JJP) is JJP
    assert JJP.tool == "tools/jjp_emu/mkjjpmulti.py"
    assert JJP.media_tool == ("tools/jjp_emu/mkjjpmulti.py", "media")
    assert STERN.tool == mt.MKMULTICARD and STERN.selector_default == mt.DEFAULT_SELECTOR_DIR
    assert STERN.sizes == mt.CARD_SIZES and STERN.conf_font == mt.CONF_FONT
    assert JJP.max_cards == 2 and not JJP.groups and not JJP.update and not JJP.bypass
    assert JJP.device(0) == "rootA" and JJP.device(1) == "rootB" and JJP.device(2) == "rootB:img2"
    assert STERN.device(0) == "p3" and STERN.device(1) == "p7" and STERN.device(2) == "p7:img2"


def test_menu_volume_default_and_cap_follow_the_platform():
    """Item 120: a JJP machine keeps its amplifiers at full while the menu plays, so its
    menu starts quiet and cannot pass 40; Stern's card keeps 50 and 0-100."""
    assert (JJP.volume_default, JJP.volume_max) == (20, 40)
    assert (STERN.volume_default, STERN.volume_max) == (50, 100)
    loud = mt.validate_form(jjp_form(volume=41), sources=False)
    assert any(e.startswith("Volume is 0-40.") for e in loud), loud
    assert not any(e.startswith("Volume is") for e in mt.validate_form(jjp_form(volume=40), sources=False))
    rows = [ImageRow(path="D:/a.raw"), ImageRow(path="D:/b.raw")]
    assert not any(e.startswith("Volume is")
                   for e in mt.validate_form(MultibootForm(images=rows, volume=41), sources=False))
    assert "Volume is 0-100." in mt.validate_form(MultibootForm(images=rows, volume=101), sources=False)


def test_a_jjp_image_plays_a_video_file_not_an_attract_clip():
    """A JJP root has no attract clip in the clear, so the Edit image dialog does not
    offer one there, and a row still set to it is refused with the way out; a video
    file is a JJP image's animation.  Stern keeps every choice."""
    assert JJP.attract_clip is False and STERN.attract_clip is True
    assert [k for k, _l in mt.ImageEditorDialog.kinds_for(JJP)] == ["logo", "picture", "video", "none"]
    # the clips PAD extracts from a JJP game are .webm (GNR: 629 of 648) - they are videos
    assert mt.is_video(r"D:\Pinball\videos\Guns N Roses\Attract_Montage_1.webm") and mt.is_video("x.FLV")
    assert "*.webm" in mt.ImageEditorDialog.FILETYPES["video"][0][1]
    assert mt.ImageEditorDialog.kinds_for(STERN) == mt.ImageEditorDialog.KINDS
    form = jjp_form()
    form.images[1].anim = "auto"
    assert any("no attract video" in e for e in mt.validate_form(form, sources=False))
    form.images[1].anim = r"D:\Pinball\videos\Guns N Roses\Attract_Montage_1.webm"
    assert not any("attract video" in e for e in mt.validate_form(form, sources=False))
    args = mt.prepare_args(form, r"D:\m")
    anims = [args[i + 1] for i, a in enumerate(args) if a == "--anim"]
    assert anims[1] == "1=" + wsl(form.images[1].anim)
    rows = [ImageRow(path="D:/a.raw", anim="auto"), ImageRow(path="D:/b.raw")]
    assert not any("attract video" in e for e in mt.validate_form(MultibootForm(images=rows), sources=False))


def test_titles_and_output_names():
    assert mt.suggest_title(ISO1, "jjp") == ("CHAKAs LOTLJ V1.0 GNR LE 3.03", "")
    assert mt.suggest_title(ISO0, "jjp") == ("GunsNRoses-v03.03", "")
    # the Stern rule is untouched
    assert mt.suggest_title("turtles_pro-1_59_0.1987-upscaled.8G.sdcard.raw") == \
        ("turtles_pro-1_59_0", "1987-upscaled")
    out = mt.default_output_path(ISO0, "jjp")
    assert out.replace("\\", "/").endswith("/multi/GunsNRoses-v03.03.multi.iso")
    assert not mt.under_library(out)
    assert mt.default_output_path("D:/x/a.raw").replace("\\", "/").endswith("/x/multi/a.multi.raw")
    assert mt.loaded_media_dir(OUT).replace("\\", "/").endswith("/multi/media-GunsNRoses-v03.03.multi")


# ---------------------------------------------------------------------------- the argv
def test_build_args_go_to_mkjjpmulti():
    form = jjp_form(media_dir=r"D:\Pinball\multi\media", force=True)
    args = mt.build_args(form)
    assert args[:2] == [JJP.tool, "build"]
    assert args[2:6] == ["--primary", wsl(ISO0), "--extra", wsl(ISO1)]
    assert args[args.index("--out") + 1] == wsl(OUT)
    assert args[args.index("--selector-dir") + 1] == "/var/tmp/jjpselect"
    assert args[args.index("--titles") + 1] == "GUNS N' ROSES 3.03;CHAKA'S LOTLJ"
    assert args[args.index("--subtitles") + 1] == "Stock;Retheme"
    assert args[args.index("--timeout") + 1] == "15"
    assert args[args.index("--default") + 1] == "0"
    assert args[args.index("--volume") + 1] == "50"
    assert args[args.index("--media-dir") + 1] == wsl(r"D:\Pinball\multi\media")
    assert "--force" in args and "--heading" in args and "--theme" in args
    for stern_only in ("--layout", "--bypass-validation", "--machine-volume", "--default-card"):
        assert stern_only not in args
    # the tab's own selector directory wins when set
    form.selector_dir = "/tmp/sel"
    assert mt.build_args(form)[mt.build_args(form).index("--selector-dir") + 1] == "/tmp/sel"


def test_plan_verify_inject_inspect_args():
    form = jjp_form()
    assert mt.plan_args(form) == [JJP.tool, "plan", "--primary", wsl(ISO0), "--extra", wsl(ISO1)]
    form.media_dir = r"D:\m"
    assert mt.plan_args(form)[-2:] == ["--media-dir", wsl(r"D:\m")]
    assert mt.verify_args(form) == [JJP.tool, "verify", "--iso", wsl(OUT),
                                    "--primary", wsl(ISO0), "--extra", wsl(ISO1),
                                    "--workdir", mt.JJP_WORKDIR + "_verify"]
    assert mt.build_args(form)[mt.build_args(form).index("--workdir") + 1] == mt.JJP_WORKDIR
    inj = mt.inject_args(form, OUT)
    assert inj[:4] == [JJP.tool, "inject", "--iso", wsl(OUT)]
    assert inj[inj.index("--titles") + 1] == "GUNS N' ROSES 3.03;CHAKA'S LOTLJ"
    assert "--machine-volume" not in inj and "--media-dir" in inj
    assert mt.inspect_args(OUT, platform="jjp") == [JJP.tool, "inspect", "--iso", wsl(OUT)]
    assert mt.inspect_args(OUT, r"D:\out", as_json=True, platform="jjp") == \
        [JJP.tool, "inspect", "--iso", wsl(OUT), "--json", "--media-out", wsl(r"D:\out")]
    # Stern is what it was
    assert mt.inspect_args("D:/c.raw")[:3] == [mt.MKMULTICARD, "inspect", "--card"]


def test_media_args_map_the_stern_words_to_jjp_seams():
    form = jjp_form(sound_move="auto", sound_confirm="auto")
    form.images[1].anim = "auto"
    form.images[0].art = "auto"
    args = mt.prepare_args(form, r"D:\Pinball\multi\media")
    assert args[:2] == list(JJP.media_tool)
    assert args[2:6] == ["--primary", wsl(ISO0), "--extra", wsl(ISO1)]
    assert args[args.index("--out") + 1] == wsl(r"D:\Pinball\multi\media")
    assert "--cards" not in args and "--group-members" not in args
    assert "0=auto" in args[args.index("--art") + 1]
    anims = [args[i + 1] for i, a in enumerate(args) if a == "--anim"]
    assert anims == ["0=none", "1=none"]                  # 'auto' has no JJP seam
    assert args[args.index("--sound-move") + 1] == "synth"
    confirms = [args[i + 1] for i, a in enumerate(args) if a == "--sound-confirm"]
    assert confirms[0] == "synth" and confirms[1:] == ["0=none", "1=none"]
    assert args[-2:] == ["--volume", "50"]
    vis = mt.prepare_args(form, r"D:\m", visual_only=True)
    assert "--visual-only" in vis and "--sound-move" not in vis
    # a Stern form still prepares with selectmedia
    assert mt.prepare_args(MultibootForm(images=[ImageRow(path="D:/a.raw"), ImageRow(path="D:/b.raw")]),
                           "D:/m")[:2] == [mt.SELECTMEDIA, "prepare"]


def test_build_commands_run_the_writing_steps_as_root():
    form = jjp_form(media_dir=r"D:\m")
    cmds = mt.build_commands(form, cwd="/repo", prepare=True)
    labels = [c[0] for c in cmds]
    assert labels == ["selector", "prepare", "plan", "build", "verify"]
    argv = dict(cmds)
    # the JJP steps that mount things run as root: on Windows a callable
    # (resolved as root just before the step, root_command's shape), on a
    # Linux desktop the rig's `sudo -n` argv, on a Mac the container whose
    # own user is root already; the plan runs as the user
    head = root_head()
    for label in ("selector", "prepare", "build", "verify"):
        if sys.platform == "win32":
            assert callable(argv[label]), label
        else:
            assert not callable(argv[label]) and list(argv[label][:len(head)]) == head, label
    assert not callable(argv["plan"]) and argv["plan"][-1].startswith("cd /repo && python3 ")
    # the Stern run keeps MAIN's shape: the plan and verify as the user, the
    # build as root, and the selector as root on Windows (PAD-140, main's
    # test_multiboot_tab.py pins it) - a user step anywhere else
    stern = MultibootForm(images=[ImageRow(path="D:/a.raw"), ImageRow(path="D:/b.raw")], out="D:/o.raw")
    scmds = dict(mt.build_commands(stern, cwd="/repo"))
    assert callable(scmds["selector"]) == (sys.platform == "win32")
    assert not callable(scmds["plan"])
    assert callable(scmds["build"]) == (sys.platform == "win32")
    if sys.platform != "win32":
        assert list(scmds["build"][:len(head)]) == head
    assert not callable(scmds["verify"])


def test_a_mac_builds_the_card_in_the_tabs_own_linux_not_the_plugins():
    """The two macOS containers are deliberately different containers.

    The JJP plugin's is Alpine and serves Direct-SSD extracts.  This tab
    cannot use it: ensurejjpselect.sh links the menu program with
    ``-nostdlib`` against the card's own libraries and
    ``-print-file-name=libc_nonshared.a``, which is a glibc artefact musl has
    not got - so ``apk add gcc make`` would not have bought it - and a
    writing run hard-fails when that compile fails.  Hence a Debian image of
    its own, and hence a name of its own so the two can be up at once.
    """
    from pinball_decryptor.plugins.jjp import executor
    assert mac_docker.CONTAINER != executor._DOCKER_CONTAINER
    assert mac_docker.IMAGE.split(":")[0] != executor._DOCKER_IMAGE
    assert "debian" in mac_docker.DOCKERFILE.lower()
    for pkg in ("gcc", "libc6-dev", "make"):
        assert pkg in mac_docker.DOCKERFILE, pkg


def test_selector_step_is_ensurejjpselect():
    line = mt.install_selector_line("/var/tmp/jjpselect", wsl(ISO0), platform="jjp")
    assert line == "bash tools/jjp_emu/ensurejjpselect.sh %s /var/tmp/jjpselect" % wsl(ISO0)
    # the PREVIEW's line (a load, a redraw) never restores an image: --preview
    assert mt.ensure_selector_line("/var/tmp/jjpselect", "/repo/tools/spike2_emu/codeselect",
                                   card=wsl(ISO0), platform="jjp") == \
        "bash tools/jjp_emu/ensurejjpselect.sh --preview %s /var/tmp/jjpselect" % wsl(ISO0)
    # ...and has a line with no ISO too: an installed program or a root on disk draws it
    assert mt.ensure_selector_line("", "/repo/tools/spike2_emu/codeselect", card="", platform="jjp") == \
        "bash tools/jjp_emu/ensurejjpselect.sh --preview '' /var/tmp/jjpselect"
    no_card = mt.install_selector_line("", "", platform="jjp")
    assert no_card.startswith("echo ") and "[selector] error:" in no_card and no_card.endswith("exit 1")
    # the Stern line is the rig's own ensureselect.sh, as before
    assert mt.install_selector_line("~/spike2root/usr/local/codeselect").startswith(
        "PAD_ROOT=~/spike2root bash tools/spike2_emu/ensureselect.sh")


def test_preview_is_native_and_the_conf_names_the_slots():
    form = jjp_form()
    args = mt.preview_snapshot_args("/var/tmp/jjpselect/jjpe/gen1/padselect/jjpselect", "D:/c.conf",
                                    "D:/m", "D:/f.ppm", 1, 0, platform="jjp")
    assert args[0] == "/var/tmp/jjpselect/jjpe/gen1/padselect/jjpselect"
    assert args[1] == "--snapshot" and "-L" not in args and "qemu-arm" not in args
    stern = mt.preview_snapshot_args("/x/codeselect", "D:/c.conf", "D:/m", "D:/f.ppm", 1, 0)
    assert stern[:3] == mt.QEMU_ARM[:3] and "-L" in stern
    conf = mt.write_preview_conf(form)
    lines = conf.splitlines()
    # a fresh row's art is 'auto', which the media step renders as art<N>.png
    assert "image=rootA|GUNS N' ROSES 3.03|Stock|art0.png||" in lines
    assert "image=rootB|CHAKA'S LOTLJ|Retheme|art1.png||" in lines
    assert "font=" + JJP.conf_font in lines
    assert not any(ln.startswith("image=p3") for ln in lines)
    sconf = mt.write_preview_conf(MultibootForm(images=[ImageRow(path="D:/a.raw", title="A"),
                                                        ImageRow(path="D:/b.raw", title="B")]))
    assert "image=p3|A||art0.png||" in sconf.splitlines() and "font=" + mt.CONF_FONT in sconf.splitlines()


# ---------------------------------------------------------------------------- the plan + the strip
PLAN_TEXT = """== layout: image 0 -> root A (sda3, re-imaged with the menu), image 1 -> root B (sda5, verbatim)
image 0 rootA GunsNRoses-v03.03.iso  (GunsNRoses 03.03, 6 piece(s), 5.80 GB compressed)
image 1 rootB CHAKAs_LOTLJ_V1.0_GNR_LE_3.03.iso  (GunsNRoses 03.03, 7 piece(s), 6.52 GB compressed)
== game code versions
version 0 rootA GunsNRoses 03.03 GunsNRoses game=c4672be7a2e44214 fl.dat=e92e8bcb148799e4 used=8.81 GB
version 1 rootB GunsNRoses 03.03 GunsNRoses game=c4672be7a2e44214 fl.dat=e92e8bcb148799e4 used=9.52 GB
== bytes on the stick
image-size 0 rootA 5856760862 re-imaged root A + the menu
image-size 1 rootB 6518261539 root B, verbatim
image-size overhead 642971400 installer live system + EFI/boot/perm pieces + configs
media-size 456314 menu media (4 file(s))
iso-size 13017993801 estimated multi-boot ISO
fits USB 8G stick size 7700000000: NO (spare -5317993801)
fits USB 16G stick size 15400000000: YES (spare 2382006199)
fits USB 32G stick size 30900000000: YES (spare 17882006199)
fits USB 64G stick size 61800000000: YES (spare 48782006199)
stick: 16G
"""


def test_parse_plan_reads_the_jjp_rows():
    info = mt.parse_plan(PLAN_TEXT, "jjp")
    assert info["bytes"] == 13017993801
    assert info["fits"]["8G"] == (False, -5317993801)
    assert info["fits"]["16G"] == (True, 2382006199)
    assert info["fits"]["64G"][0] is True
    assert info["sizes"][0] == (0, "rootA", 5856760862, "re-imaged root A + the menu")
    assert info["sizes"][1][2] == 6518261539
    assert info["overhead"] == 642971400
    # the Stern parser sees none of it (its fits line is another sentence)
    assert mt.parse_plan(PLAN_TEXT)["fits"] == {} and mt.parse_plan(PLAN_TEXT)["bytes"] is None


def test_size_view_names_the_stick():
    view = mt.card_size_view(mt.parse_plan(PLAN_TEXT, "jjp"), "jjp")
    assert view["known"] and view["need"] == "16 GB" and not view["over"]
    assert view["scale"] == 13017993801 + 2382006199
    assert [b[0] for b in view["bands"]][:2] == ["Image 0 - re-imaged root A + the menu",
                                                 "Image 1 - root B, verbatim"]
    assert view["bands"][-1] == (JJP.overhead_label, 642971400, "overhead")
    big = mt.parse_plan(PLAN_TEXT.replace("YES", "NO"), "jjp")
    big["fits"] = {k: (False, -1000) for k in big["fits"]}
    over = mt.card_size_view(big, "jjp")
    assert over["over"] and over["head"] == "too big" and "64 GB stick holds" in over["detail"]


# ---------------------------------------------------------------------------- the form
def test_validate_form_holds_two_images_and_no_groups():
    ok = jjp_form()
    errs = mt.validate_form(ok, sources=False)
    assert not [e for e in errs if "images fit" in e or "Random" in e]
    three = jjp_form()
    three.images.append(ImageRow(path="D:/x.iso", title="third"))
    assert any("At most 2 images fit one install ISO" in e for e in mt.validate_form(three, sources=False))
    grouped = jjp_form()
    grouped.images.append(ImageRow(path="", title="RANDOM",
                                   members=[mt.MemberRow(path=ISO0), mt.MemberRow(path=ISO1)]))
    assert any("Random groups are not available for a JJP install" in e
               for e in mt.validate_form(grouped, sources=False))
    empty = jjp_form(out="")
    assert "Set the output .iso path." in mt.validate_form(empty, sources=False)
    assert "Set the output .raw path." in mt.validate_form(MultibootForm(images=ok.images), sources=False)


INSPECT = {
    "iso": "/var/tmp/jjp116/GunsNRoses-v03.03.multi.iso", "size": 12972720128,
    "tool": "mkjjpmulti", "tool_version": "1.0", "written": "2026-09-13T12:46:41Z",
    "layout": "jjp-ab", "game": {"name": "GunsNRoses", "title": "Guns N Roses", "version": "03.03"},
    "installer_redirected": True,
    "images": [
        {"index": 0, "device": "rootA", "title": "GUNS N' ROSES 3.03", "subtitle": "Stock JJP code",
         "art": "art0.png", "anim": None, "music": None, "confirm": None,
         "art_source": "/var/tmp/jjp116/media/.jjp_src/logo0.png", "anim_source": "none",
         "music_source": "none", "confirm_source": None,
         "source": "/mnt/d/Pinball/images/JJP/GunsNRoses-v03.03.iso", "source_exists": True,
         "name": "GunsNRoses", "game_version": "03.03", "gamename": "GunsNRoses",
         "game_sha256": "c4672be7", "used_bytes": 8811286528, "pieces": 6, "pieces_bytes": 5810854064},
        {"index": 1, "device": "rootB", "title": "CHAKA'S LOTLJ", "subtitle": "Land of the Lost Jungle retheme (3.03)",
         "art": "art1.png", "anim": None, "music": None, "confirm": None,
         "art_source": "/var/tmp/jjp116/media/.jjp_src/logo1.png", "anim_source": "none",
         "music_source": "none", "confirm_source": None,
         "source": "/mnt/d/Pinball/images/JJP/CHAKAs_LOTLJ_V1.0_GNR_LE_3.03.iso", "source_exists": True,
         "name": "GunsNRoses", "game_version": "03.03", "gamename": "GunsNRoses",
         "game_sha256": "c4672be7", "used_bytes": 9522069504, "pieces": 7, "pieces_bytes": 6518261539}],
    "timeout": 15, "default": 0, "heading": None, "volume": 50, "sound_move": "move.wav",
    "sound_confirm": "confirm.wav", "theme": "midnight", "colors": {}, "jjp_update": "refuse",
    "log": None, "media_files": ["art0.png", "art1.png", "confirm.wav", "move.wav"],
    "media": {"images": [{"art": "art0.png", "anim": None, "music": None, "confirm": None},
                         {"art": "art1.png", "anim": None, "music": None, "confirm": None}],
              "sound_move": "move.wav", "sound_confirm": "confirm.wav", "volume": 50},
    "warnings": []}


def test_form_from_inspect_reads_the_jjp_report():
    form, warnings = mt.form_from_inspect(json.loads(json.dumps(INSPECT)), OUT, platform="jjp")
    assert form.platform == "jjp" and form.selector_dir == "/var/tmp/jjpselect"
    assert [r.device for r in form.images] == ["rootA", "rootB"]
    assert [r.title for r in form.images] == ["GUNS N' ROSES 3.03", "CHAKA'S LOTLJ"]
    assert form.images[1].subtitle == "Land of the Lost Jungle retheme (3.03)"
    assert form.timeout == 15 and form.default == 0 and form.volume == 50
    assert form.heading == mt.DEF_HEADING and form.theme == "midnight" and not form.compact
    assert form.machine_volume is False
    assert form.images[0].path.replace("\\", "/").lower().endswith("/pinball/images/jjp/gunsnroses-v03.03.iso")
    assert mt.parse_inspect("noise\n" + json.dumps(INSPECT))["layout"] == "jjp-ab"
    # a Stern load is what it was
    sform, _w = mt.form_from_inspect(json.loads(json.dumps(INSPECT)), "D:/c.raw")
    assert sform.platform == "stern" and sform.selector_dir == mt.DEFAULT_SELECTOR_DIR


def test_path_state_and_status_words():
    kind, text, _tone, _cr = mt.card_path_state("", {"kind": "unknown"}, platform="jjp")
    assert kind == "empty" and text == JJP.empty_path_text and "ISO" in text
    kind, text, _tone, _cr = mt.card_path_state("", {"kind": "unknown"})
    assert text == mt.EMPTY_PATH_TEXT
    assert dict(JJP.status_checks)["card"] == "Install ISO"
    assert dict(STERN.status_checks) == dict(mt.STATUS_CHECKS)


# ---------------------------------------------------------------------------- the rig's script
def test_ensurejjpselect_prints_both_lines():
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tools", "jjp_emu", "ensurejjpselect.sh")
    if not os.path.isfile(here):
        pytest.skip("ensurejjpselect.sh not present")
    with open(here, encoding="utf-8") as f:
        text = f.read()
    assert '[selector] menu program: $SEL' in text
    assert '[preview] selector: $BIN' in text
    assert '[selector] error:' in text
    assert "make -C" in text and "PLATFORM=jjp" in text and "DESTDIR=" in text
    # a load or a redraw restores nothing, and a writing run restores the root
    # partition alone, into a file renamed only when whole (2026-09-15)
    assert 'if [ "${1:-}" = "--preview" ]' in text and "jjpselect_sysroot" in text
    # An aarch64 Linux gets a sentence, not a page of "ld: skipping
    # incompatible" after minutes of restoring - and the check comes BEFORE
    # the restore, which is the expensive half (PAD-193).
    assert "uname -m" in text and "x86_64 | amd64" in text
    arch_at = text.index("ARCH=$(uname -m)")
    assert arch_at < text.index("sysroot_ok || sysroot_from_disk"), \
        "the architecture check must come before the root restore"
    calls = [ln for ln in text.splitlines() if "mount.sh" in ln and not ln.lstrip().startswith("#")]
    assert calls and all("--root-only" in ln for ln in calls), calls
    with open(os.path.join(os.path.dirname(here), "mount.sh"), encoding="utf-8") as f:
        mount = f.read()
    assert 'if [ "${1:-}" = "--root-only" ]' in mount
    assert '-o "$dest.part"' in mount and 'mv -f "$dest.part" "$dest"' in mount



# ------------------------------------------------------------- the menu's font
def _ensurejjpselect():
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "tools", "jjp_emu", "ensurejjpselect.sh")
    if not os.path.isfile(here):
        pytest.skip("ensurejjpselect.sh not present")
    with open(here, encoding="utf-8") as f:
        return f.read()


def test_the_menus_font_survives_a_linux_that_has_no_fonts():
    """PAD-194: a Mac built the menu program and then could not build a card.

    ``make install PLATFORM=jjp`` copies the HOST's DejaVuSans-Bold.ttf beside
    jjpselect and skips it without a word when the host has none; a Debian
    slim container (which is what a Mac's multi-boot Linux is) carries no
    fonts at all.  So the build refused - "--selector-dir /var/tmp/jjpselect
    has no font.ttf and /usr/share/fonts/... is not on this host" - after
    seven minutes of restoring a root, and the preview's conf named a
    font.ttf that was never written either.

    The card's own root HAS that font, and this script already mounts one to
    copy libraries out of, so it takes the font in the same pass and names it
    to make.
    """
    text = _ensurejjpselect()
    # taken while the root is open, beside the libraries
    assert "CARD_FONT=usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" in text
    assert 'f=$(in_root "$root" "$CARD_FONT") && cp "$f" "$tmp/font.ttf"' in text
    # ...and named to `make install`, whose DEJAVU is a ?= default (the
    # invocation wraps, so it is the joined logical line that is read)
    joined = text.replace("\\" + "\n", " ")
    install_line = [ln for ln in joined.splitlines()
                    if "make -C" in ln and "DESTDIR=" in ln and " install" in ln]
    assert install_line and all("DEJAVU=" in ln for ln in install_line), install_line
    # ...and laid down on the way out even when nothing was rebuilt, so a host
    # that grew a font since the last build does not need a rebuild to use it
    assert "install_font" in text.split("ok() {", 1)[1].split("}", 1)[0]
    # THE COPY IS POSIX, AND IN ONE PLACE.  `install -D` is GNU-only - BSD
    # install rejects the option - and it cost v0.229.3: on a macOS host the
    # copy failed, 2>/dev/null hid it and no font was written.  Both callers
    # go through put_font now, which is mkdir -p + cp + chmod.
    code = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("install -D" in ln for ln in code), \
        "GNU-only: macOS install has no -D"
    assert 'mkdir -p "$(dirname "$FONT")" && cp "$1" "$FONT" && chmod 644 "$FONT"' in text
    assert text.count("put_font() {") == 1 and text.count("put_font \"$src\"") == 2


def _shell_func(text, name):
    """One shell function's source, lifted out of the script on disk."""
    fn = text[text.index(name + "() {"):]
    return fn[:fn.index("\n}\n") + 3]


#: A BSD/macOS `install`, for the PATH the driver below runs with.  There is
#: no -D there (make the leading directories) and the option is rejected
#: outright, which is the whole of what went wrong.
_BSD_INSTALL = """#!/bin/sh
for a in "$@"; do
  case "$a" in -*D*) echo "install: illegal option -- D" >&2; exit 64 ;; esac
done
exec /usr/bin/install "$@"
"""


@pytest.mark.skipif(not shutil.which("bash"), reason="no bash")
def test_the_font_is_the_hosts_first_then_the_cards(tmp_path):
    """install_font, run for real: host's DejaVu wins, the card's copy is the
    fallback, an existing font.ttf is never overwritten, and a host with
    neither is left exactly as it was (the Makefile's own message then).

    AND WITH A BSD `install` IN FRONT ON THE PATH, on every platform.  The
    first cut of this copied the font with `install -D`, which is a GNU
    extension macOS has not got, under `2>/dev/null` and above a `return 0`:
    the copy failed, the redirect hid the usage error, the return hid the
    status, and a Mac silently ended up with no font at all.  ubuntu-latest
    was green throughout and v0.229.3 was tagged and released before macOS
    said otherwise.  The stub rejects -D the way BSD does, so a relapse goes
    red on every runner instead of on the one nobody watches.
    """
    text = _ensurejjpselect()
    bsd = tmp_path / "bin"
    bsd.mkdir()
    (bsd / "install").write_text(_BSD_INSTALL, encoding="utf-8", newline="\n")
    (bsd / "install").chmod(0o755)
    # EVERYTHING RELATIVE and the driver on disk, PATH included: on Windows
    # `bash` is as likely to be WSL's launcher as Git's, and that one cannot
    # see C:\... - nor does this process's environment cross into it, so the
    # stub has to go on the PATH from a line of the script.
    driver = ("#!/bin/bash\nset -u\nPATH=$PWD/bin:$PATH\nexport PATH\n"
              + _shell_func(text, "put_font")
              + _shell_func(text, "install_font") + """
FONT=sel/jjpe/gen1/padselect/font.ttf
DEJAVU=host/DejaVuSans-Bold.ttf
SYSROOT=sysroot
install_font
if [ -f "$FONT" ]; then cat "$FONT"; else echo NONE; fi
""")
    (tmp_path / "drive.sh").write_text(driver, encoding="utf-8", newline="\n")

    def run(host=None, card=None, already=None):
        for d in ("sel", "host", "sysroot"):
            shutil.rmtree(str(tmp_path / d), ignore_errors=True)
            (tmp_path / d).mkdir()
        if host is not None:
            (tmp_path / "host" / "DejaVuSans-Bold.ttf").write_text(host)
        if card is not None:
            (tmp_path / "sysroot" / "font.ttf").write_text(card)
        if already is not None:
            d = tmp_path / "sel" / "jjpe" / "gen1" / "padselect"
            d.mkdir(parents=True, exist_ok=True)
            (d / "font.ttf").write_text(already)
        r = subprocess.run([shutil.which("bash"), "drive.sh"], cwd=str(tmp_path),
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    assert run(host="HOST", card="CARD") == "HOST"
    assert run(card="CARD") == "CARD"          # the container's case
    assert run() == "NONE"                     # neither: today's behaviour
    assert run(host="HOST", already="MINE") == "MINE"
    assert run(card="") == "NONE"              # a torn copy is not a font
