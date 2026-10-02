"""Colour profile: the colour correction a project's build applies for the
machine's screen (PAD-305).

WHY.  A machine's display is not the PC monitor the art was made on.
A field report photographed a display test card on a Stern Godzilla: mid greys come
out far too bright and blue, saturated patches bloom, and everything under
about 24/255 sinks into one lifted black.  A profile pre-corrects for that:
the PC copy stays the "golden" asset, and only what the machine is given is
bent so it shows what the PC shows.

A STAGED CHANGE OF THE PROJECT, like every other Replace tab's: the Color
profile tab records the project's profile in its ``.staged_changes.json``
(:data:`KEY`), the Write tab lists it as pending, the next build or Emulate
Start applies it, and Revert all clears it.  No profile (or one that changes
nothing) is the "off" state; there is no separate switch.

WHERE IT APPLIES.  On Spike 2, in the game's own drawing shaders
(plugins/stern/shader_profile.py): everything on the screen, no file touched.
Elsewhere, at staging, to the user's replacement pictures and videos (the
only thing PAD can reach there), each read from the user's untouched source
every time, so it can never land twice.

THE MATHS, kept identical between Pillow (pictures), ffmpeg (videos) and the
GLSL the shaders get:

1. saturation: each pixel mixed toward its own Rec.601 grey by
   ``saturation`` (1 = unchanged, 0 = greyscale).
2. per channel: ``out = lift + (1 - lift) * clip(in * gain) ** gamma`` on a
   0..1 scale.  Gamma above 1 darkens the mid tones (the machine shows them
   too bright), gain below 1 pulls a channel down overall, lift raises the
   darkest values.

A COPY is plain ``key = value`` text (:func:`to_text`, :func:`read_file`), so
a user can keep one per machine, share it, or edit it in any text editor and
Load it back.  Unknown keys and bad values are skipped and named, never fatal.

A SECOND PROFILE, FOR CHOSEN FILES (PAD-312).  The display-wide profile
reaches the game's own art too, which Stern already made for that screen;
a field report wanted only the NEW pictures and videos corrected, and each
one switchable.  So a project also carries a chosen-files profile
(:data:`ASSET_KEY`, the Recommended one until the user changes it) that is
baked into a replacement picture or video as it is staged, and into a
picture added in Scenes, when that file is switched on: a tab-wide box per
kind (:data:`ALL_IMAGES_KEY`, :data:`ALL_VIDEOS_KEY`) that every file
follows unless it has a switch of its own (:data:`IMAGE_SLOTS_KEY`,
:data:`VIDEO_SLOTS_KEY`, ``{rel: bool}``; an added picture's switch is the
``color`` key of its own scene edit).  The two profiles are independent and
compose: the game then draws the baked file through the display-wide one.
Where the display-wide profile corrects the files itself (not Spike 2) it
wins, and the chosen-files switches are not offered.
"""

import contextlib
import threading
from dataclasses import dataclass

#: The project's profile in its ``.staged_changes.json``.
KEY = "color_profile"

#: The chosen-files profile (PAD-312) and its switches, in the same file.
ASSET_KEY = "asset_color_profile"
#: The machine's screen as the Scenes preview draws it (PAD-324): what the
#: screen does to what it is given, preview only, never written to a card.
#: Absent = the individual files profile, undone (PAD-312's model).
SCREEN_KEY = "screen_profile"
ALL_IMAGES_KEY = "color_all_images"
ALL_VIDEOS_KEY = "color_all_videos"
IMAGE_SLOTS_KEY = "image_color_slots"
VIDEO_SLOTS_KEY = "video_color_slots"

#: Rec.601 luma weights: the grey a pixel is desaturated toward.
_LUMA = (0.299, 0.587, 0.114)

