"""PAD-1542 proof shot: the Audio tab shows a song the game plays in parts as one song.

    python scripts/shot_pad1542.py <repo> <out_dir> <project> <screen> [--after]

Serves <repo> on <project>, a scratch project holding Iron Maiden LE 1.18's real records for three
songs in parts (Flight of Icarus: idx 471's 0.6 s opening, idx 950's 219 s and idx 941's 10.5 s
ending; The Trooper; Hallowed Be Thy Name) with the card's own sound request map
(C:\\tmp\\PAD-1542\\mkproj.py), and hovers the song badge of idx 950. Writes
<before_|after_><screen>.png.

Before (main) nothing on the rows says idx 950 is one piece of a song: replacing it kept the game's
0.6 s opening of Flight of Icarus in front of the user's song. After (--after) the song's music
carries a link badge with how many parts it has, its tip naming the pieces a replacement there leaves
out, and each piece says whose song it is.

Needs Playwright (the user site-packages one) and the installed Edge. Never point it at a real project:
the capture server rewrites caches inside it.
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
    repo, out_dir, project, screen = (os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]),
                                      os.path.abspath(sys.argv[3]), sys.argv[4])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1542-")
    launcher = os.path.join(scratch, "launch1542.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env={"PYTHONPATH": site.getusersitepackages()})
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = os.path.join(out_dir, ("after_" if after else "before_") + screen + ".png")
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1080})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "audio")
            for _ in range(120):
                a = state().get("audio") or {}
                if a.get("rows") and not a.get("scanning"):
                    break
                time.sleep(1)
            time.sleep(2)
            rows = (state().get("audio") or {}).get("rows") or []
            flat = []
            for r in rows:
                flat.append(r)
                flat.extend(r.get("kids") or ())
            print("rows:", json.dumps([{k: r.get(k) for k in ("k", "sp", "spn")}
                                       for r in flat if r.get("k")]), flush=True)
            badge = page.locator("xpath=//*[contains(text(),'idx0950.wav')]/ancestor::*"
                                 "[.//*[contains(@class,'aud-modes')]][1]"
                                 "//*[contains(@class,'aud-modes')]")
            if after and badge.count():
                badge.first.hover()
                time.sleep(1.5)
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
