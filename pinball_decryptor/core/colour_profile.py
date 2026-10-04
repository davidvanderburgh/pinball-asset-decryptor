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

BRIGHTNESS AND CONTRAST (PAD-333) are two more numbers on the profile, but
no new term in the maths: both act on the shade before step 2, as
``clip(in * brightness * k) ** contrast`` with ``k = 2 * 0.5 ** (1 /
contrast)`` (so a mid grey stays a mid grey and contrast is the slope
there), and that folds exactly into each channel's own gain and gamma
(:meth:`Profile.curve`).  So every place that applies a profile (Pillow,
ffmpeg, the shaders, the browser previews) gets them with no change of its
own, and the machine's boot menu still finds its fixed shader slots.

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

The game's own pictures are locked out of it, except on the advanced
"Unlock the game's own pictures" box, one setting shown on the Images tab
(PAD-335) and above the Scenes Layers list (PAD-344) (:data:`STOCK_IMAGES_KEY`): then a stock picture with its own switch on is
staged from its pristine bytes with the profile baked in, the way a
replacement is.  The tab-wide box never reaches a stock picture.
"""

import contextlib
import functools
import os
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
#: stored under SCREEN_KEY alone: "Same as individual files" (PAD-341)
SCREEN_FOLLOW = "follow"
ALL_IMAGES_KEY = "color_all_images"
ALL_VIDEOS_KEY = "color_all_videos"
IMAGE_SLOTS_KEY = "image_color_slots"
VIDEO_SLOTS_KEY = "video_color_slots"
#: The Images tab's advanced box (PAD-335): the game's own pictures unlocked.
STOCK_IMAGES_KEY = "image_color_unlocked"
#: The Video tab's Advanced box (PAD-336): the game's own clips get a Color
#: switch too, and one switched on is re-encoded from its own original with
#: the individual files profile.  Off (absent), they stay locked.
STOCK_VIDEOS_KEY = "video_color_stock"

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
#   brightness  1 = unchanged, 1.2 = 20% brighter, 0.8 = 20% darker
#   contrast    1 = unchanged, above 1 = more, below 1 = less
#
# "Recommended": made from photos of a display test card on a Stern Spike 2
# machine (a Godzilla), whose middle shades show too bright and too blue.

name = Recommended
gamma = 1.10 1.20 1.35
gain = 1.00 1.00 1.00
lift = 0.00 0.00 0.00
saturation = 0.90
brightness = 1.00
contrast = 1.00
"""


#: every number's range, for a file and for the tab's sliders alike (PAD-338:
#: the sliders used to stop well inside it).  Gamma and contrast stop short
#: of 0, where every shade would turn white or black.
LIMITS = {"gamma": (0.1, 5.0), "gain": (0.0, 4.0), "lift": (0.0, 0.9),
          "saturation": (0.0, 4.0), "brightness": (0.0, 4.0),
          "contrast": (0.1, 4.0)}

#: the largest folded gain or gamma: the shader's ``%.6f`` slots hold
#: [0, 10) (plugins/stern/shader_profile.py), so every use stops there too
#: and the machine draws what the preview did.
CURVE_MAX = 9.999999

# -- the extra steps: colour ranges and curves (PAD-339, PAD-343) -------------
#
# First the Machine screen's alone (SCREEN_KEY, preview only), now every
# profile's (PAD-343): on top of the steps every profile has it can carry
# COLOUR RANGES (hue, saturation and brightness of one band of hues, e.g. the
# sea's cyan-blue, with grey left alone) and CURVES (a master one for all
# three channels, then one per channel, through points the user places).
# They come after the profile's own steps, ranges first, all on the 8-bit
# sRGB values as given (no linear light anywhere):
#
#   3. each range in turn: the pixel's HSV hue h, saturation s, value v and
#      chroma c = (max - min) / 255.  Its weight w = hue_w * grey_w, where
#      hue_w is 1 within width / 2 degrees of the range's hue, falls to 0 over
#      ``soft`` more degrees (smoothstep), and grey_w = smoothstep(c /
#      protect) keeps greys and near-greys (chroma under ``protect``) out.
#      Then h += shift * w, s *= 1 + (saturation - 1) * w and v *= 1 +
#      (brightness - 1) * w; s is clipped to 0..1, v to 0..255.
#   4. the master curve on all three channels, then the red, green and blue
#      curves, each a 256-entry table through its points (monotone cubic,
#      flat past the first and last point, clipped to 0..255).
#
# A range with shift 0 and saturation and brightness 1, and a curve through
# (0, 0) and (255, 255) alone, change nothing.
#
# Where each is applied: Pillow and numpy as above; ffmpeg as a lut3d (the
# ranges) and a lut1d (the curves) from .cube files (_ffmpeg_extras); the
# Spike 2 whole screen overlay as GLSL after the shader's fixed slots
# (plugins/stern/shader_profile.py extras_glsl).  The multi-boot menu's
# Color correction (PAD-307) rewrites only the slots, so it leaves them be.

#: a colour range's numbers, in the order a file and the page hold them
RANGE_FIELDS = ("hue", "width", "soft", "shift", "saturation", "brightness",
                "protect")
RANGE_LIMITS = {"hue": (0.0, 360.0), "width": (0.0, 360.0),
                "soft": (0.0, 180.0), "shift": (-180.0, 180.0),
                "saturation": (0.0, 4.0), "brightness": (0.0, 4.0),
                "protect": (0.0, 1.0)}
#: a new range: 60 degrees wide with a 30 degree soft edge each side, greys
#: (chroma under 15%) protected, changing nothing until a slider moves
RANGE_NEW = {"width": 60.0, "soft": 30.0, "shift": 0.0, "saturation": 1.0,
             "brightness": 1.0, "protect": 0.15}
MAX_RANGES = 6
#: the curves, in the order they are applied: master, then red, green, blue
CURVE_CHANNELS = ("rgb", "r", "g", "b")
CURVE_IDENTITY = ((0.0, 0.0), (255.0, 255.0))
MAX_POINTS = 16


def range_neutral(rng):
    return rng[3] == 0.0 and rng[4] == 1.0 and rng[5] == 1.0


def clean_range(vals):
    """One colour range from any 7 numbers (or fewer: the rest from a new
    range), each held to :data:`RANGE_LIMITS`.  Raises ValueError."""
    vals = [float(v) for v in vals]
    if not 1 <= len(vals) <= len(RANGE_FIELDS):
        raise ValueError("a range needs 1 to %d numbers" % len(RANGE_FIELDS))
    out = []
    for i, name in enumerate(RANGE_FIELDS):
        v = vals[i] if i < len(vals) else RANGE_NEW[name]
        if v != v:                                      # NaN
            raise ValueError("%s is not a number" % name)
        lo, hi = RANGE_LIMITS[name]
        if name == "hue":
            v = v % 360.0
        out.append(round(min(max(v, lo), hi), 3))
    return tuple(out)


