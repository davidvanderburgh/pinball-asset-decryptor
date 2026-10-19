"""PAD-633 proof shot: the name a clip no scene names gets on the Video tab.

    python scripts/shot_pad633.py <repo> <card> <out_dir> [--after]

Serves <repo> on shot_pad312's scratch copy of the Godzilla project, with a video/
folder that <repo>'s own Extract made off <card> (a card PAD built), holding only
the one clip Godzilla LE 1.16's scenes do not name (scene eae3e084, 34.asset) so
the list is that clip alone.  Before, it is named by its place among the card's
clips (video_0655 on a stock card, further on for every clip a build added);
after, by where it sits on the card, the same on every card.

- video_name.png    Video: the clip's row, selected
"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad312 as base  # noqa: E402

LONE = ("/godzilla_le/assets/lcd/auto_loaded/eae3e0844950ec5f071bf3c4e951fbff709a2028"
        "/scene.assets/34.asset")

# Run in <repo>: its extract_videos names the clips; only the lone clip's bytes
# are written and only its row is kept (the rest of the card is GBs).
EXTRACT = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
from pinball_decryptor.plugins.stern import engine as E, ext4 as X
real = X.Ext4Reader.extract_file
lone, out = sys.argv[3], sys.argv[4]
X.Ext4Reader.extract_file = lambda self, node, path, *a, **k: (
    real(self, node, path) if node.get("_lone") else None)
with open(E._lp(sys.argv[2]), "rb") as f:
    r, _a, _b = E._locate(f, E._linux_partitions(sys.argv[2]))
    find = E.find_card_videos
    def only(reader, cancel=None):
        vids, rad = find(reader, cancel)
        for p, n, _b in vids:
            if p == lone:
                n["_lone"] = True
        return vids, rad
    E.find_card_videos = only
    E.extract_videos(r, out)
vid = os.path.join(out, "video")
rows = [l for l in open(os.path.join(vid, "manifest.txt"), encoding="utf-8")
        if l.startswith("#") or l.split("\t")[1] == lone]
open(os.path.join(vid, "manifest.txt"), "w", encoding="utf-8").writelines(rows)
# the baseline a real extract writes, so the row is not "not on this card"
import hashlib
name = rows[-1].split("\t")[0]
md5 = hashlib.md5(open(os.path.join(vid, name), "rb").read()).hexdigest()
with open(os.path.join(out, ".checksums.md5"), "a", encoding="utf-8") as f:
    f.write("video/%s\t%s\n" % (name, md5))
print("lone clip ->", rows[-1].split("\t")[0])
"""


def main():
    repo, card, out_dir = sys.argv[1:4]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    scratch = tempfile.mkdtemp(prefix="pad633-")
    project = base._project(scratch)
    import json
    import shutil
    shutil.rmtree(os.path.join(project, "video"), ignore_errors=True)
    side = os.path.join(project, ".staged_changes.json")
    with open(side, encoding="utf-8") as f:
        data = json.load(f)
    data.pop("video", None)
    with open(side, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    script = os.path.join(scratch, "extract633.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(EXTRACT)
    subprocess.run([sys.executable, "-I", script, repo, card, LONE, project], check=True)
    print("video/:", sorted(os.listdir(os.path.join(project, "video"))), flush=True)
    proc, url = base._serve(repo, scratch, project)
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script("try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            webui_shot.api(url, "ui.pick_manufacturer", "stern")
            time.sleep(1)
            webui_shot.api(url, "ui.select_tab", "video")
            deadline = time.time() + 120
            rows = page.locator(".vid-tbl .scroller .tr.click")
            while time.time() < deadline and rows.count() < 1:
                time.sleep(1)
            time.sleep(3)
            if rows.count():
                rows.nth(0).click()
            time.sleep(3)
            page.mouse.move(5, 990)
            time.sleep(1)
            page.screenshot(path=out("video_name.png"))
            print("rows:", rows.count(), "page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
