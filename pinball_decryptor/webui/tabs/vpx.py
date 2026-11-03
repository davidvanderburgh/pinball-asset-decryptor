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

PAD-942: each patched table's row carries a small picture of it, the large
one on hover.  PAD SHIPS NO PICTURE, as it ships no table: the kit's
``vpxpicture.py`` reads the playfield picture out of the person's own (PAD)
copy, once, into the app's cache (``pictures_dir()``, a JPEG per table and a
sidecar keyed by the file's size and time), on a thread of its own after
the page is up so nothing waits for it; the page serves them as ``/media``.
"""

import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time

from .. import compat, emulate_core
from .base import TabService, rpc

PREVIEW_FEATURE = "vpx"

INTRO = ("Play a Visual Pinball table with the real game behind it: the "
         "game from your own card image serves the balls, fires the coils, lights "
         "the table, keeps score and shows its own screen.")

#: PAD-943 (David: "add the Visual Pinball tab to the other manufacturers
#: we are adding support for"): the tab is on every manufacturer the app
#: emulates and shows that machine's tables. Stern's eras are platforms of
#: their own; every other manufacturer's key is its platform in the kit's
#: catalogue (catalog.json). The platforms the app's emulator plays a table
#: on (a map and a bridge) are BRIDGED; the rest list their tables and say
#: they play as their authors wrote them. PAD-952: Spooky's Halloween and
#: Ultraman play behind marty02's Halloween table (spkbridge.py).
BRIDGED = ("spike2", "spike1", "spooky")
STERN_ERAS = ("spike2", "spike1")


def platform_of_manufacturer(mfr):
    key = getattr(mfr, "key", "") or ""
    if key == "stern":
        era = getattr(mfr, "current_era", "") or "spike2"
        return era if era in STERN_ERAS else ""
    return key


#: PAD-943: the other platforms' tables, where their authors put them
CATALOG_TIP = ("Every modern platform the app reads, and the Visual Pinball tables of its games: "
               "where each one is downloaded, who made it, and what plays behind it. A Spike 1 "
               "table plays on the app's emulator once the app has a map for it, like Spike 2's; "
               "the rest play as their authors wrote them. Stern SAM is not here: Visual PinMAME "
               "runs those games already.")
TABLES_TIP = ("The app ships no tables. Download a table below from its author, "
              "then Patch it: the app writes a copy named \"(PAD)\" into your tables "
              "folder and leaves your download as it is.")

CARDS_TIP = ("The folder with your SD card images (the normal .raw files, named "
             "like rush_le-1_19_0.Release.16G.sdcard.raw). A title plays its "
             "newest build in this folder.")

# PAD-941: the card for whoever builds or finishes a table
# (PAD-952: not "a Stern game" - the card is on the Spooky tab too)
AUTHORS_INTRO = ("Building a table of one of these games, or finishing one? The game sees the table only "
                 "through its own switches, coils and lights. The checklist lists every one the game "
                 "has, with its number and what a table does for it; checked against a table it "
                 "marks what that table still lacks.")
AUTHORS_TITLES_TIP = ("The titles whose game has run on this PC: the checklist is read from the "
                      "game's own tables, which the emulator writes on a title's first run. Play a "
                      "title once (here, or on the Emulate tab) and it appears.")

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_RUN_TIMEOUT_S = 120

# PAD-942: the pictures. The reader's version is in the cache key, so a
# better reader (one that reads a BITS playfield, say) remakes them all
# (2: the backglass fallback for a baked playfield)
PICTURE_VERSION = 2
PICTURES_TIP = ("The table's own playfield picture, read from your (PAD) copy once it is patched "
                "(the app ships no picture of any table). Hover over it for the large one.")


def kit_dir():
    return os.path.join(emulate_core.rig_dir(), "vpx")


def pictures_dir():
    """Where the tables' pictures are kept: machine-local, under LOCALAPPDATA
    like the app's other caches (they are remade from the tables)."""
    override = os.environ.get("PAD_VPX_PICTURES")
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "pinball_decryptor", "vpx_pictures")


