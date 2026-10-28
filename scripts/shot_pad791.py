"""PAD-791 proof shot: the Audio tab's help on music modes, where it says which files an extra sound
bank takes.

    python scripts/shot_pad791.py <repo> <out_dir> [--after] [<name> <anchor>]

Serves <repo> on shot_pad494's scratch Godzilla LE 1.16 project (a stock audio extract, the
Desktop's gzho by default, with music mode files in its sidecar), opens the help pane on the Audio
tab and scrolls it to the music modes lines (or the line holding <anchor>). Writes
<before_|after_><name>.png (default audio_help).

Before (main) the help says a file for a sound the game plays together with other sounds stays
in the main bank and is left out when that is full. After (--after, the ticket branch) it
says such a file takes a copy of those sounds into its extra bank.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad494 as S  # noqa: E402
import webui_shot  # noqa: E402

#: a line both before and after carry, the one that changed
ANCHOR = "Every file takes room in the"


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    rest = [a for a in sys.argv[3:] if a != "--after"]
    name, anchor = (rest[0], rest[1]) if len(rest) >= 2 else ("audio_help", ANCHOR)
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad791-")
    project = S._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = S._serve(repo, scratch, project)
    out = os.path.join(out_dir, ("after_" if after else "before_") + name + ".png")
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
            S._wait_scan(lambda: webui_shot.state(url))
            page.locator(".sx-help").first.click()
            time.sleep(2)
            sel = page.locator(".sx-tips .hd select")
            keys = sel.evaluate("(s) => Array.from(s.options).map((o) => o.value)")
            key = next((k for k in keys if k.lower() in ("audio", "replace audio")), None)
            print("help tabs:", keys, "->", key, flush=True)
            if key:
                sel.select_option(value=key)
                time.sleep(1.5)
            found = page.evaluate("""(anchor) => {
                const pane = document.querySelector('.sx-tips');
                const all = pane ? Array.from(pane.querySelectorAll('li, p, div')) : [];
                const hit = all.filter((e) => e.children.length < 6 && e.textContent.includes(anchor));
                if (!hit.length) return '';
                const el = hit[hit.length - 1];
                el.scrollIntoView({block: 'center'});
                return el.textContent.slice(0, 120);
            }""", anchor)
            print("anchor:", repr(found), flush=True)
            time.sleep(1)
            texts = page.locator(".sx-tips").all_inner_texts()
            print("old line:", any("an extra bank can't serve" in t for t in texts),
                  "| new line:", any("takes a copy of those sounds" in t for t in texts), flush=True)
            page.screenshot(path=out)
            print("shot", out, "| page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
