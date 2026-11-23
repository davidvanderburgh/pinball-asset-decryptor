"""PAD-1515 proof: the layout editor's preview against the game's own frames.
    python compare.py <rig shots dir> [<editor shots dir>]
Opens tools/jjp_emu/proof/pad1515/modes in the app's Modes tab (a scratch copy; Wonka 03.03), shoots
each layout editor's canvas (box outlines hidden), and measures the proof's exact colors in it and in
the rig's frames (run.sh: mode.png, menu.png, board1.png), in screen pixels (1360x768):
  the mode panel ff00ff, its picture 00ff00, the menu 0000a0, the panes ff0000 / 0000ff.
Every edge must agree within 3 px.  Needs Playwright (PAD_PWLIB / the user site) and Edge.
"""
import json
import os
import shutil
import sys
import tempfile
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import webui_shot  # noqa: E402

ISO = r"D:\Pinball\images\JJP\Wonka-v03.03.iso"
W, H = 1360, 768
TOL = 3


def bbox(img, rgb, tol=8):
    a = np.asarray(img.convert("RGB")).astype(int)
    m = (abs(a[..., 0] - rgb[0]) <= tol) & (abs(a[..., 1] - rgb[1]) <= tol) & (abs(a[..., 2] - rgb[2]) <= tol)
    if m.sum() < 50:
        return None
    rows = np.nonzero(m.sum(1) >= 0.5 * m.sum(1).max())[0]
    cols = np.nonzero(m.sum(0) >= 0.5 * m.sum(0).max())[0]
    sx, sy = W / a.shape[1], H / a.shape[0]
    return [round(float(v), 1) for v in (cols.min() * sx, rows.min() * sy, (cols.max() + 1) * sx, (rows.max() + 1) * sy)]


def editor_shots(out):
    scratch = tempfile.mkdtemp(prefix="pad1515cmp-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_input": ISO, "write_original": ISO, "write_output": scratch}}}, f)
    shutil.copytree(os.path.join(HERE, "modes"), os.path.join(scratch, "jjp_modes", "Wonka-v03.03"))
    import site
    proc, url = webui_shot.start_server(settings, scratch, extra_env={
        "PYTHONPATH": site.getusersitepackages(), "PAD_JJP_MODES_DIR": os.path.join(scratch, "jjp_modes")})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(channel="msedge")
            page = b.new_page(viewport={"width": 1700, "height": 1100})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(3)
            page.add_style_tag(content=".jjpl-el, .jjpl-el.dflt, .jjpl-el.sel { outline: none !important; } .jjpl-tag { display: none !important; }")
            shots = {}
            for fn, screen, name in (("2_layout.mode", "mode", "mode"), ("1_wizard.mode", "progress", "board1")):
                webui_shot.api(url, "modes.jjp_open", fn)
                time.sleep(2)
                c = page.locator(".jjpl[data-screen=%s] .jjpl-canvas" % screen).first
                c.scroll_into_view_if_needed()
                time.sleep(1.5)
                shots[name] = os.path.join(out, "editor_%s.png" % name)
                c.screenshot(path=shots[name])
            page.get_by_text("Every mode of this game", exact=False).first.click()
            time.sleep(2)
            c = page.locator(".jjpl[data-screen=menu] .jjpl-canvas").first
            c.scroll_into_view_if_needed()
            time.sleep(1.5)
            shots["menu"] = os.path.join(out, "editor_menu.png")
            c.screenshot(path=shots["menu"])
            b.close()
        return shots
    finally:
        proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    rig = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else rig
    os.makedirs(out, exist_ok=True)
    ed = editor_shots(out)
    checks = (("mode", "the mode's panel", (255, 0, 255)), ("mode", "its picture", (0, 255, 0)),
              ("menu", "the menu", (0, 0, 160)), ("board1", "pane 1 (lit)", (255, 0, 0)))
    bad = 0
    for shot, what, rgb in checks:
        r = bbox(Image.open(os.path.join(rig, shot + ".png")), rgb)
        e = bbox(Image.open(ed[shot]), rgb)
        d = max(abs(x - y) for x, y in zip(r, e)) if r and e else None
        ok = d is not None and d <= TOL
        bad += not ok
        print("%-18s game %-28s editor %-28s %s" % (what, r, e, "ok (%.1f px)" % d if ok else "DIFFERS"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
