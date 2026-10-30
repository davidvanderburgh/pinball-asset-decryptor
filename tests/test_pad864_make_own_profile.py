"""PAD-864 (DragonRR): the Color profile tab's overlay is a section of its
own (Spike 2 opens on individual files), every mode has a Machine screen box
that sets every preview's Machine screen switch at once and draws the tab's
own preview through the screen, and Make your own profile saves the test
card and an AI template that Load reads back."""

import io
import os

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.webui import look_switches
from pinball_decryptor.webui.tabs import color as color_tab


def _open(w, proj):
    w.call("ui.set", "extract", "output", str(proj))
    w.call("ui.select_tab", "color")
    w.drain()


def test_the_template_loads_as_it_is_and_names_every_test_card_colour():
    text = color_tab.template_text()
    prof, problems = cp.parse(text)
    assert problems == [] and prof.is_identity() and prof.name == "My machine"
    for v in color_tab.CARD_GREYS:
        assert " %d" % v in text
    for c in (color_tab.CARD_FULL + color_tab.CARD_SEA + color_tab.CARD_SKIN):
        assert "%d %d %d" % c in text
    for k, (lo, hi) in cp.LIMITS.items():
        assert "%-11s %g to %g" % (k, lo, hi) in text
    # its commented examples are valid lines once the # comes off
    live = "\n".join(line[2:] if line.startswith("# range =")
                     or line.startswith("# curve_rgb =") else line
                     for line in text.splitlines())
    prof, problems = cp.parse(live)
    assert problems == [] and len(prof.ranges) == 1


def test_the_test_card_saved_is_the_previews(tmp_path):
    from PIL import Image
    data = color_tab.card_bytes()
    im = Image.open(io.BytesIO(data)).convert("RGB")
    assert im.size == color_tab.CARD_SIZE
    assert im.getpixel((20, 40)) == (0, 0, 0)          # the first grey step
    assert im.getpixel((620, 40)) == (255, 255, 255)   # the last
    assert im.getpixel((20, 100)) == color_tab.CARD_FULL[0]
    assert im.getpixel((20, 220)) == color_tab.CARD_SEA[0]
    assert color_tab.test_card_png().endswith(
        __import__("base64").b64encode(data).decode())


def test_download_buttons_save_the_card_and_a_template_load_reads(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    card = tmp_path / "out" / "card.png"
    tpl = tmp_path / "out" / "template.txt"
    card.parent.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, proj)
        asked = []
        w.window.ask_save = lambda key, title, **k: (
            asked.append((key, k.get("initialfile"))),
            str(card if k.get("defaultextension") == ".png" else tpl))[1]
        assert w.call("color.save_test_card") is True
        assert w.call("color.save_template") is True
        assert card.read_bytes() == color_tab.card_bytes()
        assert tpl.read_text(encoding="utf-8") == color_tab.template_text()
        assert [a[1] for a in asked] == ["PAD color test card.png",
                                         "PAD color profile template.txt"]
        # an AI's answer: the template with numbers in, loaded on Files
        filled = tpl.read_text(encoding="utf-8").replace(
            "gamma = 1.00 1.00 1.00", "gamma = 1.10 1.20 1.35").replace(
            "name = My machine", "name = From the AI")
        tpl.write_text(filled, encoding="utf-8")
        w.window.ask_open = lambda *a, **k: str(tpl)
        assert w.state("color")["mode"] == "assets"
        assert w.call("color.load_file") is True
        w.drain()
        s = w.state("color")
        assert s["problems"] == [] and s["name"] == "From the AI"
        assert s["gamma"] == [1.1, 1.2, 1.35]
        assert cp.asset_profile(str(proj)).gamma == (1.1, 1.2, 1.35)
        # nothing on the overlay
        assert cp.for_project(str(proj)) is None
        # a cancelled dialog saves nothing
        w.window.ask_save = lambda *a, **k: ""
        os.remove(card)
        assert w.call("color.save_test_card") is False and not card.exists()


def test_spike2_opens_on_individual_files_and_the_overlay_is_still_there(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, proj)
        s = w.state("color")
        assert s["per_file"] is True and s["mode"] == "assets"
        assert w.call("color.set_mode", "display") == "display"


def test_machine_screen_box_sets_every_preview_and_the_tabs_own(tmp_path):
    from tests.webui_harness import web_app
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, proj)
        assert w.state("color")["screen_look"] is True       # all on, never set
        assert w.call("color.set_screen_look", False) is False
        w.drain()
        for _ns, where in color_tab.SCREEN_LOOKS:
            sw = look_switches.initial(w.window, where)
            assert sw["screen"] is False and sw["overlay"] and sw["files"]
        assert w.state("video")["look"]["sw"]["screen"] is False
        assert w.state("color")["screen_look"] is False
        # one preview's own switch back on: not every one is, so the box is clear
        w.call("video.set_look_part", "screen", True)
        w.call("color.set_mode", "assets")
        w.drain()
        assert w.state("color")["screen_look"] is False
        assert w.call("color.set_screen_look", True) is True
        w.drain()
        assert all(look_switches.initial(w.window, where)["screen"]
                   for _ns, where in color_tab.SCREEN_LOOKS)
        # what the tab's preview draws after the profile on show
        s = w.state("color")
        screen = cp.screen_shown(str(proj))[0] or cp.SCREEN_PRESETS[0][1]
        assert len(s["after"]) == 1 and s["after"][0]["gamma"] == list(screen.gamma)
        assert s["screen_name"] == screen.label()
        cp.store(str(proj), cp.Profile(name="Overlay", gamma=(1.3, 1.3, 1.3)))
        w.call("color.panel_open")
        w.drain()
        s = w.state("color")
        assert [a["gamma"] for a in s["after"]] == [[1.3, 1.3, 1.3], list(screen.gamma)]
        w.call("color.set_mode", "display")
        w.drain()
        assert [a["gamma"] for a in w.state("color")["after"]] == [list(screen.gamma)]
        w.call("color.set_mode", "screen")
        w.drain()
        assert w.state("color")["after"] == []
