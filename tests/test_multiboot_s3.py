"""Multi-boot tab, the Stern Spike 3 backend (PAD-1263): the same tab builds ONE Spike 3
SD card through tools/spike3_emu/mks3multi.py - image 0's card with every image's games
tree in its games partition and a boot menu (s3select) the machine shows at power-up.

Pure, like tests/test_multiboot_dp.py: the argv each step would run, the images.conf the
preview draws from, what the plan's rows parse to, the words the page shows, and which
Emulate entry Run in emulator takes.  Nothing here reaches WSL.  The builder's own tests are
tests/test_mks3multi.py; the hook's are tools/spike2_emu/codeselect/test/padselect_s3_test.sh;
the machine-side proof is the emulator run in tools/spike3_emu/MULTIBOOT.md.
"""
from types import SimpleNamespace

import pytest

from pinball_decryptor.webui import multiboot_core as mt
from pinball_decryptor.webui.multiboot_backend import BOF, DP, JJP, S3, SPOOKY, STERN, backend_for
from pinball_decryptor.webui.multiboot_core import ImageRow, MultibootForm, wsl
from pinball_decryptor.webui.tabs import multiboot as mbtab

A = "D:/Pinball/images/Stern/spike3/fallout_le-0_81_0_spike3.Release.64G.sdcard-secure.raw"
B = "D:/Pinball/images/Stern/spike3/fallout_le-0_82_0_spike3.Release.64G.sdcard-secure.raw"
OUT = "D:/Pinball/multi/fallout_le-0_81_0_spike3.Release.64G.sdcard-secure.multi.raw"
KEYS = "C:/Users/me/.pad/spike3_padkeys.json"


@pytest.fixture(autouse=True)
def _keyfile(monkeypatch):
    # the user's own key file, wherever the app keeps it: only its PATH travels
    from pinball_decryptor.webui import spike3_key
    monkeypatch.setattr(spike3_key, "find_keyfile", lambda *a, **k: KEYS)


def s3_form(**kw):
    rows = [ImageRow(path=A, title="FALLOUT LE 0.81.0", subtitle="Stock"),
            ImageRow(path=B, title="FALLOUT LE 0.82.0", subtitle="Newer code")]
    base = dict(images=rows, out=OUT, platform="s3", timeout=20, default=0,
                volume=50, heading="SELECT GAME CODE")
    base.update(kw)
    return MultibootForm(**base)


def _values(args, flag):
    return [args[i + 1] for i, a in enumerate(args) if a == flag]


# ---------------------------------------------------------------------------- the backend
def test_backend_and_capability(manufacturers_by_key):
    assert backend_for("s3") is S3 and backend_for(s3_form()) is S3
    stern = manufacturers_by_key["stern"]
    assert S3.tool == "tools/spike3_emu/mks3multi.py"
    assert S3.media_tool == ("tools/spike3_emu/mks3multi.py", "media")
    assert S3.ensure_tool == "tools/spike3_emu/ensures3select.sh"
    assert S3.card_flag == "--card" and S3.image_exts == (".raw", ".img") and S3.out_ext == ".raw"
    # a CARD (its words a card's), built by a tool that takes the shared command line
    assert S3.own_tool and not S3.update_file
    assert mt.own_tool(S3) and mt.own_tool(DP) and mt.own_tool(BOF) and mt.own_tool(SPOOKY)
    assert not (mt.own_tool(STERN) or mt.own_tool(JJP))
    assert not (S3.groups or S3.compact or S3.update or S3.bypass or S3.extract or S3.read_card)
    assert not (S3.scores_column or S3.settings_tile or S3.attract_clip or S3.sound)
    assert S3.emulate and S3.flash and S3.preview_native
    assert S3.root_steps == frozenset(("selector", "build", "verify", "inject"))
    assert S3.selector_default == "/var/tmp/s3select" and S3.selector_binary == "s3select"
    # the Spike 3 era of the Stern plugin offers the tab
    from pinball_decryptor.plugins.stern import manufacturer as sm
    assert sm._SPIKE3_CAPS.multiboot is True
    assert stern.key == "stern"


def test_the_platform_follows_the_stern_era():
    class Mfr:
        key = "stern"
        capabilities = SimpleNamespace(multiboot=True)

        def __init__(self, era):
            self._era = era

        def current_era(self):
            return self._era
    assert mbtab.multiboot_platform(Mfr("spike3")) == "s3"
    assert mbtab.multiboot_platform(Mfr("spike2")) == "stern"
    assert mbtab.multiboot_platform(SimpleNamespace(key="jjp")) == "jjp"
    assert mbtab.multiboot_platform(SimpleNamespace(key="stern")) == "stern"


