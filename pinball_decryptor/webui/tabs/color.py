"""The Color profile tab (PAD-305): the colour correction a project's build
applies so the machine's display shows what the PC does.

A STAGED CHANGE OF THE PROJECT, like every other Replace tab's: the profile
the controls show is saved in the project's ``.staged_changes.json``
(core/colour_profile.py ``store``) the moment it changes, the Write tab lists
it as pending, the next build or Emulate Start applies it, and Revert all
clears it.  "No change" is the off state; there is no separate switch.
Save a copy / Load move a profile between projects (one per machine).
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
import logging
import os

from .base import TabService, rpc
from ...core import colour_profile as cp

log = logging.getLogger(__name__)

#: limits of the page's controls: the whole range a file accepts (PAD-338)
LIMITS = cp.LIMITS

_CARD_CACHE = []


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
        self.set(sample="card", sample_url="", sample_path="", samples=[],
                 problems=[], rev=0, active=False, project="",
                 has_project=False, try_note="", mode="display",
                 per_file=False, all_images=False, all_videos=False,
                 asset_counts={"images": 0, "videos": 0, "added": 0},
                 asset_active=False)

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

    def _shown(self):
        if self._screen_mode():
            return self._screen or cp.SCREEN_PRESETS[0][1]
        if self._assets_mode():
            return self._asset or cp.recommended(self._project, files=True)
        return self._prof or cp.Profile(name="No change")

    def _follows(self):
        """Is the mode on show the Recommended one following the machine
        screen (PAD-346)?"""
        assets = self._project
        if not (self._on_display and assets and os.path.isdir(assets)):
            return False
        try:
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
               "asset_counts": {"images": 0, "videos": 0, "added": 0},
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

    def _publish(self, problems=None):
        p = self._shown()
        assets = self._project
        state = self._asset_state(assets)
        if self._screen_mode():
            active = self._screen_stored
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
            project=assets,
            **state,
            has_project=bool(assets and os.path.isdir(assets)),
            presets=presets,
            limits={k: list(v) for k, v in LIMITS.items()},
            range_limits={k: list(v) for k, v in cp.RANGE_LIMITS.items()},
            range_new=dict(cp.RANGE_NEW), max_ranges=cp.MAX_RANGES,
            max_points=cp.MAX_POINTS)
        if problems is not None:
            values["problems"] = list(problems)
        self.set(**values)

    def _store(self, prof, rev=False, follow=False):
        """Stage *prof* for the project (``None`` or no change = none;
        *follow*: the machine screen follows the individual files one)."""
        assets = self._project
        if not (assets and os.path.isdir(assets)):
            self.toast("Choose a project folder on the Extract tab first.",
                       "error")
            return False
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
            self._asset = prof
            try:
                cp.store_asset_profile(assets, prof)
            except Exception as e:                      # noqa: BLE001
                self.set(problems=["could not save the project's profile "
                                   "(%s)" % e])
                return False
            if rev:
                self._rev += 1
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
        """The Scenes tab's Color profiles bar opened (PAD-350): the
        profiles are read again from the project, as the tab does on show."""
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
        return self._store(cp.Profile(**kw))

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
            "colour_profile", "Save a copy of this color profile",
            initialfile=self._save_name(), defaultextension=".txt",
            filetypes=[("Color profile", "*.txt"), ("All files", "*.*")])
        if not path:
            return False
        try:
            cp.save(p, path)
        except OSError as e:
            self.toast("Could not save the profile: %s" % e, "error")
            return False
        self.toast("Saved %s" % os.path.basename(path), "success")
        return True

    @rpc
    def load_file(self):
        path = self.window.ask_open(
            "colour_profile", "Load a color profile",
            filetypes=[("Color profile", "*.txt"), ("All files", "*.*")])
        if not path:
            return False
        try:
            prof, problems = cp.read_file(path)
        except OSError as e:
            self.toast("Could not read the profile: %s" % e, "error")
            return False
        if not prof.name:
            prof = cp.Profile(name=os.path.splitext(os.path.basename(path))[0],
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
        self._load()
        self._publish_sample()

    def on_project(self, folder):
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