#: The profile a new file starts from: Stern Godzilla, read off a field
#: report's photographs of a display test card on the machine (PAD-305).  The
#: machine showed 128 grey as roughly (164, 187, 226) and 64 as (100, 113,
#: 148): mids far too bright, most of all in blue, then green, while white
#: stayed white.  Darkening each channel's mids by its own gamma (and a touch
#: less colour) is the pre-correction; a phone photo is not a colour meter,
#: so this is a starting point to tune against the test card, not a
#: calibration.
DEFAULT_TEXT = """\
# Pinball Asset Decryptor colour profile
#
# Corrects colors for a pinball machine's screen.  Load it on a project's
# Color profile tab and every build of that project applies it (on Spike 2,
# to everything the game draws).  No picture or video file is changed.
#
# Edit the numbers, save, and Load it again.  Three numbers = red green blue.
#
#   gamma       above 1 darkens the mid tones, below 1 brightens them
#   gain        multiplies the channel (0.9 = 10% less of that colour)
#   lift        raises the darkest values (0.05 = black becomes 13 of 255)
#   saturation  1 = unchanged, below 1 = less colour, above 1 = more
#
# "Recommended": made from photos of a display test card on a Stern Spike 2
# machine (a Godzilla), whose middle shades show too bright and too blue.

name = Recommended
gamma = 1.10 1.20 1.35
gain = 1.00 1.00 1.00
lift = 0.00 0.00 0.00
saturation = 0.90
"""


