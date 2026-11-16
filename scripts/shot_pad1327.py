"""PAD-1327 proof shot: Prolonged Competition on a Spike 3 Star Wars ELG 1.10 project (the play options).

    python scripts/shot_pad1327.py <repo> <out.png> [--tick] [--tab playopts|modes] [--records [--counts]]

Serves <repo>, with the mode maker's preview on, on a scratch project made from the Star Wars ELG 1.10 Spike 3 card (its
.extract_source.json names it) and shows the play options. Before (main) Prolonged Competition is not offered for it;
after it is, and with --tick it is ticked.

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

CARD = os.environ.get("PAD1327_CARD") or r"D:\Pinball\images\Stern\spike3\star_wars_elg-1_10_0_spike3.Release.64G.sdcard-secure.raw"
CARD_VERSION = os.environ.get("PAD1327_VERSION", "1.10.0")   # round 2: Fallout LE 0.82 (PAD1327_CARD)
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
    out = os.path.abspath(sys.argv[2])
    tick = "--tick" in sys.argv[3:]
    tab = sys.argv[sys.argv.index("--tab") + 1] if "--tab" in sys.argv else "playopts"
    contract = False
    scratch = tempfile.mkdtemp(prefix="pad1327-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": CARD_VERSION}, f)
    launcher = os.path.join(scratch, "launch1327.py")
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
            page = browser.new_page(viewport={"width": 1500, "height": 2600 if contract else 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", tab)
            time.sleep(6)
            if "--records" in sys.argv[3:]:      # round 4: the High scores button under the mode list opens the records
                page.get_by_text("High scores").first.click()
                time.sleep(4)
                if "--counts" in sys.argv[3:]:   # round 6: a new record that counts shots and goals
                    page.get_by_role("button", name="New record").first.click()
                    time.sleep(1)
                    page.get_by_text("Shots and goals", exact=True).first.click()
                    time.sleep(2)
            if tick:
                webui_shot.api(url, "modes.set_prolonged_comp", True)
                time.sleep(3)
            if contract:            # the Score feed card alone, its API contract open
                page.get_by_text("What your server receives").click()
                time.sleep(1)
                page.locator(".po-opt", has_text="Score feed").first.screenshot(path=out)
            else:
                page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