def clean_points(points):
    """A curve's points, as ``((x, y), ...)`` sorted by input, each 0..255,
    one point per input (the later one wins), at most :data:`MAX_POINTS`.
    Raises ValueError with fewer than two."""
    seen = {}
    for pt in points:
        x, y = (float(v) for v in pt)
        if x != x or y != y:
            raise ValueError("a point is not a number")
        x = round(min(max(x, 0.0), 255.0), 2)
        seen[x] = round(min(max(y, 0.0), 255.0), 2)
    if len(seen) < 2:
        raise ValueError("a curve needs at least two points")
    if len(seen) > MAX_POINTS:
        raise ValueError("a curve holds at most %d points" % MAX_POINTS)
    return tuple(sorted(seen.items()))


def curve_table(points):
    """256 output values (ints 0..255) for inputs 0..255 through *points*:
    Fritsch-Carlson monotone cubic between them (no overshoot where the
    points rise or fall), flat past the first and the last.
    static/js/tabs/color.js ``curveTable`` mirrors it."""
    if len(points) < 2:
        return list(range(256))
    return [int(min(max(y + 0.5, 0.0), 255.0))
            for y in curve_values(points, range(256))]


def curve_values(points, inputs):
    """The curve through *points* (two or more) at each of *inputs* (any
    shades 0..255, fractions too), unrounded: :func:`curve_table`'s maths."""
    import bisect
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    n = len(xs)
    d = [(ys[k + 1] - ys[k]) / (xs[k + 1] - xs[k]) for k in range(n - 1)]
    m = [0.0] * n
    m[0], m[n - 1] = d[0], d[n - 2]
    for k in range(1, n - 1):
        m[k] = (d[k - 1] + d[k]) / 2.0 if d[k - 1] * d[k] > 0 else 0.0
    for k in range(n - 1):
        if d[k] == 0.0:
            m[k] = m[k + 1] = 0.0
            continue
        a, b = m[k] / d[k], m[k + 1] / d[k]
        r = a * a + b * b
        if r > 9.0:
            t = 3.0 / r ** 0.5
            m[k], m[k + 1] = t * a * d[k], t * b * d[k]
    out = []
    for v in inputs:
        if v <= xs[0]:
            y = ys[0]
        elif v >= xs[n - 1]:
            y = ys[n - 1]
        else:
            k = bisect.bisect_left(xs, v) - 1
            h = xs[k + 1] - xs[k]
            t = (v - xs[k]) / h
            t2, t3 = t * t, t * t * t
            y = ((2 * t3 - 3 * t2 + 1) * ys[k] + (t3 - 2 * t2 + t) * h * m[k]
                 + (-2 * t3 + 3 * t2) * ys[k + 1] + (t3 - t2) * h * m[k + 1])
        out.append(y)
    return out


def _smooth(t):
    import numpy as np
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def apply_ranges(rgb, ranges):
    """*rgb* (float ``(..., 3)``, 0..255) through each colour range in turn
    (step 3 above); a pixel no range reaches comes back exactly as given."""
    import numpy as np
    out = np.asarray(rgb, np.float64)
    for hue, width, soft, shift, sat, bright, protect in ranges:
        if range_neutral((hue, width, soft, shift, sat, bright, protect)):
            continue
        r, g, b = out[..., 0], out[..., 1], out[..., 2]
        mx = out.max(-1)
        mn = out.min(-1)
        c = mx - mn
        safe = np.where(c > 0, c, 1.0)
        h = np.where(mx == r, ((g - b) / safe) % 6.0,
                     np.where(mx == g, (b - r) / safe + 2.0,
                              (r - g) / safe + 4.0)) * 60.0
        s = np.where(mx > 0, c / np.where(mx > 0, mx, 1.0), 0.0)
        dist = np.abs((h - hue + 180.0) % 360.0 - 180.0)
        half = width / 2.0
        if width >= 360.0:
            hw = np.ones_like(h)
        elif soft > 0:
            hw = _smooth(1.0 - (dist - half) / soft)
        else:
            hw = (dist <= half).astype(np.float64)
        if protect > 0:
            gw = _smooth(c / 255.0 / protect)
        else:
            gw = (c > 0).astype(np.float64)
        w = np.where(c > 0, hw * gw, 0.0)
        h2 = (h + shift * w) % 360.0
        s2 = np.clip(s * (1.0 + (sat - 1.0) * w), 0.0, 1.0)
        v2 = np.clip(mx * (1.0 + (bright - 1.0) * w), 0.0, 255.0)
        chans = []
        for n in (5.0, 3.0, 1.0):
            k = (n + h2 / 60.0) % 6.0
            chans.append(v2 - v2 * s2 * np.clip(np.minimum(k, 4.0 - k), 0, 1))
        out = np.where((w > 0)[..., None], np.stack(chans, -1), out)
    return out