@dataclass(frozen=True)
class Profile:
    name: str = ""
    gamma: tuple = (1.0, 1.0, 1.0)
    gain: tuple = (1.0, 1.0, 1.0)
    lift: tuple = (0.0, 0.0, 0.0)
    saturation: float = 1.0

    def is_identity(self):
        return (self.gamma == (1.0, 1.0, 1.0) and self.gain == (1.0, 1.0, 1.0)
                and self.lift == (0.0, 0.0, 0.0) and self.saturation == 1.0)

    def label(self):
        return self.name or "colour profile"

    # -- the maths ----------------------------------------------------------
    def matrix(self):
        """The 3x3 saturation matrix, row-major (out_r = row 0 . rgb)."""
        s = self.saturation
        rows = []
        for i in range(3):
            rows.append(tuple((1 - s) * _LUMA[j] + (s if i == j else 0.0)
                              for j in range(3)))
        return tuple(rows)

    def table(self, channel):
        """256 output values for input 0..255 on *channel* (0 r, 1 g, 2 b)."""
        g, k, lo = self.gamma[channel], self.gain[channel], self.lift[channel]
        out = []
        for v in range(256):
            x = min(max(v / 255.0 * k, 0.0), 1.0)
            y = lo + (1.0 - lo) * (x ** g)
            out.append(int(min(max(y * 255.0 + 0.5, 0), 255)))
        return out

    def ffmpeg_filters(self):
        """The same correction as ffmpeg filters, in order."""
        out = []
        if self.saturation != 1.0:
            m = self.matrix()
            names = ("r", "g", "b")
            out.append("colorchannelmixer=" + ":".join(
                "%s%s=%.6f" % (names[i], names[j], m[i][j])
                for i in range(3) for j in range(3)))
        exprs = []
        for i, ch in enumerate(("r", "g", "b")):
            g, k, lo = self.gamma[i], self.gain[i], self.lift[i]
            if g == 1.0 and k == 1.0 and lo == 0.0:
                continue
            # commas inside an option are escaped for the filtergraph parser
            exprs.append(
                "%s=%.6f*255+%.6f*pow(clip(val*%.6f/255\\,0\\,1)\\,%.6f)*255+0.5"
                % (ch, lo, 1.0 - lo, k, g))
        if exprs:
            out.append("lutrgb=" + ":".join(exprs))
        return out

    def apply_array(self, rgb):
        """*rgb* (uint8 ``(h, w, 3)``) corrected, the same maths as
        :meth:`apply_image`."""
        import numpy as np
        out = np.asarray(rgb, np.uint8)
        if self.saturation != 1.0:
            m = np.asarray(self.matrix(), np.float32)
            out = np.clip(out.astype(np.float32) @ m.T + 0.5, 0, 255).astype(
                np.uint8)
        luts = [np.asarray(self.table(c), np.uint8) for c in range(3)]
        return np.stack([luts[c][out[..., c]] for c in range(3)], axis=-1)

    def undo_table(self, channel):
        """The inverse of :meth:`table` on *channel*: what the machine's
        screen does to a value this profile corrects (PAD-312).  Where the
        correction clips, the inverse holds at the edge."""
        g, k, lo = self.gamma[channel], self.gain[channel], self.lift[channel]
        out = []
        for v in range(256):
            y = v / 255.0
            x = (y - lo) / (1.0 - lo) if lo < 1.0 else y
            x = min(max(x, 0.0), 1.0) ** (1.0 / g)
            if k > 0:
                x = x / k
            out.append(int(min(max(x * 255.0 + 0.5, 0), 255)))
        return out

    def inverse(self):
        """A forward profile that does what :meth:`undo_array` does (PAD-324):
        the screen this profile corrects for, as sliders can show it.  Exact
        for gamma and gain; the lift is dropped (it has no forward form) and
        the saturation is mixed before the shades rather than after, so it
        is a close starting point, not a bit-exact copy.  Black and white
        cannot be undone and gives full color back."""
        gamma = tuple(1.0 / g if g > 0 else 1.0 for g in self.gamma)
        gain = tuple((k ** -g) if k > 0 else 1.0
                     for k, g in zip(self.gain, self.gamma))
        sat = 1.0 / self.saturation if self.saturation > 0 else 1.0
        r = lambda v: round(v, 3)                       # noqa: E731
        return Profile(name=self.name, gamma=tuple(r(v) for v in gamma),
                       gain=tuple(r(v) for v in gain), lift=(0.0, 0.0, 0.0),
                       saturation=r(sat))

    def undo_array(self, rgb):
        """*rgb* (uint8 ``(h, w, 3)``) as the machine's screen would show
        it, taking this profile as the correction measured for that screen:
        the inverse of :meth:`apply_array`.  Black and white (saturation 0)
        cannot be undone and is left as it is."""
        import numpy as np
        src = np.asarray(rgb, np.uint8)
        luts = [np.asarray(self.undo_table(c), np.uint8) for c in range(3)]
        out = np.stack([luts[c][src[..., c]] for c in range(3)], axis=-1)
        if self.saturation not in (0.0, 1.0):
            m = np.asarray(Profile(saturation=1.0 / self.saturation).matrix(),
                           np.float32)
            out = np.clip(out.astype(np.float32) @ m.T + 0.5, 0, 255).astype(
                np.uint8)
        return out

    def apply_image(self, im):
        """*im* (any Pillow mode) corrected; alpha passes through untouched.
        Returns a new RGB or RGBA image."""
        from PIL import Image
        alpha = None
        if im.mode in ("RGBA", "LA", "PA") or (
                im.mode == "P" and "transparency" in im.info):
            im = im.convert("RGBA")
            alpha = im.getchannel("A")
            rgb = im.convert("RGB")
        else:
            rgb = im.convert("RGB")
        if self.saturation != 1.0:
            m = self.matrix()
            rgb = rgb.convert("RGB", m[0] + (0.0,) + m[1] + (0.0,)
                              + m[2] + (0.0,))
        rgb = rgb.point(self.table(0) + self.table(1) + self.table(2))
        if alpha is not None:
            rgb.putalpha(alpha)
        return rgb if alpha is not None else rgb.convert("RGB")


def _numbers(text, n):
    vals = [float(t) for t in text.replace(",", " ").split()]
    if len(vals) == 1 and n == 3:
        vals = vals * 3
    if len(vals) != n:
        raise ValueError("needs %d number%s" % (n, "" if n == 1 else "s"))
    return tuple(vals)


