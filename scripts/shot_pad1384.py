"""PAD-1384 proof shots: the JJP Modes tab scrolls, and New mode offers Blocks, C++ or the form.

    python scripts/shot_pad1384.py <repo> <out_dir> <before|after>

Jersey Jack picked, the Modes tab, Wonka 03.03, in a 1500x1000 window (a normal app window,
not a tall one, so the page is longer than the window). Shots:

* <kind>_modes_scroll.png - the page after six mouse-wheel turns over the form; prints the
  page's scroll offset (0 = it could not scroll).
* <kind>_modes_new.png - the page right after New mode is clicked.
* after only: <kind>_modes_blocks.png / <kind>_modes_cpp.png - a mode made of blocks and one
  in C++ open in the editor (made through the wizard, as a user would).

Needs Playwright (the user site-packages one) and the installed Edge; the app runs on a
scratch APPDATA.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

WONKA_ISO = r"D:\Pinball\images\JJP\Wonka-v03.03.iso"


def _scroll_top(page):
    return page.evaluate("""() => { const p = document.querySelector('.jjpm-page');
        let n = 0; for (let e = p; e; e = e.parentElement) n += e.scrollTop || 0; return n; }""")


def main():
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1384-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_input": WONKA_ISO, "write_original": WONKA_ISO,
                                             "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch,
                                        extra_env={"PYTHONPATH": site.getusersitepackages(),
                                                   "PAD_JJP_MODES_DIR": os.path.join(scratch, "jjp_modes")})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(3)
            webui_shot.api(url, "modes.jjp_pick_title", "Wonka-v03.03")
            time.sleep(2)
            box = page.locator(".jjpm-editor").bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 200)
            for _ in range(6):
                page.mouse.wheel(0, 400)
                time.sleep(0.3)
            time.sleep(1)
            print("SCROLL", _scroll_top(page))
            page.screenshot(path=os.path.join(out_dir, kind + "_modes_scroll.png"))
            for _ in range(10):
                page.mouse.wheel(0, -1000)
            time.sleep(1)
            page.locator(".jjpm-list-card button", has_text="New mode").click()
            time.sleep(2)
            page.screenshot(path=os.path.join(out_dir, kind + "_modes_new.png"))
            if kind == "after":
                for how, shot, name in (("blocks", "modes_blocks", "Block Rush"), ("cpp", "modes_cpp", "Code Rush")):
                    if not page.locator(".jjpm-new").count():
                        page.locator(".jjpm-list-card button", has_text="New mode").click()
                        time.sleep(1)
                    page.locator(f'.jjpm-new [data-kind="{how}"]').click()
                    time.sleep(1)
                    page.locator("#jjpm-new-name").fill(name)
                    page.screenshot(path=os.path.join(out_dir, kind + "_" + shot + "_wizard.png"))
                    page.locator(".jjpm-new button", has_text="Make it").click()
                    deadline = time.time() + 120          # its C++ built in the app's Linux
                    while time.time() < deadline:
                        c = webui_shot.state(url)["modes"]["jjp"].get("code") or {}
                        if not c.get("running") and not c.get("stale"):
                            break
                        time.sleep(2)
                    time.sleep(2)
                    j = webui_shot.state(url)["modes"]["jjp"]
                    print(how.upper(), j.get("open"), j.get("kind"), "code:", {k: v for k, v in (j.get("code") or {}).items() if k != "lines"},
                          "check:", (j.get("check") or {}).get("problems"))
                    page.screenshot(path=os.path.join(out_dir, kind + "_" + shot + ".png"))
            browser.close()
    finally:
        proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