@dataclass(frozen=True)
class Profile:
    name: str = ""
    gamma: tuple = (1.0, 1.0, 1.0)
    gain: tuple = (1.0, 1.0, 1.0)
    lift: tuple = (0.0, 0.0, 0.0)
    saturation: float = 1.0
    brightness: float = 1.0
    contrast: float = 1.0
    #: PAD-339 (the machine screen's), PAD-343 (every profile's): colour ranges (:data:`RANGE_FIELDS`
    #: tuples) and curves (``((channel, ((x, y), ...)), ...)``, channels from
    #: :data:`CURVE_CHANNELS`); see the steps above :func:`curve_table`
    ranges: tuple = ()
    curves: tuple = ()

    def is_identity(self):
        return (self.gamma == (1.0, 1.0, 1.0) and self.gain == (1.0, 1.0, 1.0)
                and self.lift == (0.0, 0.0, 0.0) and self.saturation == 1.0
                and self.brightness == 1.0 and self.contrast == 1.0
                and not self.has_extras())

    def has_extras(self):
        """Does a colour range or a curve change anything (PAD-339)?"""
        return (any(not range_neutral(r) for r in self.ranges)
                or any(pts != CURVE_IDENTITY for _ch, pts in self.curves))

    def plain(self):
        """The profile without its colour ranges and curves."""
        if not (self.ranges or self.curves):
            return self
        import dataclasses
        return dataclasses.replace(self, ranges=(), curves=())

    def curve_tables(self):
        """``[r, g, b]`` 256-entry tables of the master curve then each
        channel's own, or ``None`` when no curve changes anything."""
        cv = {ch: pts for ch, pts in self.curves if pts != CURVE_IDENTITY}
        if not cv:
            return None
        master = curve_table(cv["rgb"]) if "rgb" in cv else list(range(256))
        out = []
        for ch in ("r", "g", "b"):
            own = curve_table(cv[ch]) if ch in cv else None
            out.append([own[v] if own else v for v in master])
        return out

    def extras_array(self, rgb):
        """*rgb* (uint8 ``(h, w, 3)``) through the colour ranges, then the
        curves (steps 3 and 4)."""
        import numpy as np
        out = np.asarray(rgb, np.uint8)
        live = [r for r in self.ranges if not range_neutral(r)]
        if live:
            out = np.clip(apply_ranges(out, live) + 0.5, 0, 255).astype(
                np.uint8)
        tabs = self.curve_tables()
        if tabs is not None:
            luts = [np.asarray(t, np.uint8) for t in tabs]
            out = np.stack([luts[c][out[..., c]] for c in range(3)], axis=-1)
        return out

    def curve(self):
        """``(gamma, gain, lift)`` per channel with the brightness and
        contrast folded in (PAD-333): ``clip(in * b * k) ** c`` then
        ``clip(y * gain) ** gamma`` is ``clip(in * b * k * gain ** (1 / c))
        ** (c * gamma)``.  Every use of the maths goes through this."""
        b, c = self.brightness, self.contrast
        if b == 1.0 and c == 1.0:
            return self.gamma, self.gain, self.lift
        c = max(c, 0.01)
        k = max(b, 0.0) * 2.0 * 0.5 ** (1.0 / c)
        return (tuple(min(g * c, CURVE_MAX) for g in self.gamma),
                tuple(min(k * max(g, 0.0) ** (1.0 / c), CURVE_MAX)
                      for g in self.gain),
                self.lift)

    def folded(self):
        """The same correction with brightness and contrast 1: the numbers
        the shaders are written with (plugins/stern/shader_profile.py)."""
        gamma, gain, lift = self.curve()
        return Profile(name=self.name, gamma=tuple(gamma), gain=tuple(gain),
                       lift=tuple(lift), saturation=self.saturation)

    def key(self):
        """Every number, as text: a cache key that changes with any of them.
        A profile at brightness and contrast 1 spells what it always did."""
        out = "%s|%s|%s|%s" % (self.gamma, self.gain, self.lift,
                               self.saturation)
        if self.brightness != 1.0 or self.contrast != 1.0:
            out += "|%s|%s" % (self.brightness, self.contrast)
        if self.has_extras():
            out += "|%s|%s" % (self.ranges, self.curves)
        return out

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
        gamma, gain, lift = self.curve()
        g, k, lo = gamma[channel], gain[channel], lift[channel]
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
        gamma, gain, lift = self.curve()
        for i, ch in enumerate(("r", "g", "b")):
            g, k, lo = gamma[i], gain[i], lift[i]
            if g == 1.0 and k == 1.0 and lo == 0.0:
                continue
            # commas inside an option are escaped for the filtergraph parser
            exprs.append(
                "%s=%.6f*255+%.6f*pow(clip(val*%.6f/255\\,0\\,1)\\,%.6f)*255+0.5"
                % (ch, lo, 1.0 - lo, k, g))
        if exprs:
            out.append("lutrgb=" + ":".join(exprs))
        return out + self._ffmpeg_extras()

    def _ffmpeg_extras(self):
        """The colour ranges and curves as ffmpeg filters (PAD-343): the
        ranges as a ``lut3d``, the curves as a ``lut1d`` (exact: one entry
        per level), each a .cube file written once per profile, since ffmpeg
        has no inline form of either."""
        out = []
        live = [r for r in self.ranges if not range_neutral(r)]
        if live:
            out.append("lut3d=file=%s:interp=tetrahedral"
                       % _cube_arg(_cube_3d(live)))
        tabs = self.curve_tables()
        if tabs is not None:
            out.append("lut1d=file=%s" % _cube_arg(_cube_1d(tabs)))
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
        out = np.stack([luts[c][out[..., c]] for c in range(3)], axis=-1)
        if self.has_extras():
            out = self.extras_array(out)
        return out

    def undo_table(self, channel):
        """The inverse of :meth:`table` on *channel*: what the machine's
        screen does to a value this profile corrects (PAD-312).  Where the
        correction clips, the inverse holds at the edge."""
        gamma, gain, lift = self.curve()
        g, k, lo = gamma[channel], gain[channel], lift[channel]
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
        fwd_gamma, fwd_gain, _lift = self.curve()
        gamma = tuple(1.0 / g if g > 0 else 1.0 for g in fwd_gamma)
        gain = tuple((k ** -g) if k > 0 else 1.0
                     for k, g in zip(fwd_gain, fwd_gamma))
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
        if self.has_extras():
            import numpy as np
            from PIL import Image
            rgb = Image.fromarray(self.extras_array(np.asarray(rgb)), "RGB")
        if alpha is not None:
            rgb.putalpha(alpha)
        return rgb if alpha is not None else rgb.convert("RGB")


#: Grid points per side of the colour ranges' 3D table: 65 keeps a video
#: within a few levels of the same picture through Pillow (33 was 12 off)
CUBE_SIZE = 65


def _cube_file(text):
    """*text* as a .cube file in the temp folder, named by its contents (so
    a profile's file is written once and two profiles never share one)."""
    import hashlib
    import os
    import tempfile
    d = os.path.join(tempfile.gettempdir(), "pad_colour_luts")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, hashlib.sha1(text.encode()).hexdigest()[:20]
                        + ".cube")
    if not os.path.isfile(path):
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="ascii", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    return path


def _cube_3d(ranges):
    """The .cube file of *ranges* (:func:`apply_ranges`), red fastest."""
    return _cube_file(_cube_3d_text(tuple(ranges), CUBE_SIZE))


@functools.lru_cache(maxsize=8)
def _cube_3d_text(ranges, n):
    import numpy as np
    axis = np.linspace(0.0, 255.0, n)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    grid = np.stack([r, g, b], -1).reshape(-1, 1, 3)
    out = np.clip(apply_ranges(grid, ranges) / 255.0, 0.0, 1.0).reshape(-1, 3)
    lines = ["LUT_3D_SIZE %d" % n]
    lines += ["%.6f %.6f %.6f" % tuple(v) for v in out]
    return "\n".join(lines) + "\n"


def _cube_1d(tables):
    """The .cube file of ``[r, g, b]`` 256-entry tables."""
    lines = ["LUT_1D_SIZE 256"]
    lines += ["%.6f %.6f %.6f" % (tables[0][v] / 255.0, tables[1][v] / 255.0,
                                  tables[2][v] / 255.0) for v in range(256)]
    return _cube_file("\n".join(lines) + "\n")


