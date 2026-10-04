"""PAD-361 proof shots: the Scenes tab's first loop of Play on Godzilla's credits (120 frames).

    python scripts/shot_pad361.py <repo> <project> <out_dir> <prefix>

Serves <repo> on a settings copy whose Stern project is <project> (only read: the rig selects
and plays, never edits), opens Scenes on the credits console scene, presses Play and writes:

- <prefix>_first_loop.png  3 s after Play, while the first frames are still being drawn
- <prefix>_timing.txt      the first loop's stalls: how often, and for how long, the frame
                           counter stood still once playing had begun
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402
import shot_pad251_tab as rig  # noqa: E402
from shot_pad261 import CREDITS, PROBE  # noqa: E402


def stalls(samples, frame_ms):
    """(first frame ms, [(at ms, held ms)]) over the first pass through the frames: a stall is
    the counter standing on one frame for more than three frame times."""
    first = next((s for s in samples if s[2] and s[1].startswith("Frame ")), None)
    if first is None:
        return None, []
    out, last, since, top = [], first[1], first[0], 1
    for t, lab, _ in samples[samples.index(first):]:
        if not lab.startswith("Frame "):
            continue
        n = int(lab.split()[1])
        if n < top:                                  # wrapped: the first loop is over
            break
        if lab != last:
            if t - since > 3 * frame_ms:
                out.append((since, t - since))
            last, since, top = lab, t, n
    return first[0], out


def main():
    repo, project, out, prefix = sys.argv[1:5]
    os.makedirs(out, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad361-")
    proc, url = rig._serve(repo, scratch, project)
    api = lambda m, *a: webui_shot.api(url, m, *a)          # noqa: E731
    state = lambda: webui_shot.state(url)                    # noqa: E731
    from playwright.sync_api import sync_playwright
    notes = ["code: %s" % repo]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.add_init_script(
                "try { localStorage.setItem('pad.log.open', '0'); } catch (e) {}")
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            api("ui.pick_manufacturer", "stern")
            page.locator(".rail").get_by_text("Scenes", exact=True).first.click()
            rig._wait(lambda: state()["text_scenes"].get("alive"), 30)
            assert api("text_scenes.select", CREDITS)
            rig._wait(lambda: state()["text_scenes"].get("tree_view") and
                      state()["text_scenes"].get("frames"), 60)
            time.sleep(1.5)
            page.get_by_role("button", name="Play").first.click()
            t0 = time.time()
            page.evaluate("() => { window.__pad361 = (%s)(30000); }" % PROBE.strip())
            time.sleep(3)
            page.screenshot(path=os.path.join(out, "%s_first_loop.png" % prefix))
            rig._wait(lambda: (state()["text_scenes"].get("tree_play") or {}).get("done"), 180, 0.5)
            play = state()["text_scenes"]["tree_play"]
            notes.append("every frame drawn %.1f s after Play" % (time.time() - t0))
            frame_ms = 1000.0 / (play.get("fps") or 30)
            first, st = stalls(page.evaluate("() => window.__pad361"), frame_ms)
            notes.append("%d frames at %g fps; first frame on the canvas %s ms after Play"
                         % (play["frames"], play.get("fps") or 30, first))
            notes.append("first loop: %d stalls, %d ms frozen in all%s"
                         % (len(st), sum(h for _, h in st),
                            (": " + ", ".join("%d ms at %d ms" % (h, t) for t, h in st)) if st else ""))
            notes.append("page errors: %s" % errors)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:                               # noqa: BLE001
            proc.kill()
    with open(os.path.join(out, prefix + "_timing.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(notes) + "\n")
    print("\n".join(notes))


if __name__ == "__main__":
    main()
