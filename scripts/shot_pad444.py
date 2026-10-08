"""PAD-444 proof shots: which of the game's modes plays each clip, a row for each mode of a clip
two battles share, and the clips the game never plays.

    python scripts/shot_pad444.py <repo> <out_dir> [--after]

Serves <repo> on a SCRATCH Godzilla Pro 1.16 project holding the stock extract's clips whose
names mention Gigan (``D:\\Pinball\\gz116_bottleneck\\stock116``, copied with their manifest rows
and baseline digests) and recording the stock Pro 1.16 card as its source, so the Video tab can
read the card's game program. Writes, under the same names before and after:

- video_modes.png      searched for "gigan_ghidorah_vs_godzilla1"; after, the Battle vs Gigan row
                       of the clip it shares with the Ghidorah and Gigan tag team is selected
                       (before: the shared clip, main's one row for it)
- video_own_clip.png   new footage picked for the Gigan battle (after: in its own row, the list
                       on that battle's clips; before: on the shared clip, which main has)
- video_not_played.png after: the list on "Not played by the game"; before: the same search,
                       one of those clips selected

Each screen is served fresh, with the folder seeded as a pick there would leave it. Needs
Playwright (the user site-packages one) and the installed Edge.
"""
import hashlib
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

STOCK = os.environ.get("PAD444_EXTRACT", r"D:\Pinball\gz116_bottleneck\stock116")
CARD = os.environ.get("PAD444_CARD", r"D:\Pinball\images\Stern\spike2"
                      r"\godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")
SHARED = "video/gigan_ghidorah_vs_godzilla13.mov"
FOLLOW = "video/gigan_ghidorah_vs_godzilla13_battle_vs_gigan.mov"
GIGAN = "cmode_battle_vs_gigan"
UNPLAYED_ROW = "gigan_ghidorah_vs_godzilla11.mp4"
FOOTAGE = "MonsterBattles_Gigan_Idle.mp4"          # the "new footage" picked


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _project(scratch):
    """The stock extract's Gigan clips, as a project of their own."""
    dst = os.path.join(scratch, "gz116pro")
    vid = os.path.join(dst, "video")
    os.makedirs(vid)
    rows, sums = ["# output\tcard path\tbytes"], []
    with open(os.path.join(STOCK, "video", "manifest.txt"), encoding="utf-8") as f:
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 2 or line.startswith("#") or "gigan" not in cols[0].lower():
                continue
            shutil.copy2(os.path.join(STOCK, "video", cols[0]), os.path.join(vid, cols[0]))
            rows.append("\t".join(cols))
            sums.append("video/%s\t%s" % (cols[0], _md5(os.path.join(vid, cols[0]))))
    with open(os.path.join(vid, "manifest.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.write("\n".join(sums) + "\n")
    st = os.stat(CARD)
    with open(os.path.join(dst, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": CARD, "input_name": os.path.basename(CARD),
                   "size": st.st_size, "mtime": int(st.st_mtime), "card_version": "1.16.0"}, f)
    return dst


def _seed_pick(scratch, project, rel, own_clip):
    """The folder as a pick of the new footage for *rel* leaves it (a clip of its own for the
    Gigan battle: its file and record too)."""
    mine = os.path.join(scratch, "battra_footage.mp4")
    shutil.copy2(os.path.join(STOCK, "video", FOOTAGE), mine)
    data = {"video": {rel: mine}}
    if own_clip:
        shutil.copy2(os.path.join(project, *SHARED.split("/")), os.path.join(project, *rel.split("/")))
        data["own_clips"] = [{"name": os.path.splitext(os.path.basename(rel))[0],
                              "clip": "gigan_ghidorah_vs_godzilla13", "mode": GIGAN, "rel": rel,
                              "of": SHARED, "state": "own"}]
    with open(os.path.join(project, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _serve(repo, scratch, project):
    launcher = os.path.join(scratch, "launch444.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(base.LAUNCHER % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project,
                                               "write_assets": project,
                                               "extract_input": CARD}}}, f)
    import site
    return webui_shot.start_server(
        settings, scratch, app_cmd=[sys.executable, launcher],
        extra_env={"PYTHONPATH": site.getusersitepackages(),
                   "PAD_TITLE_CACHE": os.path.join(os.path.dirname(scratch), "pad444-titles")})


def _shot(repo, out, screen, after):
    scratch = tempfile.mkdtemp(prefix="pad444-")
    project = _project(scratch)
    if screen == "video_own_clip":
        _seed_pick(scratch, project, FOLLOW if after else SHARED, after)
    proc, url = _serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
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
            api("ui.select_tab", "video")
            time.sleep(2)
            base._wait_scan(state, "video")
            if after:
                # the card's game program is read once, off the UI thread
                deadline = time.time() + 120
                while time.time() < deadline:
                    if ((state().get("video") or {}).get("modes") or {}).get("ready"):
                        break
                    time.sleep(1)
                m = (state().get("video") or {}).get("modes") or {}
                print(screen, "modes:", [(x["label"], x["n"]) for x in m.get("list") or []],
                      flush=True)
            row = lambda n: page.locator(".vid-tbl .tr:has-text('%s')" % n)  # noqa: E731
            if screen == "video_modes":
                api("ui.set", "video", "search", "gigan_ghidorah_vs_godzilla1")
                time.sleep(2)
                if after:
                    row("gigan_ghidorah_vs_godzilla13.mov").nth(1).click()
                else:
                    row("gigan_ghidorah_vs_godzilla13.mov").first.click()
            elif screen == "video_own_clip":
                if after:
                    api("video.set_mode_filter", GIGAN)
                    time.sleep(2)
                    row("gigan_ghidorah_vs_godzilla13.mov").first.click()
                else:
                    api("ui.set", "video", "search", "gigan_ghidorah_vs_godzilla1")
                    time.sleep(2)
                    row("gigan_ghidorah_vs_godzilla13.mov").first.click()
            else:
                if after:
                    api("video.set_mode_filter", "__unplayed__")
                else:
                    api("ui.set", "video", "search", "gigan")
                time.sleep(2)
                row(UNPLAYED_ROW).first.click()
            time.sleep(3)
            page.mouse.move(5, 990)
            time.sleep(0.6)
            page.screenshot(path=os.path.join(out, ("after_" if after else "before_") + screen + ".png"))
            v = state().get("video") or {}
            print(screen, "preview:", (v.get("preview") or {}).get("rel"),
                  ((v.get("preview") or {}).get("modes") or {}).get("text"), flush=True)
            print(screen, "page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()


def main():
    repo, out = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out, exist_ok=True)
    for screen in ("video_modes", "video_own_clip", "video_not_played"):
        _shot(repo, out, screen, after)


if __name__ == "__main__":
    main()