def _cube_arg(path):
    """*path* as a filtergraph option value: forward slashes, the drive's
    colon escaped, quoted (a Windows path breaks the graph otherwise)."""
    return "'%s'" % path.replace("\\", "/").replace(":", "\\:")


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
    limits = LIMITS
    single = ("saturation", "brightness", "contrast")
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
        if key == "range" or key in _CURVE_KEYS:
            try:
                if key == "range":
                    if len(fields.get("ranges", ())) >= MAX_RANGES:
                        raise ValueError("at most %d ranges" % MAX_RANGES)
                    vals = [float(t) for t in val.replace(",", " ").split()]
                    fields["ranges"] = fields.get("ranges", ()) + (
                        clean_range(vals),)
                else:
                    pts = clean_points(_points(val))
                    ch = _CURVE_KEYS[key]
                    fields["curves"] = tuple(
                        c for c in fields.get("curves", ()) if c[0] != ch) + (
                        (ch, pts),)
            except ValueError as e:
                problems.append("line %d: %s %s" % (n, key, e))
            continue
        if key not in limits:
            problems.append("line %d: unknown setting '%s'" % (n, key))
            continue
        try:
            nums = _numbers(val, 1 if key in single else 3)
        except ValueError as e:
            problems.append("line %d: %s %s" % (n, key, e))
            continue
        lo, hi = limits[key]
        if any(not (lo <= v <= hi) for v in nums):
            problems.append("line %d: %s must be between %g and %g"
                            % (n, key, lo, hi))
            continue
        fields[key] = nums[0] if key in single else nums
    if "curves" in fields:
        fields["curves"] = _curve_order(fields["curves"])
    return Profile(**fields), problems


#: a curve's line in a profile file, by channel
CURVE_KEY_OF = {"rgb": "curve_rgb", "r": "curve_red", "g": "curve_green",
                "b": "curve_blue"}
_CURVE_KEYS = {v: k for k, v in CURVE_KEY_OF.items()}


def _points(text):
    """``x y, x y, ...`` -> pairs."""
    out = []
    for part in text.split(","):
        nums = part.split()
        if not nums:
            continue
        if len(nums) != 2:
            raise ValueError("needs points as 'input output' pairs, "
                             "comma separated")
        out.append((float(nums[0]), float(nums[1])))
    return out


def _curve_order(curves):
    """*curves* (``(channel, points)`` pairs) in :data:`CURVE_CHANNELS`
    order, the ones that change nothing left out."""
    have = dict(curves)
    return tuple((ch, have[ch]) for ch in CURVE_CHANNELS
                 if ch in have and have[ch] != CURVE_IDENTITY)


def extras_from(ranges=None, curves=None):
    """``(ranges, curves)`` as a Profile holds them, from the page's or a
    stored file's lists: ``ranges`` ``[[7 numbers], ...]``, ``curves``
    ``{channel: [[x, y], ...]}``.  A bad entry is skipped."""
    rs = []
    for r in list(ranges or ())[:MAX_RANGES]:
        try:
            rs.append(clean_range(r))
        except (TypeError, ValueError):
            continue
    cv = []
    for ch, pts in (curves.items() if isinstance(curves, dict) else ()):
        if ch not in CURVE_CHANNELS:
            continue
        try:
            cv.append((ch, clean_points(pts)))
        except (TypeError, ValueError):
            continue
    return tuple(rs), _curve_order(cv)


def _from_dict(d):
    try:
        return Profile(name=str(d.get("name") or ""),
                       gamma=tuple(float(v) for v in d["gamma"])[:3],
                       gain=tuple(float(v) for v in d["gain"])[:3],
                       lift=tuple(float(v) for v in d["lift"])[:3],
                       saturation=float(d["saturation"]),
                       brightness=float(d.get("brightness", 1.0)),
                       contrast=float(d.get("contrast", 1.0)),
                       **dict(zip(("ranges", "curves"), extras_from(
                           d.get("ranges"), d.get("curves")))))
    except (KeyError, TypeError, ValueError):
        return None


def for_project(assets_dir):
    """The profile staged for *assets_dir*, or ``None`` (none staged)."""
    from . import staged_changes
    d = staged_changes.load(assets_dir).get(KEY)
    if isinstance(d, dict) and d.get(FOLLOW_SCREEN):
        return recommended(assets_dir)
    return _from_dict(d) if isinstance(d, dict) else None


def follows_screen(assets_dir):
    """Is the overlay the Recommended one, following the machine screen?"""
    from . import staged_changes
    d = staged_changes.load(assets_dir).get(KEY)
    return bool(isinstance(d, dict) and d.get(FOLLOW_SCREEN))


def store(assets_dir, prof, follow=False):
    """Stage *prof* for *assets_dir*; ``None`` (or a profile that changes
    nothing) takes it away; *follow*: the Recommended one, following the
    machine screen (PAD-346)."""
    from . import staged_changes
    data = staged_changes.load(assets_dir)
    if follow:
        data[KEY] = {FOLLOW_SCREEN: True}
    elif prof is None or prof.is_identity():
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
    return prof.key()


# -- the chosen-files profile (PAD-312) ---------------------------------------

def _profile_dict(prof):
    out = {"name": prof.name, "gamma": list(prof.gamma),
           "gain": list(prof.gain), "lift": list(prof.lift),
           "saturation": prof.saturation}
    if prof.brightness != 1.0 or prof.contrast != 1.0:
        out["brightness"] = prof.brightness
        out["contrast"] = prof.contrast
    if prof.ranges:
        out["ranges"] = [list(r) for r in prof.ranges]
    if prof.curves:
        out["curves"] = {ch: [list(p) for p in pts] for ch, pts in prof.curves}
    return out


def asset_profile(assets_dir):
    """The profile baked into the chosen files of *assets_dir*: the one
    stored, else the Recommended one, the machine screen undone (PAD-346:
    it follows that screen)."""
    from . import staged_changes
    d = staged_changes.load(assets_dir).get(ASSET_KEY)
    prof = _from_dict(d) if isinstance(d, dict) else None
    return prof if prof is not None else recommended(assets_dir, files=True)


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


def stock_videos_unlocked(data):
    """The Video tab's Advanced box, from a loaded sidecar *data*."""
    return bool(isinstance(data, dict) and data.get(STOCK_VIDEOS_KEY))


def stock_video_rels(data):
    """The game's own clips switched on with the Advanced box ticked
    (PAD-336), from a loaded sidecar *data*: only a clip's own switch counts
    (the Every replaced video box never reaches a stock clip), and a clip
    with a replacement picked is not stock."""
    if not stock_videos_unlocked(data):
        return []
    slots = data.get(VIDEO_SLOTS_KEY)
    picks = data.get("video") or {}
    if not isinstance(slots, dict):
        return []
    if not isinstance(picks, dict):
        picks = {}
    return sorted(str(rel) for rel, on in slots.items()
                  if on and not picks.get(rel))


def stock_images_unlocked(assets_dir):
    """Is the Images tab's advanced "Unlock the game's own pictures" box
    ticked (PAD-335)?"""
    if not assets_dir:
        return False
    from . import staged_changes
    return bool(staged_changes.load(assets_dir).get(STOCK_IMAGES_KEY))


