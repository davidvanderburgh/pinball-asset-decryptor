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


def random_row(title="SURPRISE", kind="none", path=""):
    """A random card over the two builds already in the list, the only kind the
    BOF tab offers (a .fun is named for its title, so no folder holds a group)."""
    row = ImageRow(path="", title=title, subtitle="", keep=True, roll="any",
                   members=[mt.MemberRow(path=FUN0, title="LABYRINTH"),
                            mt.MemberRow(path=FUN1, title="SARAH CODE")])
    return mt.set_group_media(row, kind, path)


# ---------------------------------------------------------------------------- the backend
def test_backend_lookup_and_what_bof_has():
    assert backend_for("bof") is BOF and backend_for(bof_form()) is BOF
    assert backend_for("jjp") is JJP and backend_for(None) is STERN
    assert BOF.tool == "tools/bof_emu/mkbofmulti.py"
    assert BOF.media_tool == ("tools/bof_emu/mkbofmulti.py", "media")
    assert BOF.ensure_tool == "tools/bof_emu/ensurebofselect.sh"
    assert BOF.card_flag == "--fun" and BOF.image_exts == (".fun",) and BOF.out_ext == ".fun"
    assert not (BOF.compact or BOF.update or BOF.bypass or BOF.extract or BOF.read_card)
    assert not (BOF.scores_column or BOF.emulate or BOF.flash or BOF.settings_tile)
    # the menu plays sounds through the machine's aplay, and rolls a random card
    assert BOF.sound and BOF.groups
    # four builds per update (a FAT32 file), six cards with the random ones
    assert BOF.max_games == 4 and BOF.max_cards == 6
    # a .fun is named for its title, so no folder of builds makes a group
    assert BOF.add_choices == frozenset({"_add_image", "_add_random_over_existing"})
    assert BOF.root_steps == frozenset() and BOF.preview_native
    # the program FILE each image becomes on the machine
    assert BOF.device(0) == "GDCraze.x86_64" and BOF.device(1) == "pad_image1.bin"
    # Stern and JJP keep what they had (the new flags default on)
    for be in (STERN, JJP):
        assert be.sound and be.scores_column and be.emulate and be.flash, be.key
        assert be.add_choices is None and not be.max_games, be.key


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


def _values(args, flag):
    return [args[i + 1] for i, a in enumerate(args) if a == flag]


def test_media_args_carry_pictures_music_and_sounds():
    form = bof_form(sound_move="auto", sound_confirm="D:/snd/chime.wav")
    form.images[0].art = "auto"
    form.images[1].art = "D:/pics/sarah.png"
    form.images[1].anim = "D:/clips/sarah.mp4"
    form.images[1].music = "D:/snd/sarah.wav"
    args = mt.prepare_args(form, r"D:\m")
    assert args[:2] == list(BOF.media_tool)
    assert args[args.index("--cards") + 1] == "2"
    # the form's words go as they are: mkbofmulti maps what a .fun cannot give
    # ('auto' art is a text card there, an 'auto' sound the synthetic click)
    assert _values(args, "--art") == ["0=auto", "1=" + wsl("D:/pics/sarah.png")]
    assert _values(args, "--anim") == ["0=none", "1=" + wsl("D:/clips/sarah.mp4")]
    assert _values(args, "--music") == ["0=none", "1=" + wsl("D:/snd/sarah.wav")]
    assert _values(args, "--sound-move") == ["auto"]
    # the menu-wide confirm, then each card's own (none = the menu's)
    assert _values(args, "--sound-confirm") == [wsl("D:/snd/chime.wav"), "0=none", "1=none"]
    assert args[-2:] == ["--volume", "50"]
    # the preview's half draws the pictures and makes no sounds
    vis = mt.prepare_args(form, r"D:\m", visual_only=True)
    assert "--visual-only" in vis and "--sound-move" not in vis and "--sound-confirm" not in vis


