"""PAD-958 proof shots: the Visual Pinball tab lists every machine's tables.

    python scripts/shot_pad958.py <out_dir> <home> <name> [--after] [--mfr stern] [--filter spooky]

shot_pad954.py's server (one preview code, PAD802_CODE from the
environment), with USERPROFILE at <home>: a scratch home whose
.pad-vpx.json is a copy of the person's (their tables folder is READ, never
written: nothing is patched), so the downloads' and pictures' caches are
scratch ones. On manufacturer <mfr>; with --filter, the page's machine
filter is set to that platform first. Waits until every download is read
and the coverage is in, then writes <before_|after_><name>.png: the page
in a tall window (1900 x 3000). Needs Playwright and the installed Edge.
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

WIDTH, HEIGHT = 1900, 3000


def opt(name, default=""):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    out_dir, home, name = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    pre = "after_" if "--after" in sys.argv else "before_"
    mfr, flt = opt("--mfr", "stern"), opt("--filter")
    code = os.environ.get("PAD802_CODE", "")
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad958-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": mfr, "theme": "dark",
                   "preview_codes": [code] if code else []}, f)
    userbase = os.path.join(os.environ.get("APPDATA", ""), "Python")
    proc, url = webui_shot.start_server(settings, os.path.join(scratch, "srv"),
                                        extra_env={"PYTHONUSERBASE": userbase, "USERPROFILE": home,
                                                   "PAD_VPX_PICTURES": os.path.join(home, "pics")})
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", mfr)
            time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "vpx")
            deadline = time.time() + 300
            st = {}
            while time.time() < deadline:
                st = webui_shot.state(url).get("vpx") or {}
                downs = st.get("downloads") or []
                if (st.get("loaded") and not st.get("busy") and not st.get("stale")
                        and all(d.get("read") for d in downs)
                        and not st.get("coverage_busy") and not st.get("pictures_busy")
                        and not st.get("authors_busy")):
                    break
                time.sleep(2)
            if flt:
                print("filter: %s" % webui_shot.api(url, "vpx.set_filter", flt), flush=True)
            time.sleep(2)
            print("vpx: platform=%r tables=%d downloads=%d" % (
                st.get("platform"), len(st.get("tables") or []), len(st.get("downloads") or [])), flush=True)
            page.screenshot(path=os.path.join(out_dir, pre + name + ".png"), full_page=True)
            print("page errors: %s" % errors, flush=True)
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