def parse(text):
    """``(Profile, [problem, ...])`` from the file's text.  A bad line is
    skipped and named; it never raises."""
    fields = {}
    problems = []
    limits = {"gamma": (0.1, 5.0), "gain": (0.0, 4.0), "lift": (0.0, 0.9),
              "saturation": (0.0, 4.0)}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, sep, val = line.partition("=")
        key = key.strip().lower()
        val = val.strip()
        if not sep:
            problems.append("line %d: no '=' (%s)" % (n, raw.strip()))
            continue
        if key == "name":
            fields["name"] = val
            continue
        if key not in limits:
            problems.append("line %d: unknown setting '%s'" % (n, key))
            continue
        try:
            nums = _numbers(val, 1 if key == "saturation" else 3)
        except ValueError as e:
            problems.append("line %d: %s %s" % (n, key, e))
            continue
        lo, hi = limits[key]
        if any(not (lo <= v <= hi) for v in nums):
            problems.append("line %d: %s must be between %g and %g"
                            % (n, key, lo, hi))
            continue
        fields[key] = nums[0] if key == "saturation" else nums
    return Profile(**fields), problems


def _from_dict(d):
    try:
        return Profile(name=str(d.get("name") or ""),
                       gamma=tuple(float(v) for v in d["gamma"])[:3],
                       gain=tuple(float(v) for v in d["gain"])[:3],
                       lift=tuple(float(v) for v in d["lift"])[:3],
                       saturation=float(d["saturation"]))
    except (KeyError, TypeError, ValueError):
        return None


def for_project(assets_dir):
    """The profile staged for *assets_dir*, or ``None`` (none staged)."""
    from . import staged_changes
    d = staged_changes.load(assets_dir).get(KEY)
    return _from_dict(d) if isinstance(d, dict) else None


def store(assets_dir, prof):
    """Stage *prof* for *assets_dir*; ``None`` (or a profile that changes
    nothing) takes it away."""
    from . import staged_changes
    data = staged_changes.load(assets_dir)
    if prof is None or prof.is_identity():
        data.pop(KEY, None)
    else:
        data[KEY] = _profile_dict(prof)
    staged_changes.save(assets_dir, data)


#: The emulator's "stock colours" switch: when not None it wins over the
#: project's profile for as long as :func:`forced` holds it.  Module-wide
#: rather than per thread, because the engine fans some of an override build
#: out to a thread pool; the Emulate tab only holds it around its own
#: preparation, and Spike 2 staging around its file staging.
_FORCED = None
_FORCED_LOCK = threading.Lock()


@contextlib.contextmanager
def forced(on):
    """Within the block, :func:`active` answers ``None`` when *on* is False
    (``None`` leaves it to the project)."""
    global _FORCED
    with _FORCED_LOCK:
        prev, _FORCED = _FORCED, on
    try:
        yield
    finally:
        with _FORCED_LOCK:
            _FORCED = prev


def active(assets_dir):
    """The profile a build of *assets_dir* applies now, or ``None``."""
    if _FORCED is False:
        return None
    prof = for_project(assets_dir)
    return None if prof is None or prof.is_identity() else prof


def signature(assets_dir):
    """A short text that changes whenever what :func:`active` would apply
    changes ("" when nothing): an emulator override set records it so a
    changed or held-off profile rebuilds the set rather than reusing it."""
    prof = active(assets_dir)
    if prof is None:
        return ""
    return "%s|%s|%s|%s" % (prof.gamma, prof.gain, prof.lift, prof.saturation)


# -- the chosen-files profile (PAD-312) ---------------------------------------

def _profile_dict(prof):
    return {"name": prof.name, "gamma": list(prof.gamma),
            "gain": list(prof.gain), "lift": list(prof.lift),
            "saturation": prof.saturation}


def asset_profile(assets_dir):
    """The profile baked into the chosen files of *assets_dir*: the one
    stored, else the Recommended starting point (a new project corrects the
    files it is told to the way the test card said to)."""
    from . import staged_changes
    d = staged_changes.load(assets_dir).get(ASSET_KEY)
    prof = _from_dict(d) if isinstance(d, dict) else None
    return prof if prof is not None else PRESETS[0][1]


