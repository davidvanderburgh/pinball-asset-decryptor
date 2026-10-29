"""PAD-812 proof shots: the Video tab's compare report.

    python scripts/shot_pad812.py <repo> <out_dir> [--after]

Serves <repo> on a scratch project of clips ffmpeg makes (the stock clips, one already written
once so its snapshot holds the stock clip), with replacements and random clips picked in its
sidecar, and writes under the same names before and after:

- <before_|after_>video_menu.png  the Video tab's More menu
- <before_|after_>csv.png         the CSV that menu exports, opened as a table: before, the
                                  only one there is (Export CSV, lengths as m:ss); after, the
                                  compare report

Needs Playwright (the user site-packages one), the installed Edge and ffmpeg.
"""
import csv
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

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


def _clip(path, secs, size="1360x768", fps=30, src="testsrc"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "%s=size=%s:rate=%d:duration=%s" % (src, size, fps, secs),
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", path], check=True)
    return path


def _project(scratch):
    proj = os.path.join(scratch, "godzilla_pro")
    v = lambda n: os.path.join(proj, "video", n)                  # noqa: E731
    mine = lambda n: os.path.join(scratch, "my clips", n)         # noqa: E731
    _clip(v("GZ_Intro.mp4"), 12.4)
    _clip(v("Battle_Gigan_Start.mp4"), 6.5)
    _clip(os.path.join(proj, ".orig", "video", "Battle_Gigan_Start.mp4"), 6.5)
    _clip(v("Kaiju_Award.mp4"), 3.2)
    _clip(v("Attract_Loop.mp4"), 20)
    # the extract's baseline, so the folder reads as an extract with nothing changed yet
    import hashlib
    with open(os.path.join(proj, ".checksums.md5"), "w", encoding="utf-8") as f:
        for n in sorted(os.listdir(os.path.join(proj, "video"))):
            with open(v(n), "rb") as g:
                f.write("video/%s\t%s\n" % (n, hashlib.md5(g.read()).hexdigest()))
    side = {
        "video": {"video/GZ_Intro.mp4": _clip(mine("Intro_retheme.mp4"), 14.36, "1920x1080", 25,
                                               "smptebars"),
                  "video/Battle_Gigan_Start.mp4": _clip(mine("Gigan_new.mp4"), 6.04, src="smptebars"),
                  "video/Kaiju_Award.mp4": _clip(mine("Award_A.mp4"), 3.2, src="smptebars")},
        "video_variants": {"video/Kaiju_Award.mp4": [_clip(mine("Award_B.mp4"), 2.84, src="smptebars"),
                                                     _clip(mine("Award_C.mp4"), 4.1, "1280x720",
                                                           src="smptebars")]},
        "video_trim": True,
        "video_asis_slots": {"video/Kaiju_Award.mp4": True},
    }
    with open(os.path.join(proj, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump(side, f)
    return proj


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch812.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages()})


def _reply(url, mid, value):
    base = url.split("/?")[0]
    token = url.split("t=")[1].split("&")[0]
    req = urllib.request.Request(
        base + "/api/reply", data=json.dumps({"id": mid, "v": value}).encode(),
        headers={"Content-Type": "application/json", "X-PAD-Token": token})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def _table_page(path, title):
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    head = "".join("<th>%s</th>" % html.escape(c) for c in rows[0])
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % html.escape(os.path.basename(c)
                                                                       if os.sep in c else c)
                                           for c in r) for r in rows[1:])
    return ("<html><body style='font:12px Segoe UI;margin:12px'><h3>%s</h3>"
            "<table border=1 cellspacing=0 cellpadding=4 style='border-collapse:collapse'>"
            "<tr style='background:#eee'>%s</tr>%s</table></body></html>"
            % (html.escape(title), head, body))


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad812-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = _serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)   # noqa: E731
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
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "video")
            deadline = time.time() + 120
            while time.time() < deadline:
                st = state().get("video") or {}
                if st.get("rows") and not st.get("scanning") and \
                        "still checking" not in (st.get("status") or ""):
                    break
                time.sleep(1)
            time.sleep(2)
            print("rows:", [(r["rel"], r.get("rep"), r.get("len")) for r in st.get("rows") or []],
                  flush=True)
            page.locator("button[aria-label='More']").first.click()
            time.sleep(1)
            labels = page.locator(".menu .mi").all_inner_texts()
            print("menu:", labels, flush=True)
            page.screenshot(path=out("video_menu.png"))
            item = page.locator(".menu .mi:has-text('compare report')").first
            if not item.count():
                item = page.locator(".menu .mi:has-text('Export CSV')").first
            item.click()
            csv_path = os.path.join(scratch, "report.csv")
            mid = None
            for _ in range(40):
                opened = (state().get("modals") or {}).get("open") or []
                if opened:
                    mid = opened[-1]["id"]
                    break
                time.sleep(0.25)
            print("dialog:", mid, _reply(url, mid, csv_path), flush=True)
            for _ in range(120):
                if os.path.isfile(csv_path) and not (state().get("video") or {}).get("report_busy"):
                    break
                time.sleep(0.5)
            time.sleep(1)
            shutil.copy2(csv_path, out("report.csv"))
            tab = browser.new_page(viewport={"width": 1900, "height": 420})
            tab.set_content(_table_page(csv_path, os.path.basename(
                "Compare report (video_compare.csv)" if after else
                "Export CSV (video_slots.csv), the only CSV the tab exports")))
            tab.screenshot(path=out("csv.png"), full_page=True)
            print("page errors:", errors, flush=True)
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
