"""PAD-1476 proof shots: a mode's Lights page and the co-op intro, offering the light shows the game's own modes play.

    python scripts/shot_pad1476.py <repo> <out_dir> <before|after> <intro video>

Serves <repo> (preview on) on a scratch project made from the Godzilla LE 1.16 card (the PAD-1114 rig,
scripts/shot_pad1114.py), and writes two shots to <out_dir>:

* <kind>_mode_lights.png - a new mode's Lights page, "The game's light shows", its "When it starts" list drawn open
  (the native drop-down cannot be photographed, so it is shown as a list box). After: the shows of the game's own
  modes under each mode (read off the card), the start show set to first lit show (#210).
* <kind>_coop_intro.png - the Co-op characters dialog with <intro video> as the co-op and team games' intro. After:
  its "Light show with it" row, set to a lit show of the game's (#214).

Needs Playwright (the user site-packages one), the installed Edge and the card in D:\\Pinball\\images\\Stern\\spike2.
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''
OPEN_LIST = """(lab) => {
  const row = [...document.querySelectorAll('.modes-kv .lbl')].find((e) => e.textContent.trim() === lab);
  const sel = row && row.nextElementSibling && row.nextElementSibling.querySelector('select');
  if (!sel) return 0;
  sel.size = Math.min(sel.options.length + sel.querySelectorAll('optgroup').length, 26);
  sel.style.height = 'auto'; sel.style.width = '420px';
  sel.closest('.field').style.height = 'auto'; sel.closest('.field').style.width = '420px';
  return sel.options.length;
}"""


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    video = os.path.abspath(sys.argv[4])
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1476-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1476.py")
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
        sys.path.insert(0, repo)
        from pinball_decryptor.plugins.stern import coop_play as CP
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1300})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(6)
            # ---- a mode's Lights page
            webui_shot.api(url, "modes.new")
            time.sleep(3)
            page.get_by_role("tab", name="Lights").first.click()
            page.wait_for_selector("text=The game's light shows", timeout=60000)
            if kind == "after":            # the card's reading (the game's modes' shows) comes from a worker
                try:
                    page.wait_for_function("[...document.querySelectorAll('optgroup')].some((g) => "
                                           "g.label.startsWith('From '))", timeout=600000)
                except Exception as e:                       # noqa: BLE001
                    print("no mode shows:", e, flush=True)
                webui_shot.api(url, "ui.set", "modes", "f:show_start", "#210")
                time.sleep(3)
            n = page.evaluate(OPEN_LIST, "When it starts")
            print("start list options", n, flush=True)
            page.locator(".modes-kv .lbl", has_text="When it starts").first.evaluate(
                "e => e.scrollIntoView({block: 'start'})")
            page.mouse.move(5, 1290)
            time.sleep(1.5)
            page.screenshot(path=os.path.join(out_dir, "%s_mode_lights.png" % kind))
            print("shot mode_lights", flush=True)
            # ---- the co-op intro
            page.set_viewport_size({"width": 1500, "height": 1900})
            webui_shot.api(url, "modes.set_coop", True)
            time.sleep(3)
            page.get_by_role("button", name="Characters…").dispatch_event("click")
            page.wait_for_selector("text=Co-op characters", timeout=180000)
            webui_shot.api(url, "modes.coop_chars_preset")
            page.wait_for_selector(".modes-coop-ch-row", timeout=180000)
            CP.save_intro(project, video)
            if kind == "after":
                webui_shot.api(url, "modes.coop_intro_show", "#214")
            webui_shot.api(url, "modes.coop_chars_show", 0)
            time.sleep(5)
            print("intro", CP.load_characters(project).get("intro"), CP.load_characters(project).get("intro_show"),
                  flush=True)
            page.mouse.move(5, 1890)
            time.sleep(2)
            page.screenshot(path=os.path.join(out_dir, "%s_coop_intro.png" % kind))
            print("shot coop_intro", flush=True)
            browser.close()
    finally:
        proc.terminate()
        time.sleep(2)
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
