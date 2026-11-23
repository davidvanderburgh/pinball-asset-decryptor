"""The Modes tab on a Jersey Jack game (PAD-1350): custom modes for JJP titles.

On Stern Spike 2 the Modes tab edits a card project's modes.  On JJP there is no project to
edit: a JJP custom mode is a ``key = value`` file the JJP mode SDK's runtime reads inside the
retail game (tools/jjp_emu/MODES.md), and a title's modes are one folder of them.  So on JJP
the tab is this instead (``JjpModesMixin``, the ``jjp`` key of the ``modes`` state):

* the title is the selected card's (PAD-1412: custom_modes.label_for_card - its file name,
  else its volume ID; no game picker), a card no port report knows says so, a title that
  cannot run modes says why;
* the title's modes, each a form: what starts it (the game's switches, its events, a game
  mode ending, a score, a combo), the scoring shots,
  points, timer, completion, the game's sounds (heard from an extract folder), its lamps and
  lamp groups, the game's fonts and colours for the panel - every name picked from the port
  report, so nothing can be misspelt;
* the checker (the build's own, ``mkjjpmodes.check_modes``) after every edit;
* Build: the stock install ISO in, the same ISO with the modes out
  (``mkjjpmodes.py build``, as root in WSL - it loop-mounts the ISO's root), run on a worker
  with its lines shown as they come.
* three ways to make a mode (PAD-1384), as on Stern: the form; its own C++ against the JJP
  mode SDK's ``jjp_mode.h`` (edited here, built to a library the runtime loads in the game);
  or blocks (the Stern Blocks editor with JJP's palette, plugins/jjp/block_modes.py), which
  write that C++.  A changed mode's code is built in the app's Linux at once (one build at a
  time, ``mkjjpmodes.py code`` as root: it installs g++ the first time), its result in Check;
* Write to USB stick (PAD-1375): the everyday way in - a ``hotfix`` folder the game's own
  Update USB hot fix runs (``mkjjpmodes.py stick``), no reinstall, scores kept; or a stick that
  turns the modes off, back on, or takes them out.  The steps at the machine are shown with it.
  Its runtime is built from the stock ISO once (as root in WSL) and kept; the stick itself is
  plain files written in-process.

The Stern half of the tab is untouched: every Stern hook returns early on JJP (``_jjp_on``).
"""
import os
import subprocess
import sys
import threading
import time

from ..plugins.jjp import custom_modes as CM
from ..plugins.jjp import screen_layout as SL
from .tabs.base import rpc

#: app settings key: {"iso": {label: path}, "out": {label: path},
#: "sounds": {label: folder}, "stick": the stick last written to, "stick_action": {label: action}}
SETTINGS_KEY = "jjp_modes"


