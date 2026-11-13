"""PAD-1232 proof shots: the Video tab's Vs stock column, the "Speed my file to
the stock clip's length" choice, and the Replacement player at that speed.

    python scripts/shot_pad1232.py <repo> <out_dir> <before|after> <project> <clip1> <clip2> <clip3>

Serves <repo> on <project> (a video extract with ATTRACT_LOOP1..3 under
video/, its .extract_source.json naming the card), its .staged_changes.json
written first with <clip1..3> picked for ATTRACT_LOOP1..3.  Shoots
``<tag>_table.png`` (sorted by Vs stock where there is one), then
right-clicks ATTRACT_LOOP1 and opens "This clip's length" for
``<tag>_length_menu.png``; on the branch it then picks "Speed my file to the
stock clip's length", plays the Replacement player a moment and shoots
``<tag>_preview.png``.  Needs Playwright (user site-packages) and Edge.
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

ROWS = ("ATTRACT_LOOP1", "ATTRACT_LOOP2", "ATTRACT_LOOP3")


def main():
    repo, out_dir, tag, project = (os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]),
                                   sys.argv[3], os.path.abspath(sys.argv[4]))
    clips = [os.path.abspath(c) for c in sys.argv[5:8]]
    os.makedirs(out_dir, exist_ok=True)
    side = os.path.join(project, ".staged_changes.json")
    with open(side, "w", encoding="utf-8") as f:
        json.dump({"video": {"video/%s.mov" % r: c for r, c in zip(ROWS, clips)}}, f)
    with open(os.path.join(project, ".extract_source.json"), encoding="utf-8") as f:
        card = json.load(f)["input_path"]
    scratch = tempfile.mkdtemp(prefix="pad1232-")
    launcher = os.path.join(scratch, "launch1232.py")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write("import sys\nsys.path.insert(0, %r)\n"
                "from pinball_decryptor.webui import host\n"
                "sys.argv = ['host'] + sys.argv[1:]\nsys.exit(host.main())\n" % repo)
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {
                       "extract_input": card, "write_original": card,
                       "extract_output": project, "write_assets": project,
                       "write_output": scratch}}}, f)
    import site
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, launcher],
                                        extra_env={"PYTHONPATH": site.getusersitepackages(),
                                                   "PAD_TICKET": "", "PAD_SLOT": ""})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            page.on("console", lambda m: print("console:", m.type, m.text, flush=True)
                    if m.type in ("error", "warning") else None)
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "video")
            time.sleep(12)                      # the scan and its probe passes
            print("sort by Vs stock:", webui_shot.api(url, "video.sort", "fit"), flush=True)
            time.sleep(2)
            row = page.locator(".vid-name", has_text=ROWS[0]).first
            row.click()
            time.sleep(3)
            page.mouse.move(5, 995)
            page.screenshot(path=os.path.join(out_dir, "%s_table.png" % tag))
            print("fit cells:", page.locator(".vid-fit").all_inner_texts(), flush=True)
            row.click(button="right")
            time.sleep(0.8)
            page.get_by_text("This clip's length", exact=True).first.hover()
            time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, "%s_length_menu.png" % tag))
            speed = page.get_by_text("Speed my file to the stock clip's length", exact=True)
            if speed.count():
                speed.first.click()
            else:
                page.keyboard.press("Escape")
            time.sleep(4)
            play = page.locator(".vid-pane").nth(1).get_by_role("button", name="Play")
            if play.count():
                play.first.click()
                time.sleep(3.2)
                rate = page.evaluate("() => { const v = document.querySelectorAll('.vid-pane video')[1];"
                                     " return v ? [v.playbackRate, v.currentTime] : null; }")
                print("replacement player rate/time:", rate, flush=True)
                page.locator(".vid-pane").nth(1).get_by_role("button", name="Pause").first.click()
                time.sleep(0.5)
            page.mouse.move(5, 995)
            page.screenshot(path=os.path.join(out_dir, "%s_preview.png" % tag))
            browser.close()
        print("staged:", open(side, encoding="utf-8").read(), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
