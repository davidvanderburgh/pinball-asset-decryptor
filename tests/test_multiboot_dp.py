"""Multi-boot tab, the Dutch Pinball backend (PAD-853): the same tab builds ONE Big Lebowski
update zip through tools/dp_emu/mkdpmulti.py - the stock version stays on the machine, every
other build's files travel beside the menu and a launcher the machine's own USB update installs.

Pure, like tests/test_multiboot_bof.py: the argv each step would run, the images.conf the
preview draws from, what the plan's rows parse to, the words the page shows.  Nothing here
reaches WSL.  The builder's own tests are tests/test_mkdpmulti.py, and the machine-side proof
is tools/dp_emu/machine_sim.sh (MULTIBOOT.md).
"""
import re

from pinball_decryptor.webui import multiboot_core as mt
from pinball_decryptor.webui.multiboot_backend import BOF, DP, JJP, STERN, backend_for
from pinball_decryptor.webui.multiboot_core import ImageRow, MultibootForm, wsl

STOCK = "D:/Pinball/images/Dutch Pinball/TBL-v1.15.zip"       # forward slashes: read on Linux CI too
MOD = "D:/Pinball/images/Dutch Pinball/TBL-v1.15 my mod.zip"
OUT = "D:/Pinball/images/Dutch Pinball/multi/TBL-v9.0853.zip"


def dp_form(**kw):
    rows = [ImageRow(path=STOCK, title="THE BIG LEBOWSKI", subtitle="Stock 1.15"),
            ImageRow(path=MOD, title="THE BIG LEBOWSKI", subtitle="My own build")]
    base = dict(images=rows, out=OUT, platform="dp", timeout=10, default=0,
                volume=50, heading="SELECT GAME CODE")
    base.update(kw)
    return MultibootForm(**base)


def _values(args, flag):
    return [args[i + 1] for i, a in enumerate(args) if a == flag]


# ---------------------------------------------------------------------------- the backend
def test_backend_and_capability(manufacturers_by_key):
    assert backend_for("dp") is DP and backend_for(dp_form()) is DP
    assert manufacturers_by_key["dp"].capabilities.multiboot is True
    assert DP.tool == "tools/dp_emu/mkdpmulti.py"
    assert DP.media_tool == ("tools/dp_emu/mkdpmulti.py", "media")
    assert DP.ensure_tool == "tools/dp_emu/ensuredpselect.sh"
    assert DP.card_flag == "--zip" and DP.image_exts == (".zip",) and DP.out_ext == ".zip"
    assert DP.update_file and BOF.update_file and not (STERN.update_file or JJP.update_file)
    assert not (DP.groups or DP.compact or DP.update or DP.bypass or DP.extract or DP.read_card)
    assert not (DP.scores_column or DP.emulate or DP.flash or DP.settings_tile or DP.attract_clip)
    assert DP.root_steps == frozenset() and DP.preview_native and DP.sound
    assert DP.add_choices == frozenset({"_add_image"})
    assert DP.selector_default == "/var/tmp/dpselect" and DP.selector_binary == "dpselect"


def test_a_missing_output_is_called_an_update():
    state = mt.card_path_state("C:/Users/me/multi/TBL-v9.0853.zip", {"kind": "missing"}, platform="dp")
    assert "Build update" in state[1] and "new update at" in state[1] and "card" not in state[1]


def test_titles_and_output_name():
    assert mt.suggest_title(STOCK, "dp") == ("THE BIG LEBOWSKI", "Version 1.15")
    assert mt.suggest_title(MOD, "dp") == ("THE BIG LEBOWSKI", "my mod")
    assert mt.suggest_title("D:/x/lebowski_gold.zip", "dp") == ("THE BIG LEBOWSKI", "lebowski gold")
    # the machine's update menu reads the version off the name: TBL-v9.<four digits>.zip,
    # a build's folder one digit more, seven characters at most (the game's loader)
    name = DP.output_name(STOCK)
    m = re.match(r"^TBL-v(9\.\d{4})\.zip$", name)
    assert m and len(m.group(1)) + 1 <= 7
    assert DP.device(0) == "stock" and DP.device(2) == "build2"


