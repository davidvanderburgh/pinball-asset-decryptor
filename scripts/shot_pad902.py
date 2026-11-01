"""PAD-902 proof shot: a problem report carries Visual Pinball's controller log.

    python scripts/shot_pad902.py <repo> <out_dir>

Serves <repo> on a scratch settings folder with TEMP pointed at a scratch folder
holding a controller log (padcontroller.log) as a Metallica table writes one, opens
Report a problem from the top bar, previews "What will be sent" and shoots the end of
the record: ``report.png``.  Before PAD-902 the record ends with the app's own log;
after, the controller's lines (the table's run, DOF up and how many events it sent)
follow it.  Needs Playwright (PAD_PWLIB or the user site) and Edge.
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

LOG = """15:36:44 game metallica_spike: map metallica_spike.vpxmap.json: switches=52 solenoids=22 lamp groups=86
15:36:44 DOF for mtl_180h: up
15:36:45 rig: no run up for metallica_spike
15:36:45 starting metallica_spike on slot 1; the table plays once the game is up
15:36:45 run
15:36:46 sol 40 -> 0
15:37:31 rig: rig board slot 1 (metallica_spike)
15:37:31 switch table: 94 ids; padled version 7
15:37:31 attached to rig board slot 1 (metallica_spike) after 46 s
15:37:33 foreground: [B2S Backglass Server] -> the player again (once; the window is the user's from here)
15:37:40 sw 1065 -> id 65 = 1
15:40:02 stop after 17110 polls (0 failed)
15:40:02 DOF for mtl_180h finished after 3184 events
"""


def main():
    repo, out_dir = sys.argv[1:3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad902-")
    temp = os.path.join(scratch, "temp")
    os.makedirs(temp)
    with open(os.path.join(temp, "padcontroller.log"), "w", encoding="utf-8") as f:
        f.write(LOG)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern"}, f)
    import site
    proc, url = webui_shot.start_server(
        settings, scratch, extra_env={"PYTHONPATH": site.getusersitepackages(),
                                      "PAD_REPORTS_URL": "http://127.0.0.1:9",
                                      "TEMP": temp, "TMP": temp})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(3)
            page.locator("button.sx-rep-btn").first.click()
            page.wait_for_selector("#sx-rep-text", timeout=20000)
            page.fill("#sx-rep-text", "Metallica VPX DOF stopped working on the latest release.")
            page.locator("details.sx-rep-facts summary", has_text="What will be sent").click()
            page.wait_for_selector("pre.sx-rep-pre", timeout=20000)
            time.sleep(1.5)
            # the end of the record, where the logs are
            page.evaluate("""() => { const pre = document.querySelector('pre.sx-rep-pre');
                let el = pre; while (el) { el.scrollTop = el.scrollHeight; el = el.parentElement; } }""")
            time.sleep(0.8)
            page.screenshot(path=os.path.join(out_dir, "report.png"))
            print("shot report.png", flush=True)
            print("controller log in the record:",
                  "Visual Pinball controller log" in page.inner_text("pre.sx-rep-pre"), flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