def stock_image_rels(assets_dir, assigned=()):
    """The game's own pictures (not in *assigned*) switched on while the
    Images tab's unlock box is ticked: staged from their pristine bytes with
    the chosen-files profile baked in.  Only a picture's own switch counts."""
    if not stock_images_unlocked(assets_dir):
        return []
    settings = asset_settings(assets_dir)
    built = built_image_rels(assets_dir)
    return sorted(rel for rel, on in settings["images"].items()
                  if on and rel not in assigned and rel not in built)


# -- the user's own pictures built earlier (PAD-345) ---------------------------

#: Where a built picture's uncorrected bytes wait while its colour switch is
#: on (a dotfolder: the slot scanners and the Write's diff skip it).
UNCORRECTED_DIR = ".uncorrected"


def built_image_rels(assets_dir, data=None):
    """The user's own pictures an earlier build put in the project folder
    whose pick is gone (the Images tab's "changed on disk (name)" rows):
    the sidecar still names the replacement.  They are not the game's own
    pictures, so they are never locked and never rebuilt from the .orig/
    snapshot (that is Stern's picture, not the user's)."""
    if not assets_dir:
        return set()
    if data is None:
        from . import staged_changes
        data = staged_changes.load(assets_dir)
    names = data.get("replacement_names") or {}
    picks = data.get("image") or {}
    if not isinstance(names, dict):
        return set()
    if not isinstance(picks, dict):
        picks = {}
    return {str(rel) for rel, name in names.items()
            if name and str(rel).startswith("images/") and not picks.get(rel)}


def built_image_on(assets_dir):
    """The built pictures (:func:`built_image_rels`) switched on: only their
    own switch counts, never the Every replaced picture box (the file may
    have been built corrected before; a box ticked later must not correct
    every one of them again)."""
    built = built_image_rels(assets_dir)
    if not built:
        return []
    settings = asset_settings(assets_dir)
    return sorted(rel for rel in built if settings["images"].get(rel))


def uncorrected_path(assets_dir, rel):
    """The kept uncorrected copy of built picture *rel*, or ``None``."""
    if not assets_dir or not rel:
        return None
    p = os.path.join(assets_dir, UNCORRECTED_DIR, *rel.split("/"))
    return p if os.path.isfile(p) else None


def keep_uncorrected(assets_dir, rel):
    """Copy built picture *rel* aside before a correction is baked into it,
    once: the copy is then what every correction starts from and what goes
    back when the switch goes off.  Returns the copy's path, or ``None``."""
    got = uncorrected_path(assets_dir, rel)
    if got:
        return got
    import shutil
    src = os.path.join(assets_dir, *rel.split("/"))
    if not os.path.isfile(src):
        return None
    dst = os.path.join(assets_dir, UNCORRECTED_DIR, *rel.split("/"))
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    except OSError:
        return None
    return dst


def discard_uncorrected(assets_dir, rel):
    """A new pick replaces built picture *rel*: its kept copy is stale."""
    p = uncorrected_path(assets_dir, rel)
    if p:
        try:
            os.remove(p)
        except OSError:
            pass


def put_back_uncorrected(assets_dir, rel):
    """Built picture *rel*'s switch went off: its uncorrected copy goes back
    over the project's file.  True when one did."""
    import shutil
    src = uncorrected_path(assets_dir, rel)
    if not src:
        return False
    try:
        shutil.copy2(src, os.path.join(assets_dir, *rel.split("/")))
        os.remove(src)
    except OSError:
        return False
    root = os.path.join(assets_dir, UNCORRECTED_DIR)
    d = os.path.dirname(src)
    while os.path.normcase(d) != os.path.normcase(root) and d.startswith(root):
        try:
            os.rmdir(d)
        except OSError:
            break
        d = os.path.dirname(d)
    try:
        os.rmdir(root)
    except OSError:
        pass
    return True


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


def _screen_stored(assets_dir):
    """What the project stores for its machine screen: a dict, or ``None``."""
    from . import staged_changes
    d = staged_changes.load(assets_dir).get(SCREEN_KEY) if assets_dir else None
    return d if isinstance(d, dict) else None


def screen_profile(assets_dir):
    """The machine's screen stored for *assets_dir* (PAD-324), or ``None``:
    then the Scenes preview takes the Recommended screen (PAD-341), or the
    individual files profile, undone, when :func:`screen_follows`."""
    d = _screen_stored(assets_dir)
    return _from_dict(d) if d is not None and not d.get(SCREEN_FOLLOW)         else None


def screen_follows(assets_dir):
    """True when the project picked "Same as individual files": the screen
    is that profile, undone (what every project had before PAD-341)."""
    d = _screen_stored(assets_dir)
    return bool(d and d.get(SCREEN_FOLLOW))


def store_screen_profile(assets_dir, prof, follow=False):
    """Set the machine's screen of *assets_dir* (``None`` = back to the
    Recommended screen; *follow* = the individual files profile, undone).
    No change IS stored: it says the PC shows what the machine does.
    Preview only, so nothing is pending."""
    from . import staged_changes
    data = staged_changes.load(assets_dir)
    if follow:
        data[SCREEN_KEY] = {SCREEN_FOLLOW: True}
    elif prof is None:
        data.pop(SCREEN_KEY, None)
    else:
        data[SCREEN_KEY] = _profile_dict(prof)
    staged_changes.save(assets_dir, data)


def screen_shown(assets_dir):
    """The screen the Scenes preview uses now, as sliders can show it:
    the stored one, else the Recommended screen, else (following) the
    individual files profile's :meth:`inverse`.  ``(profile, stored)``."""
    prof = screen_profile(assets_dir)
    if prof is not None:
        return prof, True
    if not screen_follows(assets_dir):
        return SCREEN_PRESETS[0][1], False
    files = asset_profile(assets_dir)
    inv = files.inverse()
    if inv.is_identity():
        name = "No change"
    else:
        name = "%s, undone" % files.label()
    return Profile(name=name, gamma=inv.gamma, gain=inv.gain, lift=inv.lift,
                   saturation=inv.saturation), False


# -- Recommended = the machine screen, undone (PAD-346) -----------------------
#
# The whole screen overlay's and the individual files' Recommended is worked
# out from the Machine screen on show: a profile that, given to that screen,
# comes back as the colours the user made.  It is built from the controls
# every profile has, so the sliders, ranges and curves show it and a user can
# nudge it from there without a jump:
#
#   - saturation 1 / the screen's;
#   - per channel a curve that undoes the screen's shades (its gamma, gain,
#     lift, brightness and contrast and its curves, all per channel), then
#     corrected so a grey comes back grey through the whole screen, ranges
#     included (the screen's ranges reach the slightly tinted greys a
#     correction sends; the profile's own cannot see them);
#   - each screen range, turned round (shift, saturation and brightness
#     reversed, at the hue the screen moves that band to), then nudged one
#     number at a time while the round trip over a grid of colours improves.
#
# Exact for greys up to the 8-bit steps; colours the screen cannot show at
# all (past its brightest or most saturated) stay out of reach.  Worked out
# once per screen (cached).

