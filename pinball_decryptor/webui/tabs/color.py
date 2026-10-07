"""The Color profile tab (PAD-305): the colour correction a project's build
applies so the machine's display shows what the PC does.

A STAGED CHANGE OF THE PROJECT, like every other Replace tab's: the profile
the controls show is saved in the project's ``.staged_changes.json``
(core/colour_profile.py ``store``) the moment it changes, the Write tab lists
it as pending, the next build or Emulate Start applies it, and Revert all
clears it.  "No change" is the off state; there is no separate switch.
Save a copy / Load move a profile between projects (one per machine).
SAVED PROFILES (PAD-360): the list beside them is the profile files in the
folder they last used and in PAD's own Color profiles folder (Save a copy's
first stop), by file name; picking one loads it.  The list, and the starting
points, show which one is in use.
"See it in the emulator" hands the Emulate tab a run of this project's edits
with the profile, restarting a running game.  (Never "Try it": that is the
preview-gated mode maker's word, and this tab is public.)

TWO PROFILES ON SPIKE 2 (PAD-312).  Where the game draws everything through
the profile, the tab has two modes: "Whole screen" (the profile above) and
"Chosen files", a second profile (core/colour_profile.py ``asset_profile``,
Recommended until changed) baked into the replaced pictures and videos and
the pictures added in Scenes that are switched on.  The mode's switches are
the two tab-wide boxes here; each file's own switch is on the Images and
Video tabs and in the Scenes layers.  The same sliders, preview, Save a
copy and Load serve whichever mode is showing.

THE MACHINE SCREEN (PAD-324).  A third Spike 2 mode: not a correction but
the screen itself, what the machine does to what it is given.  Only the
Scenes preview's "As on the machine" uses it; nothing is written to the
card, the Write tab lists nothing, and Revert all leaves it (it describes
the user's machine, not a change to the card).  Until one is stored the
mode shows the individual files profile, undone, which is what Scenes uses.

ONE PROFILE PER FILE (PAD-368, DragonRR).  With a file clicked on the Images
or Video tab or a layer in Scenes while the Color profiles bar is open there,
the bar's Files mode is THAT file's profile (``set_file``): what it shows is
the profile baked into it now, and a change gives the file a profile of its
own (core/colour_profile.py ``store_own_profile``), attaching it if its
switch was off.  "Same as the other files" drops it again.  With no file
picked, and always on the Color profile tab itself, Files is the project's
individual files profile, which every file without its own gets.

RECOMMENDED FOLLOWS THE SCREEN (PAD-346).  On Spike 2 the overlay's and the
individual files' Recommended is the Machine screen on show, undone
(core/colour_profile.py ``recommended``), worked out again whenever the
screen changes and shown on the same sliders, ranges and curves, so moving
one starts from exactly what it was.  Picking it stores "follow the screen"
rather than numbers; moving a slider stores numbers again ("My profile").

COLOR RANGES AND CURVES (PAD-339, PAD-343).  First the machine screen's
alone, now every mode's: the files bake them (Pillow, ffmpeg .cube tables)
and the Spike 2 overlay draws them in its shaders (shader_profile
``extras_glsl``), so the same cards show whichever mode is open.

The PREVIEW is drawn by the page itself (static/js/tabs/color.js) with the
same maths, so a slider moves the picture as it is dragged; this side only
says which picture: a test card PAD draws, or one of the user's own.
"""

import base64
import io
import json
import logging
import os
import time

from .base import TabService, rpc
from ...core import colour_profile as cp
from ...core import config, staged_changes

log = logging.getLogger(__name__)

#: limits of the page's controls: the whole range a file accepts (PAD-338)
LIMITS = cp.LIMITS

#: Undo (PAD-354): moves of one slider closer together than this are one step
UNDO_GROUP_S = 1.5
#: and no more steps than this are kept per profile
UNDO_MAX = 100

_CARD_CACHE = []

#: the browse key Save a copy and Load share, so the list follows them
BROWSE_KEY = "colour_profile"


def default_profiles_dir():
    """PAD's own Color profiles folder: where Save a copy goes the first
    time, and always listed (PAD-360)."""
    return os.path.join(os.path.dirname(config.SETTINGS_FILE),
                        "Color profiles")