def asset_stored(assets_dir):
    """Has the user set the chosen-files profile, or is it still the default?"""
    from . import staged_changes
    return isinstance(staged_changes.load(assets_dir).get(ASSET_KEY), dict)


def store_asset_profile(assets_dir, prof):
    """Set the chosen-files profile of *assets_dir* (``None`` = back to the
    default).  A profile that changes nothing IS stored: it is how the
    switches stay as they are while the files go on uncorrected."""
    from . import staged_changes
    data = staged_changes.load(assets_dir)
    if prof is None:
        data.pop(ASSET_KEY, None)
    else:
        data[ASSET_KEY] = _profile_dict(prof)
    staged_changes.save(assets_dir, data)


def asset_active(assets_dir):
    """The chosen-files profile when it changes something, else ``None``."""
    prof = asset_profile(assets_dir)
    return None if prof.is_identity() else prof


_KIND = {"images": (ALL_IMAGES_KEY, IMAGE_SLOTS_KEY),
         "videos": (ALL_VIDEOS_KEY, VIDEO_SLOTS_KEY)}


def _kind_keys(kind):
    try:
        return _KIND[kind]
    except KeyError:
        raise ValueError("kind must be images or videos, not %r" % (kind,))


def asset_settings(assets_dir):
    """The switches: ``{"all_images", "all_videos", "images": {rel: bool},
    "videos": {rel: bool}}`` (a file with no switch of its own follows its
    kind's box)."""
    from . import staged_changes
    data = staged_changes.load(assets_dir) if assets_dir else {}

    def _slots(key):
        m = data.get(key)
        return ({str(r): bool(v) for r, v in m.items()}
                if isinstance(m, dict) else {})
    return {"all_images": bool(data.get(ALL_IMAGES_KEY)),
            "all_videos": bool(data.get(ALL_VIDEOS_KEY)),
            "images": _slots(IMAGE_SLOTS_KEY),
            "videos": _slots(VIDEO_SLOTS_KEY)}


def set_asset_all(assets_dir, kind, on):
    """The tab-wide box of *kind* ("images" / "videos"): every replaced file
    of that kind without a switch of its own follows it."""
    all_key, _slots_key = _kind_keys(kind)
    from . import staged_changes
    data = staged_changes.load(assets_dir)
    if on:
        data[all_key] = True
    else:
        data.pop(all_key, None)
    staged_changes.save(assets_dir, data)


def set_asset_slot(assets_dir, kind, rel, value):
    """One file's own switch: ``True`` / ``False``, or ``None`` to follow
    its kind's box again."""
    _all_key, slots_key = _kind_keys(kind)
    from . import staged_changes
    data = staged_changes.load(assets_dir)
    m = dict(data.get(slots_key) or {}) if isinstance(
        data.get(slots_key), dict) else {}
    if value is None:
        m.pop(rel, None)
    else:
        m[rel] = bool(value)
    if m:
        data[slots_key] = m
    else:
        data.pop(slots_key, None)
    staged_changes.save(assets_dir, data)


def asset_applies(settings, kind, rel, own=None):
    """Is *rel* (of *kind*) switched on?  *own*, when not ``None``, is the
    file's own switch given by the caller (a scene edit's ``color`` key)."""
    if own is None:
        own = settings.get(kind, {}).get(rel)
    if own is not None:
        return bool(own)
    return bool(settings.get("all_" + kind))


def asset_map(assets_dir, kind, rels):
    """``{rel: Profile}`` for the files among *rels* that get the
    chosen-files profile baked in as they are staged; empty when the
    profile changes nothing or no file is switched on."""
    if not assets_dir:
        return {}
    prof = asset_active(assets_dir)
    if prof is None:
        return {}
    settings = asset_settings(assets_dir)
    return {rel: prof for rel in rels if asset_applies(settings, kind, rel)}


