"""The Modes tab on a Spooky game (PAD-1417): custom modes for Spooky's Unity titles.

The JJP editor's model (webui/modes_jjp.py) for Spooky: no project, a title's modes are one
folder of ``key = value`` files that PAD's runtime reads inside the retail game
(tools/spooky_emu/modes: ``padunity.so`` + ``PadModes.dll``).  ``SpookyModesMixin``, the ``spk``
key of the ``modes`` state:

* the title is the selected card's (its update file: the game by its name, the version from
  it), a card no port report knows says so;
* the title's modes, each the JJP form with the keys the Spooky runtime runs
  (plugins/spooky/custom_modes.FORM_GROUPS), every name picked from the port report;
* the checker (the build's own, ``mkspkmodes.check_modes``) after every edit;
* Build: the stock update in, the same update with the runtime and the modes out (its launch
  line preloads the runtime), in-process on a worker - no Linux needed;
* Try it: the runtime and the modes staged as the update's ``pad/`` folder, and the Emulate
  tab started on the stock update with them (run_game.sh SPK_PAD_OVERLAY).

The page is the JJP page's (static/js/tabs/modes_jjp.js) with its calls on ``modes.spk_*``.
"""
import os
import sys
import threading
import time

from ..plugins.spooky import custom_modes as SM
from .tabs.base import rpc

#: app settings key: {"stock": {label: path}, "out": {label: path}, "sounds": {label: folder}}
SETTINGS_KEY = "spooky_modes"