def test_random_card_media_build_and_inject_args():
    form = bof_form(default=2)
    form.images.append(random_row())
    media = mt.prepare_args(form, r"D:\m")
    assert media[media.index("--cards") + 1] == "3"
    assert _values(media, "--group-members") == ["0=0,1"]
    # a style is drawn from logos a .fun does not give up: a new BOF card is its words
    assert _values(media, "--group-art") == ["0=none"] and _values(media, "--group-anim") == ["0=none"]
    # the builds keep their own cards: the random card adds no image
    assert _values(media, "--art") == ["0=auto", "1=auto"]
    args = mt.build_args(form)
    assert _values(args, "--group-over") == ["0-1|SURPRISE|"]
    assert _values(args, "--group-roll") == ["0=any"]
    assert _values(args, "--extra") == [wsl(FUN1)] and "--group" not in args
    # the countdown can land on the random card: it is named by its CARD
    assert _values(args, "--default-card") == ["2"]
    assert _values(mt.inject_args(form, OUT), "--default-card") == ["2"]
    assert _values(mt.plan_args(form), "--group-roll") == ["0=any"]
    # a random card above the builds names its place
    top = bof_form()
    top.images.insert(0, random_row())
    assert _values(mt.build_args(top), "--group-over") == ["0-1@0|SURPRISE|"]
    assert _values(mt.build_args(top), "--primary") == [wsl(FUN0)]
    # its own picture is its gart<G>.png; a style is nothing on BOF
    pic = bof_form()
    pic.images.append(random_row(kind="picture", path="D:/pics/dice.png"))
    assert _values(mt.prepare_args(pic, r"D:\m"), "--group-art") == ["0=" + wsl("D:/pics/dice.png")]
    assert mt.card_media_names(pic)[2][0] == "gart0.png"
    styled = bof_form()
    styled.images.append(random_row(kind=mt.GROUP_MEDIA_DEFAULT))
    assert mt.card_media_names(styled)[2][:2] == ("", "")


def test_sounds_are_compared_as_mkbofmulti_renders_them():
    # 'auto' is rendered as the synthetic sound / no bed; the manifest says so
    assert mt.sound_as_rendered("bof", "sound", "auto") == "synth"
    assert mt.sound_as_rendered("bof", "sound", "auto@3") == "synth"
    assert mt.sound_as_rendered("bof", "music", "auto") == "none"
    assert mt.sound_as_rendered("bof", "sound", "/mnt/d/x.wav") == "/mnt/d/x.wav"
    for plat in ("stern", "jjp"):
        assert mt.sound_as_rendered(plat, "sound", "auto") == "auto"
        assert mt.sound_as_rendered(plat, "music", "auto") == "auto"


def test_random_card_choices_on_bof():
    assert mt.group_media_default("bof") == "none"
    assert mt.group_media_default("stern") == mt.GROUP_MEDIA_DEFAULT
    kinds = [k for k, _label in mt.ImageEditorDialog.group_kinds_for(BOF)]
    assert sorted(kinds) == ["none", "picture"]      # its words, or a picture of its own
    assert mt.ImageEditorDialog.group_kinds_for(STERN) == mt.ImageEditorDialog.GROUP_KINDS


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


def test_preview_conf_names_the_programs():
    form = bof_form()
    args = mt.preview_snapshot_args("/var/tmp/bofselect/bofselect", "D:/c.conf", "D:/m", "D:/f.ppm", 1, 0,
                                    platform="bof")
    assert args[0] == "/var/tmp/bofselect/bofselect" and "-L" not in args
    lines = mt.write_preview_conf(form).splitlines()
    # 'auto' art is a text-only card on BOF, and a card's confirm is the menu's
    assert "image=GDCraze.x86_64|LABYRINTH|Stock|||" in lines
    assert "image=pad_image1.bin|SARAH CODE|Mod|||" in lines
    assert "font=" + BOF.conf_font in lines
    assert mt.card_media_names(form) == [("", "", "", ""), ("", "", "", "")]
    form.images[1].art = "D:/pics/sarah.png"
    assert mt.card_media_names(form)[1][0] == "art1.png"
    form.images[1].music = "D:/snd/sarah.wav"
    form.images[1].confirm = "D:/snd/yes.wav"
    assert mt.card_media_names(form)[1][2:] == ("music1.wav", "confirm1.wav")
    form.images[0].music = "auto"
    assert mt.card_media_names(form)[0][2] == ""        # 'auto' music: nothing reads a .fun's own yet
    # a JJP form still names art<N>.png for 'auto'
    jform = MultibootForm(images=[ImageRow(path="D:/a.iso"), ImageRow(path="D:/b.iso")], platform="jjp")
    assert mt.card_media_names(jform)[0][0] == "art0.png"
    # the Sounds line says nothing of a Stern card's machine volume (the form's
    # tick is on by default, and no BOF or JJP machine has one to follow)
    for f in (bof_form(machine_volume=True), jform):
        f.machine_volume = True
        assert "the machine's own" not in mt.menu_summary(f)


def test_validate_form_caps_and_groups():
    assert not [e for e in mt.validate_form(bof_form(), sources=False)
                if "fit" in e or "Random" in e]
    five = bof_form()
    five.images = five.images + [ImageRow(path="D:/x%d/lab.fun" % i) for i in range(3)]
    assert any("At most 4 builds fit one update" in e for e in mt.validate_form(five, sources=False))
    # a random card is a card, not a build
    four = bof_form()
    four.images = four.images + [ImageRow(path="D:/x%d/lab.fun" % i) for i in range(2)] + [random_row()]
    assert not [e for e in mt.validate_form(four, sources=False) if "fit" in e or "Random" in e]
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