def picture_key(path):
    """The cache name for the table at *path*: its path, size and time, so a
    re-patched copy (a new file) gets a new picture; None when it is not there."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    words = "%d|%s|%d|%d" % (PICTURE_VERSION, os.path.normcase(os.path.abspath(path)),
                             st.st_size, st.st_mtime_ns)
    return hashlib.sha1(words.encode("utf-8")).hexdigest()[:20]


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
        self._want_coverage = False       # Check again forces the Coverage column's read
        self._pictures_lock = threading.Lock()
        self._pictures_running = False
        ok = sys.platform == "win32"
        missing = not os.path.isfile(os.path.join(kit_dir(), "vpxsetup.py"))
        note = ("Visual Pinball runs on Windows only." if not ok else
                "The Visual Pinball kit is missing from tools/spike2_emu/vpx; "
                "this install looks incomplete." if missing else "")
        self.set(intro=INTRO, tables_tip=TABLES_TIP, cards_tip=CARDS_TIP,
                 ok=ok and not missing, note=note, loaded=False, busy="",
                 progress=None, registered=False, vpx="", tables_dir="",
                 library="", cards={}, tables=[], patched=[], presets=[],
                 layout="", monitors=0, display=None, runtime_state="unknown",
                 runtime_text="Checking…", message="", message_level="info",
                 authors_intro=AUTHORS_INTRO, authors_titles_tip=AUTHORS_TITLES_TIP,
                 author_titles=[], author_platforms={}, author_title="", author_note="", coverage={},
                 sheet=None, platform="", bridged=True,
                 catalog_tip=CATALOG_TIP, catalog={"platforms": {}, "tables": []},
                 pictures={}, pictures_busy="", pictures_tip=PICTURES_TIP,
                 # PAD-943: the page is up the moment the kit's state is in (or
                 # the last one seen, from the cache); these say what is still coming
                 authors_busy=False, coverage_busy=False, stale=False, downloads=[])
        self._extras_running = False
        self._extras_gen = 0
        # PAD-943: the tables folder is watched while the tab is up, so a
        # download dropped in shows without Check again
        self._watching = False
        self._folder_sig = None

    # -- hooks ---------------------------------------------------------------
    def on_manufacturer(self, mfr):
        """The machine this tab is for (PAD-943): its platform's tables,
        catalogue block and author titles; the rest of the kit's state is
        the same on every manufacturer."""
        platform = platform_of_manufacturer(mfr)
        self.set(platform=platform, bridged=not platform or platform in BRIDGED)
        self._pick_author_title()

    def _pick_author_title(self):
        """The authors' card's game: one of this platform's, the current pick
        when it is one, else the title of the first table whose card is
        here, else the first."""
        platform = self.get("platform") or ""
        plats = self.get("author_platforms") or {}
        titles = [t for t in self.get("author_titles") or []
                  if not platform or plats.get(t, "spike2") == platform]
        chosen = self.get("author_title") or ""
        if chosen not in titles:
            cards = set(self.get("cards") or {})
            chosen = next((t.get("title") for t in self.get("tables") or []
                           if t.get("title") in titles and set(t.get("titles") or []) & cards), None) \
                or (titles[0] if titles else "")
        self.set(author_title=chosen)

    def on_show(self):
        if self.get("ok") and not self._busy:
            self._check()
        self._watch_folder()

    def _check(self):
        """Read everything again; the Coverage column from its cache when
        nothing it was read from has changed (Check again reads it anyway)."""
        return self._start("Checking", lambda: None)

    # -- the tables folder, watched (PAD-943) --------------------------------
    WATCH_S = 3.0

    def _folder_signature(self):
        d = self.get("tables_dir") or ""
        if not d:
            return None
        try:
            names = os.listdir(d)
        except OSError:
            return None
        sig = []
        for n in names:
            path = os.path.join(d, n)
            # PAD-952: the downloads in the folders in it too (originals)
            subs = []
            if os.path.isdir(path):
                try:
                    subs = [os.path.join(n, m) for m in os.listdir(path) if m.lower().endswith(".vpx")]
                except OSError:
                    subs = []
            for rel in subs or ([n] if n.lower().endswith(".vpx") else []):
                try:
                    st = os.stat(os.path.join(d, rel))
                    sig.append((rel, st.st_size, int(st.st_mtime)))
                except OSError:
                    continue
        return tuple(sorted(sig))

    def _watch_folder(self):
        """A thread that looks at the tables folder every WATCH_S seconds
        and re-reads the kit's state when a table came, went or changed
        (David: a download dropped in the folder must show by itself)."""
        if self._watching or not self.get("ok"):
            return
        self._watching = True

        def run():
            while self._watching:
                time.sleep(self.WATCH_S)
                try:
                    sig = self._folder_signature()
                except Exception:                           # noqa: BLE001
                    continue
                if sig is None:
                    continue
                if self._folder_sig is not None and sig != self._folder_sig and not self._busy:
                    self._folder_sig = sig
                    self._start("Checking", lambda: None)
                elif self._folder_sig is None or not self._busy:
                    self._folder_sig = sig
        threading.Thread(target=run, daemon=True, name="pad-vpx-watch").start()

    def on_close(self):
        self._watching = False

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
        """Read the kit's state and the runtime's onto the page (any thread).

        PAD-943 (David: the tables took ten seconds to show; they must be
        instant, the rest lazy): the page is up as soon as the kit's state is
        in (half a second), and before that from the LAST state seen on this
        PC (the cache), so a second opening draws at once; the authors'
        titles (~2 s, asks WSL) and the Coverage column (~7 s) come in on a
        thread of their own with the page usable, each card saying it is
        still looking; the pictures as PAD-942 had them."""
        if not self.get("loaded"):
            # the Coverage column as it was last read on this PC (~7 s over
            # WSL otherwise): kept until a map, the kit or the titles change
            cov = self._cached_coverage()
            if cov and not self.get("coverage"):
                self.set(coverage=cov["coverage"])
            cached = self._cached_state()
            if cached:
                pictures, _todo = self._pictures_known(self._picture_files(cached))
                self.set(loaded=True, stale=True, authors_busy=True, coverage_busy=not self.get("coverage"),
                         pictures=pictures, **cached)
        st = self._kit("vpxsetup.py", ["state"])
        try:
            from ...core import runtime
            rt_state, rt_text = runtime.status(refresh=True)
        except Exception as exc:                            # noqa: BLE001
            rt_state, rt_text = "unknown", str(exc)
        if "error" in st:
            self.set(loaded=True, busy="", stale=False, runtime_state=rt_state, runtime_text=rt_text,
                     message=st["error"], message_level="error")
            return
        st.pop("_text", None)
        self._save_state(st)
        # PAD-942: the pictures already in the cache go up with the page; the
        # rest are read on their own thread, the page usable meanwhile
        pictures, todo = self._pictures_known(self._picture_files(st))
        want_cov = self._want_coverage or not self.get("coverage")
        self.set(loaded=True, busy="", stale=False, runtime_state=rt_state, runtime_text=rt_text,
                 pictures=pictures, authors_busy=True, coverage_busy=want_cov, **st)
        self._start_extras(st, want_cov)
        if todo:
            self._read_pictures(todo)

    # -- the slow parts, after the page is up (PAD-943) ---------------------
    @staticmethod
    def _state_cache_path():
        """The last kit state seen on this PC, beside the pictures' cache."""
        return os.path.join(os.path.dirname(pictures_dir().rstrip("\\/")), "vpx_state.json")

    def _cached_state(self):
        try:
            with open(self._state_cache_path(), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) and "tables" in d else None
        except (OSError, ValueError):
            return None

    def _save_state(self, st):
        self._write_cache(self._state_cache_path(), st)

    @staticmethod
    def _write_cache(path, d):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(d, f)
            os.replace(path + ".tmp", path)
        except (OSError, TypeError, ValueError):
            pass

    # -- the Coverage column, kept between sittings (PAD-943) ---------------
    @classmethod
    def _coverage_cache_path(cls):
        return os.path.join(os.path.dirname(cls._state_cache_path()), "vpx_coverage.json")

    @staticmethod
    def _coverage_key(titles):
        """What the column was read from: the kit's maps and the reader
        (their times), and the titles with tables on this PC. A map edited, the
        app updated (new owed rules) or a title played for the first time
        reads it again; nothing else does."""
        kit = kit_dir()
        parts = []
        for f in sorted(glob.glob(os.path.join(kit, "*.shadow.json"))) + [os.path.join(kit, "vpxauthor.py")]:
            try:
                parts.append("%s:%d" % (os.path.basename(f), int(os.path.getmtime(f))))
            except OSError:
                parts.append(os.path.basename(f))
        return ";".join(parts) + "|" + ",".join(sorted(titles or []))

    def _cached_coverage(self):
        """{key, coverage} as last written, or None."""
        try:
            with open(self._coverage_cache_path(), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) and isinstance(d.get("coverage"), dict) and d.get("key") else None
        except (OSError, ValueError):
            return None

    def _start_extras(self, st, want_cov):
        """The authors' titles, then the coverage, on their own thread: the
        newest load wins (a job's reload while one is still looking starts
        another; the older one's answers are dropped)."""
        with self._lock:
            self._extras_gen += 1
            gen = self._extras_gen
            self._extras_running = True
        threading.Thread(target=self._load_extras, args=(st, want_cov, gen),
                         daemon=True, name="pad-vpx-extras").start()

    def _load_extras(self, st, want_cov, gen):
        def mine():
            return gen == self._extras_gen
        try:
            # PAD-941: the titles a checklist can be made for (their device
            # tables, or a Spike 1 game, on this PC): asks WSL
            got = self._kit("vpxauthor.py", ["titles"])
            titles_ok = "error" not in got
            titles = sorted(got.get("titles") or []) if titles_ok else []
            if mine():
                self.set(author_titles=titles, author_platforms=got.get("platforms") or {} if titles_ok else {},
                         authors_busy=False)
                self._pick_author_title()
            # PAD-943: the downloads not read yet (which map fits, which
            # catalogue table the name is), ~0.3 s a file, once per file
            if any(not d.get("read") for d in st.get("downloads") or []):
                got = self._kit("vpxsetup.py", ["downloads"], timeout=600)
                if "error" not in got and mine():
                    self.set(downloads=got.get("downloads") or [], tables=got.get("tables") or self.get("tables"))
            # how much each table's map wires of its game (the Coverage column):
            # read from the same tables, ~7 s over WSL's share for 20 titles, so
            # kept on this PC between sittings (David: "can't we cache it?"),
            # read again when a map, the kit or the titles change, and on
            # Check again; never after a job
            key = self._coverage_key(titles)
            cached = self._cached_coverage()
            if not want_cov and cached and cached["key"] == key and titles_ok:
                if mine():
                    self.set(coverage=cached["coverage"], coverage_busy=False)
            else:
                if mine():
                    self.set(coverage_busy=True)
                got = self._kit("vpxauthor.py", ["coverage"], timeout=300)
                fresh = "error" not in got and isinstance(got.get("coverage"), dict)
                coverage = got["coverage"] if fresh else (self.get("coverage") or {})
                self._want_coverage = False
                if fresh and titles_ok:
                    self._write_cache(self._coverage_cache_path(), {"key": key, "coverage": coverage})
                if mine():
                    self.set(coverage=coverage, coverage_busy=False)
        finally:
            with self._lock:
                if mine():
                    self._extras_running = False

    # -- the tables' pictures (PAD-942) -------------------------------------
    @staticmethod
    def _picture_files(st):
        """{row output name: the table file its picture is read from}: the
        (PAD) copy of every patched row, known to the kit or not (the page
        lists any other (PAD) table in the folder as a row of its own)."""
        tables_dir = st.get("tables_dir") or ""
        if not tables_dir:
            return {}
        files = {}
        for t in st.get("tables") or []:
            if t.get("patched") and t.get("output"):
                files[t["output"]] = os.path.join(tables_dir, t["output"])
        for name in st.get("patched") or []:
            files.setdefault(name, os.path.join(tables_dir, name))
        return files

    def _pictures_known(self, files):
        """What the cache holds for *files* ({output: record}) and what it
        lacks ({output: (file, key)}); sidecars and pictures of tables no
        longer here are dropped."""
        d = pictures_dir()
        known, todo, keep = {}, {}, set()
        for output, path in files.items():
            key = picture_key(path)
            if not key:
                continue
            rec = None
            try:
                with open(os.path.join(d, key + ".json"), encoding="utf-8") as f:
                    rec = json.load(f)
            except (OSError, ValueError):
                rec = None
            if isinstance(rec, dict) and (rec.get("error") or
                                          (rec.get("file") and os.path.isfile(rec["file"]))):
                known[output] = rec
                keep.add(key + ".json")
                if rec.get("file"):
                    keep.add(os.path.basename(rec["file"]))
            else:
                todo[output] = (path, key)
        # (not while a read is writing there: its files are not in keep yet)
        with self._pictures_lock:
            prune = not self._pictures_running
        if prune:
            try:
                for name in os.listdir(d):
                    if name not in keep and name.endswith((".json", ".jpg")):
                        os.remove(os.path.join(d, name))
            except OSError:
                pass
        return known, todo

    def _read_pictures(self, todo):
        """Read the pictures *todo* ({output: (file, key)}) with the kit, one
        run for all of them, each onto the page as it is done; never under
        the page's busy, so Patch and Play stay usable."""
        with self._pictures_lock:
            if self._pictures_running:
                return False
            self._pictures_running = True
        d = pictures_dir()
        by_file = {}
        for output, (path, key) in todo.items():
            by_file.setdefault(path, []).append((output, key))

        def line(text):
            if not text.startswith("picture "):
                return
            try:
                got = json.loads(text[8:])
            except ValueError:
                return
            for output, key in by_file.get(got.get("table"), []):
                rec = ({"error": got["error"]} if got.get("error")
                       else {k: got.get(k) for k in ("file", "w", "h", "source")})
                try:
                    with open(os.path.join(d, key + ".json"), "w", encoding="utf-8") as f:
                        json.dump(rec, f)
                except OSError:
                    pass
                pictures = dict(self.get("pictures") or {})
                pictures[output] = rec
                self.set(pictures=pictures)

        def run():
            n = len(by_file)
            self.set(pictures_busy="Reading the picture%s of %d table%s" % ("" if n == 1 else "s", n,
                                                                             "" if n == 1 else "s"))
            try:
                os.makedirs(d, exist_ok=True)
                got = self._kit("vpxpicture.py", [d] + sorted(by_file), timeout=900, on_line=line)
                if "error" in got and not got.get("pictures"):
                    self._say("the tables' pictures were not read: %s" % got["error"], "warning")
            finally:
                self.set(pictures_busy="")
                with self._pictures_lock:
                    self._pictures_running = False
        threading.Thread(target=run, daemon=True, name="pad-vpx-pictures").start()
        return True

    # -- the page's buttons -------------------------------------------------
    @rpc
    def refresh(self):
        self._want_coverage = True
        return self._check()

    @rpc
    def restart_wsl(self):
        """"Restart WSL…" (PAD-943, David: the Emulate tabs have it, so this
        tab too). The cure for the game's screen gone blank on the desktop
        (WSLg's window with no picture while the game draws behind it - its
        frame share to Windows dead), a window that will not close, or
        crackly sound. `wsl --shutdown` closes EVERYTHING in WSL: every game
        on every tab, and it starts again by itself on the next use."""
        if sys.platform != "win32" or self._busy:
            return False
        if not compat.messagebox.askyesno(
                "Restart WSL",
                "Restart WSL?\n\n"
                "This is the cure for what the emulator cannot fix itself:\n\n"
                "  \u2022 the game's screen gone blank on the desktop (on the taskbar, "
                "but nothing in its window) while the table still plays\n"
                "  \u2022 a game window left on screen that will not close\n"
                "  \u2022 crackly or stuttery sound after a long session\n\n"
                "This closes EVERYTHING running in WSL - every game on every "
                "tab, not only this table's. Nothing on disk is lost, and WSL "
                "starts again by itself the next time it is used.\n\n"
                "Restart WSL now?"):
            return False

        def work():
            out = subprocess.run(["wsl.exe", "--shutdown"], capture_output=True,
                                 timeout=_RUN_TIMEOUT_S, creationflags=_CREATE_NO_WINDOW)
            if out.returncode:
                raise RuntimeError("wsl --shutdown returned %d: %s"
                                   % (out.returncode, (out.stdout or out.stderr or b"").decode("utf-8", "replace").strip()))
            self._say("WSL is down; it starts again by itself the next time a table opens. "
                      "Open the table again when ready.")
        return self._start("Restarting WSL", work)

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
    def choose_tables(self):
        """Where the patched tables live (PAD-848): the "Patched" marks, the
        Play list and where Patch writes. Cancel keeps the current one."""
        folder = self.window.ask_folder("vpx_tables", "The folder with your patched (PAD) tables",
                                        initialdir=self.get("tables_dir") or None)
        if not folder:
            return False
        folder = os.path.normpath(folder)

        def work():
            got = self._kit("vpxsetup.py", ["tables", folder])
            res = got.get("result") or got.get("error")
            if res != "ok":
                self._say(res, "error")
                return
            n = len(got.get("patched") or [])
            self._say("tables folder %s: %s." % (folder, "%d patched table%s" % (n, "" if n == 1 else "s")
                                                  if n else "no patched tables in it yet"))
        return self._start("Reading the tables folder", work)

    @rpc
    def patch(self, output=None):
        """The person's own download of a table the kit knows: recognised by
        its script and written as the "(PAD)" copy into Visual Pinball's
        tables folder (beside the download while Visual Pinball is not set up).

        PAD-927: each table's row has its own Patch button, *output* its
        "(PAD)" name: the file dialog names that table, and a download that
        turns out to be another table the kit knows is patched as that one,
        with the page saying so.

        PAD-939: a patched table's Patch again runs on the download it was
        patched from when the kit recorded it and it is still there (the
        row's `source`); else the dialog asks for it, as the first Patch did."""
        want = next((t for t in self.get("tables") or [] if output and t.get("output") == output), None)
        title = ("Choose your download of %s" % want["name"] if want
                 else "Choose the Visual Pinball table you downloaded")
        # PAD-943: the download in the tables folder its map fits needs no dialog
        path = (want or {}).get("source") or (want or {}).get("download") or self.window.ask_open(
            "vpx_table", title, [("Visual Pinball table", "*.vpx"), ("All files", "*.*")])
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
            elif want:
                got_out = re.search(r'open "([^"]+)"', text)
                made = os.path.basename(got_out.group(1)) if got_out else ""
                if made and made != want["output"]:
                    self._say("%s is not %s: it was patched as the table it is, %s."
                              % (os.path.basename(path), want["name"], made), "warning")
        return self._start("Patching the table", work)

    @rpc
    def patch_folder(self):
        """PAD-927: every table in a folder of downloads at once. Each .vpx
        in it (not a "(PAD)" copy) goes through the same patch; the ones the
        kit does not know are counted, not errors. The page's progress bar
        counts the files."""
        folder = self.window.ask_folder("vpx_table", "The folder with the tables you downloaded",
                                        initialdir=self.get("tables_dir") or None)
        if not folder:
            return False
        folder = os.path.normpath(folder)
        out = self.get("tables_dir") or folder

        def work():
            try:
                names = os.listdir(folder)
            except OSError as exc:
                self._say("could not read %s: %s" % (folder, exc), "error")
                return
            files = sorted(f for f in names if f.lower().endswith(".vpx") and "(PAD)" not in f)
            packed = sorted(f for f in names if f.lower().endswith((".zip", ".rar", ".7z")))
            if not files:
                self._say("no tables in %s (no .vpx files that are not (PAD) copies%s)."
                          % (folder, "; %d archive%s to unpack first" % (len(packed), "" if len(packed) == 1 else "s")
                             if packed else ""), "warning")
                return
            done, unknown, failed = [], [], []
            for i, name in enumerate(files):
                self.set(progress=i / len(files), busy="Patching %d of %d: %s" % (i + 1, len(files), name))
                got = self._kit("padvpx.py", ["patch", os.path.join(folder, name), "--out", out], timeout=600)
                text = got.get("_text") or ""
                if "this table is not one the kit knows" in text:
                    unknown.append(name)
                elif "open \"" in text:
                    done.append(name)
                    self._say("patched %s." % name)
                else:
                    failed.append(name)
                    self._say("%s did not patch; the session log has what it said." % name, "warning")
            self.set(progress=None)
            words = "%d of %d table%s patched" % (len(done), len(files), "" if len(files) == 1 else "s")
            if unknown:
                words += "; %d not one the app knows (%s)" % (len(unknown), ", ".join(unknown))
            if failed:
                words += "; %d did not patch (%s)" % (len(failed), ", ".join(failed))
            if packed:
                words += "; %d archive%s skipped, unpack %s first (%s)" % (
                    len(packed), "" if len(packed) == 1 else "s", "it" if len(packed) == 1 else "them",
                    ", ".join(packed))
            self._say(words + ".", "warning" if failed else "info")
        return self._start("Patching the folder", work)

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

    # -- for table authors (PAD-941) -----------------------------------------
    @rpc
    def pick_author_title(self, title):
        if title in (self.get("author_titles") or []):
            self.set(author_title=title)
            return True
        return False

    @rpc
    def checklist(self, with_table=False):
        """The chosen title's checklist, shown in the app (the `sheet`). With
        *with_table*, the dialog first asks for the .vpx to check: the sheet
        then marks every part of the machine that table leaves out, and a
        table the kit has no map for gets a starter map to save."""
        title = self.get("author_title") or ""
        if not title:
            return False
        table = ""
        if with_table:
            table = self.window.ask_open("vpx_table", "Choose the table to check against %s" % title,
                                         [("Visual Pinball table", "*.vpx"), ("All files", "*.*")])
            if not table:
                return False
            table = os.path.normpath(table)
        return self._sheet(title, table)

    @rpc
    def row_checklist(self, output):
        """A table row's Coverage cell: the checklist for that table, checked
        against the download it was patched from (or its (PAD) copy)."""
        t = next((t for t in self.get("tables") or [] if output and t.get("output") == output), None)
        if not t or not t.get("title"):
            return False
        tables_dir = self.get("tables_dir") or ""
        table = t.get("source") or ""
        if not table and t.get("patched") and tables_dir:
            table = os.path.join(tables_dir, output)
        return self._sheet(t["title"], table)

    def _sheet(self, title, table):
        def work():
            args = ["data", title] + (["--table", table] if table else [])
            got = self._kit("vpxauthor.py", args, timeout=300)
            if "error" in got:
                self.set(author_note=got["error"])
                self._say(got["error"], "warning" if "No device tables" in got["error"] else "error")
                return
            got.pop("_text", None)
            words = self._checklist_words(got["summary"])
            self.set(author_note=words, sheet=got)
            self._say(words)
        return self._start("Reading the checklist", work)

    @rpc
    def close_sheet(self):
        self.set(sheet=None)
        return True

    @rpc
    def export(self, kind):
        """The open sheet as a file: CSV, Markdown, or the starter map."""
        sheet = self.get("sheet") or {}
        if not sheet:
            return False
        stem = "%s - Visual Pinball table checklist" % sheet.get("title", "")
        if sheet.get("inventory"):
            stem += " - " + re.sub(r'[\/:*?"<>|]+', "_", os.path.splitext(sheet["inventory"]["name"])[0])
        if kind == "csv":
            text, name, types = sheet.get("csv", ""), stem + ".csv", [("CSV", "*.csv")]
        elif kind == "md":
            text, name, types = sheet.get("markdown", ""), stem + ".md", [("Markdown", "*.md")]
        elif kind == "starter" and sheet.get("starter"):
            text = json.dumps(sheet["starter"], indent=1)
            name, types = "%s.starter.shadow.json" % sheet.get("title", ""), [("Map", "*.json")]
        else:
            return False
        path = self.window.ask_save("vpx_checklist", "Save the checklist as", initialfile=name, filetypes=types,
                                    defaultextension=os.path.splitext(name)[1],
                                    initialdir=self.get("tables_dir") or None)
        if not path:
            return False
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        except OSError as exc:
            self._say("could not write %s: %s" % (path, exc), "error")
            return False
        self._say("saved %s." % path)
        return True

    @staticmethod
    def _checklist_words(got):
        """One sentence of what the checklist found, for the page and the log."""
        t = got.get("title", "")
        words = "%s: %d switches, %d coils, %d inserts" % (t, got.get("switches", 0),
                                                           got.get("coils", 0), got.get("inserts", 0))
        if got.get("asked") and got["asked"] != t:
            words = "%s is %s's table. " % (got.get("table", "the table"), t) + words
        if "missing_switches" in got:
            words += (". %s against the app's map: %d switches, %d coils and %d inserts the table "
                      "leaves out, %d marked GUESS" % (got.get("table", "the table"), got["missing_switches"],
                                                       got["missing_coils"], got["missing_inserts"],
                                                       got.get("guesses", 0)))
            if got.get("id_mismatch"):
                words += ("; %d switches the map numbers otherwise than this PC's game"
                          % got["id_mismatch"])
        elif got.get("table"):
            words += ". The app has no map for %s: a starter map is ready to save" % got["table"]
        if not got.get("ids", True):
            words += ". No switch ids yet: play the title once and make it again"
        return words + "."

    @rpc
    def play(self, name):
        if not name:
            return False

        def work():
            got = self._kit("vpxsetup.py", ["open", name])
            res = got.get("result") or got.get("error")
            if res == "ok":
                self._say("opening %s. The game starts by itself: a window where its screen goes "
                          "shows how far it is." % name)
            else:
                self._say(res, "error")
        return self._start("Opening the table", work)

    @rpc
    def play_download(self, path):
        """PAD-952: a download whose real game can never run on this PC
        (America's Most Haunted), opened in Visual Pinball as it is."""
        if not path:
            return False

        def work():
            got = self._kit("vpxsetup.py", ["open_download", path])
            res = got.get("result") or got.get("error")
            if res == "ok":
                self._say("opening %s as its author wrote it." % os.path.basename(path))
            else:
                self._say(res, "error")
        return self._start("Opening the table", work)


TAB = VpxTab
