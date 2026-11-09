"""PAD-1083 proof shots: the Co-op characters dialog with Godzilla's set loaded and BIOGOJI (six powers) shown, and
BIOGOJI's pick card full size, whose badge ran off the card.

    python scripts/shot_pad1083.py <repo> <out_dir> <before|after>

Serves <repo>, with the mode maker's preview on, on a scratch project made from the Godzilla LE 1.16 card, opens the
Modes tab's Co-op characters dialog, loads Godzilla's set and shows BIOGOJI. Writes <out_dir>/<kind>_card_biogoji_set.png (the set as
loaded), then, with BIOGOJI's own badge words emptied (a project saved before the set had them),
<kind>_characters_dialog.png and <kind>_card_biogoji.png.

Needs Playwright (the user site-packages one), the installed Edge and the card in D:\\Pinball\\images\\Stern\\spike2.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

BIO = 5                                                     # BIOGOJI in Godzilla's set
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


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    print("repo", repo, flush=True)
    scratch = tempfile.mkdtemp(prefix="pad1083-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1083.py")
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
            page = browser.new_page(viewport={"width": 1500, "height": 1800})
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
            chars = dict(CP.load_characters(project), pick=True)          # the shipped set, as Load gives it
            with open(os.path.join(out_dir, "%s_card_biogoji_set.png" % kind), "wb") as f:
                f.write(CP.preview(project, chars, CP.words_for(), BIO))
            # the reporter's own project: BIOGOJI's six powers saved with no badge words of its own
            webui_shot.api(url, "modes.coop_char_set", BIO, None, None, None, "")
            webui_shot.api(url, "modes.coop_chars_show", BIO)
            time.sleep(4)
            chars = CP.load_characters(project)
            print("rows", [(c["name"], c.get("header"), c["powers"]) for c in chars["list"]], flush=True)
            page.locator(".modes-coop-ch-row").nth(BIO).scroll_into_view_if_needed()
            page.mouse.move(5, 1790)
            time.sleep(2)
            page.screenshot(path=os.path.join(out_dir, "%s_characters_dialog.png" % kind))
            if os.environ.get("PAD1083_CLICK"):                  # the warning's link opens the badge-words box
                page.get_by_text("Write shorter badge words").click()
                box = page.locator(".modes-coop-ch-powers input").last
                box.wait_for(timeout=10000)
                print("badge box placeholder:", box.get_attribute("placeholder"), flush=True)
                box.scroll_into_view_if_needed()
                page.screenshot(path=os.environ["PAD1083_CLICK"])
            browser.close()
        chars = dict(CP.load_characters(project), pick=True)
        with open(os.path.join(out_dir, "%s_card_biogoji.png" % kind), "wb") as f:
            f.write(CP.preview(project, chars, CP.words_for(), BIO))
        print("shots in", out_dir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