def test_card_png():
    """A small display test card (grey steps, full and half colours, dark
    sea tones, a smooth ramp and skin tones): the shades a display gets
    wrong first.  Drawn here, so it ships with nothing of anyone else's."""
    if _CARD_CACHE:
        return _CARD_CACHE[0]
    from PIL import Image, ImageDraw
    w, h = 640, 400
    im = Image.new("RGB", (w, h), (24, 24, 24))
    d = ImageDraw.Draw(im)
    x0, cw = 16, (w - 32)
    greys = [0, 8, 16, 24, 32, 48, 64, 80, 96, 112, 128, 160, 192, 224, 240,
             255]
    step = cw / len(greys)
    for i, v in enumerate(greys):
        d.rectangle([x0 + i * step, 16, x0 + (i + 1) * step - 1, 76],
                    fill=(v, v, v))
    full = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 255, 255),
            (255, 0, 255), (255, 255, 0)]
    step = cw / len(full)
    for i, c in enumerate(full):
        half = tuple(v // 2 for v in c)
        d.rectangle([x0 + i * step, 88, x0 + (i + 1) * step - 1, 138], fill=c)
        d.rectangle([x0 + i * step, 140, x0 + (i + 1) * step - 1, 190],
                    fill=half)
    sea = [(8, 24, 40), (8, 32, 56), (12, 48, 80), (16, 64, 104),
           (24, 80, 128), (32, 96, 152)]
    skin = [(255, 224, 196), (234, 192, 160), (198, 145, 110),
            (160, 105, 75), (110, 70, 50), (70, 45, 32)]
    for row, (y, colours) in enumerate(((202, sea), (254, skin))):
        step = cw / len(colours)
        for i, c in enumerate(colours):
            d.rectangle([x0 + i * step, y, x0 + (i + 1) * step - 1, y + 48],
                        fill=c)
    for x in range(cw):
        v = round(x * 255 / (cw - 1))
        d.line([x0 + x, 314, x0 + x, 384], fill=(v, v, v))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    _CARD_CACHE.append("data:image/png;base64,"
                       + base64.b64encode(buf.getvalue()).decode())
    return _CARD_CACHE[0]


def _clamp(key, v):
    lo, hi = LIMITS[key]
    return min(max(float(v), lo), hi)


class ColorTab(TabService):
    ns = "color"
    key = "Color Profile"
    label = "Color profile"
    group = "Replace"
    icon = "palette"

    def __init__(self, window):
        super().__init__(window)
        self._prof = None            # the project's profile (None = No change)
        self._asset = None           # the chosen-files profile (PAD-312)
        self._screen = None          # the machine screen (PAD-324)
        self._screen_stored = False
        self._mode = "display"       # "display" | "assets" | "screen"
        self._on_display = False
        self._rev = 0
        self._sample = "card"
        self._project = ""
        self._undo = {}              # PAD-354: {stored key: [what it was, ...]}
        self._redo = {}
        self._last_move = {}         # {stored key: (slider, time)}: one drag = one step
        self._file = None            # PAD-368: {kind, rel, label, attach} the bar is on
        self.set(sample="card", sample_url="", sample_path="", samples=[],
                 problems=[], rev=0, active=False, project="",
                 has_project=False, try_note="", mode="display",
                 per_file=False, all_images=False, all_videos=False,
                 asset_counts={"images": 0, "videos": 0, "added": 0},
                 asset_active=False, file=None,
                 own_names={"images": {}, "videos": {}, "text": {}})

    # -- the project ---------------------------------------------------------
    def _assets(self):
        var = getattr(self.window, "write_assets_var", None)
        try:
            return (var.get() or "").strip() if var is not None else ""
        except Exception:                               # noqa: BLE001
            return ""

    def _load(self):
        """Read the project's staged profile into the controls."""
        assets = self._assets()
        if assets != self._project:
            self._undo, self._redo, self._last_move = {}, {}, {}
        self._project = assets
        prof = None
        asset = None
        screen, stored = None, False
        if assets and os.path.isdir(assets):
            try:
                prof = cp.for_project(assets)
                asset = cp.asset_profile(assets)
                screen, stored = cp.screen_shown(assets)
            except Exception:                           # noqa: BLE001
                log.exception("color profile load")
        self._prof = prof
        self._asset = asset
        self._screen = screen
        self._screen_stored = stored
        self._rev += 1
        self._publish(problems=[])

    def _assets_mode(self):
        return self._mode == "assets" and self._on_display

    def _screen_mode(self):
        return self._mode == "screen" and self._on_display

    def _file_mode(self):
        """Files mode on one file (PAD-368): ``(kind, rel)`` or ``None``."""
        f = self._file
        if not (f and self._assets_mode() and self._project
                and os.path.isdir(self._project)):
            return None
        return f["kind"], f["rel"]

    def _own(self):
        """The file on show's own profile, or ``None`` (it gets the
        project's)."""
        fm = self._file_mode()
        if fm is None:
            return None
        try:
            return cp.own_profile(self._project, *fm)
        except Exception:                               # noqa: BLE001
            log.exception("color profile own")
            return None

    def _shown(self):
        if self._screen_mode():
            return self._screen or cp.SCREEN_PRESETS[0][1]
        if self._assets_mode():
            own = self._own()
            if own is not None:
                return own
            return self._asset or cp.recommended(self._project, files=True)
        return self._prof or cp.Profile(name="No change")

    def _follows(self):
        """Is the mode on show the Recommended one following the machine
        screen (PAD-346)?"""
        assets = self._project
        if not (self._on_display and assets and os.path.isdir(assets)):
            return False
        try:
            fm = self._file_mode()
            if fm is not None and self._own() is not None:
                return cp.own_follows_screen(assets, *fm)
            if self._assets_mode():
                return not cp.asset_stored(assets)
            if not self._screen_mode():
                return cp.follows_screen(assets)
        except Exception:                               # noqa: BLE001
            log.exception("color profile follows")
        return False

    def _asset_state(self, assets):
        """The chosen-files mode's switches and counts for the page."""
        out = {"all_images": False, "all_videos": False,
               "asset_counts": {"images": 0, "videos": 0, "added": 0, "text": 0},
               "asset_active": False}
        if not (assets and os.path.isdir(assets)):
            return out
        try:
            st = cp.asset_settings(assets)
            out["all_images"] = st["all_images"]
            out["all_videos"] = st["all_videos"]
            out["asset_counts"] = cp.asset_counts(assets)
            out["asset_active"] = cp.asset_active(assets) is not None
        except Exception:                               # noqa: BLE001
            log.exception("color profile switches")
        return out

    # -- saved profiles (PAD-360) --------------------------------------------
    def _profile_folders(self):
        """The folders the Saved profiles list is read from: the one Save a
        copy / Load last used, then PAD's own."""
        out = []
        try:
            last = self.window.last_browse_dir(BROWSE_KEY)
        except Exception:                               # noqa: BLE001
            last = ""
        for d in (last, default_profiles_dir()):
            if d and os.path.isdir(d) and not any(
                    os.path.normcase(os.path.abspath(d))
                    == os.path.normcase(os.path.abspath(o)) for o in out):
                out.append(d)
        return out

    def _preset_on(self, p, assets):
        """The starting point the profile on show is, or ""."""
        ok = bool(assets and os.path.isdir(assets))
        try:
            if self._screen_mode():
                if ok and cp.screen_follows(assets):
                    return "follow"
                if not self._screen_stored:
                    return "screen_recommended"
                table = cp.SCREEN_PRESETS
            else:
                if self._assets_mode():
                    if self._follows():
                        return "recommended"
                elif self._prof is None:
                    return "none"
                elif self._on_display and ok and cp.follows_screen(assets):
                    return "recommended"
                table = cp.PRESETS
        except Exception:                               # noqa: BLE001
            log.exception("color profile starting point")
            return ""
        for k, prof in table:
            if prof is None or (k == "recommended" and self._on_display):
                continue
            if (prof.is_identity() and p.is_identity()) or (
                    prof.name == p.name and cp.same_numbers(prof, p)):
                return k
        return ""

    def _saved_state(self, p):
        """The Saved profiles list and the one in use: the file whose
        numbers the profile on show has, its own name first."""
        try:
            saved = cp.saved_profiles(self._profile_folders())
        except Exception:                               # noqa: BLE001
            log.exception("color profile saved list")
            saved = []
        same = [(n, path, prof) for n, path, prof in saved
                if cp.same_numbers(prof, p)]
        pick = next((path for n, path, prof in same
                     if p.name in (prof.name, n)), "")
        if not pick and same and p.name not in ("", "No change"):
            pick = same[0][1]
        return [{"value": path, "label": n} for n, path, _p in saved], pick

    def _file_state(self):
        """The file the bar's Files mode is on (PAD-368), for the page."""
        f = self._file
        if not f or self._file_mode() is None:
            return None
        return {"kind": f["kind"], "rel": f["rel"], "label": f["label"],
                "on": f.get("on"), "own": self._own() is not None}

    def _publish(self, problems=None):
        p = self._shown()
        saved, saved_on = self._saved_state(p)
        assets = self._project
        state = self._asset_state(assets)
        fstate = self._file_state()
        try:
            own_names = cp.own_profile_names(
                assets if assets and os.path.isdir(assets) else "")
        except Exception:                               # noqa: BLE001
            log.exception("color profile own names")
            own_names = {"images": {}, "videos": {}, "text": {}}
        if self._screen_mode():
            active = self._screen_stored
        elif fstate is not None:
            active = bool(fstate["on"] and not p.is_identity())
        elif self._assets_mode():
            active = bool(state["asset_active"]
                          and sum(state["asset_counts"].values()))
        else:
            active = self._prof is not None
        if self._screen_mode():
            presets = [{"key": k,
                        "label": cp.SCREEN_PRESET_LABELS.get(k)
                        or (v.name if v is not None else k),
                        "tip": cp.SCREEN_PRESET_TIPS.get(k, "")}
                       for k, v in cp.SCREEN_PRESETS]
        else:
            tips = dict(cp.PRESET_TIPS)
            if self._on_display:
                tips.update(cp.PRESET_TIPS_SPIKE2)
            presets = [{"key": k, "label": v.name, "tip": tips.get(k, "")}
                       for k, v in cp.PRESETS]
        values = dict(
            name=p.name, gamma=list(p.gamma), gain=list(p.gain),
            lift=max(p.lift), saturation=p.saturation,
            brightness=p.brightness, contrast=p.contrast, rev=self._rev,
            ranges=[list(r) for r in p.ranges],
            curves={ch: [list(pt) for pt in pts] for ch, pts in p.curves},
            active=active, mode=self._mode if self._on_display else "display",
            per_file=self._on_display,
            display_active=self._prof is not None,
            display_name=self._prof.label() if self._prof is not None else "",
            asset_name=(self._asset
                        or cp.recommended(assets, files=True)).label(),
            follows_screen=self._follows(),
            screen_stored=self._screen_stored,
            screen_follow=bool(self._screen_mode() and assets
                               and os.path.isdir(assets)
                               and cp.screen_follows(assets)),
            project=assets, file=fstate, own_names=own_names,
            **state,
            has_project=bool(assets and os.path.isdir(assets)),
            presets=presets,
            preset_on=self._preset_on(p, assets),
            saved=saved, saved_on=saved_on,
            parts=self._parts(assets),
            limits={k: list(v) for k, v in LIMITS.items()},
            range_limits={k: list(v) for k, v in cp.RANGE_LIMITS.items()},
            range_new=dict(cp.RANGE_NEW), max_ranges=cp.MAX_RANGES,
            max_points=cp.MAX_POINTS,
            can_undo=bool(self._undo.get(self._mode_key())),
            can_redo=bool(self._redo.get(self._mode_key())))
        if problems is not None:
            values["problems"] = list(problems)
        self.set(**values)

    def _parts(self, assets):
        """Which of the three profiles is in use (the Preview colors row's
        words, cp.preview_parts): the dots on the Color profiles bar's tabs,
        wherever it hangs (PAD-364: the Images tab has no preview row)."""
        try:
            return cp.preview_parts(assets if assets and os.path.isdir(assets)
                                    else "")
        except Exception:                               # noqa: BLE001
            log.exception("color profile parts")
            return cp.preview_parts("")

    # -- Undo / Redo (PAD-354) ----------------------------------------------
    # Each profile (overlay, individual files, machine screen) keeps its own
    # steps: what it was stored as in .staged_changes.json before each change,
    # so Undo puts back exactly that (No change, Recommended following the
    # screen, or numbers).  One slider dragged is one step; a starting point,
    # a Load or a Paste is one step each.
    def _mode_key(self):
        if self._screen_mode():
            return cp.SCREEN_KEY
        fm = self._file_mode()
        if fm is not None:
            return "file\n%s\n%s" % fm            # PAD-368: one file's own
        return cp.ASSET_KEY if self._assets_mode() else cp.KEY

    @staticmethod
    def _raw(data, key):
        if key.startswith("file\n"):
            _f, kind, rel = key.split("\n", 2)
            m = data.get(cp.FILE_PROFILES_KEY[kind])
            return m.get(rel) if isinstance(m, dict) else None
        return data.get(key)

    @staticmethod
    def _put_raw(data, key, value):
        if key.startswith("file\n"):
            _f, kind, rel = key.split("\n", 2)
            k = cp.FILE_PROFILES_KEY[kind]
            m = dict(data.get(k) or {}) if isinstance(data.get(k), dict) \
                else {}
            if value is None:
                m.pop(rel, None)
            else:
                m[rel] = value
            if m:
                data[k] = m
            else:
                data.pop(k, None)
        elif value is None:
            data.pop(key, None)
        else:
            data[key] = value

    def _stored_raw(self, key):
        d = self._raw(staged_changes.load(self._project), key)
        return json.dumps(d, sort_keys=True) if d is not None else None

    def _remember(self, key, before, group=None):
        """After a change to the profile stored under *key*: *before* (what
        it was) becomes an Undo step, unless nothing changed or *group* (a
        slider's name) is still being moved."""
        if self._stored_raw(key) == before:
            return
        self._redo.pop(key, None)
        now = time.monotonic()
        last = self._last_move.get(key)
        self._last_move[key] = (group, now)
        if group and last and last[0] == group                 and now - last[1] < UNDO_GROUP_S and self._undo.get(key):
            return
        steps = self._undo.setdefault(key, [])
        steps.append(before)
        del steps[:-UNDO_MAX]

    def _publish_undo(self):
        key = self._mode_key()
        self.set(can_undo=bool(self._undo.get(key)),
                 can_redo=bool(self._redo.get(key)))

    @rpc
    def undo(self, redo=False):
        """Undo (or Redo) the last change to the profile on show."""
        assets = self._project
        key = self._mode_key()
        steps = (self._redo if redo else self._undo).get(key)
        if not (steps and assets and os.path.isdir(assets)):
            return False
        back = steps.pop()
        (self._undo if redo else self._redo).setdefault(key, []).append(
            self._stored_raw(key))
        self._last_move.pop(key, None)
        try:
            data = staged_changes.load(assets)
            self._put_raw(data, key, None if back is None else json.loads(back))
            staged_changes.save(assets, data)
        except Exception as e:                          # noqa: BLE001
            self.set(problems=["could not undo (%s)" % e])
            return False
        self._load()
        self._changed(display=key in (cp.KEY, cp.SCREEN_KEY))
        self._tell_tabs()
        return True

    def _store(self, prof, rev=False, follow=False, group=None):
        """Stage *prof* for the project (``None`` or no change = none;
        *follow*: the machine screen follows the individual files one;
        *group*: the slider moved, so one drag is one Undo step)."""
        assets = self._project
        if not (assets and os.path.isdir(assets)):
            self.toast("Choose a project folder on the Extract tab first.",
                       "error")
            return False
        key = self._mode_key()
        before = self._stored_raw(key)
        done = self._store_mode(prof, rev, follow)
        if done:
            self._remember(key, before, group)
            self._publish_undo()
        return done

    def _store_mode(self, prof, rev, follow):
        assets = self._project
        if self._screen_mode():
            # the machine screen: preview only, nothing pending; None goes
            # back to the Recommended screen
            try:
                cp.store_screen_profile(assets, prof, follow=follow)
                self._screen, self._screen_stored = cp.screen_shown(assets)
                # a Recommended overlay or files profile follows the screen
                # (PAD-346)
                self._prof = cp.for_project(assets)
                self._asset = cp.asset_profile(assets)
            except Exception as e:                      # noqa: BLE001
                self.set(problems=["could not save the machine screen "
                                   "(%s)" % e])
                return False
            if rev:
                self._rev += 1
            self._publish(problems=[])
            self._changed()
            self._tell_tabs()
            return True
        if self._assets_mode():
            # the chosen-files profile: No change is stored as itself, so
            # the switches keep their places while the files go on as made
            if prof is None:
                prof = cp.Profile(name="No change")
            fm = self._file_mode()
            if fm is not None:
                return self._store_own(prof, rev)
            self._asset = prof
            try:
                cp.store_asset_profile(assets, prof)
            except Exception as e:                      # noqa: BLE001
                self.set(problems=["could not save the project's profile "
                                   "(%s)" % e])
                return False
            if rev:
                self._rev += 1
                self._files_preview_on()
            self._publish(problems=[])
            self._changed(display=False)
            self._tell_tabs()
            return True
        if prof is not None and prof.is_identity():
            prof = None
        self._prof = prof
        try:
            cp.store(assets, prof)
            # the files' Recommended follows the overlay (PAD-346)
            self._asset = cp.asset_profile(assets)
        except Exception as e:                          # noqa: BLE001
            self.set(problems=["could not save the project's profile (%s)"
                               % e])
            return False
        if rev:
            self._rev += 1
        self._publish(problems=[])
        self._changed()
        self._tell_tabs()
        return True

    def _store_own(self, prof, rev, follow=False):
        """PAD-368: the file on show gets a profile of its own (*follow*: the
        Recommended one), and the profile is attached to it."""
        kind, rel = self._file_mode()
        try:
            cp.store_own_profile(self._project, kind, rel, prof, follow=follow)
        except Exception as e:                          # noqa: BLE001
            self.set(problems=["could not save the file's profile (%s)" % e])
            return False
        self._attach()
        if rev:
            self._rev += 1
            self._files_preview_on()
        self._publish(problems=[])
        self._changed(display=False)
        self._tell_tabs()
        return True

    def _attach(self):
        """A profile picked for one file is meant for it: a file whose
        switch is off gets it switched on, where it has a switch."""
        f = self._file
        if not f or f.get("on") is not False:
            return
        how = f.get("attach") or {}
        try:
            if how.get("ns") in ("images", "video"):
                done = self.window.service(how["ns"]).set_color(f["rel"], True)
            elif how.get("ns") == "scenes" and how.get("node") is not None:
                done = self.window.service("text").scenes.tree_color(
                    how["node"], True)
            else:
                return
        except Exception:                               # noqa: BLE001
            log.exception("color profile attach")
            return
        if done:
            f["on"] = True

    def _files_preview_on(self):
        """PAD-369 (DragonRR): an individual files profile picked (a starting
        point, a saved one or a Load) is meant to be seen, so the Preview
        colors switch for individual files goes on in Scenes and on the Video
        players where it was off.  It stays on until it is turned off again.
        Nothing is drawn here: the redraw that follows the pick does it."""
        from .. import look_switches
        try:
            scenes = getattr(self.window.service("text"), "scenes", None)
        except Exception:                               # noqa: BLE001
            scenes = None
        for where, svc in (("scenes", scenes),
                           ("video", self.window.service("video"))):
            try:
                if where == "scenes":
                    sw = svc._look_sw() if svc is not None else None
                else:
                    sw = getattr(svc, "_lsw", None)
                if sw is None:
                    sw = look_switches.initial(self.window, where)
                if sw.get("files", True):
                    continue
                sw["files"] = True
                look_switches.save(self.window, where, sw)
                if where == "scenes" and svc is not None and getattr(
                        svc, "_alive", False):
                    svc._publish_look()
            except Exception:                           # noqa: BLE001
                log.exception("color profile preview switch %s", where)

    @rpc
    def set_file(self, kind=None, rel=None, label="", on=None, attach=None):
        """The Color profiles bar is open beside a clicked file (PAD-368):
        its Files mode shows and changes that file's profile.  No *rel*:
        back to the project's individual files profile."""
        if kind not in cp.FILE_PROFILES_KEY or not rel or not self._on_display:
            if self._file is not None:
                self._file = None
                self._rev += 1
                self._publish()
            return False
        f = {"kind": kind, "rel": str(rel), "label": str(label or "")[:120]
             or os.path.basename(str(rel)), "on": on,
             "attach": attach if isinstance(attach, dict) else None}
        same = (self._file is not None and self._file["kind"] == kind
                and self._file["rel"] == f["rel"])
        self._file = f
        if not same or self._mode != "assets":
            self._mode = "assets"
            self._rev += 1
        self._publish(problems=[] if not same else None)
        return True

    @rpc
    def file_shared(self):
        """"Same as the other files": the file on show drops its own profile
        and gets the project's individual files profile again (PAD-368)."""
        fm = self._file_mode()
        if fm is None:
            return False
        key = self._mode_key()
        before = self._stored_raw(key)
        try:
            cp.store_own_profile(self._project, fm[0], fm[1], None)
        except Exception as e:                          # noqa: BLE001
            self.set(problems=["could not save the file's profile (%s)" % e])
            return False
        self._remember(key, before)
        self._rev += 1
        self._publish(problems=[])
        self._publish_undo()
        self._changed(display=False)
        self._tell_tabs()
        return True

    def _tell_tabs(self):
        """The Images and Video tabs and an open Scenes editor show the
        chosen-files switches and the corrected pictures."""
        for ns, name in (("images", "color_all_changed"),
                         ("video", "color_all_changed"),
                         ("video", "publish_look"),
                         ("text", "scenes_pictures_changed")):
            try:
                fn = getattr(self.window.service(ns), name, None)
            except Exception:                           # noqa: BLE001
                fn = None
            if fn is not None:
                try:
                    fn()
                except Exception:                       # noqa: BLE001
                    log.exception("color profile %s.%s", ns, name)

    def _tell_scenes(self):
        """An open Scenes editor draws again through the new screen, and the
        Video tab's players follow (PAD-330)."""
        for ns, name in (("text", "scenes_pictures_changed"),
                         ("video", "publish_look")):
            try:
                fn = getattr(self.window.service(ns), name, None)
            except Exception:                           # noqa: BLE001
                fn = None
            if fn is not None:
                try:
                    fn()
                except Exception:                       # noqa: BLE001
                    log.exception("color profile %s redraw", ns)

    @rpc
    def set_mode(self, mode):
        """Whole screen / Chosen files / Machine screen (Spike 2): which
        profile the sliders and the preview show."""
        mode = (mode if mode in ("assets", "screen") and self._on_display
                else "display")
        if mode != self._mode:
            self._mode = mode
            self._rev += 1
        self._publish(problems=[])
        return self._mode

    @rpc
    def panel_open(self):
        """The Color profiles bar opened on the Scenes tab (PAD-350), or on
        the Images or Video tab (PAD-364): the profiles are read again from
        the project, as the tab does on show."""
        self.set(try_note="")
        self._load()
        return True

    @rpc
    def set_all(self, kind, on):
        """The chosen-files mode's tab-wide boxes: every replaced picture
        ("images") or video ("videos") without a switch of its own."""
        assets = self._project
        if not (assets and os.path.isdir(assets)) or kind not in (
                "images", "videos"):
            return False
        try:
            cp.set_asset_all(assets, kind, bool(on))
        except Exception:                               # noqa: BLE001
            log.exception("color profile set_all")
            return False
        self._publish(problems=[])
        self._changed(display=False)
        self._tell_tabs()
        return True

    def asset_switches_changed(self):
        """A file's own switch moved on the Images or Video tab or in
        Scenes: the counts here follow."""
        self._publish(problems=[])

    def _changed(self, display=True):
        """The Write tab's pending list, Emulate's offer and a running game's
        note follow a staged change (the Emulate notes are the display-wide
        profile's)."""
        hooks = (("write", "_maybe_rescan_write_preview"),)
        if display:
            hooks = (("emulate", "_refresh_colour_note"),
                     ("emulate", "colour_live")) + hooks
        for ns, name in hooks:
            fn = getattr(self.window.service(ns), name, None)
            if fn is not None:
                try:
                    fn()
                except Exception:                       # noqa: BLE001
                    log.exception("color profile %s.%s", ns, name)

    @rpc
    def set_params(self, params):
        """The page's sliders: any of name, gamma [r g b], gain [r g b],
        lift (one number, all three), saturation, brightness, contrast,
        ranges [[7 numbers], ...] and curves {channel: [[in, out], ...]}
        (PAD-339 on the machine screen, PAD-343 in every mode)."""
        p = self._shown()
        kw = dict(name=p.name, gamma=p.gamma, gain=p.gain, lift=p.lift,
                  saturation=p.saturation, brightness=p.brightness,
                  contrast=p.contrast, ranges=p.ranges, curves=p.curves)
        params = params or {}
        if "name" in params:
            kw["name"] = str(params["name"] or "").strip()[:60]
        for key in ("gamma", "gain"):
            if key in params:
                kw[key] = tuple(round(_clamp(key, v), 3)
                                for v in list(params[key])[:3])
        if "lift" in params:
            v = round(_clamp("lift", params["lift"]), 3)
            kw["lift"] = (v, v, v)
        for key in ("saturation", "brightness", "contrast"):
            if key in params:
                kw[key] = round(_clamp(key, params[key]), 3)
        if "ranges" in params or "curves" in params:
            ranges, curves = cp.extras_from(
                params.get("ranges", [list(r) for r in p.ranges]),
                params.get("curves", {ch: pts for ch, pts in p.curves}))
            kw["ranges"], kw["curves"] = ranges, curves
        if kw["name"] in ("", "No change"):
            kw["name"] = "My screen" if self._screen_mode() else "My profile"
        elif kw["name"] == cp.RECOMMENDED and "name" not in params \
                and self._follows():
            # moved off the Recommended one: from here it keeps its numbers
            # and no longer follows the machine screen (PAD-346)
            kw["name"] = "My profile"
        # one slider dragged (one key moved) is one Undo step
        group = next(iter(params)) if len(params) == 1 else None
        return self._store(cp.Profile(**kw), group=group)

    @rpc
    def preset(self, key):
        if self._screen_mode():
            for k, prof in cp.SCREEN_PRESETS:
                if k == key:
                    return self._store(prof, rev=True, follow=k == "follow")
            return False
        if key == "recommended" and self._on_display:
            return self._store_recommended()
        for k, prof in cp.PRESETS:
            if k == key:
                return self._store(None if k == "none" else prof, rev=True)
        return False

    def _store_recommended(self):
        """Spike 2's Recommended overlay or files profile: the machine
        screen undone, following it from now on (PAD-346)."""
        assets = self._project
        if not (assets and os.path.isdir(assets)):
            self.toast("Choose a project folder on the Extract tab first.",
                       "error")
            return False
        key = self._mode_key()
        before = self._stored_raw(key)
        done = self._store_recommended_mode()
        if done:
            self._remember(key, before)
            self._publish_undo()
        return done

    def _store_recommended_mode(self):
        assets = self._project
        if self._file_mode() is not None:
            return self._store_own(None, True, follow=True)
        try:
            if self._assets_mode():
                cp.store_asset_profile(assets, None)
                self._asset = cp.asset_profile(assets)
            else:
                cp.store(assets, None, follow=True)
                self._prof = cp.for_project(assets)
                self._asset = cp.asset_profile(assets)
        except Exception as e:                          # noqa: BLE001
            self.set(problems=["could not save the project's profile (%s)"
                               % e])
            return False
        self._rev += 1
        if self._assets_mode():
            self._files_preview_on()
        self._publish(problems=[])
        self._changed(display=not self._assets_mode())
        self._tell_tabs()
        return True

    def _save_name(self):
        """Save a copy's file name for the mode on show (PAD-341)."""
        if self._screen_mode():
            return "Machine Color Profile.txt"
        if self._assets_mode():
            return "File Color Profile.txt"
        return "Overlay Profile.txt" if self._on_display             else "Color Profile.txt"

    @rpc
    def save_copy(self):
        p = self._shown()
        path = self.window.ask_save(
            BROWSE_KEY, "Save a copy of this color profile",
            initialfile=self._save_name(), defaultextension=".txt",
            filetypes=[("Color profile", "*.txt"), ("All files", "*.*")],
            initialdir=self._save_dir())
        if not path:
            return False
        try:
            cp.save(p, path)
        except OSError as e:
            self.toast("Could not save the profile: %s" % e, "error")
            return False
        self.toast("Saved %s" % os.path.basename(path), "success")
        self._publish()
        return True

    def _save_dir(self):
        """Save a copy's first folder: the one it last used, else PAD's own
        Color profiles folder (made here), so the list has it."""
        try:
            last = self.window.last_browse_dir(BROWSE_KEY)
        except Exception:                               # noqa: BLE001
            last = ""
        if last:
            return last
        d = default_profiles_dir()
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            return None
        return d

    @rpc
    def load_file(self):
        path = self.window.ask_open(
            BROWSE_KEY, "Load a color profile",
            filetypes=[("Color profile", "*.txt"), ("All files", "*.*")],
            initialdir=self._save_dir())
        if not path:
            return False
        return self._load_path(path)

    @rpc
    def use_saved(self, path):
        """The Saved profiles list: load the file picked (PAD-360)."""
        known = {os.path.normcase(os.path.abspath(o))
                 for _n, o, _p in cp.saved_profiles(self._profile_folders())}
        if not path or os.path.normcase(os.path.abspath(path)) not in known:
            self._publish()
            return False
        return self._load_path(path)

    def _load_path(self, path):
        try:
            prof, problems = cp.read_file(path)
        except OSError as e:
            self.toast("Could not read the profile: %s" % e, "error")
            return False
        if prof.name in ("", "My profile", "My screen"):
            # a copy saved without a name of its own goes by its file's
            # (PAD-360), so the tab and the list say which one is in use
            stem = os.path.splitext(os.path.basename(path))[0]
            prof = cp.Profile(name=stem[:60],
                              gamma=prof.gamma, gain=prof.gain,
                              lift=prof.lift, saturation=prof.saturation,
                              brightness=prof.brightness,
                              contrast=prof.contrast, ranges=prof.ranges,
                              curves=prof.curves)
        problems = list(problems)
        self._store(prof, rev=True)
        if problems:
            self.set(problems=problems)
        self.toast("Loaded %s" % prof.label(), "success")
        return True

    @rpc
    def try_emulator(self):
        """"See it in the emulator": the Emulate tab runs this project's
        edits with the profile, restarting a running game."""
        emu = self.window.service("emulate")
        fn = getattr(emu, "try_colour", None)
        if fn is None or not getattr(emu, "_visible", False):
            self.set(try_note="This machine has no emulator in PAD yet.")
            return False
        note = fn()
        self.set(try_note=note or "")
        self.window.select_tab("emulate")
        return True

    def clear_replace_assignments(self, assets_dir):
        """Revert all: the project's profiles go with its other changes.
        The machine screen stays: it is the user's machine, not a change."""
        try:
            cp.store(assets_dir, None)
            cp.store_asset_profile(assets_dir, None)
            cp.set_asset_all(assets_dir, "images", False)
            cp.set_asset_all(assets_dir, "videos", False)
            for kind in cp.FILE_PROFILES_KEY:
                for rel in list(cp.own_profile_names(assets_dir)[kind]):
                    cp.store_own_profile(assets_dir, kind, rel, None)
        except Exception:                               # noqa: BLE001
            log.exception("color profile revert")
        same = (os.path.normcase(os.path.abspath(assets_dir or ""))
                == os.path.normcase(os.path.abspath(self._project or "")))
        if same:
            self._load()

    # -- the preview picture -----------------------------------------------
    def _replacement_pictures(self):
        """``[(label, path)]`` of the pictures the user has assigned on the
        Images tab of this project, for the preview's picker."""
        assets = self._assets()
        if not assets or not os.path.isdir(assets):
            return []
        try:
            from ...core import staged_changes
            saved = staged_changes.load(assets).get("image") or {}
        except Exception:                               # noqa: BLE001
            return []
        out, seen = [], set()
        for rel, path in sorted(saved.items()):
            if (isinstance(path, str) and os.path.isfile(path)
                    and path not in seen):
                seen.add(path)
                out.append((os.path.basename(path), path))
        return out[:60]

    def _publish_sample(self):
        mine = self._replacement_pictures()
        opts = [{"value": "card", "label": "Test card"}]
        opts += [{"value": p, "label": "Mine: %s" % label}
                 for label, p in mine]
        if self._sample not in ("card",) and not any(
                o["value"] == self._sample for o in opts):
            if os.path.isfile(self._sample):
                opts.append({"value": self._sample, "label": os.path.basename(
                    self._sample)})
            else:
                self._sample = "card"
        self.set(samples=opts, sample=self._sample,
                 sample_url=test_card_png() if self._sample == "card" else "",
                 sample_path="" if self._sample == "card" else self._sample)

    @rpc
    def pick_sample(self, value):
        if value == "browse":
            path = self.window.ask_open(
                "colour_profile_sample", "Preview the profile on a picture",
                filetypes=[("Pictures", "*.png *.jpg *.jpeg *.webp *.bmp"),
                           ("All files", "*.*")])
            if not path:
                self._publish_sample()
                return False
            value = path
        self._sample = value or "card"
        self._publish_sample()
        return True

    # -- hooks ---------------------------------------------------------------
    def rail_needs(self):
        return "project"

    def on_show(self):
        self.set(try_note="")
        # the tab itself is the project's profiles, never one file's
        self._file = None
        self._load()
        self._publish_sample()

    def on_project(self, folder):
        self._file = None
        self._load()

    def on_manufacturer(self, mfr):
        try:
            on_display = bool(mfr.colour_profile_on_display())
        except Exception:                               # noqa: BLE001
            on_display = False
        self._on_display = on_display
        if not on_display:
            self._mode = "display"
        self.set(on_display=on_display)
        self._load()


TAB = ColorTab