def test_titles_devices_and_output_name():
    assert mt.suggest_title(A, "s3") == ("FALLOUT LE 0.81.0", "")
    assert mt.suggest_title("D:/x/pokemon_le-0_82_0.Release.64G.sdcard-secure.raw", "s3") == \
        ("POKEMON LE 0.82.0", "")
    assert mt.suggest_title("D:/x/pokemon_le-0_82_0 my mod.raw", "s3") == ("POKEMON LE 0.82.0", "my mod")
    assert mt.suggest_title("D:/x/odd name.raw", "s3") == ("odd name", "")
    assert S3.device(0) == "img0" and S3.device(3) == "img3"
    assert S3.output_name(A).endswith(".multi.raw")
    # a Spike 2 name keeps the Stern reading
    assert mt.suggest_title("D:/x/tmnt_pro-1_59_0.16G.sdcard.raw", "stern")[0] == "tmnt_pro-1_59_0"


# ---------------------------------------------------------------------------- the argv
def test_plan_build_verify_inject_go_to_mks3multi():
    form = s3_form(media_dir=r"D:\m")
    plan = mt.plan_args(form)
    assert plan[:2] == ["tools/spike3_emu/mks3multi.py", "plan"]
    assert _values(plan, "--primary") == [wsl(A)] and _values(plan, "--extra") == [wsl(B)]
    assert _values(plan, "--keyfile") == [wsl(KEYS)] and "--layout" not in plan
    build = mt.build_args(form)
    assert build[:2] == ["tools/spike3_emu/mks3multi.py", "build"]
    assert _values(build, "--out") == [wsl(OUT)]
    assert _values(build, "--selector-dir") == ["/var/tmp/s3select"]
    assert _values(build, "--titles") == ["FALLOUT LE 0.81.0;FALLOUT LE 0.82.0"]
    assert _values(build, "--subtitles") == ["Stock;Newer code"]
    assert _values(build, "--timeout") == ["20"] and _values(build, "--keyfile") == [wsl(KEYS)]
    assert _values(build, "--media-dir") == [wsl(r"D:\m")]
    assert "--bypass-validation" not in build          # a Spike 2 card's, not this one's
    verify = mt.verify_args(form)
    assert verify[:4] == ["tools/spike3_emu/mks3multi.py", "verify", "--card", wsl(OUT)]
    assert _values(verify, "--primary") == [wsl(A)] and _values(verify, "--extra") == [wsl(B)]
    assert _values(verify, "--keyfile") == [wsl(KEYS)]
    inject = mt.inject_args(form, OUT)
    assert inject[:4] == ["tools/spike3_emu/mks3multi.py", "inject", "--card", wsl(OUT)]
    assert _values(inject, "--keyfile") == [wsl(KEYS)]
    media = mt.prepare_args(form, r"D:\m")
    assert media[:2] == ["tools/spike3_emu/mks3multi.py", "media"]
    # no key file anywhere: the step goes without it, and the builder says what is missing
    from pinball_decryptor.webui import spike3_key
    spike3_key.find_keyfile = lambda *a, **k: None
    assert "--keyfile" not in mt.build_args(form)
    # the other platforms keep their own tools and no key
    stern = MultibootForm(images=[ImageRow(path="D:/a.raw"), ImageRow(path="D:/b.raw")], out="D:/m.raw")
    assert "--keyfile" not in mt.build_args(stern) and mt.build_args(stern)[0].endswith("mkmulticard.py")


