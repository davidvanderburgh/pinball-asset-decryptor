"""PAD-1621 proof shots: Replace Images and Replace Video on a Pokemon Pro (Spike 3) project, before and after
the Godot game's pictures and clips (the pokedex, battles and arenas) came out of its resource pack.

    python scripts/shot_pad1621.py <repo> <project> <out_dir> <before|after>

Serves <repo> on scratch settings with <project> (an Extract of the Pokemon Pro 0.87 card made by that repo's
code) as the Stern project, and shoots Replace Images (grouped by scene; Source: Godot, its pokedex tiles open, Bulbasaur picked - main has
neither, so its shot stays on All sources) and Replace Video.
Writes <out_dir>/<kind>_replace_images.png and <kind>_replace_video.png.  The project is never written
(PAD_UI_CAPTURE).

Needs Playwright (the user site-packages one), the installed Edge and the card in D:\\Pinball\\images\\Stern\\spike3.
"""
import json
import os
import site
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike3\pokemon_pro-0_87_0_spike3.Release.64G.sdcard-secure.raw"
TILES = "godot/scenes/shared_items/gfx/char_3_up/pokedex_tiles"
PICK = "001_BULBASAUR_LEFT_3up.png"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo, project, out_dir, kind = (os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]),
                                    os.path.abspath(sys.argv[3]), sys.argv[4])
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1621-")
    launcher = os.path.join(scratch, "launch1621.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_input": CARD, "write_original": CARD,
                                               "extract_output": project, "write_assets": project,
                                               "write_output": scratch}}}, f)
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1100})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "images")
            time.sleep(4)
            webui_shot.api(url, "images.set_grouped", True)
            time.sleep(25)                                    # the scan of ~7000 pictures
            # the Godot game's pictures: main has no such source (refused, All sources stays) and no such rows
            print("source Godot:", webui_shot.api(url, "images.set_source", "Godot"), flush=True)
            time.sleep(3)
            webui_shot.api(url, "images.toggle_group", "godot::" + TILES, True)
            time.sleep(2)
            print("select:", webui_shot.api(url, "images.select", "images/" + TILES + "/" + PICK), flush=True)
            time.sleep(4)
            page.mouse.move(5, 1090)
            page.screenshot(path=os.path.join(out_dir, "%s_replace_images.png" % kind))
            webui_shot.api(url, "ui.select_tab", "video")
            time.sleep(30)
            # the Godot game's clips (arena and battle backgrounds) are all HEVC, named *_h265.mp4
            page.get_by_placeholder("Search").last.fill("h265")
            time.sleep(3)
            row = page.get_by_text("Stadium_01_22_26_h265", exact=False)
            if row.count():
                row.first.click()
                time.sleep(6)
            page.mouse.move(5, 1090)
            page.screenshot(path=os.path.join(out_dir, "%s_replace_video.png" % kind))
            browser.close()
        print("shots in", out_dir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
