"""PAD-508 proof shots: Up / Down step through the Scenes tab's Layers and Contents lists
(they scrolled the list, like the mouse wheel), and a Table with several rows selected
goes on from the last one instead of jumping to its top row.

    python scripts/shot_pad508.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch copy of the Godzilla project, plus five of its
small mode clips for the Video list.  Real key presses (Playwright, the installed Edge),
under the same names before and after:

- scenes_layers.png    the score panel's Layers: a layer clicked, then Down three times
- scenes_contents.png  the same scene's Contents: a picture clicked, then Down twice
- video_multi.png      Video: a clip clicked, a second one Ctrl-clicked, then Down once

Each step's selection, the list's scroll and what has the focus go to the console.
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

SCORE = "/godzilla_le/assets/lcd/auto_loaded/9d57875196c613785a1eee010c55223a0f1aa821"
CLIPS = ("atomic_breath", "destoroyah", "king_ghidorah", "mechagodzilla", "mothra_s_song")

PROBE = r"""(sel) => {
  const box = [...document.querySelectorAll(sel)].find((t) => t.getClientRects().length);
  if (!box) return null;
  const sc = box.querySelector('.scroller') || box;
  const rows = [...sc.querySelectorAll(sc === box ? '.sc-item:not(.note)' : '.tr.click')];
  const on = rows.map((r, i) => (r.classList.contains('sel') ? i : -1)).filter((i) => i >= 0);
  const ae = document.activeElement;
  return {rows: rows.length, sel: on, name: on.length ? rows[on[on.length - 1]].textContent.slice(0, 32) : null,
          scrollTop: Math.round(sc.scrollTop), focusInList: !!(ae && sc.contains(ae)),
          focus: ae ? ae.tagName + '.' + String(ae.className || '').slice(0, 30) : null};
}"""


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad508-")
    project = base._project(scratch)
    for m in CLIPS:
        src = os.path.join(base.SOURCE, "modes", m)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(project, "modes", m))
    print("serving", repo, "project", project, flush=True)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    from playwright.sync_api import sync_playwright

    def settle(page, wait=1.5):
        try:
            page.wait_for_function("!document.querySelector('.toast')", timeout=15000)
        except Exception:                               # noqa: BLE001
            print("toasts still up", flush=True)
        page.mouse.move(5, 1140)
        time.sleep(wait)

    def wait_for(page, sel, n, limit=120):
        deadline = time.time() + limit
        while time.time() < deadline and page.locator(sel).count() < n:
            time.sleep(1)
        return page.locator(sel).count()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1150})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open', '0');"
                " localStorage.setItem('pad.fontbar.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)

            def keys(label, sel, seq):
                for k in seq:
                    page.keyboard.press(k)
                    time.sleep(1.5)
                    print(label, k, page.evaluate(PROBE, sel), flush=True)

            # ---- Scenes: Layers
            api("ui.select_tab", "scenes")
            wait_for(page, ".scenes-list .tr.click", 4)
            time.sleep(2)
            api("text_scenes.select", SCORE + "/scene.radium") or api("text_scenes.select", SCORE)
            wait_for(page, ".tree-layers .ly-item", 8, 90)
            time.sleep(4)
            sel = ".tree-layers"
            page.locator(sel + " .ly-item").nth(2).locator(".sc-t").click()
            time.sleep(2)
            print("layers: row 2 clicked", page.evaluate(PROBE, sel), flush=True)
            keys("layers", sel, ("ArrowDown", "ArrowDown", "ArrowDown"))
            tv = (webui_shot.state(url).get("text_scenes") or {}).get("tree_view") or {}
            print("layers: Python's selection", tv.get("sel"), tv.get("sels"), flush=True)
            settle(page)
            page.screenshot(path=out("scenes_layers.png"))

            # ---- Scenes: Contents
            page.locator(".sc-views button", has_text="Contents").click()
            time.sleep(2)
            sel = ".scenes-contents:not(.tree-layers)"
            page.locator(sel + " .sc-item:not(.note)").nth(1).locator(".sc-t").click()
            time.sleep(1.5)
            print("contents: row 1 clicked", page.evaluate(PROBE, sel), flush=True)
            keys("contents", sel, ("ArrowDown", "ArrowDown"))
            print("contents: Python's item", (webui_shot.state(url).get("text_scenes") or {}).get("item"),
                  flush=True)
            settle(page)
            page.screenshot(path=out("scenes_contents.png"))

            # ---- Video: two rows selected, then Down
            api("ui.select_tab", "video")
            wait_for(page, ".vid-tbl .scroller .tr.click", 5)
            time.sleep(3)
            sel = ".vid-tbl"
            rows = page.locator(sel + " .scroller .tr.click")
            rows.nth(1).click()
            time.sleep(1)
            rows.nth(3).click(modifiers=["Control"])
            time.sleep(1.5)
            print("video: rows 1 and 3 selected", page.evaluate(PROBE, sel), flush=True)
            keys("video", sel, ("ArrowDown",))
            settle(page, 3)
            page.screenshot(path=out("video_multi.png"))
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
