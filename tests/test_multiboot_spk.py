"""Multi-boot tab, the Spooky Pinball backend (PAD-980): the same tab builds ONE update of a
Spooky title's own kind through tools/spooky_emu/mkspkmulti.py - the launcher as its
main.x86_64, the stock build whole, every other build's changed files.

Pure, like tests/test_multiboot_dp.py: the argv each step would run, the images.conf the
preview draws from, what the plan's rows parse to, the words the page shows.  Nothing here
reaches WSL.  The builder's own tests are tests/test_mkspkmulti.py, and the machine-side proof
is tools/spooky_emu/machine_sim.sh (MULTIBOOT.md).
"""
import shlex

from pinball_decryptor.webui import multiboot_core as mt
from pinball_decryptor.webui.multiboot_backend import DP, SPOOKY, backend_for
from pinball_decryptor.webui.multiboot_core import ImageRow, MultibootForm, wsl

STOCK = "D:/Pinball/images/Spooky/v2025.12.01.09.scooby"      # forward slashes: read on Linux CI too
MOD = "D:/Pinball/mods/Scooby-Doo my mod/v2025.12.01.09.scooby"
OUT = "D:/Pinball/images/Spooky/multi/v2025.12.01.09.scooby"


def spk_form(**kw):
    rows = [ImageRow(path=STOCK, title="SCOOBY-DOO", subtitle="Stock"),
            ImageRow(path=MOD, title="SCOOBY-DOO", subtitle="My own build")]
    base = dict(images=rows, out=OUT, platform="spooky", timeout=10, default=0,
                volume=50, heading="SELECT GAME CODE")
    base.update(kw)
    return MultibootForm(**base)


def _values(args, flag):
    return [args[i + 1] for i, a in enumerate(args) if a == flag]


def test_backend_and_capability(manufacturers_by_key):
    assert backend_for("spooky") is SPOOKY and backend_for(spk_form()) is SPOOKY
    assert manufacturers_by_key["spooky"].capabilities.multiboot is True
    assert SPOOKY.tool == "tools/spooky_emu/mkspkmulti.py"
    assert SPOOKY.media_tool == ("tools/spooky_emu/mkspkmulti.py", "media")
    assert SPOOKY.ensure_tool == "tools/spooky_emu/ensurespkselect.sh"
    assert SPOOKY.card_flag == "--update" and SPOOKY.update_file
    assert set(SPOOKY.image_exts) == {".scooby", ".beetlejuice", ".looney", ".ed", ".pkg"}
    assert not (SPOOKY.groups or SPOOKY.compact or SPOOKY.update or SPOOKY.bypass or SPOOKY.extract
                or SPOOKY.read_card or SPOOKY.scores_column or SPOOKY.emulate or SPOOKY.flash)
    assert SPOOKY.root_steps == frozenset() and SPOOKY.preview_native and SPOOKY.sound
    assert SPOOKY.selector_default == "/var/tmp/spkselect" and SPOOKY.selector_binary == "spkselect"


def test_titles_devices_and_output_name():
    assert mt.suggest_title(STOCK, "spooky") == ("Scooby-Doo", "v2025.12.01.09")
    assert mt.suggest_title(MOD, "spooky") == ("Scooby-Doo my mod", "v2025.12.01.09")
    assert mt.suggest_title("D:/x/tcm-1_00.pkg", "spooky")[0] == "Texas Chainsaw Massacre"
    assert mt.suggest_title("D:/x/code_H78.pkg", "spooky")[0] == "Halloween"
    assert mt.suggest_title("D:/x/code_UM.pkg", "spooky")[0] == "Ultraman"
    assert mt.suggest_title("D:/x/2025.10.08.looney", "spooky")[0] == "Looney Tunes"
    # the machines' update menus list the title's own names: the primary's, kept
    assert SPOOKY.output_name(STOCK) == "v2025.12.01.09.scooby"
    assert SPOOKY.output_name("D:/x/tcm-1_00.pkg") == "tcm-1_00.pkg"
    assert SPOOKY.device(0) == "b0" and SPOOKY.device(2) == "b2"


