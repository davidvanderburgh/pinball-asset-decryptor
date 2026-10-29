"""Visual Pinball tab: the Spike 2 emulator plays a Visual Pinball table.

A PREVIEW FEATURE (core/preview.py, ``vpx``): the rail shows the tab only
with a preview code for it, on Windows, for a manufacturer the Spike 2
emulator runs (PAD-802).  It is the Visual Pinball kit (tools/spike2_emu/vpx,
docs/plans/vpx_bridge.md) with buttons, in place of the separate setup
window and beta installer it used to need:

* the controller (``PAD.Controller``) registered, Visual Pinball found,
  chosen or downloaded, the PAD runtime (installed from its own row);
* the folder of card images, and which card each title boots;
* the tables the kit knows: which download each one is (PAD SHIPS NO
  TABLE: the person downloads the tribute from its author), and a Patch
  button that writes the "(PAD)" copy into Visual Pinball's tables folder;
* where the playfield and the LCD window go, and Play.

THIN: every step is the kit's own code, run with the app's Windows Python
(``vpxsetup.py`` for the state and settings, ``padvpx.py`` for patch and
register), and one JSON object comes back from its last line.  The kit's
pywin32, its DPI awareness and its module names stay out of the app.
"""

import json
import os
import subprocess
import sys
import threading

from .. import emulate_core
from .base import TabService, rpc

PREVIEW_FEATURE = "vpx"

INTRO = ("Play a Visual Pinball table with the real Stern game behind it: the "
         "game from your own card image serves the balls, fires the coils, lights "
         "the table, keeps score and shows its own screen.\n"
         "Download a table the app knows from its author, patch it here, then open "
         "it with Play.")

TABLES_TIP = ("The app ships no tables. Download a table below from its author, "
              "then Patch it: the app writes a copy named \"(PAD)\" into Visual "
              "Pinball's tables folder and leaves your download as it is.")

CARDS_TIP = ("The folder with your SD card images (the normal .raw files, named "
             "like rush_le-1_19_0.Release.16G.sdcard.raw). A title plays its "
             "newest build in this folder.")

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_RUN_TIMEOUT_S = 120


def kit_dir():
    return os.path.join(emulate_core.rig_dir(), "vpx")


def kit_python():
    return emulate_core.windows_python(console=True)


def last_json(text):
    """The last line of *text* that is a JSON object, or None."""
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


