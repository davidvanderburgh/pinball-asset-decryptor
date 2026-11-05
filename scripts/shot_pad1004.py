"""PAD-1004 proof shot: the Jukebox list sorts by a column, and its column titles stay in view.

    python scripts/shot_pad1004.py <repo> <out_dir> [--after]

Uses shot_pad1000's scratch project (20 Beatles songs in the jukebox). Writes:

- <before_|after_>audio_jukebox_sort.png   the Jukebox window, its list scrolled to the bottom

Before (main) the column titles scroll off with the rows and do nothing when clicked. After (--after)
the shot clicks the Song title (sorts A to Z) and then How often (most often first), then scrolls
the list to the bottom: the titles stay at the top of the list, How often shows its arrow.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad1000 as P  # noqa: E402
import webui_shot  # noqa: E402


def _order(page):
    return page.evaluate("""() => [...document.querySelectorAll('.modal .aud-juke tbody tr')]
      .map((r) => r.cells[0].textContent + ' ' + r.cells[3].querySelector('button, select, [class]')?.textContent
               + ' ' + r.cells[1].textContent.slice(0, 40))""")


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1004-")
    project = P._project(scratch)
    proc, url = P._serve(repo, scratch, project)
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = os.path.join(out_dir, ("after_" if after else "before_") + "audio_jukebox_sort.png")
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "audio")
            time.sleep(2)
            P._open(page, state)
            if after:
                page.locator(".modal .aud-juke th button:has-text('Song')").click()
                time.sleep(0.5)
                print("by song:", _order(page)[:4], flush=True)
                page.locator(".modal .aud-juke th button:has-text('How often')").click()
                time.sleep(0.5)
                print("by how often:", _order(page), flush=True)
                if "--cycle" in sys.argv:                    # turned round, then the list's own order back
                    for what in ("rarest first:", "own order:"):
                        page.locator(".modal .aud-juke th button:has-text('How often')").click()
                        time.sleep(0.5)
                        print(what, [r.split()[0] for r in _order(page)], flush=True)
                    return
            page.evaluate("() => { const l = document.querySelector('.modal .aud-juke'); l.scrollTop = l.scrollHeight; l.scrollLeft = 0; }")
            page.mouse.move(5, 890)
            time.sleep(0.5)
            print("head in view:", page.evaluate("""() => { const l = document.querySelector('.modal .aud-juke'),
              h = l.querySelector('thead th').getBoundingClientRect(), r = l.getBoundingClientRect();
              return {list_top: Math.round(r.top), head_top: Math.round(h.top), scrolled: l.scrollTop}; }"""), flush=True)
            page.screenshot(path=out)
            print("shot", out, "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
