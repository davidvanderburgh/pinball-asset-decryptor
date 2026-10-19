"""PAD-614 proof shots: RAMP FRENZY (tools/mode_views/showcase.py) in each of a blocks mode's view tabs.

    python scripts/shot_pad614.py <out dir> [<repo>] [--card <card image>]

The server runs from <repo> (default: this tree) against a scratch settings folder and a Godzilla Pro 1.15 project
holding the one blocks mode, bound to a real Godzilla Pro 1.15 card (read only: the Playfield reads its picture off
it). One shot per view, <view>.png; a tree without that tab (main before PAD-614) shoots the Blocks tab in its place,
which is how the same rules looked there. Shots: cards, story, script, table, timeline, graph, cmakes (the C the
blocks make), picker and picker_after (a Rule card's shot picked on the playfield), script_error (a typing mistake
shown on its line), ceditor (a mode written in C, on its Code page).
"""

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
import webui_shot  # noqa: E402
from shot_pad612 import CARD, HOST, SEED  # noqa: E402

VIEWS = [("cards", "Rule cards"), ("story", "Story"), ("script", "Script"), ("table", "Shot table"),
         ("timeline", "Timeline"), ("graph", "Node graph"), ("cmakes", "C it makes")]
# a C mode made for the last shot opens nothing in the OS's editor
HOST_614 = HOST.replace("from pinball_decryptor.webui import host",
                        "tab.ModesTab.open_path = lambda self, path: True\nfrom pinball_decryptor.webui import host")