class VpxTab(TabService):
    ns = "vpx"
    key = "Visual Pinball"
    label = "Visual Pinball"
    group = "Play"
    icon = "playfield"

    def __init__(self, window):
        super().__init__(window)
        self._lock = threading.Lock()
        self._busy = False
        ok = sys.platform == "win32"
        missing = not os.path.isfile(os.path.join(kit_dir(), "vpxsetup.py"))
        note = ("Visual Pinball runs on Windows only." if not ok else
                "The Visual Pinball kit is missing from tools/spike2_emu/vpx; "
                "this install looks incomplete." if missing else "")
        self.set(intro=INTRO, tables_tip=TABLES_TIP, cards_tip=CARDS_TIP,
                 ok=ok and not missing, note=note, loaded=False, busy="",
                 progress=None, registered=False, vpx="", tables_dir="",
                 library="", cards={}, tables=[], patched=[], presets=[],
                 layout="", monitors=0, runtime_state="unknown",
                 runtime_text="Checking…", message="", message_level="info")

    # -- hooks ---------------------------------------------------------------
    def on_show(self):
        if self.get("ok") and not self._busy:
            self.refresh()

    # -- the kit, out of process --------------------------------------------
    def _kit(self, script, args, timeout=_RUN_TIMEOUT_S, on_line=None):
        """Run the kit's *script* with *args*; the JSON its last line holds
        (``{"error": ...}`` when there is none)."""
        exe = kit_python()
        if not exe:
            return {"error": "No Windows Python was found to run the Visual Pinball kit with."}
        cmd = [exe, os.path.join(kit_dir(), script)] + [str(a) for a in args]
        try:
            if on_line is None:
                r = subprocess.run(cmd, capture_output=True, timeout=timeout,
                                   cwd=kit_dir(), creationflags=_CREATE_NO_WINDOW)
                text = r.stdout.decode("utf-8", "replace")
                err = r.stderr.decode("utf-8", "replace")
                code = r.returncode
            else:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     cwd=kit_dir(), creationflags=_CREATE_NO_WINDOW)
                lines = []
                for raw in p.stdout:
                    line = raw.decode("utf-8", "replace").rstrip()
                    lines.append(line)
                    on_line(line)
                code = p.wait(timeout=timeout)
                text, err = "\n".join(lines), ""
        except Exception as exc:                            # noqa: BLE001
            return {"error": "The Visual Pinball kit did not run: %s" % exc}
        got = last_json(text)
        if got is None:
            tail = (err or text).strip().splitlines()[-3:]
            got = {"error": "The Visual Pinball kit failed (exit %s): %s"
                   % (code, " ".join(tail) or "no output")}
        got["_text"] = text
        return got

    def _start(self, what, work):
        """Run *work* on a thread with the page saying *what*; one at a time."""
        with self._lock:
            if self._busy:
                return False
            self._busy = True
        self.set(busy=what, progress=None)

        def run():
            try:
                work()
            except Exception as exc:                        # noqa: BLE001
                self._say("%s failed: %s" % (what, exc), "error")
            try:
                # busy until the page holds what the job changed
                self._load()
            finally:
                with self._lock:
                    self._busy = False
        threading.Thread(target=run, daemon=True, name="pad-vpx").start()
        return True

    def _say(self, text, level="info"):
        self.set(message=text, message_level=level)
        try:
            self.ctx.loop.post(self.window.append_log, "Visual Pinball: " + text, level)
        except Exception:                                   # noqa: BLE001
            pass

    def _load(self):
        """Read the kit's state and the runtime's onto the page (any thread)."""
        st = self._kit("vpxsetup.py", ["state"])
        try:
            from ...core import runtime
            rt_state, rt_text = runtime.status(refresh=True)
        except Exception as exc:                            # noqa: BLE001
            rt_state, rt_text = "unknown", str(exc)
        if "error" in st:
            self.set(loaded=True, busy="", runtime_state=rt_state, runtime_text=rt_text,
                     message=st["error"], message_level="error")
            return
        st.pop("_text", None)
        self.set(loaded=True, busy="", runtime_state=rt_state, runtime_text=rt_text, **st)

    # -- the page's buttons -------------------------------------------------
    @rpc
    def refresh(self):
        return self._start("Checking", lambda: None)

    @rpc
    def install_runtime(self):
        """Install (or update) the PAD runtime from its own row (PAD-840).

        The row used to say "Set it up on the Emulate tab", and that tab offers
        the install only when its Linux is out of date or logs in as root: on a
        PC with a working Ubuntu it says nothing, and "Install Missing" installs
        WSL and Ubuntu, never this.  So the row was red with no way to clear it.
        The same ladder as every Emulate tab (core/runtime_prompt.ensure), with
        its consent before a replace."""
        from ...core import runtime
        from .. import runtime_prompt

        def progress(done, total):
            if total:
                self.set(progress=done / total)

        def ask():
            return bool(self.ctx.loop.call(runtime_prompt.ask_before_replacing))

        def work():
            state = runtime_prompt.ensure(
                say=self._say, progress=progress, ask=ask,
                on_blocked=lambda exc: self._say(
                    "the download did not go through: %s" % exc, "error"))
            runtime.invalidate()
            self.set(progress=None)
            if state == "ready":
                self._say("the emulator's Linux is installed.")
        return self._start("Installing the emulator's Linux", work)

    @rpc
    def register(self):
        """PAD.Controller in the registry: the installer does this, and this
        is the repair.  HKLM, so elevated (no prompt when the app already is)."""
        exe = kit_python()
        script = os.path.join(kit_dir(), "padvpx.py")

        def work():
            ps = ("Start-Process -FilePath '%s' -ArgumentList '\"%s\" register' "
                  "-Verb RunAs -Wait -WindowStyle Hidden"
                  % (exe.replace("'", "''"), script.replace("'", "''")))
            subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=300, creationflags=_CREATE_NO_WINDOW)
            st = self._kit("vpxsetup.py", ["state"])
            if st.get("registered"):
                self._say("the controller is registered.")
            else:
                self._say("the controller is still not registered (was the "
                          "administrator prompt declined?).", "warning")
        return self._start("Registering the controller", work)

    @rpc
    def choose_vpx(self):
        folder = self.window.ask_folder("vpx_folder", "The folder Visual Pinball is in "
                                        "(the one with VPinballX64.exe)")
        if not folder:
            return False

        def work():
            got = self._kit("vpxsetup.py", ["vpx", os.path.normpath(folder)])
            res = got.get("result") or got.get("error")
            if res == "ok":
                self._say("Visual Pinball is in %s." % os.path.normpath(folder))
            else:
                self._say(res, "warning")
        return self._start("Checking the folder", work)

    @rpc
    def download_vpx(self):
        folder = self.window.ask_folder("vpx_folder", "Where to put Visual Pinball "
                                        "(an empty folder, for example C:\\Visual Pinball)")
        if not folder:
            return False
        folder = os.path.normpath(folder)

        def line(text):
            if text.startswith("progress "):
                try:
                    self.set(progress=float(text.split()[1]))
                except ValueError:
                    pass
            elif text.startswith("say "):
                self._say(text[4:])

        def work():
            got = self._kit("vpxsetup.py", ["download", folder], timeout=1800, on_line=line)
            res = got.get("result") or got.get("error")
            if res == "ok":
                self._say("Visual Pinball 10.8.0 is in %s." % folder)
            else:
                self._say(res, "error")
        return self._start("Downloading Visual Pinball", work)

    @rpc
    def choose_library(self):
        folder = self.window.ask_folder("vpx_library", "The folder with your SD card images",
                                        initialdir=self.get("library") or None)
        if not folder:
            return False
        folder = os.path.normpath(folder)

        def work():
            got = self._kit("vpxsetup.py", ["library", folder])
            if "error" in got:
                self._say(got["error"], "error")
                return
            n = len(got.get("cards") or {})
            self._say("card folder %s: %s." % (folder, "%d title%s" % (n, "" if n == 1 else "s")
                                                 if n else "no card images found in it"))
        return self._start("Reading the card folder", work)

    @rpc
    def patch(self):
        """The person's own download of a table the kit knows: recognised by
        its script and written as the "(PAD)" copy into Visual Pinball's
        tables folder (beside the download while Visual Pinball is not set up)."""
        path = self.window.ask_open("vpx_table", "Choose the Visual Pinball table you downloaded",
                                    [("Visual Pinball table", "*.vpx"), ("All files", "*.*")])
        if not path:
            return False
        path = os.path.normpath(path)
        out = self.get("tables_dir") or os.path.dirname(path)

        def work():
            self._say("patching %s ..." % os.path.basename(path))
            got = self._kit("padvpx.py", ["patch", path, "--out", out], timeout=600)
            text = got.get("_text") or ""
            for ln in text.splitlines():
                if ln.strip():
                    self._say(ln.strip())
            if "this table is not one the kit knows" in text:
                self._say("That table is not one the app can patch. It knows the tables "
                          "listed on this page.", "warning")
            elif "open \"" not in text:
                self._say("The patch did not finish; the session log has what it said.", "error")
        return self._start("Patching the table", work)

    @rpc
    def layout(self, key):
        preset = next((p for p in self.get("presets") or [] if p.get("key") == key), None)
        if preset is None:
            return False

        def work():
            got = self._kit("vpxsetup.py", ["layout", key, json.dumps(preset.get("player")),
                                            json.dumps(preset.get("lcd"))])
            if "error" in got:
                self._say(got["error"], "error")
            else:
                self._say("window layout: %s." % preset.get("words", key))
        return self._start("Saving the layout", work)

    @rpc
    def play(self, name):
        if not name:
            return False

        def work():
            got = self._kit("vpxsetup.py", ["open", name])
            res = got.get("result") or got.get("error")
            if res == "ok":
                self._say("opening %s. The game starts by itself, within a minute." % name)
            else:
                self._say(res, "error")
        return self._start("Opening the table", work)


TAB = VpxTab
