"""PAD-1547 proof shots: Images tab on a Sonic (JJP) extract, a ring-display frame right-clicked,
and after: the pixel editor open on it.

    python scripts/shot_pad1547.py <project> <out_dir> <before|after>

<project> is a scratch Sonic extract (graphics/Mini LED ...); its caches get rebuilt, so never point
this at a real project.  Writes <out_dir>/<kind>_menu.png and <kind>_editor.png.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

FIND = os.environ.get("PAD1547_FIND", "Bad_Crabby_Loop03")


def main():
    project, out_dir, kind = (os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3])
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1547-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_output": project, "write_assets": project,
                                             "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch, extra_env={
        "PYTHONPATH": site.getusersitepackages(),
        "PYTHONUSERBASE": os.path.join(os.environ.get("APPDATA", ""), "Python")})
    print("repo", os.path.dirname(HERE), "url", url, flush=True)
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        webui_shot.api(url, "ui.select_tab", "images")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 980})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            page.get_by_role("button", name="Scan", exact=True).click()
            page.locator(".img-page input.search, .img-page .search input").first.fill(FIND)
            row = page.locator(".img-tbl .tr", has_text=FIND).first
            try:
                row.wait_for(timeout=int(os.environ.get("PAD1547_ROW_WAIT", "240000")))
            except Exception:
                page.screenshot(path=os.path.join(out_dir, "%s_debug.png" % kind))
                raise
            time.sleep(1.5)
            row.click()
            time.sleep(1.5)
            row.click(button="right")
            time.sleep(1.0)
            page.screenshot(path=os.path.join(out_dir, "%s_menu.png" % kind))
            item = page.get_by_text("Edit pixels", exact=False)
            if item.count():
                item.first.click()
                page.locator(".pxe").first.wait_for(timeout=20000)
                time.sleep(1.5)
                for k in (os.environ.get("PAD1547_STROKES") or "").split(";"):
                    if k:
                        x, y = (float(v) for v in k.split(","))
                        box = page.locator(".pxe-canvas").bounding_box()
                        page.mouse.click(box["x"] + box["width"] * x, box["y"] + box["height"] * y)
                time.sleep(1.5)
            else:
                page.keyboard.press("Escape")
                time.sleep(0.5)
            page.screenshot(path=os.path.join(out_dir, "%s_editor.png" % kind))
            print("shots in", out_dir, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
