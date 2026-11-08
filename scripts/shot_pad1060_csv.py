"""PAD-1060 proof shot (the tester's reply): a callout made Sound FX with its
name cleared, then Rename from callouts.csv.

    python scripts/shot_pad1060_csv.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Stern project whose callouts.csv has the row
"Okay." for "idx0891 - Okay" (speech).  Audio Properties clears the name and
sets Sound FX, then More > Rename from callouts.csv is pressed and answered
Yes.  Writes <before_|after_>audio_csv_rename.png once that is done (before:
the name "Okay" is back) and prints callouts.csv and the file names.

Needs Playwright (the user site-packages one) and the installed Edge.
"""
import hashlib
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
    ("00m00s798 - idx0891 - Okay.wav", "speech", "Okay."),
    ("00m00s798 - idx3324 - Thanks for watching!.wav", "speech",
     "Thanks for watching!"),
    ("00m00s809 - idx1864 - WOOSH.wav", "speech", "WOOSH"),
)


def _project(scratch):
    dst = os.path.join(scratch, "venom")
    os.makedirs(os.path.join(dst, "audio"))
    lines, rows = [], []
    for i, (name, kind, text) in enumerate(SOUNDS):
        p = os.path.join(dst, "audio", name)
        P._wav(p, 2000 + 300 * i)
        with open(p, "rb") as f:
            lines.append("audio/%s\t%s\n" % (name, hashlib.md5(f.read()).hexdigest()))
        rows.append("audio,%s,0.798,%s,%s\n" % (name, kind, text))
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    with open(os.path.join(dst, "callouts.csv"), "w", encoding="utf-8",
              newline="") as f:
        f.write("folder,file,seconds,classification,text\n")
        f.writelines(rows)
    return dst


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1060csv-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = S._serve(repo, scratch, project)
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = os.path.join(out_dir, ("after_" if after else "before_")
                       + "audio_csv_rename.png")
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

            P._props(page, "idx0891")
            page.locator(".modal input").first.fill("")
            page.locator(".modal select").first.select_option("sfx")
            page.get_by_role("button", name="OK").first.click()
            time.sleep(1.5)

            page.get_by_role("button", name="More").first.click()
            time.sleep(1)
            page.get_by_text("Rename from callouts.csv…", exact=True).first.click()
            time.sleep(1.5)
            yes = page.get_by_role("button", name="Yes")
            if yes.count():
                yes.first.click()
                time.sleep(2)
            page.screenshot(path=out)
            print("shot", out, flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                                   # noqa: BLE001
            proc.kill()
    with open(os.path.join(project, "callouts.csv"), encoding="utf-8") as f:
        print("callouts.csv after:\n" + f.read(), flush=True)
    print("files after:", sorted(os.listdir(os.path.join(project, "audio"))), flush=True)


if __name__ == "__main__":
    main()
