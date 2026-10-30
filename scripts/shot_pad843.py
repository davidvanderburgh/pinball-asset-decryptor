"""PAD-843 proof shot: the Audio tab's Advanced Audio Options on a Spike 2
card, scrolled to where the "Allow replacements longer or shorter than the
original" checkbox was (after: the always-on note in its place).

    python scripts/shot_pad843.py <repo> <out_dir> [--after]

Writes before_/after_spike2_advanced_length.png.  Needs Playwright (the user
site-packages one) and the installed Edge.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, ("after_" if after else "before_")
                       + "spike2_advanced_length.png")
    scratch = tempfile.mkdtemp(prefix="pad843-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    proc, url = base._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1100})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            print("era", api("ui.set_era", "spike2"), flush=True)
            time.sleep(1)
            api("ui.select_tab", "audio")
            time.sleep(2)
            page.click("button:has-text('Advanced')")
            time.sleep(1.5)
            # Scroll the dialog to the blip-free row, the one above the
            # length option, so both shots frame the same place.
            page.locator(".modal .aud-adv b:has-text('Blip-free')").scroll_into_view_if_needed()
            page.evaluate("""() => { const b = [...document.querySelectorAll('.modal .aud-adv b')]
                .find(e => e.textContent.includes('Blip-free'));
              b.scrollIntoView({block: 'start'}); }""")
            time.sleep(0.5)
            page.mouse.move(5, 1090)
            page.screenshot(path=out)
            print("saved", out, "page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
