"""PAD-1488 (PR #42) proof shot: the Images tab's resolution columns.

    python scripts/shot_pad1488.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad1462's scratch King Kong LE project with one 310x310 scene picture replaced by a
1240x1240 picture of itself (four times the original) and its Imported size (Keep size before) ticked, then
photographs the Images tab with that row selected:

- images_columns.png   before: one Resolution column and Keep size; after: Origin, Original, Imported, Current,
                       Written, and the preview's note on the size the Write puts it on at

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
import shot_pad1462 as themes  # noqa: E402,F401 - sets the King Kong scratch source on shot_pad312
import shot_pad360 as saved  # noqa: E402
import shot_pad463 as imgs  # noqa: E402

NAME = "radimg_310x310_031445cf.png"
PIC = imgs.TEX + NAME


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad1488-")
    project = imgs._project(scratch)
    folder = os.path.join(scratch, "My color profiles")
    os.makedirs(folder)
    from PIL import Image
    with Image.open(os.path.join(project, *PIC.split("/"))) as im:
        big = im.convert("RGBA").resize((im.width * 4, im.height * 4), Image.LANCZOS)
    mine = os.path.join(scratch, "big_" + NAME)
    big.save(mine)
    side = os.path.join(project, ".staged_changes.json")
    with open(side, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("image", {})[PIC] = mine
    data["image_keep_size"] = [PIC]
    with open(side, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print("serving", repo, "project", project, flush=True)
    proc, url = saved._serve(repo, scratch, project, folder)
    state = lambda: webui_shot.state(url)                    # noqa: E731

    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open.images', '0');"
                " localStorage.setItem('pad.colorbar.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "images")
            time.sleep(2)
            themes.base._wait_scan(state, "images")
            key = NAME.split("_")[-1][:8]
            webui_shot.api(url, "ui.set", "images", "search", "310x310")
            time.sleep(3)
            page.locator(".img-tbl .tr:has-text('%s')" % key).first.click()
            time.sleep(4)
            try:
                page.wait_for_function("!document.querySelector('.toast')", timeout=15000)
            except Exception:                               # noqa: BLE001
                pass
            page.mouse.move(5, 990)
            time.sleep(2)
            rows = [r for r in (state().get("images") or {}).get("rows") or [] if key in json.dumps(r)]
            print("row:", json.dumps(rows[:1])[:600], flush=True)
            print("preview keep:", json.dumps((state().get("images") or {}).get("preview", {}).get("keep"))[:600],
                  flush=True)
            page.screenshot(path=out("images_columns.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