def added_picture_colour(assets_dir, op, settings=None, prof=None):
    """The profile a picture added in Scenes (*op*, an ``add_picture``
    edit) is written with, or ``None``: its own ``color`` key, else the
    pictures box."""
    if not assets_dir:
        return None
    if prof is None:
        prof = asset_active(assets_dir)
    if prof is None:
        return None
    if settings is None:
        settings = asset_settings(assets_dir)
    on = asset_applies(settings, "images", op.get("image") or "",
                       own=op.get("color"))
    return prof if on else None


def screen_profile(assets_dir):
    """The machine's screen stored for *assets_dir* (PAD-324), or ``None``:
    then the Scenes preview takes the individual files profile, undone."""
    from . import staged_changes
    d = staged_changes.load(assets_dir).get(SCREEN_KEY) if assets_dir else None
    return _from_dict(d) if isinstance(d, dict) else None


def store_screen_profile(assets_dir, prof):
    """Set the machine's screen of *assets_dir* (``None`` = back to the
    individual files profile, undone).  No change IS stored: it says the
    PC shows what the machine does.  Preview only, so nothing is pending."""
    from . import staged_changes
    data = staged_changes.load(assets_dir)
    if prof is None:
        data.pop(SCREEN_KEY, None)
    else:
        data[SCREEN_KEY] = _profile_dict(prof)
    staged_changes.save(assets_dir, data)


def screen_shown(assets_dir):
    """The screen the Scenes preview uses now, as sliders can show it:
    the stored one, else the individual files profile's :meth:`inverse`.
    ``(profile, stored)``."""
    prof = screen_profile(assets_dir)
    if prof is not None:
        return prof, True
    files = asset_profile(assets_dir)
    inv = files.inverse()
    if files == PRESETS[0][1]:
        name = "Recommended screen"
    elif inv.is_identity():
        name = "No change"
    else:
        name = "%s, undone" % files.label()
    return Profile(name=name, gamma=inv.gamma, gain=inv.gain, lift=inv.lift,
                   saturation=inv.saturation), False


def machine_view(assets_dir):
    """A function ``rgb uint8 array -> rgb uint8 array`` showing a frame of
    *assets_dir* the way the machine's screen will (PAD-312): through the
    whole-screen profile, as the game's shaders draw it, then through the
    screen itself.  The screen is the one stored on the Color profile tab
    (PAD-324, applied forwards), else the inverse of the chosen-files
    profile (that profile is the correction measured for the screen, so
    undoing it IS the screen).  ``None`` when there is nothing to show."""
    display = active(assets_dir)
    stored = screen_profile(assets_dir)
    if stored is not None:
        screen, undo = (None if stored.is_identity() else stored), False
    else:
        screen, undo = asset_active(assets_dir), True
    if display is None and screen is None:
        return None

    def view(rgb):
        if display is not None:
            rgb = display.apply_array(rgb)
        if screen is not None:
            rgb = screen.undo_array(rgb) if undo else screen.apply_array(rgb)
        return rgb
    return view


def asset_counts(assets_dir):
    """How many files the chosen-files profile reaches now: ``{"images",
    "videos", "added"}`` (replaced pictures, replaced videos, pictures
    added in Scenes), by the switches alone (the profile may still be No
    change)."""
    from . import staged_changes
    out = {"images": 0, "videos": 0, "added": 0}
    if not assets_dir:
        return out
    data = staged_changes.load(assets_dir)
    settings = asset_settings(assets_dir)
    for kind, key in (("images", "image"), ("videos", "video")):
        picks = data.get(key) or {}
        if isinstance(picks, dict):
            out[kind] = sum(1 for rel, src in picks.items()
                            if src and asset_applies(settings, kind, rel))
    try:
        from ..plugins.stern import scene_edit
        for ops in scene_edit.load(assets_dir).values():
            for op in ops or ():
                if (isinstance(op, dict) and op.get("op") == "add_picture"
                        and asset_applies(settings, "images",
                                          op.get("image") or "",
                                          own=op.get("color"))):
                    out["added"] += 1
    except Exception:                                   # noqa: BLE001
        pass
    return out


