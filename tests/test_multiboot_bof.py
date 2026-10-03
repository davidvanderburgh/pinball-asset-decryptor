"""Multi-boot tab, the Barrels of Fun backend (PAD-342): the same tab builds ONE
multi-boot .fun through tools/bof_emu/mkbofmulti.py - the stock .fun as it is, every
other build of the title as a delta against it, the menu and the boot hook.

Pure, like tests/test_multiboot_jjp.py: what is asserted is the argv each step would run,
the images.conf the preview draws from, what the plan's rows parse to and what the page
is told to show.  Nothing here reaches WSL, and the Stern and JJP defaults are asserted
alongside so the seam can be seen to leave their argv alone.
"""
import json

from pinball_decryptor.webui import multiboot_core as mt
from pinball_decryptor.webui.multiboot_backend import BOF, JJP, STERN, backend_for
from pinball_decryptor.webui.multiboot_core import ImageRow, MultibootForm, wsl

FUN0 = "D:/Pinball/images/BoF/lab.fun"                       # forward slashes: read on Linux CI too
FUN1 = "D:/Pinball/images/BoF/Labyrinth (Sarah mod)/lab.fun"
OUT = "D:/Pinball/images/BoF/multi/lab.fun"


def bof_form(**kw):
    rows = [ImageRow(path=FUN0, title="LABYRINTH", subtitle="Stock"),
            ImageRow(path=FUN1, title="SARAH CODE", subtitle="Mod")]
    base = dict(images=rows, out=OUT, platform="bof", timeout=10, default=0,
                volume=50, heading="SELECT GAME CODE")
    base.update(kw)
    return MultibootForm(**base)


# ---------------------------------------------------------------------------- the backend
def test_backend_lookup_and_what_bof_has():
    assert backend_for("bof") is BOF and backend_for(bof_form()) is BOF
    assert backend_for("jjp") is JJP and backend_for(None) is STERN
    assert BOF.tool == "tools/bof_emu/mkbofmulti.py"
    assert BOF.media_tool == ("tools/bof_emu/mkbofmulti.py", "media")
    assert BOF.ensure_tool == "tools/bof_emu/ensurebofselect.sh"
    assert BOF.card_flag == "--fun" and BOF.image_exts == (".fun",) and BOF.out_ext == ".fun"
    assert not (BOF.groups or BOF.compact or BOF.update or BOF.bypass or BOF.extract or BOF.read_card)
    assert not (BOF.sound or BOF.scores_column or BOF.emulate or BOF.flash or BOF.settings_tile)
    assert BOF.root_steps == frozenset() and BOF.preview_native
    # the program FILE each image becomes on the machine
    assert BOF.device(0) == "GDCraze.x86_64" and BOF.device(1) == "pad_image1.bin"
    # Stern and JJP keep what they had (the new flags default on)
    for be in (STERN, JJP):
        assert be.sound and be.scores_column and be.emulate and be.flash, be.key


def test_titles_and_output_name():
    # a .fun is named for its title whatever build it is: the folder names the build
    assert mt.suggest_title(FUN1, "bof") == ("Labyrinth (Sarah mod)", "")
    # a folder that does not name the game names a library, not a build
    assert mt.suggest_title(FUN0, "bof") == ("Labyrinth", "")
    assert mt.suggest_title("x/renamed.fun", "bof") == ("renamed", "")
    out = mt.default_output_path(FUN0, "bof").replace("\\", "/")
    # the title's own name, which the machine's updater looks for on the stick
    assert out.endswith("/multi/lab.fun")
    assert BOF.is_image("x/LAB.FUN") and not BOF.is_image("x/card.raw")


# ---------------------------------------------------------------------------- the argv
def test_build_args_go_to_mkbofmulti():
    form = bof_form(media_dir=r"D:\Pinball\multi\media", force=True)
    args = mt.build_args(form)
    assert args[:2] == [BOF.tool, "build"]
    assert args[2:6] == ["--primary", wsl(FUN0), "--extra", wsl(FUN1)]
    assert args[args.index("--out") + 1] == wsl(OUT)
    assert args[args.index("--selector-dir") + 1] == "/var/tmp/bofselect"
    assert args[args.index("--titles") + 1] == "LABYRINTH;SARAH CODE"
    assert args[args.index("--subtitles") + 1] == "Stock;Mod"
    assert args[args.index("--timeout") + 1] == "10"
    assert args[args.index("--media-dir") + 1] == wsl(r"D:\Pinball\multi\media")
    assert "--force" in args and "--heading" in args
    for not_here in ("--layout", "--bypass-validation", "--machine-volume", "--own-scores", "--workdir"):
        assert not_here not in args
    # a form switched over from another platform keeps no other platform's menu dir
    for other in (mt.DEFAULT_SELECTOR_DIR, JJP.selector_default):
        f = bof_form(selector_dir=other)
        assert mt.build_args(f)[mt.build_args(f).index("--selector-dir") + 1] == "/var/tmp/bofselect"
    f = bof_form(selector_dir="/tmp/sel")
    assert mt.build_args(f)[mt.build_args(f).index("--selector-dir") + 1] == "/tmp/sel"