class SpookyModesMixin:
    _spk_label = ""
    _spk_file = ""
    _spk_build = None
    _spk_running = False
    _spk_cancel = False

    # ------------------------------------------------------------------ gate
    def _spk_on(self):
        mfr = getattr(self.window, "current_mfr", None)
        return bool(mfr is not None and getattr(mfr.capabilities, "spooky_modes", False))

    def _spk_card(self):
        v = getattr(self.window, "extract_input_var", None)
        try:
            return (v.get() if v is not None else "").strip()
        except Exception:                                   # noqa: BLE001
            return ""

    def _spk_hook_card(self):
        v = getattr(self.window, "extract_input_var", None)
        if v is None or v is getattr(self, "_spk_card_hooked", None):
            return
        self._spk_card_hooked = v

        def changed(*_a):
            if self._spk_on() and getattr(self, "_visible", False):
                self._post(self.spk_refresh)
        v.trace_add("write", changed)

    def _spk_settings(self):
        s = getattr(self.app, "_settings", None)
        if not isinstance(s, dict):
            s = self.__dict__.setdefault("_spk_local_settings", {})
            return s.setdefault(SETTINGS_KEY, {})
        d = s.get(SETTINGS_KEY)
        if not isinstance(d, dict):
            d = s[SETTINGS_KEY] = {}
        return d

    def _spk_remember(self, kind, value):
        self._spk_settings().setdefault(kind, {})[self._spk_label] = value

    def _spk_recall(self, kind):
        return (self._spk_settings().get(kind) or {}).get(self._spk_label, "")

    def _spk_need(self):
        if not self._spk_label:
            raise ValueError("select a Spooky game's update first")
        return self._spk_label

    # ------------------------------------------------------------------ state
    def spk_refresh(self):
        titles = SM.titles()
        self._spk_hook_card()
        card = self._spk_card()
        label = SM.label_for_card(card)
        if label != self._spk_label:
            self._spk_label, self._spk_file, self._spk_build = label, "", None
        st = {"on": True, "ns": "spk", "maker": "Spooky", "titles": titles, "label": self._spk_label,
              "max": SM.MAX_MODES, "card": card, "card_name": os.path.basename(card),
              "groups": [{"title": g, "keys": list(ks)} for g, ks in SM.FORM_GROUPS],
              "title_keys": list(SM.TITLE_FORM), "fields": self._spk_fields()}
        if self._spk_label:
            port = SM.load_port(self._spk_label) or {}
            title = next((t for t in titles if t["label"] == self._spk_label), None)
            st["title"] = title
            st["can_run"] = bool(title and title["can_run"])
            if st["can_run"]:
                modes = SM.list_modes(self._spk_label)
                if self._spk_file not in [m["file"] for m in modes]:
                    self._spk_file = modes[0]["file"] if modes else ""
                st["modes"] = modes
                st["open"] = self._spk_file
                st["form"] = dict(SM.read_mode(self._spk_label, self._spk_file)) if self._spk_file else {}
                st["kind"] = "form"
                st["title_cfg"] = dict(SM.read_title(self._spk_label))
                st["folder"] = SM.title_dir(self._spk_label)
                st["names"] = {k: SM.names_for(port, k, st["folder"]) for k in ("switches", "sound", "font", "lamps")}
                st["check"] = self._spk_check_state()
                st["sounds"] = self._spk_sounds_state(port)
                st["build"] = self._spk_build_state()
                st["points_scale"] = port.get("points_scale") or 1
                st["points_round"] = port.get("points_round") or 0
        self.set(spk=st)

    def _spk_fields(self):
        out = {}
        for k in list(SM.mk().KEYS):
            kind = SM.key_kind(k)
            choices = list(kind) if isinstance(kind, tuple) else []
            out[k] = {"label": SM.LABELS.get(k, k), "kind": "choice" if choices else kind,
                      "choices": choices, "default": SM.DEFAULTS.get(k, "")}
        return out

    def _spk_check_state(self):
        try:
            modes, problems = SM.check(self._spk_label)
        except Exception as e:                              # noqa: BLE001
            return {"ok": False, "problems": [str(e)], "n": 0}
        return {"ok": not problems, "problems": problems, "n": len(modes),
                "when": time.strftime("%H:%M:%S")}

    def _spk_sounds_state(self, port):
        folder = self._spk_recall("sounds") or self._spk_guess_sounds()
        idx = SM.sound_index(folder) if folder else {}
        have = [n for n in port.get("sounds") or () if SM.sound_file(idx, n, port)] if idx else []
        return {"folder": folder or "", "have": have, "total": len(port.get("sounds") or ())}

    def _spk_guess_sounds(self):
        """The project (Extract output) when it is this game's extract: its .spooky_meta names
        the game."""
        try:
            folder = self.project()
        except Exception:                                   # noqa: BLE001
            folder = ""
        if not folder or not os.path.isfile(os.path.join(folder, ".spooky_meta")):
            return ""
        try:
            import json
            with open(os.path.join(folder, ".spooky_meta"), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            return ""
        port = SM.load_port(self._spk_label) or {}
        return folder if meta.get("game") == port.get("title") else ""

    def _spk_stock_folders(self):
        card = self._spk_card()
        out = [os.path.dirname(card)] if card else []
        return out + ([SM.LIBRARY] if sys.platform == "win32" else [])

    def _spk_out_folder(self, stock):
        cands = []
        v = getattr(self.window, "write_output_var", None)
        try:
            cands.append(v.get().strip() if v is not None else "")
        except Exception:                                   # noqa: BLE001
            pass
        cands += [os.path.join(os.path.expanduser("~"), "Documents"), os.path.expanduser("~")]
        for d in cands:
            n = (d or "").replace("\\", "/").lower()
            if d and os.path.isdir(d) and not n.startswith("d:/pinball/images"):
                return d
        return os.path.expanduser("~")

    def _spk_build_state(self):
        card = self._spk_card()
        if SM.label_for_card(card) != self._spk_label or "PAD modes" in card:
            card = ""
        stock = self._spk_recall("stock") or card or SM.find_stock(self._spk_label, self._spk_stock_folders())
        out = self._spk_recall("out") or (SM.default_out(stock, self._spk_out_folder(stock)) if stock else "")
        b = dict(self._spk_build or {})
        b.update({"iso": stock, "out": out, "running": self._spk_running, "busy": self._spk_running})
        return b

    def _spk_publish(self, **parts):
        st = dict(self.get("spk") or {})
        st.update(parts)
        self.set(spk=st)

    # ------------------------------------------------------------------ rpcs
    @rpc
    def spk_open(self, fn):
        self._spk_file = os.path.basename(fn or "")
        self.spk_refresh()

    @rpc
    def spk_new(self, name="New Mode", how="form"):
        self._spk_file = SM.new_mode(self._spk_need(), (name or "New Mode").strip() or "New Mode")
        self.spk_refresh()
        return self._spk_file

    @rpc
    def spk_duplicate(self):
        if self._spk_file:
            self._spk_file = SM.duplicate_mode(self._spk_need(), self._spk_file)
        self.spk_refresh()

    @rpc
    def spk_delete(self):
        if not self._spk_file:
            return
        from . import compat
        name = (SM.read_mode(self._spk_label, self._spk_file).get("name") or self._spk_file)
        if not compat.messagebox.askyesno("Delete mode", "Delete the mode \"%s\"?" % name):
            return
        SM.delete_mode(self._spk_label, self._spk_file)
        self._spk_file = ""
        self.spk_refresh()

    @rpc
    def spk_set(self, key, value):
        """One field of the open mode (saved at once), or of title.cfg (``title:<key>``)."""
        label = self._spk_need()
        value = "" if value is None else str(value).strip()
        if key.startswith("title:"):
            vals = SM.read_title(label)
            vals[key[6:]] = value
            SM.write_title(label, vals)
        else:
            if not self._spk_file:
                raise ValueError("no mode open")
            if key not in SM.mk().KEYS:
                raise ValueError("unknown key %s" % key)
            vals = SM.read_mode(label, self._spk_file)
            vals[key] = value
            SM.write_mode(label, self._spk_file, vals)
        self._spk_publish(form=dict(SM.read_mode(label, self._spk_file)) if self._spk_file else {},
                          title_cfg=dict(SM.read_title(label)), modes=SM.list_modes(label),
                          check=self._spk_check_state())

    @rpc
    def spk_check(self):
        self._spk_publish(check=self._spk_check_state())

    @rpc(loop=False)
    def spk_sound_path(self, name):
        folder = self._spk_recall("sounds") or self._spk_guess_sounds()
        port = SM.load_port(self._spk_label) or {}
        return SM.sound_file(SM.sound_index(folder), name, port) if folder else ""

    @rpc
    def spk_sounds_browse(self):
        d = self.window.ask_folder("spooky_modes_sounds", "Pick this game's extract folder (its sounds)")
        if d:
            self.spk_set_sounds(d)

    @rpc
    def spk_set_sounds(self, folder):
        self._spk_need()
        self._spk_remember("sounds", folder or "")
        self._spk_publish(sounds=self._spk_sounds_state(SM.load_port(self._spk_label) or {}))

    @rpc
    def spk_set_iso(self, path):
        self._spk_need()
        self._spk_remember("stock", (path or "").strip())
        self._spk_publish(build=self._spk_build_state())

    @rpc
    def spk_iso_browse(self):
        p = self.window.ask_open("spooky_modes_stock", "Pick the game's stock update",
                                 filetypes=[("Spooky updates", "*.*")])
        if p:
            self.spk_set_iso(p)

    @rpc
    def spk_set_out(self, path):
        self._spk_need()
        self._spk_remember("out", (path or "").strip())
        self._spk_publish(build=self._spk_build_state())

    @rpc
    def spk_out_browse(self):
        b = self._spk_build_state()
        name = os.path.basename(b.get("out") or b.get("iso") or "update")
        p = self.window.ask_save("spooky_modes_out", "Where the update with your modes goes (keep its name: "
                                 "the machine reads an update by its name)", initialfile=name)
        if p:
            self.spk_set_out(p)

    @rpc
    def spk_reveal(self, what="folder"):
        from .shellx_common import reveal
        if what == "out":
            reveal(os.path.dirname(self._spk_build_state().get("out") or ""))
        else:
            reveal(SM.title_dir(self._spk_need()))

    # ------------------------------------------------------------------ build
    @rpc
    def spk_build(self):
        label = self._spk_need()
        if self._spk_running:
            raise ValueError("a build is running")
        b = self._spk_build_state()
        stock, out = b.get("iso") or "", b.get("out") or ""
        if not stock or not os.path.isfile(stock):
            raise ValueError("Pick the stock update of %s first" % SM.display_name(label))
        if not out:
            raise ValueError("Say where the new update goes first")
        if os.path.normcase(os.path.abspath(stock)) == os.path.normcase(os.path.abspath(out)):
            raise ValueError("The new update cannot replace the stock one")
        modes, problems = SM.check(label)
        if problems:
            raise ValueError("Fix the %d problem(s) the check found first" % len(problems))
        self._spk_running, self._spk_cancel = True, False
        self._spk_build = {"lines": [], "done": False, "ok": False, "msg": "Starting the build...",
                           "started": time.time(), "modes": len(modes), "pct": 0}
        self._spk_publish(build=self._spk_build_state())
        threading.Thread(target=self._spk_build_worker, args=(label, stock, out), daemon=True,
                         name="spooky-modes-build").start()

    def _spk_build_worker(self, label, stock, out):
        lines = self._spk_build["lines"]
        last = [0.0]

        def log(line):
            lines.append(line)
            self.ctx.loop.post(self._spk_build_tick)

        def progress(done, total):
            self._spk_build["pct"] = int(done * 100 / max(1, total))
            if time.time() - last[0] > 0.5:
                last[0] = time.time()
                self.ctx.loop.post(self._spk_build_tick)

        ok, msg = False, ""
        try:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            SM.mk().build(stock, SM.title_dir(label), out, SM.load_port(label), log=log, progress=progress,
                          cancelled=lambda: self._spk_cancel)
            ok, msg = True, "Built %s (%.1f GB)." % (os.path.basename(out), os.path.getsize(out) / 1e9)
        except Exception as e:                              # noqa: BLE001 - the card says why
            msg = "Build canceled." if self._spk_cancel else "The build stopped: %s" % e
        self.ctx.loop.post(self._spk_build_end, ok, msg)

    def _spk_build_tick(self):
        if self._spk_build is None:
            return
        b = self._spk_build
        b["msg"] = (b["lines"][-1] if b["lines"] else "Copying the update...") + (
            "" if b.get("done") else " %d%%" % b.get("pct", 0))
        self._spk_publish(build=self._spk_build_state())

    def _spk_build_end(self, ok, msg):
        self._spk_running = False
        b = self._spk_build = dict(self._spk_build or {})
        b.update({"lines": list(b.get("lines") or [])[-14:], "done": True, "ok": ok, "msg": msg,
                  "secs": int(time.time() - b.get("started", time.time()))})
        self.log("Spooky modes: " + msg, "info" if ok else "error")
        self._spk_publish(build=self._spk_build_state())

    @rpc
    def spk_build_cancel(self):
        if self._spk_running:
            self._spk_cancel = True

    # ------------------------------------------------------------------ Try it
    def _spk_try_base(self):
        env = os.environ.get("PAD_SPOOKY_TRY_DIR")
        if env:
            return env
        from ..core import config
        return os.path.join(os.path.dirname(config.SETTINGS_FILE), "spooky_modes_try")

    @rpc
    def spk_try(self):
        """The stock update in the Emulate tab with these modes in it (the runtime and the mode
        folder as the update's pad/, no new update) -> True when the start was handed over."""
        label = self._spk_need()
        stock = self._spk_build_state().get("iso") or ""
        if not stock or not os.path.isfile(stock):
            raise ValueError("Pick the stock update of %s first (under Build)" % SM.display_name(label))
        _modes, problems = SM.check(label)
        if problems:
            raise ValueError("Fix the %d problem(s) the check found first" % len(problems))
        pad = SM.stage_try(label, self._spk_try_base())
        emu = self.window.service("emulate_spooky")
        if emu is None or not hasattr(emu, "launch_file"):
            raise ValueError("the Emulate tab is not in this app")
        self.window.select_tab("emulate_spooky")
        return bool(emu.launch_file(stock, pad_overlay=pad))