def asset_signature(assets_dir):
    """A short text that changes whenever what the chosen-files profile
    would bake into which file changes ("" when nothing)."""
    prof = asset_active(assets_dir)
    if prof is None:
        return ""
    s = asset_settings(assets_dir)
    return "%s|%s|%s|%s|%s|%s|%s|%s" % (
        prof.gamma, prof.gain, prof.lift, prof.saturation,
        s["all_images"], s["all_videos"], sorted(s["images"].items()),
        sorted(s["videos"].items()))


def _fmt(nums):
    return " ".join("%.2f" % v for v in nums)


def to_text(prof):
    """The file text for *prof*: the explanatory header, then its values."""
    head = DEFAULT_TEXT.split("\nname =", 1)[0]
    return ("%s\nname = %s\ngamma = %s\ngain = %s\nlift = %s\n"
            "saturation = %.2f\n" % (head, prof.name or "My profile",
                                     _fmt(prof.gamma), _fmt(prof.gain),
                                     _fmt(prof.lift), prof.saturation))


def save(prof, path):
    """Write *prof* to the text file *path* (Save a copy)."""
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(to_text(prof))
    os.replace(tmp, path)
    return path


def read_file(path):
    """``(Profile, problems)`` from any profile file (Load...)."""
    with open(path, encoding="utf-8-sig") as f:
        return parse(f.read())


#: Starting points the Color profile tab offers.  The first is the default
#: profile, named "Recommended" in the tab (it was measured on a Godzilla,
#: but nothing in it is Godzilla's own: it is the display that it corrects).
PRESETS = (
    ("recommended", parse(DEFAULT_TEXT)[0]),
    ("none", Profile(name="No change")),
    # Black-and-white playfield editions (EHoH, Godzilla): every picture as
    # its own grey (Rec.601 luma), nothing else changed.
    ("bw", Profile(name="Black and white", saturation=0.0)),
)

#: The tab's tooltip for each starting point: how it was made.
#: The Machine screen mode's starting points (PAD-324): what the screen
#: does, so Recommended is the measured correction run forwards the other way.
SCREEN_PRESETS = (
    ("screen_recommended", Profile(
        name="Recommended screen", **{
            k: v for k, v in vars(PRESETS[0][1].inverse()).items()
            if k != "name"})),
    ("none", Profile(name="No change")),
    ("bw", Profile(name="Black and white", saturation=0.0)),
    ("follow", None),
)

SCREEN_PRESET_LABELS = {"follow": "Same as individual files"}

SCREEN_PRESET_TIPS = {
    "screen_recommended": (
        "The screen measured on a real Stern Spike 2 Godzilla: a mid grey "
        "(128, 128, 128) came out around (164, 187, 226), too bright and "
        "most of all too blue, while white stayed white. A phone photo is "
        "not a color meter: nudge it until Scenes matches your machine."),
    "none": "The machine shows colors exactly as your PC does.",
    "bw": "A screen that shows everything in greys, the game's own art too.",
    "follow": ("The individual files profile, undone: what Scenes used "
               "before you set a screen of your own."),
}

PRESET_TIPS = {
    "recommended": (
        "Made from photos of a display test card on a real Stern Spike 2 "
        "machine (a Godzilla). The card's grey steps and color patches "
        "were measured in the photos: a mid grey (128, 128, 128) came out "
        "around (164, 187, 226), far too bright and most of all in blue, "
        "then green, while white stayed white. This profile darkens each "
        "color's middle shades to pull that back (red 10%, green 20%, blue "
        "35% darker) and calms colors a little (90% strength). A phone "
        "photo is not a color meter, so treat it as a starting point and "
        "tune it against your own machine."),
    "none": "Leaves every color as you made it.",
    "bw": ("Every picture and video in greys, for a black-and-white "
           "playfield edition. Nothing else is changed."),
}
