"""PR #53 review (PAD-1639) proof shot: the Modes tab's co-op panel, with "Style picked" beside the default style.

    python scripts/shot_pad1639_coop.py <repo> <out_dir> <before|after>

(Made from shot_pad1558.py.) Both shots set the default style to Characters; after, Style picked is "In the service
menu", shown open as a list box.

Serves <repo> (preview on) on a scratch project made from the Godzilla LE 1.16 card, ticks Co-op play with the
preset characters (their pick on), and writes <kind>_coop_panel.png: the list's foot with the co-op panel. After:
the style set to Characters (the native drop-down cannot be photographed open, so it is shown as a list box).

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
OPEN_LIST = """() => {
  const all = document.querySelectorAll('.modes-coop-style select');
  const sel = all[all.length - 1];
  if (!sel) return 0;
  sel.size = sel.options.length;
  sel.style.height = 'auto';
  sel.closest('.field').style.height = 'auto';
  return sel.options.length;
}"""


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1558-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1558.py")
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
            page = browser.new_page(viewport={"width": 1500, "height": 2000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(6)
            webui_shot.api(url, "modes.set_coop", True)
            time.sleep(3)
            page.get_by_role("button", name="Characters…").dispatch_event("click")
            page.wait_for_selector("text=Co-op characters", timeout=180000)
            webui_shot.api(url, "modes.coop_chars_preset")
            page.wait_for_selector(".modes-coop-ch-row", timeout=180000)
            webui_shot.api(url, "modes.coop_chars_pick", True)
            time.sleep(2)
            page.keyboard.press("Escape")
            time.sleep(2)
            webui_shot.api(url, "modes.set_coop_style", "characters")
            if kind == "after":
                webui_shot.api(url, "modes.set_coop_place", "service")
                time.sleep(2)
                print("style", page.evaluate("() => document.querySelector('.modes-coop-style select').value"), flush=True)
            page.mouse.move(1490, 5)
            time.sleep(1.5)
            panel = page.locator(".modes-coop").first
            panel.evaluate("e => e.scrollIntoView({block: 'center'})")
            time.sleep(1)
            box = panel.bounding_box()
            print("panel", box, flush=True)
            top = max(0, box["y"] - 60)
            clip = {"x": 0, "y": top, "width": min(1500, box["x"] + box["width"] + 300),
                    "height": min(2000 - top, box["height"] + 120)}
            page.screenshot(path=os.path.join(out_dir, "%s_coop_panel.png" % kind), clip=clip)
            print("shot coop_panel", flush=True)
            browser.close()
    finally:
        proc.terminate()
        time.sleep(2)
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
