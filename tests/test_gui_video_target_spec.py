import os, pytest
from pinball_decryptor.core.video import VideoInfo
from pinball_decryptor.core.video_slots import VideoSlot
from tests.conftest import HAS_DISPLAY
from tests.test_gui_smoke import app  # noqa: F401

pytestmark = [pytest.mark.gui,
              pytest.mark.skipif(not HAS_DISPLAY, reason="no Tk")]


def test_target_spec_dialog_opens(app):
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)
    app.root.update()
    w = app.window
    info = VideoInfo(path="a.mov", vcodec="h264", width=1360, height=768,
                     fps=30.0, duration=25.0, pix_fmt="yuv420p",
                     profile="Constrained Baseline", level=30)
    slot = VideoSlot(rel_path="video/AttractMode.mov", abs_path="a.mov",
                     ext=".mov", info=info, size=1)
    w._video_slots_by_rel = {slot.rel_path: slot}
    before = len(app.root.winfo_children())
    w._video_show_target_spec("video/AttractMode.mov")
    app.root.update()
    assert len(app.root.winfo_children()) > before
    import tkinter as tk
    dlgs = [c for c in app.root.winfo_children() if isinstance(c, tk.Toplevel)]
    texts = []
    def walk(wd):
        for ch in wd.winfo_children():
            try:
                texts.append(ch.cget("text"))
            except Exception:
                pass
            if isinstance(ch, tk.Text):
                texts.append(ch.get("1.0", "end"))
            walk(ch)
    for d in dlgs:
        walk(d)
    blob = "\n".join(str(t) for t in texts)
    assert "1360 x 768" in blob
    assert "Constrained Baseline" in blob
    assert "-profile:v baseline" in blob
    assert "-an" in blob
    for d in dlgs:
        d.destroy()


def test_unprobed_slot_says_so_instead_of_a_blank_dialog(app, monkeypatch):
    mfr = next(m for m in app._manufacturers if m.key == "stern")
    app._on_manufacturer_change(mfr)
    app.root.update()
    w = app.window
    slot = VideoSlot(rel_path="video/x.mov", abs_path="x.mov", ext=".mov",
                     info=None, size=1)
    w._video_slots_by_rel = {slot.rel_path: slot}
    said = []
    monkeypatch.setattr(
        "pinball_decryptor.gui.main_window.messagebox.showinfo",
        lambda *a, **k: said.append(a))
    w._video_show_target_spec("video/x.mov")
    assert said