def main():
    args = sys.argv[1:]
    card = CARD
    if "--card" in args:
        i = args.index("--card")
        card = args[i + 1]
        del args[i:i + 2]
    outdir = os.path.abspath(args[0])
    repo = os.path.abspath(args[1]) if len(args) > 1 else HERE
    os.makedirs(outdir, exist_ok=True)
    webui_shot.REPO = repo
    scratch = tempfile.mkdtemp(prefix="pad614-")
    project = os.path.join(scratch, "godzilla project")
    os.makedirs(project)
    seed = os.path.join(scratch, "seed.py")
    with open(seed, "w", encoding="utf-8") as f:
        f.write(SEED % {"repo": repo, "project": project, "views": os.path.join(HERE, "tools", "mode_views")})
    blocks_json = subprocess.run([sys.executable, seed], check=True, capture_output=True, text=True).stdout.strip()
    hostpy = os.path.join(scratch, "host.py")
    with open(hostpy, "w", encoding="utf-8") as f:
        f.write(HOST_614 % {"repo": repo, "card": card})
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                   "manufacturers": {"stern": {"extract_output": project, "write_assets": project}}}, f)
    import site
    env = {"PYTHONPATH": site.getusersitepackages()}
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=[sys.executable, hostpy], extra_env=env)
    print("repo", repo, "url", url, flush=True)
    errors = []
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "stern")
        webui_shot.api(url, "ui.select_tab", "modes")
        time.sleep(4)
        if os.environ.get("PAD_PWLIB"):
            sys.path.insert(0, os.environ["PAD_PWLIB"])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            page.evaluate("() => { localStorage.setItem('pad.modes.blockspage', 'blocks'); }")
            time.sleep(2)
            rows = page.get_by_text("RAMP FRENZY", exact=True)
            if rows.count():
                rows.first.click()
                time.sleep(2.5)
            hide = page.get_by_text("Hide log")
            if hide.count():
                hide.first.click()
                time.sleep(1)
            pane = page.locator(".bk-pane").first

            def shoot(name):
                pane.evaluate("(el) => el.scrollIntoView({block: 'start'})")
                page.mouse.move(5, 5)
                time.sleep(0.6)
                page.screenshot(path=os.path.join(outdir, name + ".png"))

            def open_tab(label):
                tab = page.get_by_role("tab", name=label, exact=True)
                if not tab.count():
                    page.get_by_role("tab", name="Blocks", exact=True).first.click()
                    time.sleep(1)
                    return False
                tab.first.click()
                time.sleep(1.5)
                return True

            for key, label in VIEWS:
                has = open_tab(label)
                print(key, "tab" if has else "(no tab: the Blocks tab instead)", flush=True)
                if has and key == "story":
                    shoot("story")
                    page.locator(".rv-rule", has_text="Score 5,000,000").first.click()
                    time.sleep(1.2)
                    shoot("story_open")
                    continue
                if not has and key == "story":
                    shoot("story_open")
                if has and key == "table":
                    # a rule opened from the view: its blocks beside or under it
                    page.locator(".rv-rule, .sg-chip", has_text="Score 5,000,000").first.click()
                    time.sleep(1)
                if has and key == "graph":
                    page.locator(".ng-thing", has_text="jackpots").first.click()
                    time.sleep(1)
                shoot(key)
                if has and key == "script":
                    ed = page.locator(".sc-text").first
                    text = ed.input_value()
                    print("script lines:", text.count("\n"), flush=True)
                    ed.fill(text.replace("score(points=5000000)", "score(points=5000000", 1))
                    time.sleep(1.2)
                    print("error:", page.locator(".sc-err").first.inner_text() if page.locator(".sc-err").count() else "-",
                          flush=True)
                    go = page.locator(".sc-err button")
                    if go.count():
                        go.first.click()
                        time.sleep(0.6)
                    shoot("script_error")
                    ed.fill(text)
                    time.sleep(1.2)
            # the playfield as the other views' shot picker: a Rule card's shot picked on the picture
            if open_tab("Rule cards"):
                btn = page.locator(".pf-pickbtn").first
                if btn.count():
                    btn.click()
                    page.wait_for_selector(".pf-pop .pf-art, .pf-pop .pf-none", timeout=60000)
                    time.sleep(1)
                    shoot("picker")
                    # the Right ramp's insert pressed on the picture: the first card's shot follows
                    hit = page.evaluate("""() => { const c = [...document.querySelectorAll('.pf-pop circle.pf-ins')]
                        .find((e) => (e.getAttribute('data-tip') || '').startsWith('RIGHT RAMP\\n'));
                        if (c) c.dispatchEvent(new MouseEvent('click', { bubbles: true })); return !!c; }""")
                    time.sleep(1.2)
                    first = page.locator(".rc-card").first.locator(".rc-hat select").first.input_value()
                    print("picked on the picture:", hit, "-> the first card's shot is now", first,
                          "| picker still open:", page.locator(".pf-pop").count(), flush=True)
                    shoot("picker_after")
            else:
                shoot("picker")
                shoot("picker_after")
            # a mode written in C: its Code page (PAD-614: the C edited in the app)
            webui_shot.api(url, "modes.new_code_mode", "Laser Show")
            time.sleep(3)
            page.locator(".modes-editor").first.evaluate("(el) => el.scrollIntoView({block: 'start'})")
            time.sleep(0.6)
            print("C editor:", page.locator(".ce-cmode .ce-ta").count(), "lines:",
                  page.locator(".ce-cmode .ce-gutter > div").count(), flush=True)
            page.mouse.move(5, 5)
            time.sleep(0.5)
            page.screenshot(path=os.path.join(outdir, "ceditor.png"))
            ta = page.locator(".ce-cmode .ce-ta")
            if ta.count():
                # typed in the app and saved with Ctrl+S: the file on disk is what was typed
                ta.first.evaluate("(el) => { el.focus(); el.selectionStart = el.selectionEnd = el.value.length; }")
                page.keyboard.type("/* typed in the app */")
                time.sleep(0.4)
                dirty = page.locator(".ce-cmode .warn").count()
                page.keyboard.press("Control+s")
                time.sleep(1.2)
                src = os.path.join(project, "modes", "laser_show", "laser_show.c")
                with open(src, encoding="utf-8") as f:
                    print("C saved from the page:", f.read().rstrip().endswith("/* typed in the app */"),
                          "| 'Not saved' shown before Ctrl+S:", bool(dirty), flush=True)
            with open(blocks_json, encoding="utf-8") as f:
                print("blocks.json scripts:", len(json.load(f).get("scripts", [])), flush=True)
            browser.close()
        print("page errors:", errors or "none", flush=True)
        print("shots in", outdir, flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