RECOMMENDED = "Recommended"
#: stored under KEY alone: the overlay is the Recommended one, following the
#: machine screen (PAD-346)
FOLLOW_SCREEN = "recommended"


def _shades_forward(screen, c, xs):
    """Channel *c* of *screen* at shades *xs*, without the colour mix or the
    ranges, unrounded."""
    gamma, gain, lift = screen.curve()
    out = []
    for v in xs:
        x = min(max(v / 255.0 * gain[c], 0.0), 1.0)
        out.append((lift[c] + (1.0 - lift[c]) * x ** gamma[c]) * 255.0)
    cv = dict(screen.curves)
    for ch in ("rgb", "rgb"[c]):
        if ch in cv and cv[ch] != CURVE_IDENTITY:
            out = curve_values(cv[ch], out)
    return out


def _fit_points(target, tol=1.0):
    """At most :data:`MAX_POINTS` curve points whose curve follows *target*
    (256 shades) within *tol*, where the points allow."""
    import numpy as np
    pts = {0.0: round(float(target[0]), 1),
           255.0: round(float(target[255]), 1)}
    while len(pts) < MAX_POINTS:
        have = np.asarray(curve_values(sorted(pts.items()), range(256)))
        miss = np.abs(have - target)
        x = int(np.argmax(miss))
        if miss[x] < tol or float(x) in pts:
            break
        pts[float(x)] = round(float(target[x]), 1)
    return tuple(sorted(pts.items()))


def _undo_shades(screen):
    """``[r, g, b]`` 256-entry float tables that undo *screen*'s shades,
    greys made to come back grey through all of it (see above)."""
    import numpy as np
    xs = np.linspace(0.0, 255.0, 4081)
    inv = []
    for c in range(3):
        f = np.maximum.accumulate(np.asarray(_shades_forward(screen, c, xs)))
        keep = np.concatenate([[True], np.diff(f) > 1e-9])
        inv.append(np.interp(np.arange(256.0), f[keep], xs[keep]))
    inv = np.stack(inv, -1)

    def undo(y):
        return np.stack([np.interp(y[:, c], np.arange(256.0), inv[:, c])
                         for c in range(3)], -1)
    grey = np.repeat(np.arange(256.0)[:, None], 3, 1)
    x = inv.copy()
    for _ in range(12):
        # a grey passes the profile's own colour mix and ranges untouched
        sent = np.uint8(np.clip(x + 0.5, 0, 255))[None]
        shown = screen.apply_array(sent)[0].astype(np.float64)
        x = np.maximum.accumulate(
            np.clip(x + undo(grey) - undo(shown), 0.0, 255.0), 0)
    # the grey fix-up follows the screen's 8-bit steps: smooth it, so the
    # curves need few points and bend no more than the screen does
    k = np.hanning(15)
    k /= k.sum()
    fix = np.stack([np.convolve(np.pad(x[:, c] - inv[:, c], 7, mode="edge"),
                                k, mode="valid") for c in range(3)], -1)
    x = np.maximum.accumulate(np.clip(inv + fix, 0.0, 255.0), 0)
    return [x[:, c] for c in range(3)]


def _round_trip(screen, prof, probe):
    """How far (mean levels) *probe* comes back from *prof* then *screen*."""
    import numpy as np
    back = screen.apply_array(prof.apply_array(probe)).astype(np.float64)
    return float(np.abs(back - probe).mean())


def _probe(step=32):
    import numpy as np
    g = np.append(np.arange(0, 256, step), 255).astype(np.uint8)
    return np.stack(np.meshgrid(g, g, g, indexing="ij"), -1).reshape(1, -1, 3)


def _undo_ranges(screen, base):
    """*screen*'s colour ranges turned round for a profile that already
    undoes its shades (*base*), then tuned against the round trip."""
    import colorsys
    import dataclasses
    import numpy as np
    start = []
    for rng in screen.ranges:
        if range_neutral(rng):
            continue
        hue, width, soft, shift, sat, bright, protect = rng
        # where the screen draws a colour of that band
        rgb = np.array(colorsys.hsv_to_rgb(hue / 360.0, 0.6, 0.6)) * 255.0
        shown = screen.apply_array(np.uint8(rgb + 0.5).reshape(1, 1, 3))
        h = colorsys.rgb_to_hsv(*(shown[0, 0] / 255.0))[0] * 360.0
        start.append(list(clean_range((
            h, width, soft, -shift, 1.0 / sat if sat > 0 else 1.0,
            1.0 / bright if bright > 0 else 1.0, protect))))
    if not start:
        return ()
    probe = _probe()

    def cost(rs):
        return _round_trip(screen, dataclasses.replace(
            base, ranges=tuple(tuple(r) for r in rs)), probe)
    steps = [10.0, 10.0, 10.0, 4.0, 0.1, 0.1, 0.05]
    rs = start
    best = cost(rs)
    for _ in range(6):
        better = False
        for i in range(len(rs)):
            for f in range(len(RANGE_FIELDS)):
                for sign in (1.0, -1.0):
                    trial = [list(r) for r in rs]
                    trial[i][f] += sign * steps[f]
                    trial[i] = list(clean_range(trial[i]))
                    c = cost(trial)
                    if c < best - 1e-4:
                        best, rs, better = c, trial, True
        if not better:
            steps = [v / 2.0 for v in steps]
    return tuple(clean_range([round(v, 2) for v in r]) for r in rs)


@functools.lru_cache(maxsize=16)
def undo_screen(screen):
    """The Recommended profile for *screen* (PAD-346): what, given to that
    screen, shows as made.  Sliders, ranges and curves only (see above)."""
    import numpy as np
    if screen is None or screen.is_identity():
        return Profile(name=RECOMMENDED)
    lo, hi = LIMITS["saturation"]
    sat = (round(min(max(1.0 / screen.saturation, lo), hi), 3)
           if screen.saturation > 0 else 1.0)
    tabs = _undo_shades(screen)
    ident = np.arange(256.0)
    curves = []
    if all(np.abs(t - tabs[0]).max() < 0.5 for t in tabs):
        if np.abs(tabs[0] - ident).max() >= 0.5:
            curves.append(("rgb", _fit_points(tabs[0])))
    else:
        for ch, t in zip("rgb", tabs):
            if np.abs(t - ident).max() >= 0.5:
                curves.append((ch, _fit_points(t)))
    base = Profile(name=RECOMMENDED, saturation=sat, curves=tuple(curves))
    return Profile(name=RECOMMENDED, saturation=sat,
                   ranges=_undo_ranges(screen, base), curves=base.curves)


def recommended(assets_dir, files=False):
    """The Recommended whole screen overlay (or, *files*, individual files
    profile) of *assets_dir* (PAD-346): the Machine screen on show, undone,
    so what the user made shows on the machine (and in Scenes' As on the
    machine) as it does on their PC.  When the screen is "Same as individual
    files" it cannot follow it in turn: then the measured Recommended.  The
    files' one is the same with the overlay on Recommended too: the two stack,
    the user's choice (PAD-356)."""
    if not assets_dir or screen_follows(assets_dir):
        return PRESETS[0][1]
    return undo_screen(screen_shown(assets_dir)[0])