def test_plan_verify_inject_inspect_args():
    form = bof_form()
    assert mt.plan_args(form) == [BOF.tool, "plan", "--primary", wsl(FUN0), "--extra", wsl(FUN1)]
    assert mt.verify_args(form) == [BOF.tool, "verify", "--fun", wsl(OUT)]
    inj = mt.inject_args(form, OUT)
    assert inj[:4] == [BOF.tool, "inject", "--fun", wsl(OUT)]
    assert inj[inj.index("--titles") + 1] == "LABYRINTH;SARAH CODE"
    assert inj[inj.index("--subtitles") + 1] == "Stock;Mod"
    assert "--machine-volume" not in inj
    assert mt.inspect_args(OUT, r"D:\o", as_json=True, platform="bof") == \
        [BOF.tool, "inspect", "--fun", wsl(OUT), "--json", "--media-out", wsl(r"D:\o")]


def test_media_args_have_no_sound_and_auto_is_a_text_card():
    form = bof_form(sound_move="auto", sound_confirm="auto")
    form.images[0].art = "auto"
    form.images[1].art = "D:/pics/sarah.png"
    args = mt.prepare_args(form, r"D:\m")
    assert args[:2] == list(BOF.media_tool)
    arts = [args[i + 1] for i, a in enumerate(args) if a == "--art"]
    assert arts == ["0=none", "1=" + wsl("D:/pics/sarah.png")]
    for snd in ("--sound-move", "--sound-confirm", "--music"):
        assert snd not in args
    assert args[-2:] == ["--volume", "50"]
    assert "--visual-only" in mt.prepare_args(form, r"D:\m", visual_only=True)


def test_build_commands_run_nothing_as_root():
    cmds = dict(mt.build_commands(bof_form(media_dir=r"D:\m"), cwd="/repo", prepare=True))
    assert list(cmds) == ["selector", "prepare", "plan", "build", "verify"]
    for label, argv in cmds.items():
        assert not callable(argv), label
        assert "sudo" not in argv[:3], label


def test_selector_step_is_ensurebofselect():
    assert mt.install_selector_line("", wsl(FUN0), platform="bof") == \
        "bash tools/bof_emu/ensurebofselect.sh %s /var/tmp/bofselect" % wsl(FUN0)
    # no .fun is no refusal: nothing of the machine is needed to build the menu
    assert mt.install_selector_line("", "", platform="bof") == \
        "bash tools/bof_emu/ensurebofselect.sh '' /var/tmp/bofselect"
    assert mt.ensure_selector_line("", "/repo/tools/spike2_emu/codeselect", card="", platform="bof") == \
        "bash tools/bof_emu/ensurebofselect.sh --preview '' /var/tmp/bofselect"


def test_preview_conf_names_the_programs_and_no_sound():
    form = bof_form()
    args = mt.preview_snapshot_args("/var/tmp/bofselect/bofselect", "D:/c.conf", "D:/m", "D:/f.ppm", 1, 0,
                                    platform="bof")
    assert args[0] == "/var/tmp/bofselect/bofselect" and "-L" not in args
    lines = mt.write_preview_conf(form).splitlines()
    # 'auto' art is a text-only card on BOF, and nothing names a sound
    assert "image=GDCraze.x86_64|LABYRINTH|Stock|||" in lines
    assert "image=pad_image1.bin|SARAH CODE|Mod|||" in lines
    assert "font=" + BOF.conf_font in lines
    assert mt.card_media_names(form) == [("", "", "", ""), ("", "", "", "")]
    form.images[1].art = "D:/pics/sarah.png"
    assert mt.card_media_names(form)[1][0] == "art1.png"
    # a JJP form still names art<N>.png for 'auto'
    jform = MultibootForm(images=[ImageRow(path="D:/a.iso"), ImageRow(path="D:/b.iso")], platform="jjp")
    assert mt.card_media_names(jform)[0][0] == "art0.png"


def test_validate_form_caps_and_groups():
    assert not [e for e in mt.validate_form(bof_form(), sources=False)
                if "fit" in e or "Random" in e]
    five = bof_form()
    five.images = five.images + [ImageRow(path="D:/x%d/lab.fun" % i) for i in range(3)]
    assert any("At most 4 images fit one update" in e for e in mt.validate_form(five, sources=False))
    assert mt.own_scores_args(bof_form()) == []


