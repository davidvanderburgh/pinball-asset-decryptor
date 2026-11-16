"""The Test card tab (PAD-1279, DragonRR's second round: "remove this feature from the
Multi-boot section and make it independent ... as simple as possible").

One list - the pictures, videos, scenes and sounds ticked TEST in the Images, Video,
Scenes and Audio tabs, and files added here from the PC - and one button that makes a
small TEST CARD from any Stern Spike 2 card image: it boots straight into a menu (DEFAULT
PAD TEST CARD, IMAGES, VIDEOS, SCENES, SOUNDS, Color correction), with no game.  The
default PAD test card patterns are always on it.  The list is testcard_core's; the build
is multiboot_core's testcard_commands, run here step by step.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types

from .base import TabService
from ..rpc import rpc, RpcError
from .. import compat
from .. import testcard_core as tc

KIND_ORDER = {k: n for n, k in enumerate(tc.KINDS)}
CARD_TYPES = [("Card images", "*.raw *.img"), ("All files", "*.*")]


class TestCardTab(TabService):
    ns = "testcard"
    key = "Test Card"
    label = "Test card"
    group = "Build"
    icon = "palette"

    def __init__(self, window):
        super().__init__(window)
        self._busy = False
        self._cancel = False
        self._proc = None
        self._lines = []
        self._pct = None
        self._step = ""
        self._msg = ("", "")

    # ------------------------------------------------------------ the page
    def on_show(self):
        self._pub()

    def _tc_list_changed(self):
        self._pub()

    def _pub(self):
        lst = tc.shared()
        rows = []
        for i, it in enumerate(lst.items):
            rows.append({"i": i, "kind": it.kind, "label": it.label,
                         "from": it.game or os.path.basename(it.project.rstrip("/\\")) if it.project else "",
                         "where": it.rel if it.project else it.path,
                         "problem": tc.item_problem(it)})
        rows.sort(key=lambda r: KIND_ORDER[r["kind"]])        # stable: each list in its own order
        self.set(rows=rows, counts=lst.counts(), source=lst.source,
                 source_ok=bool(lst.source) and os.path.isfile(lst.source), out=lst.out,
                 busy=self._busy, log=self._lines[-400:], pct=self._pct, step=self._step,
                 msg=list(self._msg), max=tc.MAX_ITEMS, full=len(lst.items) >= tc.MAX_ITEMS)

    def _say(self, line):
        self._lines.append(line)
        self._pub_soon()

    def _pub_soon(self, now=None):
        """Publish, at most four times a second while a build talks (the store is
        thread-safe; the log is resent whole)."""
        import time
        now = time.monotonic() if now is None else now
        if now - getattr(self, "_last_pub", 0.0) >= 0.25:
            self._last_pub = now
            self._pub()

    # ------------------------------------------------------------ the list
    def _changed(self):
        tc.changed(self.window)
        self._pub()
        return True

    @rpc
    def add_files(self):
        """Add files…: pictures, videos and sounds from the PC, as they are."""
        exts = " ".join("*" + e for e in sorted(set(tc.IMAGE_EXTS + tc.VIDEO_EXTS + tc.SOUND_EXTS)))
        paths = compat.filedialog.askopenfilenames(
            title="Pick pictures, videos and sounds for the test card",
            filetypes=[("Pictures, videos and sounds", exts), ("All files", "*.*")])
        if not paths:
            return False
        added, refused = tc.shared().add_files(list(paths))
        if refused:
            self._msg = ("warn", "Not added: " + "; ".join(
                "%s (%s)" % (os.path.basename(p), why) for p, why in refused[:4])
                + (" and %d more" % (len(refused) - 4) if len(refused) > 4 else ""))
        else:
            self._msg = ("", "")
        return self._changed() if added else (self._pub() or False)

    @rpc
    def remove(self, i):
        return tc.shared().remove(int(i)) and self._changed()

    @rpc
    def move(self, i, d):
        return tc.shared().move(int(i), int(d)) and self._changed()

    @rpc
    def rename(self, i, label):
        return tc.shared().rename(int(i), str(label or "")) and self._changed()

    @rpc
    def clear(self):
        tc.shared().clear()
        return self._changed()

    @rpc
    def pick_source(self):
        """Any Stern Spike 2 card image: the test card takes its boot and system from it."""
        lst = tc.shared()
        path = compat.filedialog.askopenfilename(
            title="Pick any Stern Spike 2 card image",
            initialdir=os.path.dirname(lst.source) if lst.source else None,
            filetypes=CARD_TYPES)
        if not path:
            return False
        lst.source = path
        lst.save()
        self._pub()
        return True

    # ------------------------------------------------------------ the build
    @rpc
    def build(self):
        """Build test card…"""
        if self._busy:
            return False
        lst = tc.shared()
        if not lst.source or not os.path.isfile(lst.source):
            raise RpcError("Pick a Stern Spike 2 card image first: the test card takes its boot and system from it")
        start = lst.out or os.path.join(os.path.dirname(lst.source), "pad_test_card.raw")
        out = compat.filedialog.asksaveasfilename(
            title="Save the test card as", initialdir=os.path.dirname(start) or None,
            initialfile=os.path.basename(start), defaultextension=".raw", filetypes=CARD_TYPES)
        if not out:
            return False
        if os.path.normcase(os.path.abspath(out)) == os.path.normcase(os.path.abspath(lst.source)):
            raise RpcError("That is the card image it is made from: save the test card under another name")
        lst.out = out
        lst.save()
        self._redraw_open_scenes(lst)
        items = lst.ordered()
        self._busy, self._cancel = True, False
        self._lines, self._pct, self._step = [], 0, "Getting the files ready"
        self._msg = ("", "")
        self._pub()
        threading.Thread(target=self._run, args=(lst.source, out, items), daemon=True,
                         name="testcard").start()
        return True

    @rpc
    def cancel(self):
        self._cancel = True
        proc = self._proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:                                   # noqa: BLE001
                pass
        return True

    def _redraw_open_scenes(self, lst):
        """A ticked scene of the open project is drawn again now, so the card has its edits
        as they are today (a scene of another project goes as it was when ticked)."""
        try:
            text = self.window.service("text")
            svc = getattr(text, "scenes", None)
        except Exception:                                       # noqa: BLE001
            svc = None
        if svc is None or not getattr(svc, "assets_dir", ""):
            return
        here = tc.norm_dir(svc.assets_dir)
        for it in lst.items:
            if it.kind == "scene" and tc.norm_dir(it.project) == here:
                try:
                    if not getattr(svc, "_scenes", None):
                        svc.reload()
                    it.path = svc.render_resting_frame(it.rel, it.path or tc.scene_png_path(it.project, it.rel))
                except Exception as exc:                        # noqa: BLE001
                    self._lines.append("test card: scene %r could not be drawn again (%s): its picture "
                                       "from when it was ticked goes" % (it.label, exc))
        lst.save()

    def _run(self, source, out, items):
        from .. import multiboot_core as mbc
        work = tempfile.mkdtemp(prefix="pad_testcard_")
        ok, why = False, ""
        try:
            staged = tc.stage(items, os.path.join(work, "files"), None, log=self._say,
                              cancel=lambda: self._cancel)
            if self._cancel:
                why = "canceled"
                return
            self._say("test card: %d of %d item%s, and the default PAD test card"
                      % (len(staged), len(items), "" if len(items) == 1 else "s"))
            form = types.SimpleNamespace(images=[types.SimpleNamespace(path=source)], volume=50,
                                         selector_dir=os.environ.get("PAD_MULTIBOOT_SELECTOR") or mbc.DEFAULT_SELECTOR_DIR,
                                         tests=[],
                                         platform="stern", colour_profiles={})
            media = os.path.join(work, "media")
            cmds = mbc.testcard_commands(form, out, media, test_specs=tc.test_specs(staged, mbc.wsl))
            ok, why = self._steps(mbc, cmds)
        except Exception as exc:                                # noqa: BLE001
            why = str(exc)
        finally:
            shutil.rmtree(work, ignore_errors=True)
            self._finish(ok, why, out)

    STEP_WORDS = {"selector": "Getting the menu program ready", "prepare": "Converting the files",
                  "testcard": "Writing the card"}

    def _steps(self, mbc, cmds):
        texts = {}
        n = len(cmds)
        for k, (label, argv) in enumerate(cmds):
            if self._cancel:
                return False, "canceled"
            self._step = self.STEP_WORDS.get(label, label)
            self._pct = int(100 * k / n)
            self._pub_soon()
            if callable(argv):
                argv = argv(texts)
            root_line = argv if isinstance(argv, mbc._root.RootLine) else None
            argv = mbc.runtime.rehead(argv)
            if mbc._mac.enabled() and len(argv) >= 2 and argv[1] == "exec":
                if not mbc._mac.ensure_ready_container((), mbc.rig_repo_dir(), log=self._say):
                    return False, mbc.container_note("No such container")
            self._say("$ " + argv[-1])
            if root_line is not None:
                proc = mbc._root.start(root_line, preview=False)
            else:
                proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        creationflags=mbc._rig.CREATE_FLAGS)
            self._proc = proc
            lines = []
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip()
                tick = mbc.parse_progress(line)
                if tick is not None:
                    continue
                lines.append(line)
                self._say(line)
            rc = proc.wait()
            self._proc = None
            texts[label] = "\n".join(lines)
            if self._cancel:
                return False, "canceled"
            if rc != 0:
                last = next((l for l in reversed(lines) if l.strip()), "")
                return False, "%s stopped (exit %d)%s" % (self._step.lower(), rc,
                                                          (": " + last) if last else "")
        return True, ""

    def _finish(self, ok, why, out):
        self._busy, self._proc, self._pct, self._step = False, None, (100 if ok else None), ""
        self._last_pub = 0.0
        if ok:
            size = os.path.getsize(out) / float(1 << 30) if os.path.exists(out) else 0
            self._msg = ("ok", "Test card built: %s (%.2f GB). Write it to a card like any card image; "
                               "it boots any Stern Spike 2 machine into the TEST CARD menu." % (out, size))
        elif why == "canceled":
            self._msg = ("warn", "Test card canceled. %s is unfinished." % os.path.basename(out))
        else:
            self._msg = ("bad", "The test card was not built: %s" % why)
        self._pub_soon()


TAB = TestCardTab