def filter_step(prof):
    """*prof* as one step of a browser colour filter (PAD-329): ``{"m"}`` the
    saturation mix as an SVG feColorMatrix's 20 values (None when it mixes
    nothing) and ``{"f"}`` each channel's feFuncR/G/B ``type="gamma"``
    amplitude, exponent and offset.  lift + (1 - lift) * min(in * gain, 1) **
    gamma is amplitude * in ** exponent + offset clamped to 1, so it is the
    same curve; ``None`` for a profile that changes nothing."""
    if prof is None or prof.is_identity():
        return None
    m = None
    if prof.saturation != 1.0:
        rows = prof.matrix()
        m = []
        for i in range(3):
            m += [round(v, 5) for v in rows[i]] + [0.0, 0.0]
        m += [0.0, 0.0, 0.0, 1.0, 0.0]
    f = [[round((1.0 - lo) * (k ** g), 5), round(g, 5), round(lo, 5)]
         for g, k, lo in zip(*prof.curve())]
    out = {"m": m, "f": f}
    # PAD-339: a profile's curves as feFuncR/G/B type="table" (65
    # values, straight between them); its colour ranges have no SVG form
    tabs = prof.curve_tables()
    if tabs is not None:
        out["t"] = [[round(t[min(i * 4, 255)] / 255.0, 4) for i in range(65)]
                    for t in tabs]
    return out


def video_look(assets_dir, switch, own_colours, overlay_on=True, files_on=True,
               screen_on=True):
    """The colour steps the Video tab's players draw through with As on the
    machine ticked (PAD-329), as :func:`filter_step` dicts: ``{"orig",
    "rep"}``.  The original: the whole screen overlay, then the machine
    screen.  A replacement: its baked individual-files correction when its
    Color switch is on (*switch* True), the overlay, then the screen, except
    when its switch is off (*switch* False) and *own_colours* (the gear
    menu's setting): then it passes the screen by, as a switched-off picture
    does in Scenes.  The screen is the Color profile tab's Machine screen,
    else the individual files profile undone (:func:`screen_shown`).

    *overlay_on* / *files_on* / *screen_on* are the preview's three switches
    (PAD-330): each leaves its own step out, and nothing else."""
    overlay = active(assets_dir) if overlay_on else None
    screen = screen_shown(assets_dir)[0] if screen_on else None
    if screen is not None and screen.is_identity():
        screen = None
    files = asset_active(assets_dir) if files_on else None
    orig = [filter_step(p) for p in (overlay, screen)]
    rep = []
    if switch and files is not None:
        rep.append(filter_step(files))
    rep.append(filter_step(overlay))
    if not (switch is False and own_colours):
        rep.append(filter_step(screen))
    return {"orig": [s for s in orig if s], "rep": [s for s in rep if s]}


def machine_view(assets_dir, overlay_on=True, screen_on=True):
    """A function ``rgb uint8 array -> rgb uint8 array`` showing a frame of
    *assets_dir* the way the machine's screen will (PAD-312): through the
    whole-screen profile, as the game's shaders draw it, then through the
    screen itself.  The screen is the one stored on the Color profile tab
    (PAD-324, applied forwards), else the inverse of the chosen-files
    profile (that profile is the correction measured for the screen, so
    undoing it IS the screen).  ``None`` when there is nothing to show.

    *overlay_on* / *screen_on* are two of the preview's switches (PAD-330;
    the third, the individual files bake, is the picture list's)."""
    display = active(assets_dir) if overlay_on else None
    stored = screen_profile(assets_dir)
    if not screen_on:
        screen, undo = None, False
    elif stored is not None:
        screen, undo = (None if stored.is_identity() else stored), False
    elif screen_follows(assets_dir):
        screen, undo = asset_active(assets_dir), True
    else:
        screen, undo = SCREEN_PRESETS[0][1], False
    if display is None and screen is None:
        return None

    def overlay(rgb):
        return display.apply_array(rgb)

    def view(rgb):
        if display is not None:
            rgb = display.apply_array(rgb)
        if screen is not None:
            rgb = screen.undo_array(rgb) if undo else screen.apply_array(rgb)
        return rgb
    # the overlay alone (PAD-328): what a picture that passes the screen by
    # still gets, since the game draws the overlay over everything
    view.overlay = overlay if display is not None else None
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
    out["videos"] += len(stock_video_rels(data))
    picks = data.get("image") if isinstance(data.get("image"), dict) else {}
    out["images"] += len(stock_image_rels(
        assets_dir, {r for r, src in picks.items() if src}))
    out["images"] += len(built_image_on(assets_dir))
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


def preview_parts(assets_dir):
    """What the preview's three switches name (PAD-330): ``{"overlay":
    {"name", "set"}, "files": {"name", "set", "count"}, "screen": {"name",
    "set", "stored"}}``.  ``set`` False greys a switch out: no overlay, or an
    individual files profile that changes nothing or reaches no file, or a
    screen that changes nothing."""
    out = {"overlay": {"name": "", "set": False},
           "files": {"name": "", "set": False, "count": 0},
           "screen": {"name": "", "set": False, "stored": False}}
    if not assets_dir:
        return out
    over = active(assets_dir)
    if over is not None:
        out["overlay"] = {"name": over.label(), "set": True}
    files = asset_profile(assets_dir)
    n = sum(asset_counts(assets_dir).values())
    out["files"] = {"name": files.label(), "count": n,
                    "set": bool(n and not files.is_identity())}
    shown, stored = screen_shown(assets_dir)
    out["screen"] = {"name": shown.label(), "stored": stored,
                     "set": not shown.is_identity()}
    return out


def asset_signature(assets_dir):
    """A short text that changes whenever what the chosen-files profile
    would bake into which file changes ("" when nothing)."""
    prof = asset_active(assets_dir)
    if prof is None:
        return ""
    s = asset_settings(assets_dir)
    return "%s|%s|%s|%s|%s%s" % (
        prof.key(),
        s["all_images"], s["all_videos"], sorted(s["images"].items()),
        sorted(s["videos"].items()),
        "|unlocked" if stock_images_unlocked(assets_dir) else "")


def _fmt(nums):
    return " ".join("%.2f" % v for v in nums)


def _num(v):
    return ("%.3f" % v).rstrip("0").rstrip(".")


