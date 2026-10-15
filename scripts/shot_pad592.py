"""PAD-592 proof shots: the Video tab's clip sounds play, link to the Audio tab, and a clip with
no sure sound lists the ones that may be its.

    python scripts/shot_pad592.py <repo> <out_dir> [--after]

Serves <repo> on a SCRATCH Godzilla Pro 1.16 project, as :mod:`shot_pad455` does: a few clips
of a stock extract (``PAD592_EXTRACT``, copied: it sits on another volume), the audio and
``sound_requests.tsv`` of an extract made with the PAD-455 build (hard-linked), and the stock
Pro 1.16 card as its source. Writes, under the same names before and after:

- video_clip_sounds.png   BuildingSmash_breath_new (DragonRR's picture): the sound kept with it
- video_clip_maybe.png    shoot_again: no sound is sure, the ones that may be its
- audio_from_video.png    the Audio tab after the sound's link (after) / as it opens (before)

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
SCRATCH = os.environ.get("PAD592_SCRATCH", r"D:\Pinball\pad455_shots")
CLIPS = ("BuildingSmash_breath", "BuildingSmash_breath_new", "BuildingSmash_claw",
         "BuildingSmash_claw_new", "BuildingSmash_claw_new_full", "BuildingSmash_foot",
         "BuildingSmash_tail", "BuildingSmash_tail_new", "CloudLoop", "Credits_Godzilla",
         "game_over", "shoot_again", "shoot_again_new")
SCREENS = {"video_clip_sounds": "BuildingSmash_breath_new.mp4",
           "video_clip_maybe": "shoot_again.mp4"}


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
    scratch = tempfile.mkdtemp(prefix="pad592-", dir=SCRATCH)
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
            # the sound's link to the Audio tab (the first clip's first sound)
            page.locator(".vid-tbl .tr:has-text('%s')" % SCREENS["video_clip_sounds"]).first.click()
            time.sleep(3)
            play = page.locator(".vid-sound-play").first
            if play.count():
                play.click()
                time.sleep(1)
                print("play button after a click:", play.get_attribute("aria-label"), flush=True)
                play.click()
                time.sleep(0.5)
                print("and after another:", play.get_attribute("aria-label"), flush=True)
            go = page.locator(".vid-sound-go").first
            if go.count():
                go.click()
            else:
                api("ui.select_tab", "audio")
            time.sleep(3)
            page.mouse.move(5, 990)
            time.sleep(0.6)
            page.screenshot(path=os.path.join(out, pre + "audio_from_video.png"))
            print("audio sel:", (state().get("audio") or {}).get("sel"), flush=True)
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