# ---------------------------------------------------------------------------- the argv
def test_plan_build_verify_inject_go_to_mkdpmulti():
    form = dp_form(media_dir=r"D:\m")
    plan = mt.plan_args(form)
    assert plan[:2] == ["tools/dp_emu/mkdpmulti.py", "plan"]
    assert _values(plan, "--primary") == [wsl(STOCK)] and _values(plan, "--extra") == [wsl(MOD)]
    assert "--layout" not in plan
    # the version the plan names is the one the build writes: the output's name
    assert _values(plan, "--out") == [wsl(OUT)]
    build = mt.build_args(form)
    assert build[:2] == ["tools/dp_emu/mkdpmulti.py", "build"]
    assert _values(build, "--out") == [wsl(OUT)]
    assert _values(build, "--selector-dir") == ["/var/tmp/dpselect"]
    assert _values(build, "--titles") == ["THE BIG LEBOWSKI;THE BIG LEBOWSKI"]
    assert _values(build, "--subtitles") == ["Stock 1.15;My own build"]
    assert _values(build, "--media-dir") == [wsl(r"D:\m")]
    assert mt.verify_args(form) == ["tools/dp_emu/mkdpmulti.py", "verify", "--zip", wsl(OUT)]
    inject = mt.inject_args(form, OUT)
    assert inject[:4] == ["tools/dp_emu/mkdpmulti.py", "inject", "--zip", wsl(OUT)]
    assert mt.inspect_args(OUT, platform="dp")[:4] == ["tools/dp_emu/mkdpmulti.py", "inspect", "--zip", wsl(OUT)]
    media = mt.prepare_args(form, r"D:\m")
    assert media[:2] == ["tools/dp_emu/mkdpmulti.py", "media"]
    # a BOF form still goes to its own tool
    assert mt.build_args(MultibootForm(images=[ImageRow(path="D:/a/lab.fun"), ImageRow(path="D:/b/lab.fun")],
                                       out="D:/m/lab.fun", platform="bof"))[0] == "tools/bof_emu/mkbofmulti.py"


def test_every_step_runs_as_the_user():
    cmds = dict(mt.build_commands(dp_form(media_dir=r"D:\m"), cwd="/repo", prepare=True))
    assert list(cmds) == ["selector", "prepare", "plan", "build", "verify"]
    for label, argv in cmds.items():
        assert not callable(argv), label
        assert "sudo" not in argv[:3], label


def test_selector_step_is_ensuredpselect():
    assert mt.install_selector_line("", wsl(STOCK), platform="dp") == \
        "bash tools/dp_emu/ensuredpselect.sh '%s' /var/tmp/dpselect" % wsl(STOCK)
    assert mt.ensure_selector_line("", "/repo/tools/spike2_emu/codeselect", card="", platform="dp") == \
        "bash tools/dp_emu/ensuredpselect.sh --preview '' /var/tmp/dpselect"
    # another platform's default menu directory is no place for this one's binary
    assert mt.platform_selector_dir("/var/tmp/bofselect", DP) == "/var/tmp/dpselect"
    assert mt.platform_selector_dir("/my/sel", DP) == "/my/sel"


def test_preview_conf_and_media_names():
    form = dp_form()
    lines = mt.write_preview_conf(form).splitlines()
    assert any(ln.startswith("image=stock|THE BIG LEBOWSKI|Stock 1.15") for ln in lines)
    assert any(ln.startswith("image=build1|THE BIG LEBOWSKI|My own build") for ln in lines)
    assert "font=" + DP.conf_font in lines
    # an 'auto' sound is the synthetic one, as on BOF
    assert mt.sound_as_rendered("dp", "sound", "auto", "synth") == "synth"
    assert mt.sound_as_rendered("stern", "sound", "auto", "synth") == "auto"


# ---------------------------------------------------------------------------- the plan + the strip
PLAN_TEXT = """== layout: one update zip TBL-v9.0853.zip; the machine's USB update installs it as ~/game/9.0853, Version Select switches to it once; image 0 = the stock version already on the machine; every other image = a build made beside it the first time the menu starts
== game code versions
  0  1.15  TBL-v1.15.zip  1.15  (stock, on the machine)
  1  9.08531  TBL-v1.15 my mod.zip  1.15  (laid over 1.01,1.10,1.11,1.12,1.13,1.14)
== bytes in the update
image-size 0 1.15 0 the stock version: already on the machine, nothing travels
image-size 1 9.08531 83676583 TBL-v1.15 my mod.zip's files (0.20 GB unpacked)
image-size overhead 3500000 the menu, its pictures and the launcher
zip-size 87176583 estimated multi-boot zip
machine-free 497746942 the machine's update needs 2.5 times the unpacked 0.20 GB free on its drive
fat32: fits (one file on a FAT32 stick holds at most 4.29 GB)
fits USB 8G stick size 7700000000: YES (spare 7612823417)
fits USB 16G stick size 15400000000: YES (spare 15312823417)
fits USB 32G stick size 30900000000: YES (spare 30812823417)
fits USB 64G stick size 61800000000: YES (spare 61712823417)
stick: 8G
"""


def test_parse_plan_reads_the_dp_rows():
    info = mt.parse_plan(PLAN_TEXT, "dp")
    assert info["bytes"] == 87176583
    assert info["fits"]["8G"] == (True, 7612823417)
    assert info["sizes"][1][:3] == (1, "9.08531", 83676583)
    assert info["overhead"] == 3500000 and info["fat32"] is True
    view = mt.card_size_view(info, "dp")
    assert view["known"] and view["need"] == "8 GB" and not view["over"]
    assert view["detail"].startswith("a 0.09 GB update")
    big = PLAN_TEXT.replace("fat32: fits", "fat32: TOO BIG").replace(": YES", ": NO")
    over = mt.card_size_view(mt.parse_plan(big, "dp"), "dp")
    assert over["over"] and "FAT32" in over["detail"]
