"""PAD-1326 proof shots: the Modes tab's Co-op play and Handicap per player for a Spike 3 project (Star Wars ELG 1.10),
both ticked with CO-OP PLAY in the service menu, before and after co-op and the handicaps went on Spike 3.
    python scripts/shot_pad1326.py <repo> <out_dir> <before|after>
Serves <repo>, with the mode maker's preview on, on a scratch project made from the Star Wars ELG 1.10 Spike 3 card,
opens the Modes tab, ticks Co-op play (and its service-menu row) and Handicap per player, and shoots the page around
them. Writes <out_dir>/<kind>_spike3_coop_handicap.png.
Needs Playwright (the user site-packages one), the installed Edge and the card in D:\\Pinball\\images\\Stern\\spike3.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike3\star_wars_elg-1_10_0_spike3.Release.64G.sdcard-secure.raw"

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1326-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.10.0"}, f)
    launcher = os.path.join(scratch, "launch1326.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": CARD, "write_original": CARD,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1900})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(8)
            for rpc, arg in (("modes.set_coop", True), ("modes.set_coop_menu", True), ("modes.set_handicap", True)):
                try:
                    webui_shot.api(url, rpc, arg)
                except Exception as e:                   # noqa: BLE001 - the before build may refuse a tick
                    print(rpc, "refused:", e, flush=True)
                time.sleep(3)
            time.sleep(4)
            el = page.get_by_text("Co-op play", exact=True).first
            el.scroll_into_view_if_needed()
            time.sleep(2)
            box = el.bounding_box()
            top = max(0, (box["y"] if box else 0) - 520)
            page.screenshot(path=os.path.join(out_dir, "%s_spike3_coop_handicap.png" % kind),
                            clip={"x": 0, "y": top, "width": 1500, "height": 1400})
            webui_shot.api(url, "ui.select_tab", "playopts")      # Handicap per player is a play option
            time.sleep(5)
            page.mouse.move(5, 1890)
            page.screenshot(path=os.path.join(out_dir, "%s_spike3_play_options.png" % kind),
                            clip={"x": 0, "y": 0, "width": 1500, "height": 1000})
            browser.close()
        print("shot in", out_dir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
