"""PAD-440 proof shot: several clips side by side, colour graded live.

    python scripts/shot_pad440.py <repo> <out_dir> [--after] [--narrow]

Serves <repo> on shot_pad312's scratch Godzilla project with four video slots, each
replaced by a copy of a mode clip (three with the color profile attached, the fourth
without; the project's shared files profile is the source's "Black and white") and two
saved profiles, "Warm grade" and "Cool grade", and photographs, under the
same name before and after:

- video_compare.png   the four clips selected on the Video tab, the Colors bar open on
                      Files, the first clip given "Warm grade" and the second "Cool grade"

Before (main) the tab shows one clip at a time, Original beside its Replacement, small.
After (--after, the ticket branch) Compare shows the four together, big, beside the bar,
the clicked one outlined: the clip the bar changes.  --narrow: a 1100x760 window instead
(saved as before_narrow_ / after_narrow_), to check the layout there.

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
import shot_pad360 as saved  # noqa: E402

WARM = """name = Warm grade
gamma = 1.00 1.05 1.20
gain = 1.15 1.00 0.80
lift = 0.02 0.02 0.02
saturation = 1.35
brightness = 1.00
contrast = 1.05
"""
COOL = """name = Cool grade
gamma = 1.20 1.05 0.95
gain = 0.80 0.95 1.15
lift = 0.00 0.00 0.00
saturation = 0.85
brightness = 1.00
contrast = 1.00
"""
# (slot, mode clip it is a copy of, color profile attached?); every one is replaced
CLIPS = (
    (base.VIDEO, "atomic_breath", True),
    ("video/pad440_mothra.mp4", "mothra_s_song", True),
    ("video/pad440_ghidorah.mp4", "king_ghidorah", True),
    ("video/pad440_shin.mp4", "shin_godzilla", False),
)


def _clips(scratch, project):
    side = os.path.join(project, ".staged_changes.json")
    with open(side, encoding="utf-8") as f:
        data = json.load(f)
    picks = data.setdefault("video", {})
    for rel, mode, _on in CLIPS[1:]:
        src = os.path.join(base.SOURCE, "modes", mode, "clip.mp4")
        dst = os.path.join(project, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        mine = os.path.join(scratch, "my_%s.mp4" % mode)
        shutil.copy2(src, mine)
        picks[rel] = mine
    data["video_color_slots"] = {rel: on for rel, _m, on in CLIPS}
    with open(side, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _seek_all(page, selector, t=2.5):
    """Every player on show at the same moment, so the frames compare."""
    page.evaluate("""([sel, t]) => Promise.all([...document.querySelectorAll(sel)].map((v) =>
        new Promise((ok) => { const done = () => ok(); v.addEventListener('seeked', done, { once: true });
          v.addEventListener('error', done, { once: true }); v.currentTime = t; setTimeout(done, 4000); })))""",
                  [selector, t])


def main():
    repo, out_dir = sys.argv[1:3]
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad440-")
    project = base._project(scratch)
    _clips(scratch, project)
    folder = os.path.join(scratch, "My color profiles")
    os.makedirs(folder)
    for name, text in (("Warm grade.txt", WARM), ("Cool grade.txt", COOL)):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(text)
    print("serving", repo, "project", project, flush=True)
    proc, url = saved._serve(repo, scratch, project, folder)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    tag = ("after_" if after else "before_") + ("narrow_" if "--narrow" in sys.argv else "")
    out = lambda n: os.path.join(out_dir, tag + n)          # noqa: E731

    def use(label):
        c = state().get("color") or {}
        pick = next((o["value"] for o in c.get("saved") or []
                     if label in o.get("label", "")), None)
        print("use_saved", label, api("color.use_saved", pick), flush=True)
        time.sleep(2)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            size = (1100, 760) if "--narrow" in sys.argv else (1600, 1000)
            page = browser.new_page(viewport={"width": size[0], "height": size[1]})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0');"
                " localStorage.removeItem('pad.colorbar.open.video'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            time.sleep(1)
            api("ui.select_tab", "video")
            time.sleep(2)
            st = base._wait_scan(state, "video")
            print("video rows:", [r["rel"] for r in st.get("rows") or []], flush=True)
            api("ui.set", "video", "search", "video/pad")
            time.sleep(2)
            names = [rel.split("/")[-1] for rel, _m, _r in CLIPS]
            row = lambda n: page.locator(".vid-tbl .tr:has-text('%s')" % n).first  # noqa: E731
            row(names[0]).click()
            time.sleep(1.5)
            page.click(".cpd-handle")                     # the Colors bar, on Files
            time.sleep(1.5)
            tab = page.query_selector(".cpd-tabs button:has-text('Files')")
            if tab:
                tab.click()
                time.sleep(1)
            if after:
                for n in names[1:]:
                    row(n).click(modifiers=["Control"])
                    time.sleep(0.4)
                page.click(".vid-cmp-open")
                time.sleep(3)
                tile = lambda n: page.locator(".vcm-tile", has_text=n).locator(".vcm-screen")  # noqa: E731
                print("tiles:", page.locator(".vcm-tile").count(), flush=True)
                tile(names[1]).click()
                time.sleep(1.2)
                use("Cool grade")
                tile(names[0]).click()
                time.sleep(1.2)
                use("Warm grade")
                _seek_all(page, ".vcm-tile video")
            else:
                use("Warm grade")
                row(names[1]).click()
                time.sleep(2)
                use("Cool grade")
                row(names[0]).click()
                time.sleep(1)
                for n in names[1:]:
                    row(n).click(modifiers=["Control"])
                    time.sleep(0.4)
                time.sleep(2)
                _seek_all(page, ".vid-screen video")
            time.sleep(2)
            # the "Loaded ..." toasts go first: they would sit over the bar
            try:
                page.wait_for_function("!document.querySelector('.toast')", timeout=15000)
            except Exception:                               # noqa: BLE001
                print("toasts still up", flush=True)
            page.eval_on_selector(".cpd-body", "el => { el.scrollTop = 0; }")
            page.mouse.move(5, 990)
            time.sleep(0.6)
            page.screenshot(path=out("video_compare.png"))
            c = state().get("color") or {}
            print("color:", {k: c.get(k) for k in ("mode", "name", "file", "own_names")},
                  flush=True)
            v = state().get("video") or {}
            print("compare:", [(t.get("rel"), t.get("side"), len(t.get("look") or []))
                               for t in ((v.get("compare") or {}).get("tiles") or [])], flush=True)
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
