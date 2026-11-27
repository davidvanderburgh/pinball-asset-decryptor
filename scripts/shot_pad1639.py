"""PR #53 review proof shots (PAD-1639): CO-OP PLAY Off / On and the boot menu rows.

    python scripts/shot_pad1639.py <repo> <out.png> --screen menu|svcmenu

menu: the Multi-boot tab's Menu settings dialog (Back to this menu: Either), its At power-up box: after, the countdown is
Off / 15 s / 30 s and "Boot menu:" is a choice of three where "Show this menu at power-up" was a tick. svcmenu: the
Service menu tab on a scratch project made from the Godzilla LE 1.16 card, every row this PR adds or renames ticked:
after, Co-op Play, Boot Menu, Boot Menu Timer and Boot Menu Via Flipper.

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
    out = os.path.abspath(sys.argv[2])
    screen = sys.argv[sys.argv.index("--screen") + 1] if "--screen" in sys.argv else "menu"
    scratch = tempfile.mkdtemp(prefix="pad1639-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD), "card_version": "1.16.0"}, f)
    launcher = os.path.join(scratch, "launch1639.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": CARD, "write_original": CARD,
                       "extract_output": project, "write_assets": project, "write_output": scratch}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages(), "USERPROFILE": scratch, "HOME": scratch}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher], extra_env=env)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            if screen == "menu":
                page.get_by_text("Multi-boot", exact=True).first.click()
                time.sleep(3)
                page.get_by_role("button", name="Menu settings…").first.click()
                time.sleep(2)
                pick = page.locator("#mb-f-way_back")
                if pick.count():
                    pick.select_option("both")          # BACK or the right flipper: every row live
                    time.sleep(1)
                line = page.locator(".mb-dlg-menu").get_by_text("Countdown (s):", exact=False).first
                page.evaluate("(el) => el.scrollIntoView({block: 'start'})", line.element_handle())
            else:
                for key in ("coop_play", "boot_show", "boot_timer", "boot_flip"):
                    try:
                        print(key, webui_shot.api(url, "svcmenu.set_row", key, True), flush=True)
                    except Exception as e:                  # noqa: BLE001 - main has no such row
                        print("no %s row:" % key, e, flush=True)
                webui_shot.api(url, "ui.select_tab", "svcmenu")
                time.sleep(6)
                hide = page.get_by_text("Hide log")
                if hide.count():
                    hide.first.click()
                    time.sleep(1)
                row = page.get_by_text("Saved Progress", exact=True).first
                if row.count():
                    page.evaluate("(el) => el.scrollIntoView({block: 'center'})", row.element_handle())
            page.mouse.move(3, 990)                         # no hover tooltip over a row
            time.sleep(1.5)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
