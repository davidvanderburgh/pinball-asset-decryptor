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
                 msg=list(self._msg), max=tc.MAX_ITEMS, full=len(lst.items) >= tc.MAX_ITEMS,
                 network=dict(lst.network), room_mib=tc.room_mib(lst.network), address=self._address())

    # ------------------------------------------------------------ network updates
    # Simon (2026-11-22): "we need the same feature on the test card... even more important" - a test card
    # updated over the network, like a game card (Network tab: remote access, Wi-Fi start-up, Send to machine)
    def _address(self):
        """The machine's address, as the Network tab has it (else the last one used), or ''."""
        try:
            addr = self.window.service("network").get("address")
            if addr:
                return str(addr)
        except Exception:                                       # noqa: BLE001
            pass
        try:
            from ...core import pad_ssh_key
            return pad_ssh_key.last_address() or ""
        except Exception:                                       # noqa: BLE001
            return ""

    @rpc
    def set_network(self, key, value):
        """One of the tab's network settings: room / room_gb / ssh / wifi / band5."""
        lst = tc.shared()
        if key not in tc.NETWORK_DEFAULTS:
            raise RpcError("no such setting: %s" % key)
        net = dict(lst.network)
        net[key] = value
        if key == "wifi" and not value:
            net["band5"] = False
        lst.network = tc.clean_network(net)
        lst.save()
        self._pub()
        return True

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
    def send(self):
        """Send to machine…: build the test card, then send it to the machine over the network (the Network
        tab's machine): only the files that differ go, and the machine restarts into its test card menu."""
        if self._busy:
            return False
        lst = tc.shared()
        address = self._address()
        if not lst.network.get("ssh"):
            raise RpcError("Tick Remote access first: the test card you send must let this computer in again")
        if not address:
            raise RpcError("Find the machine on the Network tab first: the test card goes to the machine there")
        if self.window.cb.get("on_send_image") is None:
            raise RpcError("Send to machine is not available here")
        if not compat.messagebox.askyesno(
                "Send test card to machine",
                "Build the test card and send it to the machine at %s?\n\nThe machine must be running a PAD "
                "test card already (a game card is refused: its game would be deleted). Only the files that "
                "differ are copied, then the machine restarts into the test card menu; leave it switched on "
                "until then." % address, icon="warning"):
            return False
        return self.build(send_to=address)

    @rpc
    def build(self, send_to=""):
        """Build test card… (and, from Send to machine…, send it to *send_to* once built)"""
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
        self._send_to = str(send_to or "")
        threading.Thread(target=self._run, args=(lst.source, out, items, dict(lst.network)), daemon=True,
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

    def _run(self, source, out, items, net=None):
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
            cmds = mbc.testcard_commands(form, out, media, test_specs=tc.test_specs(staged, mbc.wsl),
                                         p3_mib=tc.room_mib(net))
            ok, why = self._steps(mbc, cmds)
            if ok and not self._cancel:
                ok, why = self._extras(source, out, tc.clean_network(net))
        except Exception as exc:                                # noqa: BLE001
            why = str(exc)
        finally:
            shutil.rmtree(work, ignore_errors=True)
            self._finish(ok, why, out)

    def _extras(self, source, out, net):
        """Remote access and Wi-Fi start-up onto the built card, as a game card gets them (pipeline.py): a
        marker beside the image says it is unfinished until both are on."""
        if not net["ssh"] and not net["wifi"]:
            return True, ""
        from ...core import card_extras, ssh_card, wifi_card
        marker = str(ssh_card.pending_marker(out))
        step = "Remote access"
        try:
            with open(marker, "w", encoding="utf-8") as f:
                f.write("Incomplete SSH preparation; do not flash this image.\n")
            if net["ssh"]:
                self._step = "Adding remote access"
                self._pub_soon()
                note = ssh_card.apply_to_build(
                    source, out, {"enabled": True,
                                  "public_keys": card_extras.validate_keys(card_extras.with_pad_key(""))},
                    log=self._say, cancel=lambda: self._cancel)
                if note:
                    self._say("test card: " + note)
            if net["wifi"]:
                step = "Wi-Fi start-up"
                self._step = "Adding Wi-Fi start-up"
                self._pub_soon()
                note = wifi_card.apply_to_build(source, out, {"enabled": True, "band5": bool(net["band5"])},
                                                log=self._say, cancel=lambda: self._cancel)
                if note:
                    self._say("test card: " + note)
        except Exception as exc:                                # noqa: BLE001
            return False, "%s could not be added: %s" % (step.lower(), exc)
        os.remove(marker)
        return True, ""

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
        send_to, self._send_to = getattr(self, "_send_to", ""), ""
        if ok and send_to:
            # the app's own Send (the Network tab's): its progress, log and finish are the app's
            self._msg = ("ok", "Test card built: %s. Sending it to the machine at %s: the status bar and the "
                               "log follow it, and the machine restarts into the test card menu when it is done."
                         % (out, send_to))
            self._pub_soon()
            fn = self.window.cb.get("on_send_image")
            if fn is not None:
                fn(out, send_to)
            return
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
