"""PAD-1475 proof shots: the light shows one of the game's own modes plays, on its page's How it works.

    python scripts/shot_pad1475.py <repo> <outdir> <prefix> [<mode name>] [<project>] [<card>]

The PAD-1274 rig (scripts/shot_pad1274.py) on a James Bond LE 1.06 extract (audio + video), the Modes tab, the game's
mode named <mode name> (default "Aston Martin Multiball"). One shot, <prefix>_modes_how.png in <outdir>: the page
scrolled to How it works (after: "Light shows it plays" under the sounds). Prints the section's text.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike2\james_bond_le-1_06_0.Release.16G.sdcard.raw"
PROJECT = r"C:\tmp\PAD-1475\bondle"
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
    outdir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    want = sys.argv[4] if len(sys.argv) > 4 else "Aston Martin Multiball"
    project = sys.argv[5] if len(sys.argv) > 5 else PROJECT
    card = sys.argv[6] if len(sys.argv) > 6 else CARD
    os.makedirs(outdir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1475-")
    launcher = os.path.join(scratch, "launch1475.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "write_original": card,
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
            page = browser.new_page(viewport={"width": 1500, "height": 1300})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            found = False
            deadline = time.time() + 300
            while time.time() < deadline and not found:
                for mid in range(0, 120):
                    if not webui_shot.api(url, "modes.select", str(mid), "game"):
                        continue
                    time.sleep(0.6)
                    head = page.locator(".modes-editor .hd .h2")
                    if head.count() and head.first.inner_text().strip() == want:
                        found = True
                        print("mode id", mid, flush=True)
                        break
                if not found:
                    time.sleep(3)
            try:
                page.wait_for_selector("text=Sounds and callouts it plays", timeout=240000)
            except Exception:                                # noqa: BLE001
                page.screenshot(path=os.path.join(outdir, "%s_debug.png" % prefix))
                print(page.locator("body").inner_text()[:3000], flush=True)
                raise
            try:
                page.wait_for_function("!document.body.innerText.includes('Reading the card')", timeout=600000)
            except Exception as e:                           # noqa: BLE001
                print("still reading:", e, flush=True)
            time.sleep(3)
            sec = page.locator(".modes-how").first
            sec.scroll_into_view_if_needed()
            print(sec.inner_text(), flush=True)
            k = page.locator(".modes-how-k", has_text="Sounds and callouts").first
            k.scroll_into_view_if_needed()
            page.evaluate("window.scrollBy(0, 0)")
            page.mouse.move(5, 1290)
            time.sleep(1)
            page.screenshot(path=os.path.join(outdir, "%s_modes_how.png" % prefix))
            print("shot modes_how", flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
