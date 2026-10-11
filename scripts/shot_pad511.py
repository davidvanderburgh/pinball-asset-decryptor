"""PAD-511 proof shot: the Audio tab's help on music modes, where it says how a song in parts takes
a file.

    python scripts/shot_pad511.py <repo> <out_dir> [--after]

Serves <repo> on shot_pad494's scratch Godzilla LE 1.16 project (a stock audio extract, the
Desktop's gzho by default, with music mode files in its sidecar), opens the help pane on the Audio
tab and scrolls it to the music modes lines. Writes <before_|after_>audio_help.png.

Before (main) the help says nothing of songs in parts: a tester's file for "SE GZ MX TUNE 16" in
Music Mode 4 played its first seconds and then the game's own song, or the game's own song alone
where the game plays it without its opening. After (--after, the ticket branch) a line says the
file plays in place of the whole song, also where the game plays it without its opening.

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

#: a line both before and after carry, just below where the new one goes
ANCHOR = "has a loudness of its own"


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad511-")
    project = S._project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = S._serve(repo, scratch, project)
    out = os.path.join(out_dir, ("after_" if after else "before_") + "audio_help.png")
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
            }""", ANCHOR)
            print("anchor:", repr(found), flush=True)
            time.sleep(1)
            texts = page.locator(".sx-tips").all_inner_texts()
            print("songs in parts line:", any("play in parts" in t for t in texts),
                  "| no opening:", any("without its opening" in t for t in texts), flush=True)
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
