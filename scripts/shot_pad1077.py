"""PAD-1077 proof shots: Spike 3 Extract offers Sounds and its project has WAVs.

    python scripts/shot_pad1077.py <repo> <out_dir> [--before] [--card PATH]
                                    [--project DIR]

Serves <repo> with the Spike 3 preview on, picks Stern, opens Extract and
selects a Spike 3 card (default: the Pokemon LE .spk.zip). Shoots the Extract
tab with its per-type checkboxes as ``<pfx>extract.png``. With --project DIR
(an already-extracted project) the output points there, so the shot also shows
that project's file summary (Audio / Video / Images counts).

Uses a scratch settings file (never David's), Playwright and the installed Edge.
"""
import os
import site
import sys
import tempfile
import time
import shutil

sys.path.insert(0, site.getusersitepackages())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

# the Spike 3 preview code the PAD-1086 shots use (public; unlocks no key)
from shot_pad1086 import SPIKE3_CODE  # noqa: E402

DEFAULT_CARD = r"D:\Pinball\images\Stern\spike3\spk\pokemon_le-0_87_0_spike3.spk.zip"

LAUNCHER = r'''
import sys
sys.path.insert(0, %r)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _serve(repo, scratch):
    import json
    launcher = os.path.join(scratch, "launch1077.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "preview_codes": [SPIKE3_CODE]}, f)
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def _wait(state_fn, pred, limit=60):
    end = time.time() + limit
    while time.time() < end:
        try:
            if pred(state_fn()):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _arg(name, default=None):
    if name in sys.argv:
        return sys.argv[sys.argv.index(name) + 1]
    return default


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    pfx = "before_" if "--before" in sys.argv else "after_"
    card = _arg("--card", DEFAULT_CARD)
    project = _arg("--project")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1077-")
    print("serving", repo, flush=True)
    proc, url = _serve(repo, scratch)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "extract")
            time.sleep(1)
            api("extract.use_recent", "output", project or scratch)
            api("extract.use_recent", "input", card)
            _wait(state, lambda s: (s.get("extract") or {}).get("detected"), 90)
            ex = state().get("extract") or {}
            print("detected:", ex.get("detected"), flush=True)
            print("categories:", ex.get("categories") or ex.get("extract_categories"), flush=True)
            time.sleep(2)
            page.screenshot(path=os.path.join(out_dir, pfx + "extract.png"))
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
