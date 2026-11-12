"""PAD-1191 proof shots: the Video tab's player, and (``full``) the same player after its Full screen
button is pressed, playing.

    python scripts/shot_pad1191.py <repo> <out_png> <project> [full]

Serves <repo> on <project> (a video extract, its .extract_source.json naming the card), opens the
Video tab and selects the first clip.  With ``full`` it presses the player's Full screen button and
plays the clip for a few seconds before the shot.  In a browser the page fills the browser window
(the desktop app also takes its window full screen; Playwright's page has no such window).
Needs Playwright (the user site-packages one) and the installed Edge.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def main():
    repo, out_png, project = (os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]),
                              os.path.abspath(sys.argv[3]))
    full = len(sys.argv) > 4 and sys.argv[4] in ("full", "compare")
    compare = len(sys.argv) > 4 and sys.argv[4] == "compare"
    with open(os.path.join(project, ".extract_source.json"), encoding="utf-8") as f:
        card = json.load(f)["input_path"]
    scratch = tempfile.mkdtemp(prefix="pad1191-")
    launcher = os.path.join(scratch, "launch1191.py")
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
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    print("repo", repo, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.on("console", lambda m: print("console:", m.type, m.text, flush=True)
                    if m.type in ("error", "warning") else None)
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "video")
            time.sleep(15)                      # the scan and its probe pass
            hide = page.get_by_role("button", name="Hide log")
            if hide.count():
                hide.first.click()
                time.sleep(1)
            page.locator(".vid-name").first.click()
            time.sleep(5)
            if compare:
                page.locator("button.btn", has_text="Compare").first.click()
                time.sleep(5)
                print("compare tiles:", page.locator(".vcm-tile").count(), flush=True)
            if full:
                btn = page.get_by_role("button", name="Full screen").first
                print("full screen buttons:", page.get_by_role("button", name="Full screen").count(), flush=True)
                btn.click()
                time.sleep(1.5)
                print("pane full:", page.locator(".vid-pane.vid-full").count(), flush=True)
                page.locator(".vid-full .vid-transport button").first.click()     # Play
                time.sleep(1.2)
                page.mouse.move(750, 900)       # the controls show while the pointer moves
                time.sleep(0.5)
            else:
                page.locator(".vid-transport").first.scroll_into_view_if_needed()
                page.mouse.move(5, 995)
                time.sleep(1)
            page.screenshot(path=out_png)
            if full:
                page.keyboard.press("Escape")
                time.sleep(1)
                print("after Esc, pane full:", page.locator(".vid-pane.vid-full").count(), flush=True)
            browser.close()
        print("shot", out_png, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
