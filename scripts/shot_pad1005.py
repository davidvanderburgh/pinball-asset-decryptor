"""PAD-1005 proof shot: the Audio tab shows how much of the machine's memory the card's sounds will take.

    python scripts/shot_pad1005.py <repo> <out_dir> <project> <screen> [--after]

Serves <repo> on <project>, a scratch Godzilla Pro 1.16 extract with a music mode whose seven tracks each
play three songs at random (C:\\tmp\\PAD-1005\\tools\\mkproj.py: 5-minute songs fit, 7-minute ones do
not), shows only the changed slots and hovers the memory chip. Writes <before_|after_><screen>.png.

Before (main) the page head has the slot count alone: nothing says the songs are near (or past) what
the machine can hold until a Write refuses them. After (--after) a "Machine memory" chip sits beside it,
amber near the limit and red past it, its tooltip saying what counts and how much room is left.

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
    scratch = tempfile.mkdtemp(prefix="pad1005-")
    launcher = os.path.join(scratch, "launch1005.py")
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
            page = browser.new_page(viewport={"width": 1500, "height": 900})
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
            webui_shot.api(url, "audio.set_show", "Changed")
            for _ in range(60):                              # the estimate lands from its worker
                if (state().get("audio") or {}).get("mem") or not after:
                    break
                time.sleep(1)
            time.sleep(2)
            mem = (state().get("audio") or {}).get("mem")
            print("mem:", json.dumps(mem), flush=True)
            if mem:
                page.locator(".pagehead .chip", has_text="Machine memory").first.hover()
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
