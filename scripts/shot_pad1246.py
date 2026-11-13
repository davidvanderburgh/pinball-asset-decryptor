"""PAD-1246 proof shots: Audio > More > Update comments from callouts.csv.

    python scripts/shot_pad1246.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Stern project whose callouts.csv has no comments
when the Audio tab opens.  The CSV is then rewritten with a "Comments" column
(who says each callout, the mode it belongs to), the way a player brings it
back from a spreadsheet or an LLM, while the app is open.  Writes, under the
same name before and after:

- <before_|after_>audio_more_menu.png      the Audio tab with More opened
- <before_|after_>audio_comments_table.png the table after that (the after
                                           run first picks the new item and
                                           shoots its report as
                                           after_audio_comments_report.png)

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import csv
import hashlib
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_pad494 as S  # noqa: E402
import shot_pad894 as P  # noqa: E402
import webui_shot  # noqa: E402

# (index, name, the comment the edited CSV gives it)
SOUNDS = (
    (42, "Shoot the ARC for bonus", "Ken Watanabe, ARC mode"),
    (200, "JACKPOT!", "Announcer, Monster Multiball"),
    (311, "Kaiju award", "Announcer, Kaiju award"),
    (419, "Godzilla", "Godzilla roar, start of game"),
    (431, "Monster lock is lit", ""),
)


def _rows(with_comments):
    for idx, name, note in SOUNDS:
        row = ["audio", "idx%04d - %s.wav" % (idx, name), "0.600", "speech", name]
        yield row + [note] if with_comments else row


def _write_csv(path, with_comments):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["folder", "file", "seconds", "classification", "text"]
                   + (["Comments"] if with_comments else []))
        w.writerows(_rows(with_comments))


def _project(scratch):
    dst = os.path.join(scratch, "godzilla")
    os.makedirs(os.path.join(dst, "audio"))
    lines = []
    for idx, name, _note in SOUNDS:
        fname = "idx%04d - %s.wav" % (idx, name)
        p = os.path.join(dst, "audio", fname)
        P._wav(p)
        with open(p, "rb") as f:
            lines.append("audio/%s\t%s\n" % (fname, hashlib.md5(f.read()).hexdigest()))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    _write_csv(os.path.join(dst, "callouts.csv"), False)
    return dst


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1246-")
    project = _project(scratch)
    csv_path = os.path.join(project, "callouts.csv")
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
            # the player brings callouts.csv back with a Comments column
            _write_csv(csv_path, True)
            time.sleep(1)
            page.get_by_role("button", name="More").first.click()
            time.sleep(1)
            page.screenshot(path=out("audio_more_menu.png"))
            print("shot", out("audio_more_menu.png"), flush=True)
            item = page.get_by_text("Update comments from callouts.csv…", exact=True)
            print("new item present:", bool(item.count()), flush=True)
            if after and item.count():
                item.first.click()
                time.sleep(1.5)
                page.screenshot(path=out("audio_comments_report.png"))
                print("shot", out("audio_comments_report.png"), flush=True)
                ok = page.get_by_role("button", name="OK")
                if ok.count():
                    ok.first.click()
                time.sleep(1.5)
            else:
                page.keyboard.press("Escape")
                time.sleep(1)
            page.screenshot(path=out("audio_comments_table.png"))
            print("shot", out("audio_comments_table.png"), flush=True)
            print("shown comments:", {r["k"]: r.get("cm") for r in
                                      state()["audio"]["rows"]}
                  if "audio" in state() else "?", flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()


if __name__ == "__main__":
    main()