def to_text(prof):
    """The file text for *prof*: the explanatory header, then its values
    (its colour ranges and curves after them, PAD-339)."""
    head = DEFAULT_TEXT.split("\nname =", 1)[0]
    out = ("%s\nname = %s\ngamma = %s\ngain = %s\nlift = %s\n"
           "saturation = %.2f\nbrightness = %.2f\ncontrast = %.2f\n"
           % (head, prof.name or "My profile", _fmt(prof.gamma),
              _fmt(prof.gain), _fmt(prof.lift), prof.saturation,
              prof.brightness, prof.contrast))
    if prof.ranges or prof.curves:
        out += EXTRAS_HELP
    for r in prof.ranges:
        out += "range = %s\n" % " ".join(_num(v) for v in r)
    for ch, pts in prof.curves:
        out += "%s = %s\n" % (CURVE_KEY_OF[ch], ", ".join(
            "%s %s" % (_num(x), _num(y)) for x, y in pts))
    return out


#: what a machine screen's extra lines mean, written above them
EXTRAS_HELP = """
# Color ranges and curves, applied after the lines above:
#   range = hue width soft shift saturation brightness protect
#           one band of hues (degrees: 0 red, 120 green, 240 blue), its
#           width and soft edge, the hue shift, saturation and brightness
#           (1 = unchanged) and how much colour a pixel needs before it is
#           touched (0.15 = greys and near-greys left alone)
#   curve_rgb / curve_red / curve_green / curve_blue = in out, in out, ...
#           points 0..255; curve_rgb first, then each color's own
"""


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


#: the settings a profile file has, at least one of them (PAD-360: a text
#: file in the saved profiles folder that has none is not listed)
_FILE_KEYS = ("gamma", "gain", "lift", "saturation", "brightness", "contrast",
              "range", "curve_rgb", "curve_red", "curve_green", "curve_blue")

_SAVED_CACHE = {}


def saved_profiles(folders):
    """``[(name, path, Profile)]`` of the profile files (``*.txt``) in
    *folders*, by file name (PAD-360: the Saved profiles list).  A text file
    that sets none of a profile's numbers is left out."""
    import os
    out, seen = [], set()
    for folder in folders:
        try:
            names = sorted(os.listdir(folder), key=str.lower)
        except OSError:
            continue
        for n in names:
            path = os.path.join(folder, n)
            key = os.path.normcase(os.path.abspath(path))
            if not n.lower().endswith(".txt") or key in seen:
                continue
            try:
                stamp = os.stat(path)
            except OSError:
                continue
            if not os.path.isfile(path):
                continue
            seen.add(key)
            hit = _SAVED_CACHE.get(key)
            if hit is None or hit[0] != (stamp.st_mtime, stamp.st_size):
                prof = None
                try:
                    with open(path, encoding="utf-8-sig") as f:
                        text = f.read(65536)
                    keys = {ln.split("#", 1)[0].partition("=")[0].strip()
                            .lower() for ln in text.splitlines()}
                    if keys & set(_FILE_KEYS):
                        prof = parse(text)[0]
                except (OSError, UnicodeDecodeError, ValueError, TypeError):
                    prof = None
                hit = _SAVED_CACHE[key] = ((stamp.st_mtime, stamp.st_size),
                                           prof)
            if hit[1] is not None:
                out.append((os.path.splitext(n)[0], path, hit[1]))
    return out


def _numbers_of(prof):
    nums = list(prof.gamma) + list(prof.gain) + list(prof.lift) + [
        prof.saturation, prof.brightness, prof.contrast]
    return nums, [tuple(r) for r in prof.ranges if not range_neutral(r)], [
        (ch, tuple(tuple(p) for p in pts)) for ch, pts in prof.curves
        if pts != CURVE_IDENTITY]


def same_numbers(a, b, tol=0.006):
    """Do profiles *a* and *b* change colours the same way, whatever their
    names (PAD-360)?  A file keeps two decimals of a slider's three, so
    numbers within *tol* are the same."""
    if a is None or b is None:
        return False
    na, ra, ca = _numbers_of(a)
    nb, rb, cb = _numbers_of(b)
    if len(ra) != len(rb) or [c[0] for c in ca] != [c[0] for c in cb]:
        return False
    flat = lambda nums, rs, cs: list(nums) + [v for r in rs for v in r] + [  # noqa: E731
        v for _ch, pts in cs for p in pts for v in p]
    fa, fb = flat(na, ra, ca), flat(nb, rb, cb)
    if len(fa) != len(fb):
        return False
    return all(abs(x - y) <= max(tol, tol * abs(y)) for x, y in zip(fa, fb))


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

#: The Machine screen a project starts from (PAD-341): tuned by a user on
#: a real Stern Spike 2 against photos of the machine's screen, so it says
#: what the screen does (applied forwards), with the colour ranges and
#: curves (PAD-339) a global gamma could not reach: teal blues, warm
#: oranges, a red that sits low in the mids.
SCREEN_DEFAULT_TEXT = """name = Recommended screen
gamma = 1.00 1.00 1.00
gain = 1.00 1.00 1.00
lift = 0.00 0.00 0.00
saturation = 1.00
brightness = 1.00
contrast = 1.00
range = 195 60 30 10 0.87 1.33 0.15
range = 30 40 20 0 0.9 1 0.05
curve_rgb = 0 0, 24 20, 64 92, 128 180, 192 224, 255 255
curve_red = 0 0, 32 32, 64 56, 128 106, 191 176, 224 216, 255 252
curve_green = 0 0, 224 224, 255 253
curve_blue = 0 0, 32 35, 64 76, 128 156, 192 210, 255 255
"""

#: The Machine screen mode's starting points (PAD-324): what the screen
#: does.  The first is the default a project's preview uses (PAD-341).
SCREEN_PRESETS = (
    ("screen_recommended", parse(SCREEN_DEFAULT_TEXT)[0]),
    ("none", Profile(name="No change")),
    ("bw", Profile(name="Black and white", saturation=0.0)),
    ("follow", None),
)

SCREEN_PRESET_LABELS = {"follow": "Same as individual files"}

SCREEN_PRESET_TIPS = {
    "screen_recommended": (
        "The default: tuned on a real Stern Spike 2 against photos of its "
        "screen. Middle shades come out much brighter, blues lean teal and "
        "turn richer, red sits a little low. A phone photo is not a color "
        "meter: nudge it until Scenes matches your machine."),
    "none": "The machine shows colors exactly as your PC does.",
    "bw": "A screen that shows everything in greys, the game's own art too.",
    "follow": ("The individual files profile, undone: the screen that "
               "correction was made for."),
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

#: Spike 2 (PAD-346): there the Recommended overlay and files profile is the
#: Machine screen undone, so its tip says that instead.
PRESET_TIPS_SPIKE2 = {
    "recommended": (
        "Undoes the Machine screen profile, so your files show on the "
        "machine the way they look on your PC, and Scenes and the Video "
        "tab's As on the machine preview them that way too. It follows the "
        "Machine screen: tune that one to your machine and this one changes "
        "with it. Built from the sliders, Color ranges and Curves below, so "
        "you can nudge it from there; moving one keeps your numbers and it "
        "stops following. With the whole screen overlay on Recommended too, "
        "your files get both."),
}
