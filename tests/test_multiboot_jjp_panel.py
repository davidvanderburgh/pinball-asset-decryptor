"""Multi-boot panel, the JJP platform (item 118): the widgets follow the
backend.  Built on an invisible, parked root the way tests/test_multiboot_tab.py
builds its panels; skipped where Tk is unusable."""
import pytest

from pinball_decryptor.gui import multiboot_tab
from pinball_decryptor.gui.multiboot_backend import JJP, STERN


@pytest.fixture(autouse=True)
def _no_wsl(monkeypatch):
    monkeypatch.setattr(multiboot_tab, "wsl_home", lambda: "/home/x")
    monkeypatch.setattr(multiboot_tab, "wsl_account", lambda: ("x", "/home/x"))


def _root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip("Tk unavailable: %s" % exc)
    root.attributes("-alpha", 0)
    root.geometry("+10000+10000")
    return root


def _panel(**kw):
    tk = pytest.importorskip("tkinter")
    from tkinter import ttk
    root = _root()
    frame = ttk.Frame(root)
    frame.pack(fill=tk.BOTH, expand=True)
    panel = multiboot_tab.MultibootPanel(frame, log=lambda m: None, **kw)
    panel.build(frame)
    panel._auto_preview.set(False)
    panel._auto_plan = False
    root.update()
    return root, panel


def _shown(widget):
    return bool(widget.winfo_manager())


def test_a_jjp_panel_wears_the_jjp_words():
    root, panel = _panel(platform="jjp")
    try:
        assert panel.platform == "jjp"
        assert panel._src_lbl.cget("text") == JJP.out_label
        assert panel._size_lbl.cget("text") == "USB stick needed:"
        assert panel.BUILD_FLASH_TEXT == JJP.build_flash_text
        assert panel._check_lbls["card"].cget("text").endswith("Install ISO")
        assert panel._check_lbls["ready"].cget("text").endswith("Ready for the stick")
        assert not _shown(panel._from_card_btn) and not _shown(panel._recover_btn)
        assert not _shown(panel._compact_chk)
        assert panel._selector_var.get() == JJP.selector_default
        assert [c[1] for c in panel.add_row_choices()] == ["_add_image"]
        assert panel.form().platform == "jjp"
        assert panel._about_badge.icon_tip.text == panel.ABOUT_TIP_JJP
    finally:
        root.destroy()


def test_switching_platforms_clears_the_form_and_swaps_the_words():
    root, panel = _panel()
    try:
        assert panel.platform == "stern"
        assert _shown(panel._from_card_btn) and _shown(panel._recover_btn)
        assert _shown(panel._compact_chk)
        panel.add_image("D:/x/a.raw")
        panel.add_image("D:/x/b.raw")
        assert len(panel._rows) == 2
        assert panel.set_platform("jjp") is True
        assert panel.platform == "jjp" and panel._rows == []
        assert panel._out_var.get() == ""
        assert panel._src_lbl.cget("text") == JJP.out_label
        assert not _shown(panel._from_card_btn) and not _shown(panel._compact_chk)
        assert panel.set_platform("jjp") is False               # already there
        panel.add_image("D:/x/GunsNRoses-v03.03.iso")
        assert panel._rows[0].title == "GunsNRoses-v03.03"
        assert panel._out_var.get().replace("\\", "/").endswith("/x/multi/GunsNRoses-v03.03.multi.iso")
        panel.add_image("D:/x/second.iso")
        panel.add_image("D:/x/third.iso")                       # a JJP install holds two
        assert len(panel._rows) == 2
        assert panel.set_platform("stern") is True
        assert panel._rows == [] and panel._src_lbl.cget("text") == STERN.out_label
        assert _shown(panel._from_card_btn) and _shown(panel._recover_btn) and _shown(panel._compact_chk)
        assert panel._selector_var.get() == multiboot_tab.DEFAULT_SELECTOR_DIR
        assert panel._check_lbls["card"].cget("text").endswith("Card image")
        assert panel._about_badge.icon_tip.text == panel.ABOUT_TIP
    finally:
        root.destroy()
