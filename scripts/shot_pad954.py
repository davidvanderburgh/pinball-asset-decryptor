"""PAD-954 proof shots: the Visual Pinball tab on Spooky Pinball, Alice Cooper's row.

    python scripts/shot_pad954.py <out_dir> <home> [--after]

shot_pad943.py's server (one preview code, PAD802_CODE from the
environment), with USERPROFILE at <home>: a scratch home whose
.pad-vpx.json names a scratch tables folder (Alice Cooper's Nightmare
Castle's download in originals/), so nothing of the person's own folder or
caches is read or rewritten. Waits until every download is read and the
coverage is in, then writes <before_|after_>vpx_alice_cooper.png: the page in
a tall window (1900 x 2000), the download's row scrolled into view. Needs
Playwright and the installed Edge.
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

WIDTH, HEIGHT = 1900, 2000


def main():
    out_dir, home = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    pre = "after_" if "--after" in sys.argv else "before_"
    code = os.environ.get("PAD802_CODE", "")
    os.makedirs(out_dir, exist_ok=True)
    # each run reads the downloads afresh
    for f in (".pad-vpx.downloads.json",):
        try:
            os.remove(os.path.join(home, f))
        except OSError:
            pass
    scratch = tempfile.mkdtemp(prefix="pad954-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "spooky", "theme": "dark",
                   "preview_codes": [code] if code else []}, f)
    userbase = os.path.join(os.environ.get("APPDATA", ""), "Python")
    proc, url = webui_shot.start_server(settings, os.path.join(scratch, "srv"),
                                        extra_env={"PYTHONUSERBASE": userbase, "USERPROFILE": home,
                                                   "PAD_VPX_PICTURES": os.path.join(scratch, "pics")})
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
            webui_shot.api(url, "ui.pick_manufacturer", "spooky")
            time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "vpx")
            deadline = time.time() + 300
            st = {}
            while time.time() < deadline:
                st = webui_shot.state(url).get("vpx") or {}
                downs = st.get("downloads") or []
                if (st.get("loaded") and not st.get("busy") and not st.get("stale")
                        and downs and all(d.get("read") for d in downs)
                        and not st.get("coverage_busy") and not st.get("pictures_busy")):
                    break
                time.sleep(2)
            print("vpx: tables=%d downloads=%s coverage=%s" % (
                len(st.get("tables") or []),
                [(d["file"], (d.get("catalog") or {}).get("game"), d.get("title")) for d in st.get("downloads") or []],
                {k: v.get("pct") for k, v in (st.get("coverage") or {}).items() if k in ("h78", "um", "ac")}),
                flush=True)
            time.sleep(2)
            page.evaluate("(() => { const e = [...document.querySelectorAll('*')].find(n => n.children.length === 0"
                          " && /Alice Cooper/.test(n.textContent || '')); if (e) e.scrollIntoView({block: 'center'}); })()")
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, pre + "vpx_alice_cooper.png"))
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
