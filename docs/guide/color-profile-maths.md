# Color profile: the maths

Exactly what the Color profile tab does to a colour, in order. The code is
`pinball_decryptor/core/colour_profile.py`; the tab's live preview
(`webui/static/js/tabs/color.js`) runs the same steps, and a test holds the
two together.

## Colour space

Everything works on the **8-bit sRGB values as stored** (0..255, or 0..1 in
a shader), the same numbers an image editor shows. Nothing is converted to
linear light, anywhere: not in Pillow (pictures), ffmpeg (videos), the game's
shaders (Spike 2), the Scenes preview, or the browser previews (their SVG
filters run with `color-interpolation-filters="sRGB"`).

## The three profiles

| Mode on the tab | What it is | Where it applies |
| --- | --- | --- |
| Adjust whole screen overlay | a correction | Spike 2: in the game's drawing shaders, to everything on screen. Elsewhere: baked into your replacement pictures and videos when you build. |
| Adjust individual files | a correction | baked into the files you switch on when you build (Spike 2 only) |
| Machine screen (preview only) | what the machine's screen does | only the previews: Scenes "As on the machine" and the Video tab's players. Never written to a card. |

The Scenes preview shows a frame as: the whole screen overlay, then the
machine screen, over the whole composited frame: the game's own art, your
replacements and the pictures you add (a test card included). Tick the gear
menu's "Switched-off files in their own colors" to let a picture whose Color
switch is off skip the machine screen instead (it is off by default).

**Until a Machine screen is stored**, the preview uses the individual files
profile *undone*: the inverse of step 3 per channel (`x = ((in - lift) / (1 -
lift)) ** (1 / gamma) / gain`, held at the edge where the correction clipped),
then a saturation mix of `1 / saturation` (black and white cannot be undone
and is left alone). That is the screen the correction was measured for.

**How Scenes applies it**: the frame is accumulated with colour premultiplied
by coverage; before the backdrop is laid under it, each pixel's straight
colour is taken (`rgb / alpha`), put through the screen, and multiplied back,
so a soft edge keeps its edge. Every layer gets it: the game's own art, your
replacements, the pictures you add. "Export picture…" writes what the preview
shows, so turn the Machine screen switch off under Preview colors to export
without it. The card build never includes it.

## Steps every profile has

Numbers are per channel (red, green, blue) unless noted. `in` and `out` are
0..1.

1. **Color strength** (`saturation`, one number): each pixel is mixed toward
   its own Rec.601 grey, `grey = 0.299 R + 0.587 G + 0.114 B`,
   `out = grey + saturation * (in - grey)`. Rounded and clamped to 0..255.
2. **Brightness** `b` and **contrast** `c` (one number each) are folded into
   step 3, never applied separately: `clip(in * b * k) ** c` with
   `k = 2 * 0.5 ** (1 / c)` (a mid grey stays mid grey; contrast is the slope
   there) becomes `gain' = k * b * gain ** (1 / c)` and `gamma' = gamma * c`.
   Both folded numbers are capped at 9.999999 (the shader's number slots).
3. **Per channel curve**: `out = lift + (1 - lift) * clip(in * gain, 0, 1) ** gamma`.
   Rounded to 0..255 through a 256-entry table.
   - *Middle shades* on the tab is `1 / gamma` (right = brighter).
   - *Color level* is `gain`.
   - *Lift the darkest shades* is `lift` (the same for all three).

Limits: gamma 0.1..5, gain 0..4, lift 0..0.9, saturation 0..4,
brightness 0..4, contrast 0.1..4. A value outside them in a file is skipped
and named, never applied.

## Machine screen only: colour ranges, then curves

These two come after steps 1 to 3, and only on the Machine screen (the
shaders have fixed slots for steps 1 to 3 and nothing else, so a build's
profiles never carry them: the whole screen overlay and individual files
profiles drop any `range` or `curve_` line, and Load... says so).

4. **Colour ranges**, each in turn (up to 6). For a pixel with
   `max = max(R, G, B)`, `min = min(R, G, B)`:
   - HSV hue `h` (degrees), saturation `s = (max - min) / max`, value `v = max`,
     and chroma `C = (max - min) / 255`.
   - hue weight: `1` within `width / 2` degrees of the range's `hue`, then
     falling to `0` over `soft` more degrees (smoothstep), so the edge blends.
   - grey weight: `smoothstep(C / protect)`: a pixel with chroma under
     `protect` (default 0.15) is only partly reached, a pure grey (`C = 0`)
     never.
   - `w = hue weight * grey weight`, then
     `h += shift * w`, `s *= 1 + (saturation - 1) * w` (clipped 0..1),
     `v *= 1 + (brightness - 1) * w` (clipped 0..255), back to RGB, rounded.
   - Limits: hue 0..360, width 0..360, soft 0..180, shift -180..180,
     saturation 0..4, brightness 0..4, protect 0..1. A new range has shift 0,
     saturation 1 and brightness 1: it changes nothing until you move it.
5. **Curves**: the RGB (master) curve on all three channels, then the Red,
   Green and Blue curves. Each is 2 to 16 points, input and output 0..255,
   joined by a monotone cubic (Fritsch-Carlson: no overshoot between points
   that rise), flat before the first point and after the last, rounded and
   clamped to 0..255. A curve through (0, 0) and (255, 255) alone changes
   nothing.

The Video tab's players draw steps 1, 3 and 5 (as SVG filters); step 4 has
no SVG form, so the colour ranges show in Scenes and on the Color profile tab
only.

## In a saved copy

```
name = My machine
gamma = 0.91 0.83 0.74
gain = 1.00 1.00 1.00
lift = 0.00 0.00 0.00
saturation = 1.11
brightness = 1.00
contrast = 1.00
range = 205 50 30 12 0.8 0.9 0.15
curve_rgb = 0 0, 64 48, 255 255
curve_blue = 0 0, 255 240
```

`range` is `hue width soft shift saturation brightness protect`, one line per
range. Files without `range` or `curve_` lines read exactly as before.