def test_plan_build_verify_inject_go_to_mkspkmulti():
    form = spk_form(media_dir=r"D:\m")
    plan = mt.plan_args(form)
    assert plan[:2] == ["tools/spooky_emu/mkspkmulti.py", "plan"]
    assert _values(plan, "--primary") == [wsl(STOCK)] and _values(plan, "--extra") == [wsl(MOD)]
    build = mt.build_args(form)
    assert build[:2] == ["tools/spooky_emu/mkspkmulti.py", "build"]
    assert _values(build, "--out") == [wsl(OUT)]
    assert _values(build, "--selector-dir") == ["/var/tmp/spkselect"]
    assert _values(build, "--titles") == ["SCOOBY-DOO;SCOOBY-DOO"]
    assert _values(build, "--subtitles") == ["Stock;My own build"]
    assert mt.verify_args(form) == ["tools/spooky_emu/mkspkmulti.py", "verify", "--update", wsl(OUT)]
    assert mt.inject_args(form, OUT)[:4] == ["tools/spooky_emu/mkspkmulti.py", "inject", "--update", wsl(OUT)]
    assert mt.prepare_args(form, r"D:\m")[:2] == ["tools/spooky_emu/mkspkmulti.py", "media"]


def test_every_step_runs_as_the_user():
    cmds = dict(mt.build_commands(spk_form(media_dir=r"D:\m"), cwd="/repo", prepare=True))
    assert list(cmds) == ["selector", "prepare", "plan", "build", "verify"]
    for label, argv in cmds.items():
        assert not callable(argv), label
        assert "sudo" not in argv[:3], label


def test_selector_step_is_ensurespkselect():
    assert mt.install_selector_line("", wsl(STOCK), platform="spooky") == \
        "bash tools/spooky_emu/ensurespkselect.sh %s /var/tmp/spkselect" % shlex.quote(wsl(STOCK))
    assert mt.platform_selector_dir("/var/tmp/dpselect", SPOOKY) == "/var/tmp/spkselect"
    assert mt.platform_selector_dir("/var/tmp/spkselect", DP) == "/var/tmp/dpselect"


def test_preview_conf():
    lines = mt.write_preview_conf(spk_form()).splitlines()
    assert any(ln.startswith("image=b0|SCOOBY-DOO|Stock") for ln in lines)
    assert any(ln.startswith("image=b1|SCOOBY-DOO|My own build") for ln in lines)
    assert "font=" + SPOOKY.conf_font in lines


PLAN_TEXT = """== layout: one Scooby-Doo update under the primary's name (v2025.12.01.09.scooby); ...
== game code versions
  0  b0  v2025.12.01.09.scooby  (whole (the stock build))
  1  b1  v2025.12.01.09.scooby  (1 changed, 0 removed)
== bytes in the update
image-size 0 b0 1784030683 v2025.12.01.09.scooby, whole
image-size 1 b1 40 v2025.12.01.09.scooby's own files (0.00 GB unpacked)
image-size overhead 3500000 the menu, its pictures and the launcher
upd-size 1787530723 estimated multi-boot update
machine-free 10811000000 while it installs (the file, it unpacked and copied in, the old build backed up)
fat32: fits (one file on a FAT32 stick holds at most 4.29 GB; an exFAT or NTFS stick has no limit)
fits USB 8G stick size 7700000000: YES (spare 5912469277)
fits USB 16G stick size 15400000000: YES (spare 13612469277)
fits USB 32G stick size 30900000000: YES (spare 29112469277)
fits USB 64G stick size 61800000000: YES (spare 60012469277)
stick: 8G
"""


def test_parse_plan_reads_the_rows():
    info = mt.parse_plan(PLAN_TEXT, "spooky")
    assert info["bytes"] == 1787530723
    assert info["fits"]["8G"] == (True, 5912469277)
    assert info["sizes"][1][:3] == (1, "b1", 40)
    assert info["overhead"] == 3500000 and info["fat32"] is True
    view = mt.card_size_view(info, "spooky")
    assert view["known"] and view["need"] == "8 GB" and not view["over"]


def test_the_tips_are_the_spooky_ones():
    p = mt.MultibootPanel.__new__(mt.MultibootPanel)
    p._backend = SPOOKY
    assert "update of the game's own kind" in p.about_tip()


def test_the_p_roc_titles_name_themselves():
    assert mt.suggest_title("D:/x/rm-gamecode-20220902.pkg", "spooky")[0] == "Rick and Morty"
    assert mt.suggest_title("D:/x/ac-gamecode.pkg", "spooky")[0] == "Alice Cooper's Nightmare Castle"
    assert SPOOKY.output_name("D:/x/ac-gamecode.pkg") == "ac-gamecode.pkg"
