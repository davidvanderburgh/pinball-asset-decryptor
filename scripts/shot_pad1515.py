"""PAD-1515 proof shots: the JJP screen layout editor (Modes tab, Wonka 03.03).
    python scripts/shot_pad1515.py <repo> <out_dir> <before|after>
Three screens, the same set-up both times (Wonka's example modes and its wizard example, with four
progress panes of ours, copied into a scratch modes folder; David's own folders are never touched):
  mode_screen     the example mode's Settings, at its screen (the layout editor, or the old form rows)
  progress_board  the wizard mode's progress board
  menu            Every mode of this game, at the attract game type menu
  game_screen     Every mode of this game, at the game's own screen (a census of Wonka's in-game screen from
                  the PAD-1515 rig run: its HUD's PLAYER 1 box moved and scaled, a part hidden)
Needs Playwright (PAD_PWLIB / the user site) and Edge.
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

ISO = r"D:\Pinball\images\JJP\Wonka-v03.03.iso"
LABEL = "Wonka-v03.03"
RIG_FRAMES = r"C:\tmp\PAD-1515\rig"
CENSUS = os.environ.get("PAD1515_CENSUS", r"C:\tmp\PAD-1515\show")
PANES = ("CandyLaneMode", "DotsMode", "FactoryTourMode", "MikeTeaveeMode")


def _panes(folder):
    """Four lit / unlit pane pictures for the wizard's progress board."""
    from PIL import Image, ImageDraw
    cols = ((255, 120, 200), (120, 200, 255), (255, 210, 60), (140, 255, 140))
    lines = []
    for i, (mode, c) in enumerate(zip(PANES, cols)):
        for lit in (1, 0):
            im = Image.new("RGBA", (240, 160), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle((4, 4, 235, 155), 18, fill=c + (255,) if lit else (60, 60, 60, 200),
                                outline=(255, 255, 255, 255), width=5)
            d.text((20, 66), mode[:-4].upper(), fill=(0, 0, 0, 255) if lit else (150, 150, 150, 255))
            im.save(os.path.join(folder, "pane%d%s.png" % (i + 1, "" if lit else "_off")))
        lines.append("%s pane%d.png pane%d_off.png" % (mode, i + 1, i + 1))
    return lines


def main():
    repo = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    kind = sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="pad1515-")
    settings = os.path.join(scratch, "settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"disclaimer_accepted": True, "last_manufacturer": "jjp",
                   "manufacturers": {"jjp": {"extract_input": ISO, "write_original": ISO,
                                             "write_output": scratch}}}, f)
    modes = os.path.join(repo, "tools", "jjp_emu", "modes")
    mine = os.path.join(scratch, "jjp_modes", LABEL)
    shutil.copytree(os.path.join(modes, "examples", LABEL), mine)
    shutil.copy(os.path.join(modes, "wizard_examples", LABEL, "3_wizard.mode"), mine)
    with open(os.path.join(mine, "3_wizard.mode"), "a", encoding="utf-8") as f:
        f.write("".join("progress = %s\n" % ln for ln in _panes(mine)))
    # the game's own screen from the PAD-1515 Wonka rig run, as the editor's backdrop (never committed:
    # it is the game's art); the old form has no backdrop and ignores it
    frames = {}
    for n in ("game", "attract"):
        src = os.path.join(RIG_FRAMES, n + ".png")
        if os.path.isfile(src):
            os.makedirs(os.path.join(mine, ".layout"), exist_ok=True)
            frames[n] = os.path.join(mine, ".layout", n + ".png")
            shutil.copy(src, frames[n])
    if kind == "after" and os.path.isfile(os.path.join(CENSUS, "game.json")):
        os.makedirs(os.path.join(mine, ".layout"), exist_ok=True)
        for f in os.listdir(CENSUS):                  # what Show it in the game left: censuses and grabs
            if f.endswith((".json", ".png")):
                shutil.copy(os.path.join(CENSUS, f), os.path.join(mine, ".layout", f))
    import site
    proc, url = webui_shot.start_server(settings, scratch, app_cmd=None,
                                        extra_env={"PYTHONPATH": site.getusersitepackages(),
                                                   "PAD_JJP_MODES_DIR": os.path.join(scratch, "jjp_modes")})
    try:
        webui_shot.api(url, "ui.pick_manufacturer", "jjp")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.evaluate("f => { for (const [k, v] of Object.entries(f)) localStorage.setItem('pad.jjplayout.backdrop.' + k, v); }",
                          {"mode": frames.get("game", ""), "progress": frames.get("game", ""), "menu": frames.get("attract", ""),
                           "title_mode": frames.get("game", "")})
            page.reload()
            page.wait_for_function("window.__padReady === true", timeout=60000)
            time.sleep(2)
            webui_shot.api(url, "ui.select_tab", "modes")
            time.sleep(3)
            hide = page.get_by_text("Hide log", exact=True)
            if hide.count():
                hide.first.click()

            def to(sel_after, text_before):
                loc = page.locator(sel_after)
                if loc.count():
                    loc.first.evaluate("e => e.scrollIntoView({block: 'start'})")
                    return "editor"
                page.get_by_text(text_before, exact=True).first.evaluate("e => e.scrollIntoView({block: 'start'})")
                return "form"

            webui_shot.api(url, "modes.jjp_open", "1_example.mode")
            time.sleep(2)
            print("mode_screen:", to(".jjpl[data-screen=mode]", "Screen"))
            time.sleep(1.5)
            pick = page.locator(".jjpl[data-screen=mode] .jjpl-el.k-panel")
            if pick.count():                  # the panel picked: its handles and its numbers
                bb = pick.first.bounding_box()
                page.mouse.click(bb["x"] + 8, bb["y"] + bb["height"] - 8)
                time.sleep(1)
            page.screenshot(path=os.path.join(out_dir, kind + "_mode_screen.png"))

            webui_shot.api(url, "modes.jjp_open", "3_wizard.mode")
            time.sleep(2)
            print("progress_board:", to(".jjpl[data-screen=progress]", "Wizard mode and game type"))
            time.sleep(1.5)
            page.screenshot(path=os.path.join(out_dir, kind + "_progress_board.png"))

            page.get_by_text("Every mode of this game", exact=False).first.click()
            time.sleep(2)
            loc = page.locator(".jjpl[data-screen=menu]")
            if loc.count():
                loc.first.evaluate("e => e.scrollIntoView({block: 'start'})")
                print("menu: editor")
            else:
                page.locator(".jjpm-row[data-key=game_type_normal]").first.evaluate(
                    "e => e.scrollIntoView({block: 'start'})")
                print("menu: form")
            time.sleep(1.5)
            page.screenshot(path=os.path.join(out_dir, kind + "_menu.png"))

            g = page.locator(".jjpl[data-screen=game]")
            if g.count():
                # the PLAYER 1 box moved up and a little bigger, the gumdrops hidden: through the app's own calls
                lay = ((webui_shot.state(url).get("modes") or {}).get("jjp") or {}).get("layout")
                els = ((lay or {}).get("game") or {}).get("elements") or []
                mv = next((e for e in els if e["name"] == "atlas_playerup"), None)
                if mv:
                    o = mv["orig"]
                    webui_shot.api(url, "modes.jjp_place", "title", mv["key"], [o[0] + 18, o[1] - 30, o[2] * 1.15, o[3] * 1.15])
                hd = next((e for e in els if e["name"].startswith("sp_candy_gumdrops")), None)
                if hd:
                    webui_shot.api(url, "modes.jjp_screen_part", hd["name"], "hide")
                time.sleep(2)
                g.first.evaluate("e => e.scrollIntoView({block: 'start'})")
                time.sleep(1)
                chip = page.locator(".jjpl[data-screen=game] .jjpl-pchip", has_text="atlas_playerup")
                if chip.count():
                    chip.first.click()
                    time.sleep(1)
                print("game_screen: editor", bool(mv), bool(hd))
            else:
                page.locator(".jjpm-title-card .bd").first.evaluate("e => e.scrollIntoView({block: 'end'})")
                print("game_screen: form")
            time.sleep(1.5)
            page.screenshot(path=os.path.join(out_dir, kind + "_game_screen.png"))
            print("page errors:", errors)
            browser.close()
    finally:
        proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
