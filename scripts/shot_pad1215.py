"""PAD-1215 proof shot: the Modes tab's help on co-op characters, where it says how a pick is taken and when the ball
comes to the shooter lane.

    python scripts/shot_pad1215.py <repo> <out_png>

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the "before" shot). Nothing is
read or staged: a scratch project. Before (main) the help says a ball launched before picking takes the one shown and
the top line says ACTION/LAUNCH PICKS; after, each player's first ball comes to the lane only once they have picked.

Needs Playwright (the user site-packages one) and the installed Edge.
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

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''

#: a line both before and after carry, just above the one that changed
ANCHOR = "So: Action picks, the flippers choose the language"


def main():
    repo = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    scratch = tempfile.mkdtemp(prefix="pad1215-")
    project = os.path.join(scratch, "project")
    os.makedirs(project)
    launcher = os.path.join(scratch, "launch1215.py")
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
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            page.locator(".sx-help").first.click()
            time.sleep(2)
            sel = page.locator(".sx-tips .hd select")
            keys = sel.evaluate("(s) => Array.from(s.options).map((o) => o.value)")
            key = next((k for k in keys if k.lower() == "modes"), None)
            print("help tabs:", keys, "->", key, flush=True)
            if key:
                sel.select_option(value=key)
                time.sleep(1.5)
            page.locator(".sx-tips").get_by_text("Co-op play", exact=True).first.click()
            time.sleep(1)
            found = page.evaluate("""(anchor) => {
                const pane = document.querySelector('.sx-tips');
                const w = document.createTreeWalker(pane, NodeFilter.SHOW_TEXT);
                let n;
                while ((n = w.nextNode())) {
                    const at = n.textContent.indexOf(anchor);
                    if (at >= 0) {     // the changed sentences marked, and put in the middle of the pane
                        let end = n.textContent.indexOf('The seconds', at);
                        if (end < 0) end = n.textContent.length;
                        const r = document.createRange();
                        r.setStart(n, at);
                        r.setEnd(n, end);
                        const mark = document.createElement('mark');
                        r.surroundContents(mark);
                        mark.scrollIntoView({block: 'center'});
                        return mark.textContent.slice(0, 160);
                    }
                }
                return '';
            }""", ANCHOR)
            print("anchor:", repr(found), flush=True)
            time.sleep(1)
            texts = page.locator(".sx-tips").all_inner_texts()
            print("old line:", any("takes the one shown" in t for t in texts),
                  "| new line:", any("only comes to the shooter lane once" in t for t in texts), flush=True)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            browser.close()
    finally:
        proc.terminate()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