def test_the_card_builder_parses_what_the_tab_sends():
    """Every flag the tab passes is one mks3multi.py takes (argparse would refuse the run)."""
    import importlib.util
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        "mks3multi_t", os.path.join(root, "tools", "spike3_emu", "mks3multi.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    seen = {}

    def grab(a):
        seen[a.cmd] = a
        return 0
    form = s3_form(media_dir=r"D:\m")
    mod.print_plan = lambda plan: None
    mod.make_plan = lambda a: seen.setdefault("plan", a)
    mod.build_card = grab
    mod.verify_card = grab
    mod.inject_card = grab
    mod.cmd_media = grab
    for argv in (mt.plan_args(form), mt.build_args(form), mt.verify_args(form),
                 mt.inject_args(form, OUT), mt.prepare_args(form, r"D:\m")):
        assert mod.main(argv[1:]) in (0, None), argv
    assert set(seen) == {"plan", "build", "verify", "inject", "media"}
    assert seen["build"].titles == "FALLOUT LE 0.81.0;FALLOUT LE 0.82.0"


def test_root_steps_and_the_selector_step():
    cmds = dict(mt.build_commands(s3_form(media_dir=r"D:\m"), cwd="/repo", prepare=True))
    assert list(cmds) == ["selector", "prepare", "plan", "build", "verify"]
    for label in ("selector", "build", "verify"):
        assert callable(cmds[label]), label            # resolved as root just before the step
    for label in ("prepare", "plan"):
        assert not callable(cmds[label]), label
    assert mt.install_selector_line("", wsl(A), platform="s3") == \
        "bash tools/spike3_emu/ensures3select.sh %s /var/tmp/s3select" % wsl(A)
    assert mt.ensure_selector_line("", "/repo/tools/spike2_emu/codeselect", card="", platform="s3") == \
        "bash tools/spike3_emu/ensures3select.sh --preview '' /var/tmp/s3select"
    assert mt.platform_selector_dir("/var/tmp/dpselect", S3) == "/var/tmp/s3select"
    assert mt.platform_selector_dir("/my/sel", S3) == "/my/sel"


def test_preview_conf():
    lines = mt.write_preview_conf(s3_form()).splitlines()
    assert any(ln.startswith("image=img0|FALLOUT LE 0.81.0|Stock") for ln in lines)
    assert any(ln.startswith("image=img1|FALLOUT LE 0.82.0|Newer code") for ln in lines)
    assert "font=" + S3.conf_font in lines


# ---------------------------------------------------------------------------- the plan + the strip
PLAN_TEXT = """== layout: image 0's card with every image's games tree in its games partition (/games/pad/imgN); the boot and rootfs partitions are image 0's, untouched
== game code versions
  0  img0  fallout_le-0_81_0_spike3.Release.64G.sdcard-secure.raw  fallout_le  0.81.0
  1  img1  fallout_le-0_82_0_spike3.Release.64G.sdcard-secure.raw  fallout_le  0.82.0
note: every image runs on image 0's rootfs (fallout_le 0.81.0)
== bytes in the games partition
image-size 0 img0 11232145408 fallout_le-0_81_0_spike3, already on the card
image-size 1 img1 11458711552 fallout_le-0_82_0_spike3's games tree
image-size overhead 4000000 the menu and its pictures
games-room 24184557568 free in image 0's games partition, 11462711552 needed (fits)
card-size 61924705792 the card image (image 0's size)
fits SD 64G card size 61924705792: YES (spare 0)
fits SD 128G card size 124000000000: YES (spare 62075294208)
card: 64G
"""


def test_parse_plan_reads_the_s3_rows():
    info = mt.parse_plan(PLAN_TEXT, "s3")
    assert info["bytes"] == 61924705792
    assert info["fits"]["64G"] == (True, 0) and info["fits"]["128G"][0] is True
    assert info["sizes"][1][:3] == (1, "img1", 11458711552)
    assert info["overhead"] == 4000000
    assert info["versions"] == {0: "0.81.0", 1: "0.82.0"}
    view = mt.card_size_view(info, "s3")
    assert view["known"] and view["need"] == "64 GB" and not view["over"]
    over = mt.card_size_view(mt.parse_plan(PLAN_TEXT.replace(": YES", ": NO"), "s3"), "s3")
    assert over["over"]


def test_the_tips_are_the_spike3_cards():
    panel = mt.MultibootPanel.__new__(mt.MultibootPanel)
    panel._backend = S3
    tip = panel.about_tip()
    assert "Spike 3" in tip and "NEXT and PREVIOUS" in tip and "SELECT boots" in tip
    assert "Add another Spike 3 card image" in mt.MultibootPanel.ADD_ROW_TEXT_S3


# ---------------------------------------------------------------------------- Run in emulator
def test_run_in_emulator_takes_the_spike3_rig():
    calls = []

    class Emu:
        def launch_spike3_card(self, path):
            calls.append(("s3", path))

        def launch_card(self, path, select=False):
            calls.append(("s2", path))

    class Win:
        _emulate_panel = Emu()

        def select_tab(self, ns):
            calls.append(("tab", ns))

        def append_log(self, s):
            calls.append(("log", s))

        def service(self, ns):
            return None
    svc = mbtab.MultibootService.__new__(mbtab.MultibootService) if hasattr(mbtab, "MultibootService") else None
    if svc is None:
        cls = next(c for c in vars(mbtab).values() if isinstance(c, type) and hasattr(c, "run_card"))
        svc = cls.__new__(cls)
    svc.window = Win()
    svc._multiboot_panel = SimpleNamespace(platform="s3")
    svc.run_card(OUT)
    assert ("s3", OUT) in calls and ("tab", "emulate") in calls
    assert not any(c[0] == "s2" for c in calls)


def test_the_emulate_tab_marks_the_card_spike3_before_it_starts():
    from pinball_decryptor.webui.tabs import emulate as em
    started = []

    class Var:
        def __init__(self):
            self.v = ""

        def set(self, v):
            self.v = v

        def get(self):
            return self.v
    tab = em.EmulateService.__new__(em.EmulateService) if hasattr(em, "EmulateService") else None
    if tab is None:
        cls = next(c for c in vars(em).values() if isinstance(c, type) and hasattr(c, "launch_spike3_card"))
        tab = cls.__new__(cls)
    tab.emulate_card_var = Var()
    tab._card = lambda: tab.emulate_card_var.get()
    tab._spike3 = None
    tab._spike3_probed = None
    tab.start = lambda: started.append((tab._spike3, tab._spike3_probed))
    tab.launch_spike3_card(OUT)
    assert started == [(True, OUT)]
