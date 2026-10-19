"""PAD-627 proof shots: the Video tab says something about the sounds of EVERY clip - a clip a
scene plays itself (the Xilien broadcast's VO clips, the city maps), and a clip whose name a
second bank also has (the JUKEBOX loops), showed nothing at all.

    python scripts/shot_pad627.py <repo> <out_dir> [--after]

Serves <repo> on a SCRATCH Godzilla Pro 1.16 project, as :mod:`shot_pad455` does: a few clips
of a stock extract (``PAD592_EXTRACT``, copied: it sits on another volume), the audio and
``sound_requests.tsv`` of an extract made with the PAD-455 build (hard-linked), and the stock
Pro 1.16 card as its source (as :mod:`shot_pad592`). Writes, under the same names before and
after:

- video_scene_clip.png    YouAreToReport_VO3 (DragonRR's picture): a clip of the Xilien scene
- video_twin_clip.png     JUKEBOX_LOOP1 of the attract bank, a name the in-game bank has too

Needs Playwright (the user site-packages one) and the installed Edge.
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
import shot_pad312 as base  # noqa: E402
import shot_pad455 as p455  # noqa: E402

STOCK = os.environ.get("PAD592_EXTRACT", r"C:\tmp\pad446\gzpro116")
SCRATCH = os.environ.get("PAD627_SCRATCH", r"D:\Pinball\pad455_shots")
CLIPS = ("YouAreToReport_VO3", "YouAreToReport_VO4", "TokyoMap_Raid_UFO", "JUKEBOX_LOOP1",
         "JUKEBOX_LOOP1_2", "ATTRACT_LOOP1", "BuildingSmash_breath_new", "shoot_again")
SCREENS = {"video_scene_clip": "YouAreToReport_VO3.mp4",
           "video_twin_clip": "JUKEBOX_LOOP1.mov"}


def _project(scratch):
    dst = os.path.join(scratch, "gz116pro")
    vid = os.path.join(dst, "video")
    aud = os.path.join(dst, "audio")
    os.makedirs(vid)
    os.makedirs(aud)
    rows, sums = ["# output\tcard path\tbytes"], []
    with open(os.path.join(STOCK, "video", "manifest.txt"), encoding="utf-8") as f:
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 2 or line.startswith("#") or os.path.splitext(cols[0])[0] not in CLIPS:
                continue
            shutil.copy2(os.path.join(STOCK, "video", cols[0]), os.path.join(vid, cols[0]))
            rows.append("\t".join(cols))
            sums.append("video/%s\t%s" % (cols[0], p455._md5(os.path.join(vid, cols[0]))))
    with open(os.path.join(vid, "manifest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.write("\n".join(sums) + "\n")
    for n in os.listdir(os.path.join(p455.AUDIO, "audio")):
        os.link(os.path.join(p455.AUDIO, "audio", n), os.path.join(aud, n))
    shutil.copy2(os.path.join(p455.AUDIO, "sound_requests.tsv"), dst)
    st = os.stat(p455.CARD)
    with open(os.path.join(dst, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": p455.CARD, "input_name": os.path.basename(p455.CARD),
                   "size": st.st_size, "mtime": int(st.st_mtime), "card_version": "1.16.0"}, f)
    return dst


def _shot(repo, out, after):
    os.makedirs(SCRATCH, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad627-", dir=SCRATCH)
    project = _project(scratch)
    proc, url = p455._serve(repo, scratch, project)
    state = lambda: webui_shot.state(url)                    # noqa: E731
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    pre = "after_" if after else "before_"
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.setItem('pad.colorbar.open.video', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "audio")
            time.sleep(2)
            base._wait_scan(state, "audio")
            api("ui.select_tab", "video")
            time.sleep(2)
            base._wait_scan(state, "video")
            deadline = time.time() + 300
            while time.time() < deadline:
                if ((state().get("video") or {}).get("modes") or {}).get("ready"):
                    break
                time.sleep(1)
            for screen, rel in SCREENS.items():
                page.locator(".vid-tbl .tr:has-text('%s')" % rel).first.click()
                time.sleep(3)
                page.mouse.move(5, 990)
                time.sleep(0.6)
                page.screenshot(path=os.path.join(out, pre + screen + ".png"))
                pv = (state().get("video") or {}).get("preview") or {}
                print(screen, "preview:", pv.get("rel"), json.dumps(pv.get("sounds")), flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    repo, out = sys.argv[1:3]
    os.makedirs(out, exist_ok=True)
    _shot(repo, out, "--after" in sys.argv)


if __name__ == "__main__":
    main()
