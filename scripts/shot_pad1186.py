r"""PAD-1186: the Spike 3 Replace tabs and Write, clicked through in the app.

    python scripts/shot_pad1186.py <app tree> <out dir> rail <project>
    python scripts/shot_pad1186.py <app tree> <out dir> e2e  <project> <build.raw> <files dir>

<app tree> is a checkout or a ``git archive`` export (main for "before", the
ticket branch for "after").  The app is served on a scratch settings file that
carries only David's preview codes (Spike 3 is a preview feature), so nothing
of his real settings or projects is touched.

``rail``: the Extract tab with a Spike 3 card picked and an extracted Spike 3
project open - the shot shows which tabs the rail offers (main: Extract,
Compare and Emulate only; the branch: the Replace tabs, Scenes, Colors, Write).

``e2e`` (the branch): the whole job the ticket asks for, through the app's own
calls - pick the card, Extract into <project> (removed first), pick a
replacement on Replace Audio (a longer and a shorter sound), Replace Video (a
clip bigger than its slot), Replace Images, edit a line on Replace Text, look
at Scenes and Colors, then Build on Write to <build.raw> - with a shot of each
tab.  Every file dialog is answered from the plan (no dialog opens), every
yes/no with yes.  <files dir> holds the replacements (made by the caller).
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import webui_shot  # noqa: E402

CARD = r"D:\Pinball\images\Stern\spike3\pokemon_le-0_82_0.Release.64G.sdcard-secure.raw"

LAUNCHER = r'''
import json, os, sys
sys.path.insert(0, %(tree)r)
from pinball_decryptor.webui import compat
Q = %(queue)r
def _next(kind, **kw):
    try:
        with open(Q, encoding="utf-8") as f:
            items = json.load(f)
    except (OSError, ValueError):
        items = []
    ans = items.pop(0) if items else ""
    with open(Q, "w", encoding="utf-8") as f:
        json.dump(items, f)
    print("[shot1186] dialog %%s %%r -> %%r" %% (kind, kw.get("title"), ans), flush=True)
    return ans
compat.filedialog.askopenfilename = lambda **kw: _next("open", **kw)
compat.filedialog.askopenfilenames = lambda **kw: ([_next("open", **kw)] or [])
compat.filedialog.asksaveasfilename = lambda **kw: _next("save", **kw)
compat.filedialog.askdirectory = lambda **kw: _next("folder", **kw)
def _yes(*a, **k):
    print("[shot1186] yes to %%r" %% (k.get("title") or (a[0] if a else ""),), flush=True)
    return True
def _say(*a, **k):
    print("[shot1186] said %%r: %%r" %% (a[0] if a else "", (a[1] if len(a) > 1 else "")[:300]), flush=True)
for n in ("askyesno", "askokcancel"):
    setattr(compat.messagebox, n, _yes)
compat.messagebox.askyesnocancel = _yes
for n in ("showinfo", "showwarning", "showerror"):
    setattr(compat.messagebox, n, _say)
from pinball_decryptor.webui import host
sys.argv = ["host"] + sys.argv[1:]
sys.exit(host.main())
'''


def _codes():
    p = os.path.join(os.environ.get("APPDATA", ""), "pinball_decryptor",
                     "settings.json")
    try:
        with open(p, encoding="utf-8") as f:
            return list(json.load(f).get("preview_codes") or [])
    except (OSError, ValueError):
        return []


class Run:
    def __init__(self, tree, out):
        self.tree, self.out = tree, out
        self.scratch = tempfile.mkdtemp(prefix="pad1186-")
        self.queue = os.path.join(self.scratch, "dialogs.json")
        self.answer([])
        launcher = os.path.join(self.scratch, "launch1186.py")
        with open(launcher, "w", encoding="utf-8") as f:
            f.write(LAUNCHER % {"tree": tree, "queue": self.queue})
        settings = os.path.join(self.scratch, "settings.json")
        with open(settings, "w", encoding="utf-8") as f:
            json.dump({"disclaimer_accepted": True, "last_manufacturer": "stern",
                       "preview_codes": _codes()}, f)
        import site
        env = {"PYTHONPATH": site.getusersitepackages(), "PAD_TICKET": "",
               "PAD_SLOT": ""}
        self.proc, self.url = webui_shot.start_server(
            settings, self.scratch, extra_env=env,
            app_cmd=[sys.executable, launcher])
        print("tree", tree, "server", self.url.split("?")[0], flush=True)

    def answer(self, items):
        with open(self.queue, "w", encoding="utf-8") as f:
            json.dump(list(items), f)

    def api(self, m, *a):
        return webui_shot.api(self.url, m, *a)

    def st(self, ns=None):
        s = webui_shot.state(self.url)
        return s.get(ns, {}) if ns else s

    def wait_idle(self, what, timeout=3600, settle=2):
        t0 = time.time()
        time.sleep(settle)
        while time.time() - t0 < timeout:
            if not self.st("shell").get("running"):
                print("  %s done in %.0f s" % (what, time.time() - t0), flush=True)
                return True
            time.sleep(3)
        raise SystemExit("%s did not finish in %d s" % (what, timeout))

    def wait_rows(self, ns, key="rows", timeout=600):
        t0 = time.time()
        while time.time() - t0 < timeout:
            s = self.st(ns)
            if s.get(key) and not s.get("scanning"):
                return s[key]
            time.sleep(2)
        raise SystemExit("%s: no %s after %d s" % (ns, key, timeout))

    def close(self):
        self.proc.terminate()


def shot(page, path):
    time.sleep(1.5)
    page.screenshot(path=path)
    print("shot", path, flush=True)


def tabs_on_rail(run):
    sh = run.st("shell")
    return [t.get("label") or t.get("key") for t in sh.get("tabs") or []
            if t.get("visible", True)]


def rail(run, page, project, path):
    run.api("ui.pick_manufacturer", "stern")
    run.api("ui.select_tab", "extract")
    run.answer([CARD])
    run.api("extract.browse_input")
    time.sleep(4)
    if project:
        run.answer([project])
        run.api("extract.browse_output")
        time.sleep(4)
    print("rail:", tabs_on_rail(run), flush=True)
    shot(page, path)


def _rel(rows, needle):
    for r in rows:
        for k in ("rel", "iid", "id", "rel_path"):
            v = r.get(k)
            if isinstance(v, str) and needle in v:
                return v
    raise SystemExit("no row matching %r (first: %r)" % (needle, rows[:1]))


def e2e(run, page, project, build, files):
    import shutil
    shutil.rmtree(project, ignore_errors=True)
    os.makedirs(project)
    out = run.out
    run.api("ui.pick_manufacturer", "stern")
    run.api("ui.select_tab", "extract")
    run.answer([CARD])
    run.api("extract.browse_input")
    time.sleep(3)
    run.answer([project])
    run.api("extract.browse_output")
    time.sleep(2)
    print("rail before extract:", tabs_on_rail(run), flush=True)
    run.api("extract.start")
    run.wait_idle("extract")
    shot(page, os.path.join(out, "after_extract.png"))
    print("rail after extract:", tabs_on_rail(run), flush=True)

    # Replace Audio: a longer and a shorter sound
    run.api("ui.select_tab", "audio")
    run.api("audio.scan")
    rows = run.wait_rows("audio")
    print("audio rows:", len(rows), flush=True)
    for needle, src in (("idx0000", "long_tone.wav"), ("idx0001", "short_tone.wav")):
        rel = _rel(rows, needle)
        run.answer([os.path.join(files, src)])
        print("  audio.choose", rel, run.api("audio.choose", rel), flush=True)
    shot(page, os.path.join(out, "after_replace_audio.png"))

    # Replace Video: a clip bigger than its slot
    run.api("ui.select_tab", "video")
    run.api("video.scan")
    rows = run.wait_rows("video")
    print("video rows:", len(rows), flush=True)
    rel = _rel(rows, "PK_BGPattern_PokeBallRed")
    run.answer([os.path.join(files, "grow_green_hevc.mp4")])
    print("  video.choose", rel, run.api("video.choose", rel), flush=True)
    shot(page, os.path.join(out, "after_replace_video.png"))

    # Replace Images
    run.api("ui.select_tab", "images")
    run.api("images.scan")
    rows = run.wait_rows("images")
    print("image rows:", len(rows), flush=True)
    rel = _rel(rows, "Coin0015")
    run.answer([os.path.join(files, "red_coin.png")])
    print("  images.choose", rel, run.api("images.choose", rel), flush=True)
    shot(page, os.path.join(out, "after_replace_images.png"))

    # Replace Text
    run.api("ui.select_tab", "text")
    run.api("text.scan")
    rows = run.wait_rows("text")
    print("text rows:", len(rows), flush=True)
    hit = next(r for r in rows if r.get("original") == "GAME NAME")
    run.api("text.select", hit.get("iid") or hit.get("id"))
    time.sleep(1)
    print("  text.apply", run.api("text.apply", "PAD 1186"), flush=True)
    shot(page, os.path.join(out, "after_replace_text.png"))

    for tab, name in (("scenes", "after_scenes.png"), ("color", "after_colors.png")):
        try:
            run.api("ui.select_tab", tab)
            time.sleep(6)
            shot(page, os.path.join(out, name))
        except Exception as e:                       # noqa: BLE001
            print("  %s: %s" % (tab, e), flush=True)

    # Write
    run.api("ui.select_tab", "write")
    time.sleep(3)
    run.answer([build])
    print("  build location", run.api("write.change_build_location"), flush=True)
    time.sleep(3)
    shot(page, os.path.join(out, "after_write_pending.png"))
    print("  write.primary", run.api("write.primary"), flush=True)
    run.wait_idle("build", timeout=7200, settle=5)
    shot(page, os.path.join(out, "after_write_done.png"))


def main():
    tree, out, mode = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
    os.makedirs(out, exist_ok=True)
    run = Run(tree, out)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.goto(run.url)
            page.wait_for_function("window.__padReady === true", timeout=60000)
            if mode == "rail":
                rail(run, page, sys.argv[4] if len(sys.argv) > 4 else "",
                     os.path.join(out, sys.argv[5] if len(sys.argv) > 5 else "rail.png"))
            else:
                e2e(run, page, sys.argv[4], sys.argv[5], sys.argv[6])
            browser.close()
    finally:
        run.close()
        print("server log:", os.path.join(run.scratch, "server.log"))


if __name__ == "__main__":
    main()
