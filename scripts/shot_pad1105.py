"""PAD-1105 proof shots: the Audio tab hides the sounds no sound request plays.

    python scripts/shot_pad1105.py <repo> <out_dir> [--after]

Serves <repo> on a scratch Stern project made here: ten decoded sounds and a
``sound_requests.tsv`` in which four of them are played by no request (the
Requests column reads None). Writes, under the same name before and after:

- <before_|after_>audio_unused.png  the Audio list; with --after the
                                    "Hide unused" tick is on first

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

#: (file, played) - four sounds no request plays
SOUNDS = (
    ("00m00s104 - idx0001.wav", True), ("00m00s122 - idx0002.wav", True),
    ("00m00s152 - idx0003.wav", True), ("00m00s161 - idx0004.wav", False),
    ("00m00s162 - idx0005.wav", False), ("00m00s164 - idx0006.wav", True),
    ("00m00s180 - idx0007.wav", True), ("00m00s198 - idx0008.wav", False),
    ("00m00s208 - idx0009.wav", False), ("00m00s210 - idx0010.wav", True),
)


def _project(repo, scratch):
    sys.path.insert(0, repo)
    from pinball_decryptor.plugins.stern import clip_sounds as CS
    dst = os.path.join(scratch, "beatles")
    os.makedirs(os.path.join(dst, "audio"))
    lines, firsts = [], {}
    for i, (name, played) in enumerate(SOUNDS):
        p = os.path.join(dst, "audio", name)
        P._wav(p, 1500 + 200 * i)
        with open(p, "rb") as f:
            lines.append("audio/%s\t%s\n" % (name, hashlib.md5(f.read()).hexdigest()))
        if played:
            firsts[i] = [i + 1]
    with open(os.path.join(dst, ".checksums.md5"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    CS.write_requests(os.path.join(dst, CS.REQUESTS_TSV), [[1]] * 20, firsts,
                      {0: "SE FX START"}, also={})
    return dst


def main():
    repo, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    after = "--after" in sys.argv
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1105-")
    project = _project(repo, scratch)
    print("serving", repo, "project", project, flush=True)
    proc, url = S._serve(repo, scratch, project)
    state = lambda: webui_shot.state(url)                    # noqa: E731
    out = lambda n: os.path.join(out_dir, ("after_" if after else "before_") + n)  # noqa: E731
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
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
            if after:
                page.get_by_text("Hide unused", exact=True).first.click()
                time.sleep(1.5)
            st = state().get("audio") or {}
            print("req_cap:", st.get("req_cap"), "hide_unused:", st.get("hide_unused"),
                  "status:", st.get("status"), flush=True)
            print("rows:", [(r["k"], r.get("rq")) for r in st.get("rows") or []], flush=True)
            page.mouse.move(5, 990)
            time.sleep(0.6)
            page.screenshot(path=out("audio_unused.png"))
            print("shot", out("audio_unused.png"), flush=True)
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
