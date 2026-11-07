"""PAD-1048 proof shots: Audio > More > Update callouts.csv from the names.

    python scripts/shot_pad1048.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Stern project made here: sounds the player renamed
in Audio Properties after Auto-name call-outs wrote callouts.csv (so the CSV
still names the old files and the old words), and one named sound the CSV
never had.  Writes, under the same name before and after:

- <before_|after_>audio_more_menu.png   the Audio tab with More opened
- after_audio_update_question.png       (after run) the question the new item
                                        asks; answered Yes, then callouts.csv
                                        is printed

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

# (index, the name callouts.csv has, the name the player gave it in PAD)
SOUNDS = (
    (42, "Shoot the a wreck for bonus", "Shoot the ARC for bonus"),
    (200, "Jack pot", "JACKPOT!"),
    (311, "Kai Joo award", "Kaiju award"),
    (419, "Go so long", "Godzilla"),
    (431, "Monster lock is lit", "Monster lock is lit"),
)
NOT_IN_CSV = (667, "Mechagodzilla")


def _project(scratch):
    dst = os.path.join(scratch, "godzilla")
    os.makedirs(os.path.join(dst, "audio"))
    lines, rows = [], []
    for idx, heard, mine in SOUNDS + ((NOT_IN_CSV[0], None, NOT_IN_CSV[1]),):
        name = "idx%04d - %s.wav" % (idx, mine)
        p = os.path.join(dst, "audio", name)
        P._wav(p)
        with open(p, "rb") as f:
            lines.append("audio/%s\t%s\n" % (name, hashlib.md5(f.read()).hexdigest()))
        if heard is not None:
            rows.append(["audio", "idx%04d - %s.wav" % (idx, heard), "0.600",
                         "speech", heard])
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    with open(os.path.join(dst, "callouts.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["folder", "file", "seconds", "classification", "text"])
        w.writerows(rows)
    return dst


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1048-")
    project = _project(scratch)
    csv_path = os.path.join(project, "callouts.csv")
    print("serving", repo, "project", project, flush=True)
    with open(csv_path, encoding="utf-8") as f:
        print("callouts.csv before:\n" + f.read(), flush=True)
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
            page.get_by_role("button", name="More").first.click()
            time.sleep(1)
            page.screenshot(path=out("audio_more_menu.png"))
            print("shot", out("audio_more_menu.png"), flush=True)
            item = page.get_by_text("Update callouts.csv from the names…", exact=True)
            if after and item.count():
                item.first.click()
                time.sleep(1.5)
                page.screenshot(path=out("audio_update_question.png"))
                print("shot", out("audio_update_question.png"), flush=True)
                page.get_by_role("button", name="Yes").first.click()
                time.sleep(2)
                ok = page.get_by_role("button", name="OK")
                if ok.count():
                    ok.first.click()
                time.sleep(1)
            else:
                page.keyboard.press("Escape")
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
    with open(csv_path, encoding="utf-8") as f:
        print("callouts.csv after:\n" + f.read(), flush=True)


if __name__ == "__main__":
    main()
