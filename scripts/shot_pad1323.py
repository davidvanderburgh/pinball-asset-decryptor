"""PAD-1323 proof shots: random clips and screen times on a Stern Spike 3 project, before and after.

    python scripts/shot_pad1323.py <repo> <out_png> <project> <search> <row clip> menu|hover

Serves <repo> on <project> (a Spike 3 extract, its .extract_source.json naming the card), opens the Video tab,
types <search> in Search and selects the row whose file is <row clip>; then

- ``menu``  right-clicks it and opens the menu's "Random clips" (Star Wars ELG: before, the game's clips cannot be
  hooked on this build; after, "Add clips to play at random...")
- ``hover`` hovers the row's screen-time tag (Fallout: before, none - the card's 64-bit program was not read; after,
  the game's own time for the screen that shows it)

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
    repo, out_png, project, search, row, mode = (os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]),
                                                 os.path.abspath(sys.argv[3]), sys.argv[4], sys.argv[5],
                                                 sys.argv[6])
    with open(os.path.join(project, ".extract_source.json"), encoding="utf-8") as f:
        card = json.load(f)["input_path"]
    scratch = tempfile.mkdtemp(prefix="pad1323-")
    launcher = os.path.join(scratch, "launch1323.py")
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
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 860})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "video")
            time.sleep(25)                      # the scan, its probe pass, the card's program and banks
            box = page.get_by_placeholder("Search").first
            box.fill(search)
            time.sleep(3)
            page.locator(".vid-name", has_text=row).first.click()
            time.sleep(4)
            page.evaluate("() => document.querySelectorAll('video').forEach((v) => { v.pause(); })")
            if mode == "menu":
                page.locator(".vid-name", has_text=row).first.click(button="right")
                time.sleep(1)
                item = page.locator(".menu .mi:has-text('Random clips')").first
                if item.count():
                    item.hover()
                    time.sleep(1)
                print("menu:", page.locator(".menu .mi").all_inner_texts(), flush=True)
            else:
                cell = page.locator(".vid-scr").first
                print("screen-time tags:", page.locator(".vid-scr").count(), flush=True)
                if cell.count():
                    cell.hover()
                    time.sleep(1.5)
                else:
                    page.mouse.move(5, 855)
                    time.sleep(1)
            page.screenshot(path=out_png)
            print("page errors:", errors, flush=True)
            browser.close()
        print("shot", out_png, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
