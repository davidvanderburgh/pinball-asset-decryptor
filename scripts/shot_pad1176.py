"""PAD-1176 proof shots: the Audio tab's "Show comments" checkbox.

    python scripts/shot_pad1176.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Stern project whose callouts.csv already holds a
comment on two of its three callouts, and writes, under the same name before
and after:

- <before_|after_>audio_comments_on.png   the table as it opens
- <before_|after_>audio_comments_off.png  after unticking "Show comments"
                                          (before: there is none to untick)

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import csv
import hashlib
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad494 as S  # noqa: E402
import shot_pad1060 as P  # noqa: E402
import webui_shot  # noqa: E402

SOUNDS = (
    ("00m00s798 - idx0891 - Okay.wav", "Okay.", "Kong, after a Monster Battle hit"),
    ("00m01s204 - idx1022 - Here he comes.wav", "Here he comes", ""),
    ("00m00s809 - idx1864 - Run!.wav", "Run!", "Pilot: bonus count"),
)


def _project(scratch):
    dst = os.path.join(scratch, "venom")
    os.makedirs(os.path.join(dst, "audio"))
    lines, rows = [], []
    for i, (name, text, note) in enumerate(SOUNDS):
        p = os.path.join(dst, "audio", name)
        P._wav(p, 2000 + 300 * i)
        with open(p, "rb") as f:
            lines.append("audio/%s\t%s\n" % (name, hashlib.md5(f.read()).hexdigest()))
        rows.append(("audio", name, "0.600", "speech", text, note))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    with open(os.path.join(dst, "callouts.csv"), "w", encoding="utf-8", newline="") as f:
        out = csv.writer(f)
        out.writerow(("folder", "file", "seconds", "classification", "text", "comment"))
        out.writerows(rows)
    return dst


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1176-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = S._serve(repo, scratch, project)
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
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
            S._wait_scan(state)
            time.sleep(2)
            page.screenshot(path=out("audio_comments_on.png"))
            print("shot", out("audio_comments_on.png"),
                  "comments:", state().get("audio", {}).get("comments"), flush=True)
            box = page.get_by_text("Show comments", exact=True)
            print("checkbox found:", box.count(), flush=True)
            if box.count():
                box.first.click()
                time.sleep(1.5)
            page.screenshot(path=out("audio_comments_off.png"))
            print("shot", out("audio_comments_off.png"),
                  "comments:", state().get("audio", {}).get("comments"), flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
    with open(os.path.join(scratch, "settings.json"), encoding="utf-8") as f:
        print("settings:", json.dumps(json.load(f).get("audio_show_comments")), flush=True)


if __name__ == "__main__":
    main()
