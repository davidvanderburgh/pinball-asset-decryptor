"""PAD-1515 proof: the layout editor with a real mouse, in the real app (Edge, Playwright).
    python drag_check.py [<census dir>]
Wonka 03.03's example mode in a scratch folder: the mode's panel dragged 136 px right and 77 px down,
then sized from its bottom-right corner, then nudged a pixel with the arrow key; with a census of the
game's own screen (default C:\\tmp\\PAD-1515\\show), two of its parts Shift-clicked and dragged as a
group. Each step is read back from the mode file / title.cfg.  rc 0 = all of them.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)
import webui_shot  # noqa: E402
from pinball_decryptor.plugins.jjp import screen_layout as SL  # noqa: E402

ISO = r"D:\Pinball\images\JJP\Wonka-v03.03.iso"
LABEL = "Wonka-v03.03"


def main():
    census = sys.argv[1] if len(sys.argv) > 1 else r"C:\tmp\PAD-1515\show"
    scratch = tempfile.mkdtemp(prefix="pad1515drag-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_input": ISO, "write_original": ISO, "write_output": scratch}}}, f)
    mine = os.path.join(scratch, "jjp_modes", LABEL)
    shutil.copytree(os.path.join(REPO, "tools", "jjp_emu", "modes", "examples", LABEL), mine)
    os.makedirs(os.path.join(mine, ".layout"))
    for f in ("game.json", "game.png"):
        shutil.copy(os.path.join(census, f), os.path.join(mine, ".layout", f))
    import site
    proc, url = webui_shot.start_server(settings, scratch, extra_env={
        "PYTHONPATH": site.getusersitepackages(), "PAD_JJP_MODES_DIR": os.path.join(scratch, "jjp_modes")})
    bad = 0

    def form():
        return ((webui_shot.state(url).get("modes") or {}).get("jjp") or {})

    def check(what, ok, got):
        nonlocal bad
        bad += not ok
        print("%-44s %s  (%s)" % (what, "ok" if ok else "WRONG", got))
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
            webui_shot.api(url, "modes.jjp_open", "1_example.mode")
            time.sleep(2)
            canvas = page.locator(".jjpl[data-screen=mode] .jjpl-canvas").first
            canvas.scroll_into_view_if_needed()
            time.sleep(1)
            cb = canvas.bounding_box()
            k = cb["width"] / 1360.0
            panel = page.locator(".jjpl[data-screen=mode] .jjpl-el.k-panel").first
            pb = panel.bounding_box()
            # drag it by its bottom-left area (the text boxes sit higher), Alt: no snapping
            x0, y0 = pb["x"] + 6, pb["y"] + pb["height"] - 6
            page.keyboard.down("Alt")
            page.mouse.move(x0, y0)
            page.mouse.down()
            for i in range(1, 11):
                page.mouse.move(x0 + 136 * k * i / 10, y0 + 76.8 * k * i / 10)
            page.mouse.up()
            page.keyboard.up("Alt")
            time.sleep(1.5)
            box = SL.parse_box(form().get("form", {}).get("panel_at"))
            check("drag: the panel 10 % right, 10 % down", bool(box) and abs(box[0] - 26) < 0.6 and abs(box[1] - 46) < 0.6, box)
            # its bottom-right handle 68 px right
            h = page.locator(".jjpl[data-screen=mode] .jjpl-h.h-se").first
            hb = h.bounding_box()
            page.keyboard.down("Alt")
            page.mouse.move(hb["x"] + 4, hb["y"] + 4)
            page.mouse.down()
            page.mouse.move(hb["x"] + 4 + 68 * k, hb["y"] + 4, steps=8)
            page.mouse.up()
            page.keyboard.up("Alt")
            time.sleep(1.5)
            box2 = SL.parse_box(form().get("form", {}).get("panel_at"))
            check("size: 5 % wider from its corner", bool(box2) and abs(box2[2] - 73) < 0.6 and abs(box2[0] - 26) < 0.6, box2)
            page.keyboard.press("ArrowLeft")
            time.sleep(1.5)
            box3 = SL.parse_box(form().get("form", {}).get("panel_at"))
            check("nudge: one pixel left", bool(box3) and abs((box2[0] - box3[0]) * 13.6 - 1) < 0.2, box3)
            # the game's own screen: two parts, Shift-clicked, dragged together
            page.get_by_text("Every mode of this game", exact=False).first.click()
            time.sleep(2)
            g = page.locator(".jjpl[data-screen=game] .jjpl-canvas").first
            g.scroll_into_view_if_needed()
            time.sleep(1)
            names = []
            for want in ("sp_ui_bg", "atlas_playerup"):
                chip = page.locator(".jjpl[data-screen=game] .jjpl-pchip", has_text=want).first
                if chip.count():
                    names.append(want)
            if len(names) == 2:
                page.locator(".jjpl[data-screen=game] .jjpl-pchip", has_text=names[0]).first.click()
                page.locator(".jjpl[data-screen=game] .jjpl-pchip", has_text=names[1]).first.click(modifiers=["Shift"])
                time.sleep(0.5)
                sel = page.locator(".jjpl[data-screen=game] .jjpl-el.sel")
                sb = sel.last.bounding_box()
                gk = g.bounding_box()["width"] / 1360.0
                page.keyboard.down("Alt")
                page.mouse.move(sb["x"] + sb["width"] / 2, sb["y"] + sb["height"] / 2)
                page.mouse.down()
                page.mouse.move(sb["x"] + sb["width"] / 2, sb["y"] + sb["height"] / 2 - 153.6 * gk, steps=10)
                page.mouse.up()
                page.keyboard.up("Alt")
                time.sleep(1.5)
                moves = SL.screen_lines(form().get("title_cfg", {}))
                ok = all(n in moves and abs(moves[n]["dy"] + 20) < 0.6 and abs(moves[n]["dx"]) < 0.6 for n in names)
                check("group: %s and %s 20 %% up together" % tuple(names), ok,
                      {n: (moves.get(n) or {}).get("dy") for n in names})
            else:
                check("group: the census has sp_ui_bg and atlas_playerup", False, names)
            b.close()
    finally:
        proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
