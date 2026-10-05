"""PAD-388 proof shots: the Tips window of every tab, each manufacturer's in turn.

    python scripts/shot_pad388.py <repo> <out_dir> <prefix> [mfr ...]

<repo> is the source tree to serve (the ticket branch, or a ``git archive`` of main for the
"before" shots).  For each manufacturer (default: all of them) the app starts on it, and
every tab its Tips window lists that has tips of its own is shot once, at the top of its
tips: <out_dir>/<prefix>_<tab>.png (tab lower-cased, spaces to _).  A tab already shot
under an earlier manufacturer is not shot again.  Prints the tab keys it shot.
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad232 as S  # noqa: E402
import webui_shot  # noqa: E402

MFRS = ("stern", "jjp", "dp", "bof", "ap", "spooky", "pb", "cgc", "williams")


def _serve(repo, scratch, project, mfr):
    launcher = os.path.join(scratch, "launch388.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(S.LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": mfr,
                   "manufacturers": {mfr: {"extract_output": project,
                                           "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def shoot_mfr(repo, out_dir, prefix, mfr, done):
    sys.path.insert(0, repo)
    from pinball_decryptor.webui.help_content import sections_for
    scratch = tempfile.mkdtemp(prefix="pad388-")
    project = S._project(scratch, "Project")
    proc, url = _serve(repo, scratch, project, mfr)
    try:
        tabs = webui_shot.api(url, "shellx.tips").get("tabs") or []
        want = [t["key"] for t in tabs if t["key"] not in done and sections_for(t["key"])]
        if not want:
            return
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            page.locator(".sx-help").first.click()
            time.sleep(2)
            for key in want:
                page.locator(".sx-tips .hd select").select_option(value=key)
                time.sleep(1.5)
                out = os.path.join(out_dir, "%s_%s.png" % (
                    prefix, key.lower().replace(" ", "_")))
                page.screenshot(path=out)
                done.add(key)
                print("shot", mfr, key, out, flush=True)
            browser.close()
    finally:
        proc.terminate()


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    prefix = sys.argv[3]
    mfrs = sys.argv[4:] or MFRS
    os.makedirs(out_dir, exist_ok=True)
    done = set()
    for mfr in mfrs:
        try:
            shoot_mfr(repo, out_dir, prefix, mfr, done)
        except Exception as e:                          # noqa: BLE001
            print("FAILED", mfr, e, flush=True)
    print("tabs:", sorted(done))


if __name__ == "__main__":
    main()
