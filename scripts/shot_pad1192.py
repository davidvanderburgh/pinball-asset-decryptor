"""PAD-1192 proof shots: the Co-op characters dialog with Godzilla's set loaded, a damaged picture (its image data
garbled, every PNG checksum right - what hung a Write for hours) chosen as SOKOGEKIGOJI's (character 10) "When picked"
clip through the real button. Before: it is taken; after: it is refused, the log saying why.

    python scripts/shot_pad1192.py <repo> <out_dir> <before|after> <damaged picture>

Writes <out_dir>/<kind>_characters_dialog.png. Needs Playwright (the user site-packages one), the installed Edge and
the Godzilla LE 1.16 card in D:\\Pinball\\images\\Stern\\spike2 (as scripts/shot_pad1123.py).
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"
LAUNCHER = r'''
import os, sys
sys.path.insert(0, %r)
from pinball_decryptor.core import preview
preview.enabled = lambda feature: True
from pinball_decryptor.webui import compat
compat.filedialog.askopenfilename = lambda **kw: os.environ["PAD1192_PICK"]     # the file chosen in the dialog
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    bad = os.path.abspath(sys.argv[4])
    scratch = tempfile.mkdtemp(prefix="pad1192-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1192.py")
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
        extra_env={"PYTHONPATH": site.getusersitepackages(), "PAD1192_PICK": bad})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1300})
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
            row = page.locator(".modes-coop-ch-row").nth(9)                 # SOKOGEKIGOJI, character 10
            row.scroll_into_view_if_needed()
            row.get_by_role("button", name="When picked").first.dispatch_event("click")
            time.sleep(2)
            took = webui_shot.api(url, "modes.coop_char_picked", 9)
            print("coop_char_picked ->", took, flush=True)
            time.sleep(3)
            page.mouse.move(5, 1290)
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, "%s_characters_dialog.png" % kind))
            browser.close()
        print("shots in", out_dir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