class JjpModesMixin:
    _jjp_label = ""
    _jjp_file = ""
    _jjp_proc = None
    _jjp_build_lines = None
    #: which job holds _jjp_proc: "build" or "stick" (one Linux job at a time)
    _jjp_job = ""
    _jjp_stick = None
    _jjp_stick_lines = None
    #: the code build (PAD-1384): {"running", "lines", "ok", "msg"}; _jjp_code_again: a change
    #: came in while it ran, so it runs once more
    _jjp_code = None
    _jjp_code_again = False

    # ------------------------------------------------------------------ gate
    def _jjp_on(self):
        mfr = getattr(self.window, "current_mfr", None)
        return bool(mfr is not None and getattr(mfr.capabilities, "jjp_modes", False))

    def _jjp_card(self):
        """The selected card (Select card's path), or ""."""
        v = getattr(self.window, "extract_input_var", None)
        try:
            return (v.get() if v is not None else "").strip()
        except Exception:                                   # noqa: BLE001
            return ""

    def _jjp_hook_card(self):
        """Follow the selected card: another card is another title (PAD-1412)."""
        v = getattr(self.window, "extract_input_var", None)
        if v is None or v is getattr(self, "_jjp_card_hooked", None):
            return
        self._jjp_card_hooked = v

        def changed(*_a):
            if self._jjp_on() and getattr(self, "_visible", False):
                self._post(self.jjp_refresh)
        v.trace_add("write", changed)

    def _jjp_settings(self):
        s = getattr(self.app, "_settings", None)
        if not isinstance(s, dict):
            s = self.__dict__.setdefault("_jjp_local_settings", {})
            return s.setdefault(SETTINGS_KEY, {})
        d = s.get(SETTINGS_KEY)
        if not isinstance(d, dict):
            d = s[SETTINGS_KEY] = {}
        return d

    def _jjp_remember(self, kind, value):
        self._jjp_settings().setdefault(kind, {})[self._jjp_label] = value

    def _jjp_recall(self, kind):
        return (self._jjp_settings().get(kind) or {}).get(self._jjp_label, "")

    # ------------------------------------------------------------------ state
    def jjp_refresh(self):
        """Publish the whole JJP state (title list, the title's modes, the open form, check)."""
        titles = CM.titles()
        self._jjp_hook_card()
        card = self._jjp_card()
        label = CM.label_for_card(card)
        if label != self._jjp_label:
            # PAD-1412: the game is the selected card's - a new card is a new title
            self._jjp_label, self._jjp_file = label, ""
            self._jjp_build = self._jjp_stick = None
        st = {"on": True, "titles": titles, "label": self._jjp_label, "max": CM.MAX_MODES,
              "card": card, "card_name": os.path.basename(card),
              "groups": [{"title": g, "keys": list(ks)} for g, ks in CM.FORM_GROUPS],
              "title_keys": list(CM.TITLE_FORM), "fields": self._jjp_fields()}
        if self._jjp_label:
            port = CM.load_port(self._jjp_label) or {}
            title = next((t for t in titles if t["label"] == self._jjp_label), None)
            st["title"] = title
            st["can_run"] = bool(title and title["can_run"])
            if st["can_run"]:
                modes = CM.list_modes(self._jjp_label)
                if self._jjp_file not in [m["file"] for m in modes]:
                    self._jjp_file = modes[0]["file"] if modes else ""
                st["modes"] = modes
                st["open"] = self._jjp_file
                st["form"] = dict(CM.read_mode(self._jjp_label, self._jjp_file)) if self._jjp_file else {}
                st["kind"] = CM.mode_kind(self._jjp_label, self._jjp_file) if self._jjp_file else ""
                st["blocks"] = self._jjp_blocks_state(port) if st["kind"] == "blocks" else None
                st["code"] = self._jjp_code_state()
                st["api"] = CM.api_header()
                st["title_cfg"] = dict(CM.read_title(self._jjp_label))
                st["folder"] = CM.title_dir(self._jjp_label)
                st["names"] = {k: CM.names_for(port, k, st["folder"]) for k in (
                    "switches", "lamps", "sound", "font", "events", "after", "played",
                    "sound_or_file", "sound_file", "picture_file", "video_file", "coil_pulse", "coil_hold")}
                st["check"] = self._jjp_check_state()
                st["layout"] = self._jjp_layout()
                st["screens"] = self._jjp_screens_state()
                st["sounds"] = self._jjp_sounds_state(port)
                st["build"] = self._jjp_build_state()
                st["stick"] = self._jjp_stick_state()
        self.set(jjp=st)

    def _jjp_fields(self):
        """{key: {label, kind, default, choices}} for every key the form shows."""
        out = {}
        port = (CM.load_port(self._jjp_label) if self._jjp_label else None) or {}
        for k in list(CM.mk().KEYS) + [t for t in CM.mk().TITLE_KEYS if t != "game"]:
            kind = CM.key_kind(k)
            choices = list(kind) if isinstance(kind, tuple) else []
            default = CM.DEFAULTS.get(k, "")
            if k == "game_modes" and port.get("engine") == "proc":
                # PAD-1365: no Mode class to hold off (The Wizard of Oz): a game mode pauses ours
                choices, default = [c for c in choices if c != "hold"], "pause"
            out[k] = {"label": CM.LABELS.get(k, k), "kind": "choice" if choices else kind,
                      "choices": choices, "default": default}
        return out

    def _jjp_blocks_state(self, port):
        """The open blocks mode: its program, the names the editor offers, what is wrong with it
        and the C++ it makes (PAD-1384)."""
        folder = CM.title_dir(self._jjp_label)
        prog = CM.read_blocks(self._jjp_label, self._jjp_file)
        choices = CM.blocks_names(port, folder)
        try:
            with open(CM.code_path(self._jjp_label, self._jjp_file), encoding="utf-8") as f:
                cpp = f.read()
        except OSError:
            cpp = ""
        names = {"switches": choices["shots"], "lamps": choices["lamps"], "sound": choices["sounds"],
                 "coil_pulse": choices["coils"]}
        return {"program": prog, "choices": choices, "cpp": cpp,
                "problems": CM.BM.problems(prog, names), "code": CM.code_of(self._jjp_label, self._jjp_file)}

    def _jjp_code_state(self):
        c = dict(self._jjp_code or {})
        c["stale"] = [code for _f, code in CM.code_stale(self._jjp_label)] if self._jjp_label else []
        return c

    def _jjp_check_state(self):
        try:
            modes, problems = CM.check(self._jjp_label)
        except Exception as e:                              # noqa: BLE001
            return {"ok": False, "problems": [str(e)], "n": 0}
        return {"ok": not problems, "problems": problems, "n": len(modes),
                "when": time.strftime("%H:%M:%S")}

    def _jjp_sounds_state(self, port):
        folder = self._jjp_recall("sounds") or self._jjp_guess_sounds()
        idx = CM.sound_index(folder) if folder else {}
        have = [n for n in port.get("sounds") or () if CM.sound_file(idx, n)] if idx else []
        return {"folder": folder or "", "have": have, "total": len(port.get("sounds") or ())}

    def _jjp_guess_sounds(self):
        """The JJP project (Extract output) when it is this title's extract: its
        .extract_source.json names an input whose file name is the title's label."""
        try:
            folder = self.project()
        except Exception:                                   # noqa: BLE001
            folder = ""
        if not folder or not os.path.isdir(folder):
            return ""
        src = os.path.join(folder, ".extract_source.json")
        try:
            import json
            with open(src, encoding="utf-8") as f:
                name = (json.load(f).get("input_name") or "")
        except (OSError, ValueError):
            return ""
        return folder if name.lower().startswith(self._jjp_label.lower()) else ""

    def _jjp_build_state(self):
        card = self._jjp_card()
        if not (card.lower().endswith(".iso") and CM.label_for_card(card) == self._jjp_label):
            card = ""
        iso = self._jjp_recall("iso") or card or CM.find_stock_iso(self._jjp_label, self._jjp_iso_folders())
        out = self._jjp_recall("out") or (CM.default_out(iso, self._jjp_out_folder(iso)) if iso else "")
        b = dict(getattr(self, "_jjp_build", None) or {})
        b.update({"iso": iso, "out": out, "running": self._jjp_proc is not None and self._jjp_job == "build",
                  "busy": self._jjp_proc is not None})
        return b

    def _jjp_iso_folders(self):
        """Where a stock ISO is looked for: the Select card pick's folder, then the library."""
        out = []
        for attr in ("extract_input_var",):
            v = getattr(self.window, attr, None)
            try:
                p = v.get().strip() if v is not None else ""
            except Exception:                               # noqa: BLE001
                p = ""
            if p:
                out.append(p if os.path.isdir(p) else os.path.dirname(p))
        out += [r"D:\Pinball\images\JJP"] if sys.platform == "win32" else []
        return out

    def _jjp_out_folder(self, iso):
        """The Write tab's output folder, else the ISO's own - never the image library, which the
        build refuses to write into (mkmulticard.FORBIDDEN_OUTPUT_PREFIXES)."""
        cands = []
        v = getattr(self.window, "write_output_var", None)
        try:
            cands.append(v.get().strip() if v is not None else "")
        except Exception:                                   # noqa: BLE001
            pass
        cands += [os.path.dirname(iso), os.path.join(os.path.expanduser("~"), "Documents")]
        for d in cands:
            n = (d or "").replace("\\", "/").lower()
            if d and os.path.isdir(d) and not n.startswith("d:/pinball/images"):
                return d
        return os.path.expanduser("~")

    def _jjp_publish(self, **parts):
        st = dict(self.get("jjp") or {})
        st.update(parts)
        self.set(jjp=st)

    def _jjp_need(self):
        if not self._jjp_label:
            raise ValueError("select a Jersey Jack card first")
        return self._jjp_label

    # ------------------------------------------------------------------ rpcs
    @rpc
    def jjp_open(self, fn):
        self._jjp_file = os.path.basename(fn or "")
        self.jjp_refresh()

    @rpc
    def jjp_new(self, name="New Mode", how="form"):
        """A new mode (PAD-1384: made with blocks, in C++ or with the form)."""
        self._jjp_file = CM.new_mode(self._jjp_need(), (name or "New Mode").strip() or "New Mode", how or "form")
        self.jjp_refresh()
        if how in ("blocks", "cpp"):
            self.jjp_build_code()
        return self._jjp_file

    @rpc
    def jjp_duplicate(self):
        if self._jjp_file:
            self._jjp_file = CM.duplicate_mode(self._jjp_need(), self._jjp_file)
        self.jjp_refresh()
        if self._jjp_file and CM.code_of(self._jjp_label, self._jjp_file):
            self.jjp_build_code()

    # ------------------------------------------------------------------ C++ and blocks (PAD-1384)
    @rpc
    def jjp_code_text(self):
        """The open mode's C++ (CEditor's read)."""
        try:
            return {"text": CM.read_code(self._jjp_need(), self._jjp_file),
                    "file": os.path.basename(CM.code_path(self._jjp_label, self._jjp_file))}
        except (OSError, ValueError) as e:
            return {"text": "", "error": str(e)}

    @rpc
    def jjp_code_save(self, text):
        try:
            CM.write_code(self._jjp_need(), self._jjp_file, text or "")
        except (OSError, ValueError) as e:
            return {"ok": False, "error": str(e)}
        self._jjp_publish(check=self._jjp_check_state(), code=self._jjp_code_state())
        self.jjp_build_code()
        return {"ok": True}

    @rpc
    def jjp_blocks_save(self, fn, program):
        """The Blocks editor's whole program (after each change): saved, its C++ written again,
        built.  *fn* is the mode it was made for: one opened since is left alone."""
        label = self._jjp_need()
        if os.path.basename(fn or "") != self._jjp_file:
            return
        CM.save_blocks(label, self._jjp_file, program or {})
        port = CM.load_port(label) or {}
        self._jjp_publish(blocks=self._jjp_blocks_state(port), check=self._jjp_check_state(),
                          code=self._jjp_code_state())
        self.jjp_build_code()

    @rpc
    def jjp_blocks_to_cpp(self):
        """Edit as C++ (one way): the blocks mode becomes a C++ mode for good."""
        from . import compat
        if not compat.messagebox.askyesno(
                "Edit as C++", "Turn this mode into C++ for good? Its blocks are kept beside it as a "
                "backup, but C++ can't be turned back into blocks."):
            return
        CM.blocks_to_cpp(self._jjp_need(), self._jjp_file)
        self.jjp_refresh()

    @rpc
    def jjp_open_api(self):
        """The C++ API (jjp_mode.h) in the system's editor (the Stern tab's open_sdk_doc)."""
        self.open_path(CM.api_header())
        return True

    @rpc
    def jjp_build_code(self):
        """Build every changed mode's C++ in the app's Linux (one build at a time: a change while
        one runs builds once more after it)."""
        label = self._jjp_need()
        if not CM.code_stale(label):
            self._jjp_publish(code=self._jjp_code_state(), check=self._jjp_check_state())
            return
        if self._jjp_code and self._jjp_code.get("running"):
            self._jjp_code_again = True
            return
        self._jjp_code = {"running": True, "lines": [], "ok": False, "msg": "Building the C++..."}
        self._jjp_code_again = False
        self._jjp_publish(code=self._jjp_code_state())
        threading.Thread(target=self._jjp_code_worker, args=(label, self.jjp_code_argv(label)),
                         daemon=True, name="jjp-modes-code").start()

    def jjp_code_argv(self, label):
        from . import multiboot_core as MC
        return MC.root_command(CM.code_args(label, MC.wsl))

    def _jjp_code_worker(self, label, argv):
        lines = []
        try:
            if callable(argv):
                argv = argv([])
            kw = {}
            if sys.platform == "win32":
                kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", timeout=900, **kw)
            lines = [ln.rstrip() for ln in (r.stdout or "").splitlines() if ln.strip()]
            ok = r.returncode == 0
            msg = "Built." if ok else "The C++ did not build: see the lines below."
        except Exception as e:                              # noqa: BLE001
            ok, msg = False, "The C++ build could not start: %s" % e
        self.ctx.loop.post(self._jjp_code_end, label, ok, msg, lines)

    def _jjp_code_end(self, label, ok, msg, lines):
        self._jjp_code = {"running": False, "ok": ok, "msg": msg, "lines": lines[-40:]}
        if not ok:
            self.log("JJP modes: " + msg, "error")
        if label != self._jjp_label:
            return
        self._jjp_publish(code=self._jjp_code_state(), check=self._jjp_check_state(),
                          modes=CM.list_modes(label))
        if self._jjp_code_again:
            self._jjp_code_again = False
            self.jjp_build_code()

    @rpc
    def jjp_delete(self):
        if not self._jjp_file:
            return
        from . import compat
        name = (CM.read_mode(self._jjp_label, self._jjp_file).get("name") or self._jjp_file)
        if not compat.messagebox.askyesno("Delete mode", "Delete the mode \"%s\"?" % name):
            return
        CM.delete_mode(self._jjp_label, self._jjp_file)
        self._jjp_file = ""
        self.jjp_refresh()

    @rpc
    def jjp_set(self, key, value):
        """One field of the open mode (saved at once), or of title.cfg when the key is a title
        key (``title:<key>``)."""
        label = self._jjp_need()
        value = "" if value is None else str(value).strip()
        if key.startswith("title:"):
            k = key[6:]
            vals = CM.read_title(label)
            vals[k] = value
            CM.write_title(label, vals)
        else:
            if not self._jjp_file:
                raise ValueError("no mode open")
            if CM.key_kind(key) is None or key in CM.NOT_ON_FORM:
                raise ValueError("unknown key %s" % key)
            vals = CM.read_mode(label, self._jjp_file)
            vals[key] = value
            CM.write_mode(label, self._jjp_file, vals)
        self._jjp_publish(form=dict(CM.read_mode(label, self._jjp_file)) if self._jjp_file else {},
                          title_cfg=dict(CM.read_title(label)), modes=CM.list_modes(label),
                          check=self._jjp_check_state(), layout=self._jjp_layout())

    # ------------------------------------------------------------------ the layout editor (PAD-1515)
    def _jjp_layout(self):
        """The layout editor's screens: the open mode's screen and progress board, and title.cfg's
        mode screen (every mode's defaults) and attract game type menu (plugins/jjp/screen_layout.py)."""
        label = self._jjp_label
        if not label:
            return {}
        folder = CM.title_dir(label)
        title = dict(CM.read_title(label))
        form = dict(CM.read_mode(label, self._jjp_file)) if self._jjp_file else {}
        types = []
        for m in CM.list_modes(label):
            gt = (CM.read_mode(label, m["file"]).get("game_type") or "").strip()
            if gt:
                types.append(gt)
        out = {"size": list(SL.SCREEN),
               "backdrops": SL.backdrops(folder, self._jjp_recall("layout_backdrops") or ()),
               "title_mode": SL.mode_screen({}, title, folder, scope="title", defaults=CM.DEFAULTS),
               "game": SL.game_screen(folder, title, self.__dict__.get("_jjp_screen_label", "")),
               "menu": SL.game_menu(title, types, folder, defaults=CM.DEFAULTS)}
        if self._jjp_file:
            out["mode"] = SL.mode_screen(form, title, folder, scope="mode", defaults=CM.DEFAULTS)
            if (form.get("progress") or "").strip():
                out["progress"] = SL.progress_board(form, folder)
        return out

    @rpc
    def jjp_place(self, scope, key, box):
        """A box dragged in the layout editor: ``key`` of the open mode (``scope`` "mode") or of
        title.cfg ("title") set to ``box`` ([x, y, w, h], % of its parent); ``box`` None puts the
        default place back.  ``progress#<i>`` is progress line i's own box."""
        label = self._jjp_need()
        b = SL.clamp_box(box) if box is not None else None
        if key.startswith("screen#"):                 # a part of the game's own screen: screen#<census>#<name>#<i>
            _, census, name, _i = key.split("#", 3)
            if b is None:
                return self.jjp_screen_part(name, "back")
            c = next((c for c in SL.censuses(CM.title_dir(label)) if c["label"] == census), None)
            if not c:
                raise ValueError("no census of the game's screen called %s" % census)
            move = SL.move_for(SL.read_census(c["json"]), name, b)
            return self._jjp_screen_write(SL.with_screen_line(CM.read_title(label), name, move=move))
        if key.startswith("progress#"):
            if scope != "mode" or not self._jjp_file:
                raise ValueError("no mode open")
            old = CM.read_mode(label, self._jjp_file).get("progress")
            return self.jjp_set("progress", SL.progress_with_box(old, int(key[9:]), b))
        if key not in SL.BOX_KEYS:
            raise ValueError("not a place the layout editor sets: %s" % key)
        return self.jjp_set(("title:" if scope == "title" else "") + key, SL.box_text(b) if b else "")

    @rpc
    def jjp_backdrop_browse(self):
        """A picture or video from anywhere to lay out over (a frame of an extracted attract video, a
        photo of the machine's screen): remembered for the title, its path returned."""
        self._jjp_need()
        p = self.window.ask_open("jjp_layout_backdrop", "Pick a picture or video to lay out over",
                                 filetypes=[("Pictures and videos", " ".join("*" + e for e in SL.PICTURE_EXTS + SL.VIDEO_EXTS)),
                                            ("All files", "*.*")])
        if not p:
            return ""
        have = [x for x in (self._jjp_recall("layout_backdrops") or []) if x != p]
        self._jjp_remember("layout_backdrops", [p] + have[:7])
        self._jjp_publish(layout=self._jjp_layout())
        return p

    @rpc
    def jjp_place_many(self, scope, items):
        """Several dragged boxes at once ([[key, box], ...]): a group of the game's parts in one write."""
        label = self._jjp_need()
        parts = [(k, b) for k, b in items if str(k).startswith("screen#")]
        for k, b in items:
            if not str(k).startswith("screen#"):
                self.jjp_place(scope, k, b)
        if not parts:
            return
        title = CM.read_title(label)
        lines = {k: title.get(k, "") for k in SL.SCREEN_KEYS}
        cs = {c["label"]: c for c in SL.censuses(CM.title_dir(label))}
        for key, box in parts:
            _, census, name, _i = key.split("#", 3)
            if census not in cs:
                raise ValueError("no census of the game's screen called %s" % census)
            move = SL.move_for(SL.read_census(cs[census]["json"]), name, SL.clamp_box(box))
            lines = SL.with_screen_line(lines, name, move=move)
        self._jjp_screen_write(lines)

    def _jjp_screen_write(self, lines):
        label = self._jjp_need()
        vals = CM.read_title(label)
        vals.update(lines)
        CM.write_title(label, vals)
        self._jjp_publish(title_cfg=dict(CM.read_title(label)), check=self._jjp_check_state(), layout=self._jjp_layout())

    @rpc
    def jjp_screen_part(self, name, action):
        """A part of the game's own screen: ``hide`` it, ``show`` it again, or put it ``back`` where the
        game draws it (its move and its hide taken away)."""
        title = CM.read_title(self._jjp_need())
        if action == "hide":
            lines = SL.with_screen_line(title, name, hide=True)
        elif action == "show":
            lines = SL.with_screen_line(title, name, hide=False)
        elif action == "back":
            lines = SL.with_screen_line(title, name, move=(0, 0, 1), hide=False)
        else:
            raise ValueError("no such action %s" % action)
        self._jjp_screen_write(lines)

    # ---------------------------------------------- Show it in the game (PAD-1515)
    def jjp_screens_argv(self, iso, runtime):
        """The screens run's argv, as root in the app's Linux (see jjp_build_argv)."""
        from . import multiboot_core as MC
        return MC.root_command(CM.screens_args(iso, runtime, self._jjp_label, MC.wsl, self._jjp_file), exe="bash")

    def _jjp_screens_state(self):
        s = dict(getattr(self, "_jjp_screens", None) or {})
        s["running"] = self._jjp_job == "screens"
        s["iso"] = (self._jjp_build_state() or {}).get("iso") or ""
        return s

    @rpc
    def jjp_show_in_game(self):
        """The game's own screens for the layout editor: the stock ISO (Build's) booted hidden and
        muted on the app's emulator with this title's modes; a census in attract and with a ball in
        play names every part it draws (jjpmodes.c, tools/jjp_emu/jjpscreens.sh).  The runtime is
        built for the ISO first when it has not been (the USB stick's, kept per ISO)."""
        label = self._jjp_need()
        if self._jjp_proc is not None:
            raise ValueError("a build, a stick or a screens run is going")
        iso = (self._jjp_build_state() or {}).get("iso") or ""
        if not iso or not os.path.isfile(iso):
            raise ValueError("Pick the stock install ISO of %s under Build first: the game runs from it"
                             % CM.display_name(label))
        runtime = CM.runtime_path(iso)
        steps = []
        if not os.path.isfile(runtime):
            os.makedirs(os.path.dirname(runtime), exist_ok=True)
            steps.append(("Building the runtime for %s..." % os.path.basename(iso), self.jjp_runtime_argv(iso, runtime)))
        steps.append(("Running the game, hidden and muted...", self.jjp_screens_argv(iso, runtime)))
        self._jjp_screens_lines = []
        self._jjp_screens = {"lines": [], "done": False, "ok": False, "msg": steps[0][0], "started": time.time()}
        self._jjp_proc = True
        self._jjp_job = "screens"
        self._jjp_publish(screens=self._jjp_screens_state())
        threading.Thread(target=self._jjp_screens_worker, args=(steps,), daemon=True, name="jjp-screens").start()

    def _jjp_screens_worker(self, steps):
        ok, msg = False, ""
        try:
            for say, argv in steps:
                self._jjp_screens_lines.append(say)
                rc = self._jjp_stream(argv, self._jjp_screens_lines, self._jjp_screens_tick)
                if getattr(self, "_jjp_cancelled", False):
                    msg = "Stopped."
                    break
                if rc != 0:
                    refused = [ln for ln in self._jjp_screens_lines if ln.startswith("refused:")]
                    msg = (refused[-1][len("refused:"):].strip() if refused
                           else "It stopped (exit %d): %s" % (rc, self._jjp_screens_lines[-1]))
                    break
            else:
                ok, msg = True, "The game's screens are in: drag its parts where you want them."
        except Exception as e:                              # noqa: BLE001
            msg = "It could not start: %s" % e
        self.ctx.loop.post(self._jjp_screens_end, ok, msg)

    def _jjp_screens_tick(self):
        if self._jjp_screens is None:
            return
        self._jjp_screens["lines"] = list(self._jjp_screens_lines[-10:])
        self._jjp_screens["msg"] = self._jjp_screens_lines[-1] if self._jjp_screens_lines else ""
        self._jjp_publish(screens=self._jjp_screens_state())

    def _jjp_screens_end(self, ok, msg):
        self._jjp_proc = None
        self._jjp_job = ""
        self._jjp_cancelled = False
        self._jjp_screens = dict(self._jjp_screens or {})
        self._jjp_screens.update({"lines": list((self._jjp_screens_lines or [])[-10:]), "done": True, "ok": ok, "msg": msg,
                                  "secs": int(time.time() - self._jjp_screens.get("started", time.time()))})
        if ok:
            self.__dict__["_jjp_screen_label"] = "game"
        self.log("JJP modes: " + msg, "info" if ok else "error")
        self._jjp_publish(screens=self._jjp_screens_state(), layout=self._jjp_layout())

    @rpc
    def jjp_screens_cancel(self):
        p = self._jjp_proc
        if self._jjp_job != "screens" or p is None or p is True:
            return
        self._jjp_cancelled = True
        threading.Thread(target=self._jjp_stop_linux, args=(p, CM.SCREENS_PATTERN), daemon=True).start()

    @rpc
    def jjp_screen_label(self, census):
        """Which of the game's screens (a census) the editor lays out over."""
        self.__dict__["_jjp_screen_label"] = census or ""
        self._jjp_publish(layout=self._jjp_layout())

    @rpc
    def jjp_panel_word(self, scope, word):
        """A panel place picked in the layout editor (middle, bottom, top, none): the panel goes
        there, its own box (panel_at) taken away; its text keeps its places in it."""
        if word not in SL.PANEL_PLACES and word != "none":
            raise ValueError("no panel place %s" % word)
        pre = "title:" if scope == "title" else ""
        self.jjp_set(pre + "panel_at", "")
        return self.jjp_set(pre + "panel", word)

    @rpc
    def jjp_check(self):
        self._jjp_publish(check=self._jjp_check_state())
        if self._jjp_label and CM.code_stale(self._jjp_label):
            self.jjp_build_code()

    @rpc(loop=False)
    def jjp_sound_path(self, name):
        folder = self._jjp_recall("sounds") or self._jjp_guess_sounds()
        return CM.sound_file(CM.sound_index(folder), name) if folder else ""

    @rpc
    def jjp_sounds_browse(self):
        d = self.window.ask_folder("jjp_modes_sounds", "Pick this game's extract folder (its sounds)")
        if d:
            self.jjp_set_sounds(d)

    @rpc
    def jjp_set_sounds(self, folder):
        self._jjp_need()
        self._jjp_remember("sounds", folder or "")
        port = CM.load_port(self._jjp_label) or {}
        self._jjp_publish(sounds=self._jjp_sounds_state(port))

    @rpc
    def jjp_set_iso(self, path):
        self._jjp_need()
        self._jjp_remember("iso", (path or "").strip())
        if path and not self._jjp_recall("out"):
            pass
        self._jjp_publish(build=self._jjp_build_state())

    @rpc
    def jjp_iso_browse(self):
        p = self.window.ask_open("jjp_modes_iso", "Pick the stock install ISO",
                                 filetypes=[("JJP install ISOs", "*.iso"), ("All files", "*.*")])
        if p:
            self.jjp_set_iso(p)

    @rpc
    def jjp_set_out(self, path):
        self._jjp_need()
        self._jjp_remember("out", (path or "").strip())
        self._jjp_publish(build=self._jjp_build_state())

    @rpc
    def jjp_out_browse(self):
        b = self._jjp_build_state()
        p = self.window.ask_save("jjp_modes_out", "Where the ISO with your modes goes",
                                 initialfile=os.path.basename(b.get("out") or "modes.iso"),
                                 filetypes=[("Install ISO", "*.iso")], defaultextension=".iso")
        if p:
            self.jjp_set_out(p)

    @rpc
    def jjp_reveal(self, what="folder"):
        from .shellx_common import reveal
        if what == "out":
            p = (self._jjp_build_state().get("out") or "")
            reveal(os.path.dirname(p))
        else:
            reveal(CM.title_dir(self._jjp_need()))

    # ------------------------------------------------------------------ build
    def jjp_build_argv(self, iso, out):
        """The argv of the build, as root in the app's Linux (a callable on Windows - the WSL
        home is two wsl.exe probes, resolved on the worker)."""
        from . import multiboot_core as MC
        return MC.root_command(CM.build_args(iso, self._jjp_label, out, MC.wsl))

    @rpc
    def jjp_build(self):
        label = self._jjp_need()
        if self._jjp_proc is not None:
            raise ValueError("a build or a stick is being written")
        b = self._jjp_build_state()
        iso, out = b.get("iso") or "", b.get("out") or ""
        if not iso or not os.path.isfile(iso):
            raise ValueError("Pick the stock install ISO of %s first" % CM.display_name(label))
        if not out:
            raise ValueError("Say where the new ISO goes first")
        if os.path.normcase(os.path.abspath(iso)) == os.path.normcase(os.path.abspath(out)):
            raise ValueError("The new ISO cannot replace the stock one")
        modes, problems = CM.check(label)
        if problems:
            raise ValueError("Fix the %d problem(s) the check found first" % len(problems))
        argv = self.jjp_build_argv(iso, out)
        self._jjp_build_lines = []
        self._jjp_build = {"lines": [], "done": False, "ok": False, "msg": "Starting the build...",
                           "started": time.time(), "modes": len(modes)}
        self._jjp_proc = True                               # taken: the worker fills it in
        self._jjp_job = "build"
        self._jjp_publish(build=self._jjp_build_state(), stick=self._jjp_stick_state())
        threading.Thread(target=self._jjp_build_worker, args=(argv, out), daemon=True,
                         name="jjp-modes-build").start()

    def _jjp_build_worker(self, argv, out):
        ok, msg = False, ""
        try:
            rc = self._jjp_stream(argv, self._jjp_build_lines, self._jjp_build_tick)
            lines = self._jjp_build_lines
            refused = [ln for ln in lines if ln.startswith("refused:")]
            if rc == 0 and os.path.isfile(out):
                ok, msg = True, "Built %s (%.1f GB)." % (os.path.basename(out), os.path.getsize(out) / 1e9)
            elif getattr(self, "_jjp_cancelled", False):
                msg = "Build canceled."
            else:
                msg = (refused[-1][len("refused:"):].strip() if refused
                       else "The build stopped (exit %d): %s" % (rc, lines[-1] if lines else "no output"))
        except Exception as e:                              # noqa: BLE001
            msg = "The build could not start: %s" % e
        self.ctx.loop.post(self._jjp_build_end, ok, msg)

    def _jjp_stream(self, argv, lines, tick):
        """Run *argv* (a callable on Windows: resolved here, on the worker), its lines into
        *lines*, *tick* posted to the UI loop at most twice a second.  -> the exit code."""
        if callable(argv):
            argv = argv([])
        kw = {}
        if sys.platform == "win32":
            kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", **kw)
        self._jjp_proc = proc
        last = 0.0
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            lines.append(line)
            if time.time() - last > 0.5:
                last = time.time()
                self.ctx.loop.post(tick)
        return proc.wait()

    def _jjp_build_tick(self):
        if self._jjp_build is None:
            return
        self._jjp_build["lines"] = list(self._jjp_build_lines[-14:])
        self._jjp_build["msg"] = self._jjp_build_lines[-1] if self._jjp_build_lines else ""
        self._jjp_publish(build=self._jjp_build_state())

    def _jjp_build_end(self, ok, msg):
        self._jjp_proc = None
        self._jjp_job = ""
        self._jjp_cancelled = False
        self._jjp_build = dict(self._jjp_build or {})
        self._jjp_build.update({"lines": list((self._jjp_build_lines or [])[-14:]), "done": True, "ok": ok,
                                "msg": msg, "secs": int(time.time() - self._jjp_build.get("started", time.time()))})
        self.log(("JJP modes: " + msg), "info" if ok else "error")
        self._jjp_publish(build=self._jjp_build_state(), stick=self._jjp_stick_state())

    @rpc
    def jjp_build_cancel(self):
        p = self._jjp_proc
        if self._jjp_job != "build" or p is None or p is True:
            return
        self._jjp_cancelled = True
        # the tool runs inside Linux as root: stopping wsl.exe leaves it running, so it is
        # asked to stop there (it unmounts and deletes its scratch on SIGTERM), then wsl.exe
        threading.Thread(target=self._jjp_stop_linux, args=(p,), daemon=True).start()

    def _jjp_stop_linux(self, p, pattern=CM.BUILD_PATTERN):
        try:
            from ..core import runtime
            line = "pkill -TERM -f '%s'" % pattern
            if sys.platform == "win32":
                argv = runtime.wsl_head(root=True) + ["-e", "bash", "-c", line]
            else:
                argv = ["bash", "-c", line]
            subprocess.run(argv, timeout=60, capture_output=True)
        except Exception:                                   # noqa: BLE001
            pass
        try:
            p.wait(timeout=60)
        except Exception:                                   # noqa: BLE001
            try:
                p.terminate()
            except Exception:                               # noqa: BLE001
                pass

    # ------------------------------------------------------------------ USB stick (PAD-1375)
    def _jjp_stick_path(self):
        """The stick: the one last written to while it is still there, else the first removable
        drive Windows has now."""
        drives = CM.removable_drives()
        want = self._jjp_settings().get("stick") or ""
        if want and os.path.isdir(want):
            return want, drives
        return (drives[0] if drives else ""), drives

    def _jjp_stick_state(self):
        path, drives = self._jjp_stick_path()
        action = self._jjp_recall("stick_action")
        s = dict(self._jjp_stick or {})
        iso = self._jjp_build_state().get("iso") or ""
        rt = ""
        if iso and os.path.isfile(iso):
            try:
                rt = CM.runtime_path(iso)
            except OSError:
                rt = ""
        # a stick's file system matters; a folder to copy to one (on C:, say) is not a stick
        target = os.path.normcase(os.path.abspath(path)) if path else ""
        roots = [os.path.normcase(os.path.abspath(d)) for d in drives]
        on_stick = bool(target) and any(
            target == root or target.startswith(root.rstrip(os.sep) + os.sep)
            for root in roots)
        s.update({"path": path, "drives": drives, "fs": CM.stick_filesystem(path) if on_stick else "",
                  "action": action if action in dict(CM.STICK_ACTIONS) else "install",
                  "actions": [{"value": k, "label": v} for k, v in CM.STICK_ACTIONS],
                  "owner": CM.hotfix_on(path) if path and os.path.isdir(path) else "",
                  "runtime_ready": bool(rt and os.path.isfile(rt)), "iso": iso,
                  "running": self._jjp_proc is not None and self._jjp_job == "stick",
                  "busy": self._jjp_proc is not None, "steps": list(CM.STICK_STEPS)})
        return s

    @rpc
    def jjp_set_stick(self, path):
        self._jjp_need()
        self._jjp_settings()["stick"] = (path or "").strip()
        self._jjp_stick = None
        self._jjp_publish(stick=self._jjp_stick_state())

    @rpc
    def jjp_stick_browse(self):
        p = self.window.ask_folder("jjp_modes_stick", "Pick the USB stick (or a folder to copy to one)")
        if p:
            self.jjp_set_stick(p)

    @rpc
    def jjp_stick_action(self, action):
        self._jjp_need()
        if action not in dict(CM.STICK_ACTIONS):
            raise ValueError("unknown stick action %r" % action)
        self._jjp_remember("stick_action", action)
        self._jjp_stick = None
        self._jjp_publish(stick=self._jjp_stick_state())

    @rpc
    def jjp_stick_refresh(self):
        """The drives again (a stick plugged in after the tab opened)."""
        if self._jjp_label:
            self._jjp_publish(stick=self._jjp_stick_state())

    def jjp_runtime_argv(self, iso, out):
        """The runtime build's argv, as root in the app's Linux (see jjp_build_argv)."""
        from . import multiboot_core as MC
        return MC.root_command(CM.runtime_args(iso, out, MC.wsl))

    @rpc
    def jjp_write_stick(self):
        label = self._jjp_need()
        if self._jjp_proc is not None:
            raise ValueError("a build or a stick is being written")
        s = self._jjp_stick_state()
        path, action = s["path"], s["action"]
        if not path or not os.path.isdir(path):
            raise ValueError("Put in a USB stick, or pick a folder to copy to one")
        if s["owner"] == "other":
            raise ValueError("%s already has a hot fix that is not a modes stick: use another stick, "
                             "or delete its hotfix folder first" % path)
        rt_argv, rt = None, ""
        if action == "install":
            modes, problems = CM.check(label)
            if problems:
                raise ValueError("Fix the %d problem(s) the check found first" % len(problems))
            if not modes:
                raise ValueError("Make a mode first")
            iso = s["iso"]
            if not iso or not os.path.isfile(iso):
                raise ValueError("Pick the stock install ISO of %s first (under Build): the stick's "
                                 "mode runtime is built against its system" % CM.display_name(label))
            rt = CM.runtime_path(iso)
            if not os.path.isfile(rt):
                rt_argv = self.jjp_runtime_argv(iso, rt)
        self._jjp_settings()["stick"] = path
        self._jjp_stick_lines = []
        self._jjp_stick = {"lines": [], "done": False, "ok": False, "started": time.time(),
                           "msg": ("Building the mode runtime (once for this ISO)..." if rt_argv
                                   else "Writing the stick...")}
        self._jjp_proc = True
        self._jjp_job = "stick"
        self._jjp_publish(stick=self._jjp_stick_state(), build=self._jjp_build_state())
        threading.Thread(target=self._jjp_stick_worker, args=(label, path, action, rt, rt_argv),
                         daemon=True, name="jjp-modes-stick").start()

    def _jjp_stick_worker(self, label, path, action, rt, rt_argv):
        ok, msg = False, ""
        lines = self._jjp_stick_lines
        try:
            if rt_argv is not None:
                os.makedirs(os.path.dirname(rt), exist_ok=True)
                rc = self._jjp_stream(rt_argv, lines, self._jjp_stick_tick)
                if getattr(self, "_jjp_cancelled", False):
                    raise _Stop("Canceled.")
                if rc != 0 or not os.path.isfile(rt):
                    refused = [ln for ln in lines if ln.startswith("refused:")]
                    raise _Stop("The mode runtime could not be built: " + (
                        refused[-1][len("refused:"):].strip() if refused
                        else "exit %d, %s" % (rc, lines[-1] if lines else "no output")))
            self._jjp_proc = True                           # no Linux process to cancel now
            lines.append("writing the stick at %s" % path)
            self.ctx.loop.post(self._jjp_stick_tick)
            ok, out = CM.write_stick(label, path, action, rt)
            lines.extend(out)
            if ok:
                msg = {"install": "Written: the stick installs %d mode(s)." % len(CM.list_modes(label)),
                       "off": "Written: the stick turns the modes off.",
                       "on": "Written: the stick turns the modes back on.",
                       "remove": "Written: the stick takes the modes out."}[action]
            else:
                refused = [ln for ln in out if ln.startswith("refused:")]
                msg = (refused[-1][len("refused:"):].strip() if refused
                       else (out[-1] if out else "The stick was not written."))
        except _Stop as e:
            msg = str(e)
        except Exception as e:                              # noqa: BLE001
            msg = "The stick could not be written: %s" % e
        self.ctx.loop.post(self._jjp_stick_end, ok, msg)

    def _jjp_stick_tick(self):
        if self._jjp_stick is None:
            return
        self._jjp_stick["lines"] = list(self._jjp_stick_lines[-14:])
        self._jjp_stick["msg"] = self._jjp_stick_lines[-1] if self._jjp_stick_lines else ""
        self._jjp_publish(stick=self._jjp_stick_state())

    def _jjp_stick_end(self, ok, msg):
        self._jjp_proc = None
        self._jjp_job = ""
        self._jjp_cancelled = False
        self._jjp_stick = dict(self._jjp_stick or {})
        self._jjp_stick.update({"lines": list((self._jjp_stick_lines or [])[-14:]), "done": True, "ok": ok,
                                "msg": msg})
        self.log(("JJP modes stick: " + msg), "info" if ok else "error")
        self._jjp_publish(stick=self._jjp_stick_state(), build=self._jjp_build_state())

    @rpc
    def jjp_stick_cancel(self):
        p = self._jjp_proc
        if self._jjp_job != "stick" or p is None or p is True:
            return
        self._jjp_cancelled = True
        threading.Thread(target=self._jjp_stop_linux, args=(p, CM.RUNTIME_PATTERN), daemon=True).start()

    @rpc
    def jjp_reveal_stick(self):
        from .shellx_common import reveal
        p = self._jjp_stick_state().get("path") or ""
        if p:
            reveal(p)


class _Stop(Exception):
    """The stick worker's own stop: its message is the whole status line."""