# ---------------------------------------------------------------------------- the plan + the strip
PLAN_TEXT = """== layout: image 0 = the primary .fun as it is (BOF's updater installs its program); every other image = a delta against it, rebuilt and checked by the install step
== game code versions
  0  GDCraze.x86_64  lab.fun  2026.01.30
  1  pad_image1.bin  lab.fun  2026.01.30
== bytes in the update
image-size 0 GDCraze.x86_64 2931814160 the primary .fun as it is
image-size 1 pad_image1.bin 312533666 delta: 0.31 GB of its 3.94 GB differ from image 0
image-size overhead 4000000 the menu, its pictures and the scripts
fun-size 3248347826 estimated multi-boot .fun
fat32: fits (one file on a FAT32 stick holds at most 4.29 GB)
fits USB 8G stick size 7700000000: YES (spare 4451652174)
fits USB 16G stick size 15400000000: YES (spare 12151652174)
fits USB 32G stick size 30900000000: YES (spare 27651652174)
fits USB 64G stick size 61800000000: YES (spare 58551652174)
stick: 8G
"""


def test_parse_plan_reads_the_bof_rows():
    info = mt.parse_plan(PLAN_TEXT, "bof")
    assert info["bytes"] == 3248347826
    assert info["fits"]["8G"] == (True, 4451652174)
    assert info["sizes"][0] == (0, "GDCraze.x86_64", 2931814160, "the primary .fun as it is")
    assert info["sizes"][1][2] == 312533666
    assert info["overhead"] == 4000000
    assert info["versions"] == {0: "2026.01.30", 1: "2026.01.30"}
    assert info["fat32"] is True
    view = mt.card_size_view(info, "bof")
    assert view["known"] and view["need"] == "8 GB" and not view["over"]
    assert view["detail"] == "a 3.25 GB update, 4.45 GB spare on a 8 GB stick."
    # an update a FAT32 stick cannot hold as one file says THAT, not "a bigger stick"
    big = PLAN_TEXT.replace("fat32: fits", "fat32: TOO BIG").replace(": YES", ": NO")
    over = mt.card_size_view(mt.parse_plan(big, "bof"), "bof")
    assert over["over"] and over["head"] == "too big" and "FAT32" in over["detail"]


# ---------------------------------------------------------------------------- a .fun read back
INSPECT = {
    "fun": "/mnt/d/Pinball/images/BoF/multi/lab.fun", "size": 3238061057, "title": "labyrinth",
    "tool": "mkbofmulti", "tool_version": "1.0", "written": "2026-10-03T16:05:00",
    "hook": True, "install_step": True,
    "images": [
        {"index": 0, "device": "GDCraze.x86_64", "title": "LABYRINTH", "subtitle": "Stock 2026.01.30",
         "art": None, "anim": None, "music": None, "confirm": None, "art_source": None, "anim_source": None,
         "music_source": None, "confirm_source": None, "source": "/mnt/d/Pinball/images/BoF/lab.fun",
         "source_exists": True, "name": "GDCraze_linux_20260130.x86_64", "version": "2026.01.30"},
        {"index": 1, "device": "pad_image1.bin", "title": "SARAH CODE", "subtitle": "Labyrinth mod",
         "art": None, "anim": None, "music": None, "confirm": None, "art_source": None, "anim_source": None,
         "music_source": None, "confirm_source": None,
         "source": "/mnt/d/Pinball/images/BoF/Labyrinth (Sarah mod)/lab.fun",
         "source_exists": True, "name": "GDCraze_linux_20260130.x86_64", "version": "2026.01.30"}],
    "timeout": 10, "default": 0, "heading": None, "text_size": None, "counter": None,
    "countdown_word": None, "footer": None, "volume": 50, "sound_move": None, "sound_confirm": None,
    "theme": None, "colors": {}, "switches": {"switch_left": "15", "switch_right": "22",
                                              "switch_start": "14,20"},
    "media_files": [], "media": None, "warnings": []}


def test_form_from_inspect_reads_the_bof_report():
    form, warnings = mt.form_from_inspect(json.loads(json.dumps(INSPECT)), OUT, platform="bof")
    assert form.platform == "bof" and form.selector_dir == "/var/tmp/bofselect"
    assert [r.device for r in form.images] == ["GDCraze.x86_64", "pad_image1.bin"]
    assert [r.title for r in form.images] == ["LABYRINTH", "SARAH CODE"]
    assert [r.version for r in form.images] == ["2026.01.30", "2026.01.30"]
    assert form.timeout == 10 and form.default == 0 and not form.compact


def test_status_words_and_path_text():
    kind, text, _tone, _cr = mt.card_path_state("", {"kind": "unknown"}, platform="bof")
    assert kind == "empty" and text == BOF.empty_path_text and ".fun" in text
    assert dict(BOF.status_checks)["card"] == "Update"
    assert BOF.build_flash_text == "Build update…"
