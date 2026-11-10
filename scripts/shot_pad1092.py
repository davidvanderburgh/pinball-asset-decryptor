"""PAD-1092 proof shot: the Replace Audio tips window, opened on one section.

    python scripts/shot_pad1092.py <repo> <out_png> <project> <section title> [<line to centre>]

Serves <repo> on <project> (a scratch copy: the capture server rewrites caches inside it), opens the
green ? tips window on Replace Audio, clicks <section title> open and centres <line to centre> (any
words of it). Before: "How much fits" in "Longer and shorter replacements" names the 2 GB bank and the
games partition but none of the limits an owner adding lots of audio asks about. After: a section of
its own lists them (music modes, files in turn or at random, one sound's length, the machine's memory).

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
    repo, out, project, section = (os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]),
                                   os.path.abspath(sys.argv[3]), sys.argv[4])
    centre = sys.argv[5] if len(sys.argv) > 5 else ""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1092-")
    launcher = os.path.join(scratch, "launch1092.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            page.locator(".sx-help").first.click()
            time.sleep(2)
            page.locator(".sx-tips .hd select").select_option(value="Replace Audio")
            time.sleep(1.5)
            page.locator(".sx-tips").get_by_text(section, exact=True).first.click()
            time.sleep(1)
            if centre:
                line = page.locator(".sx-tips").get_by_text(centre, exact=False).first
                line.scroll_into_view_if_needed()
                page.evaluate("(el) => el.scrollIntoView({block: 'center'})", line.element_handle())
                time.sleep(1)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
