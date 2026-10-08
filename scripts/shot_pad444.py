"""PAD-444 proof shots: which of the game's modes plays each clip, and a mode's own copy.

    python scripts/shot_pad444.py <repo> <out_dir> [--after]

Serves <repo> on a SCRATCH Godzilla Pro 1.16 project holding the stock extract's clips
whose names mention Gigan (``D:\\Pinball\\gz116_bottleneck\\stock116``, copied with their
manifest rows and baseline digests) and recording the stock Pro 1.16 card as its source,
so the Video tab can read the card's game program.  Writes, under the same names before
and after:

- video_modes.png     the Video tab searched for "gigan", the clip the Gigan battle and the
                      Ghidorah and Gigan tag team both play selected
- video_own_copy.png  after "Own copy for Battle vs Ghidorah and Gigan", the list put on that
                      battle's clips only, its new copy selected (after); before, the same
                      search and selection (main has neither)

Needs Playwright (the user site-packages one) and the installed Edge.
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
SHARED = "gigan_ghidorah_vs_godzilla13"
TAG_TEAM = "Battle vs Ghidorah and Gigan"
TAG_CLASS = "cmode_battle_vs_ghidorah_and_gigan"


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
                   "PAD_TITLE_CACHE": os.path.join(scratch, "titles")})


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad444-")
    project = _project(scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = _serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
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
            st = base._wait_scan(state, "video")
            print("video rows:", len(st.get("rows") or []), flush=True)
            if after:
                # the card's game program is read once, off the UI thread
                deadline = time.time() + 120
                while time.time() < deadline:
                    m = (state().get("video") or {}).get("modes") or {}
                    if m.get("ready"):
                        break
                    time.sleep(1)
                m = (state().get("video") or {}).get("modes") or {}
                print("modes:", m.get("note"), len(m.get("list") or []), flush=True)
            api("ui.set", "video", "search", "gigan")
            time.sleep(2)
            row = lambda n: page.locator(".vid-tbl .tr:has-text('%s')" % n).first  # noqa: E731
            row(SHARED + ".").click()
            time.sleep(3)
            page.mouse.move(5, 990)
            time.sleep(0.6)
            page.screenshot(path=out("video_modes.png"))
            if after:
                btn = page.locator(".vid-modes button:has-text('%s')" % TAG_TEAM).first
                btn.click()
                time.sleep(1.5)
                ok = page.locator(".modal button:has-text('Make the copy')")
                if ok.count():
                    ok.first.click()
                base._wait_scan(state, "video")
                time.sleep(3)
                # the tag team's clips only: the list of one mode's clips, its copy among them
                api("video.set_mode_filter", TAG_CLASS)
                api("ui.set", "video", "search", "")
                time.sleep(3)
            page.mouse.move(5, 990)
            time.sleep(0.6)
            page.screenshot(path=out("video_own_copy.png"))
            v = state().get("video") or {}
            print("preview:", (v.get("preview") or {}).get("rel"), flush=True)
            print("page errors:", errors, flush=True)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    print("server log", os.path.join(scratch, "server.log"))


if __name__ == "__main__":
    main()
