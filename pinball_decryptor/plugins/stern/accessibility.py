"""Accessibility on a Spike 2 card (PAD-1589; docs/plans/pad1589_accessibility.md): colour-blind insert colours and
spoken scores.

**Colour-blind insert colours.** The game tells its shots apart by the colours of its RGB inserts (red, orange,
yellow, green, cyan, blue, purple, magenta), and for a player with red-green colour blindness red, orange, yellow and
green collapse onto one colour; with blue-yellow, yellow/orange and blue/purple pairs do. A preset moves each hue to
another round the colour wheel - in the same order, red and white staying as they are, the brightness kept - chosen so
the game's colours stay apart as that player sees them (:data:`PRESETS`, tuned on the Machado 2009 simulation; the
worst pair of the game's colours goes from 7.8 to 26.0 CIE76 apart for red-green, 16.7 to 30.1 for blue-yellow:
tests/test_pad1589_accessibility.py). On the card the mode runtime repaints every RGB insert the game lights in the
preset's colour, on a light layer of its own over the game's (pad_mode_runtime.c "accessibility"); a one-colour insert
glows in its own lens's colour and cannot change. The same integer maths is here (:func:`remap`), in the runtime
(``acc_remap``), in the emulator's playfield window (tools/spike2_emu/playfield.py) and in the Modes tab's Light shows
preview (modes_lightshows.js ``cvdRemap``): the test holds the copies together.

**Spoken scores.** At the end of each ball the machine says the player's number and score ("player two, one million
two hundred thousand five hundred"), from number words the Write makes with the computer's own voice and adds to the
card's sounds (:data:`WORDS`, :func:`make_words`) on a request the game never plays; holding the left flipper button
for two seconds in attract says each player's last score again. Off to start with: SPOKEN SCORES in the service menu.

The project sidecar keys: ``colour_blind: {"on": true, "preset": "red_green"}``, ``spoken_scores: {"on": true}``. The
runtime's file beside it on the card: ``access.cfg``."""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

#: the project sidecar's keys
CVD_KEY = "colour_blind"
SPOKEN_KEY = "spoken_scores"
#: the runtime's file beside the mode runtime (/usr/local/padmode on a card, /dump in the rig)
CFG_NAME = "access.cfg"

# ---- colour-blind presets -------------------------------------------------------------------------------------------

#: each preset: its menu value (0 is Off), its name, and its hue map - (game hue, shown hue) in degrees at the game's
#: colours, linear between them round the wheel (the shorter way). Found by search (C:/tmp/PAD-1589/cvd_lab2.py):
#: order kept, the smallest distance between any two of :data:`GAME_COLOURS` as the player sees them made largest.
PRESETS = {
    "red_green": (1, "Red-green", ((0, -5), (25, 105), (50, 155), (120, 190), (180, 210), (240, 260), (275, 335),
                                   (300, 340))),
    "blue_yellow": (2, "Blue-yellow", ((0, 0), (25, 25), (50, 40), (120, 135), (180, 200), (240, 230), (275, 290),
                                       (300, 305))),
}
PRESET_ORDER = ("red_green", "blue_yellow")
DEFAULT_PRESET = "red_green"
#: the colours Stern's games light shots in (Venom's Grendel orange is c02000, PAD-945)
GAME_COLOURS = {"red": 0xff0000, "orange": 0xff6000, "yellow": 0xffd000, "green": 0x00ff00, "cyan": 0x00ffff,
                "blue": 0x0000ff, "purple": 0x8000ff, "magenta": 0xff00ff, "white": 0xffffff}
#: the service menu's COLOUR BLIND row: 0 Off, then the presets (values shown from 0)
CVD_MENU_VALUES = 1 + len(PRESET_ORDER)
CVD_MENU_HELP = "0 Off, 1 red-green, 2 blue-yellow: inserts in colors kept apart"
SPOKEN_MENU_HELP = "On: says the player and score at each ball's end"


def _tdiv(a, b):
    """C's integer division (towards zero), so the copies in C and JavaScript give the same bytes."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def _anchors(preset):
    """The preset's hue map in tenths of a degree, closed round the wheel."""
    pts = [(a * 10, o * 10) for a, o in PRESETS[preset][2]]
    return pts + [(pts[0][0] + 3600, pts[0][1] + 3600)]


def remap(rgb, preset):
    """``rgb`` (0xRRGGBB) as the colour-blind *preset* shows it: its hue moved, its brightest and dimmest parts kept
    (so the level the game gives it stays). Grey and white stay as they are; an unknown preset changes nothing."""
    if preset not in PRESETS:
        return rgb & 0xffffff
    r, g, b = (rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if not d:
        return rgb & 0xffffff
    if mx == r:
        h = _tdiv(600 * (g - b), d)
    elif mx == g:
        h = _tdiv(600 * (b - r), d) + 1200
    else:
        h = _tdiv(600 * (r - g), d) + 2400
    h %= 3600
    pts = _anchors(preset)
    o = h
    for (a, oa), (bb, ob) in zip(pts, pts[1:]):
        if a <= h < bb:
            dd = (ob - oa) % 3600
            if dd > 1800:
                dd -= 3600
            o = oa + _tdiv(dd * (h - a), bb - a)
            break
    o %= 3600
    sector, f = o // 600, o % 600
    rise, fall = mn + d * f // 600, mx - d * f // 600
    r, g, b = ((mx, rise, mn), (fall, mx, mn), (mn, mx, rise), (mn, fall, mx), (rise, mn, mx), (mx, mn, fall))[sector]
    return (r << 16) | (g << 8) | b


def preset_value(preset):
    """The menu value of *preset* (1, 2), 0 for none."""
    return PRESETS[preset][0] if preset in PRESETS else 0


# ---- spoken scores --------------------------------------------------------------------------------------------------

#: the words the card carries, by their number in sounds.cfg's ``sword`` lines (the runtime's ACC_W_* in the same order)
WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty",
         "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million", "billion", "player",
         "points")
W = {w: i for i, w in enumerate(WORDS)}


def _below_thousand(n):
    out = []
    if n >= 100:
        out += [W[WORDS[n // 100]], W["hundred"]]
        n %= 100
    if n >= 20:
        out.append(W[WORDS[20 + n // 10 - 2]])
        n %= 10
        if n:
            out.append(n)
    elif n:
        out.append(n)
    return out


def number_words(n):
    """The word numbers (indices into :data:`WORDS`) that say *n*: 1234567 -> one million two hundred thirty four
    thousand five hundred sixty seven. The runtime's acc_say_number does the same."""
    n = int(n)
    if n <= 0:
        return [W["zero"]]
    out = []
    for scale, word in ((10 ** 9, "billion"), (10 ** 6, "million"), (10 ** 3, "thousand")):
        if n >= scale:
            out += _below_thousand(n // scale % 1000) if n // scale < 1000 else number_words(n // scale)
            out.append(W[word])
            n %= scale
    return out + _below_thousand(n)


def say_score(player, score):
    """The words said at a ball's end: player N, then the score."""
    return [W["player"], int(player)] + number_words(score)


def spoken(indices):
    """The words, as text (for logs and tests)."""
    return " ".join(WORDS[i] for i in indices)


#: why the computer cannot make the words (no voice to make them with)
NO_VOICE = ("This computer has no text-to-speech voice the app can use to make the spoken numbers (Windows: its own "
            "voices; macOS: say; Linux: install espeak-ng).")


def voice():
    """``(kind, how)`` of the computer's voice the words are made with, or ``("", why)``."""
    if sys.platform.startswith("win"):
        return "sapi", "the Windows voice"
    if sys.platform == "darwin" and shutil.which("say"):
        return "say", "the macOS voice"
    for exe in ("espeak-ng", "espeak"):
        if shutil.which(exe):
            return exe, exe
    return "", NO_VOICE


#: the words' making: 2 = the voice's silence cut off each end (:func:`trim_silence`)
WORDS_REV = 2

_SAPI = r'''
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Rate = 1
foreach ($line in Get-Content -LiteralPath $args[0]) {
  $p = $line.Split("`t")
  $s.SetOutputToWaveFile($p[1])
  $s.Speak($p[0])
}
$s.SetOutputToNull()
'''


def make_words(cache_dir, log=None, timeout=300):
    """``[(word number, wav path)]``: each of :data:`WORDS` spoken by the computer's own voice into *cache_dir* (kept:
    the same voice makes the same files, so a second Write makes none). Raises RuntimeError when there is no voice or
    it failed."""
    kind, how = voice()
    if not kind:
        raise RuntimeError(how)
    os.makedirs(cache_dir, exist_ok=True)
    tag = hashlib.md5(("%s|%d|%s" % (kind, WORDS_REV, "|".join(WORDS))).encode()).hexdigest()[:10]
    paths = [os.path.join(cache_dir, "speak_%02d_%s_%s.wav" % (i, w, tag)) for i, w in enumerate(WORDS)]
    for f in os.listdir(cache_dir):                      # another voice's, or made before this revision
        if f.startswith("speak_") and f.endswith(".wav") and os.path.join(cache_dir, f) not in paths:
            try:
                os.remove(os.path.join(cache_dir, f))
            except OSError:
                pass
    todo = [(i, p) for i, p in enumerate(paths) if not (os.path.isfile(p) and os.path.getsize(p) > 1000)]
    if todo:
        if log:
            log("Spoken scores: making %d spoken number(s) with %s." % (len(todo), how), "info")
        if kind == "sapi":
            with tempfile.TemporaryDirectory(prefix="pad_speak_") as tmp:
                lst, ps1 = os.path.join(tmp, "words.txt"), os.path.join(tmp, "say.ps1")
                with open(lst, "w", encoding="utf-8") as f:
                    f.write("".join("%s\t%s\n" % (WORDS[i], p) for i, p in todo))
                with open(ps1, "w", encoding="utf-8") as f:
                    f.write(_SAPI)
                subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, lst],
                               check=True, capture_output=True, timeout=timeout,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            for i, p in todo:
                if kind == "say":
                    cmd = ["say", "-o", p, "--data-format=LEI16@22050", WORDS[i]]
                else:
                    cmd = [kind, "-w", p, WORDS[i]]
                subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        bad = [WORDS[i] for i, p in todo if not (os.path.isfile(p) and os.path.getsize(p) > 1000)]
        if bad:
            raise RuntimeError("%s made no sound for: %s" % (how, ", ".join(bad)))
        for _i, p in todo:
            trim_silence(p)
    return list(enumerate(paths))


def trim_silence(path, floor=0.02, keep_ms=20):
    """Cut the silence a voice leaves before and after a word (Windows' runs 0.3-0.5 s each side: a score of nine
    words would outrun the 10 s the end of a ball can be held), keeping *keep_ms* each side. 16-bit PCM WAVs only;
    anything else is left as it is."""
    import array
    import wave
    try:
        with wave.open(path, "rb") as w:
            ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            if sw != 2:
                return False
            data = array.array("h", w.readframes(n))
    except (OSError, EOFError, wave.Error):
        return False
    if sys.byteorder != "little":
        data.byteswap()
    lim = int(32767 * floor)
    frames = len(data) // ch
    loud = [i for i in range(frames) if max(abs(data[i * ch + c]) for c in range(ch)) > lim]
    if not loud:
        return False
    pad = rate * keep_ms // 1000
    a, b = max(0, loud[0] - pad), min(frames, loud[-1] + 1 + pad)
    if a == 0 and b == frames:
        return False
    out = data[a * ch:b * ch]
    if sys.byteorder != "little":
        out.byteswap()
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(out.tobytes())
    return True


# ---- the project's settings -----------------------------------------------------------------------------------------

def _raw(project, key):
    if not project:
        return {}
    from ...core import staged_changes
    try:
        raw = staged_changes.load(project).get(key)
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: nothing asked
        return {}
    return raw if isinstance(raw, dict) else {}


def load_cvd(project):
    """The colour-blind preset the project puts on its card (``"red_green"``, ``"blue_yellow"``), or ``""``."""
    raw = _raw(project, CVD_KEY)
    if not raw.get("on"):
        return ""
    return raw.get("preset") if raw.get("preset") in PRESETS else DEFAULT_PRESET


def preset_of(project):
    """The preset the project's preview shows (picked even while the tick is off), default red-green."""
    p = _raw(project, CVD_KEY).get("preset")
    return p if p in PRESETS else DEFAULT_PRESET


def save_cvd(project, on, preset=None):
    """Tick (or untick) the colour-blind insert colours, *preset* the one the card starts on; returns what it was."""
    from ...core import staged_changes
    data = staged_changes.load(project)
    raw = data.get(CVD_KEY) if isinstance(data.get(CVD_KEY), dict) else {}
    was = {"on": bool(raw.get("on")), "preset": raw.get("preset") if raw.get("preset") in PRESETS else DEFAULT_PRESET}
    preset = preset if preset in PRESETS else was["preset"]
    if on or preset != DEFAULT_PRESET:
        data[CVD_KEY] = {"on": bool(on), "preset": preset}
    else:
        data.pop(CVD_KEY, None)
    staged_changes.save(project, data)
    return was


def load_spoken(project):
    """Whether the project's card says the scores."""
    return bool(_raw(project, SPOKEN_KEY).get("on"))


def save_spoken(project, on):
    """Tick (or untick) spoken scores; returns what it was."""
    from ...core import staged_changes
    data = staged_changes.load(project)
    was = bool((data.get(SPOKEN_KEY) or {}).get("on")) if isinstance(data.get(SPOKEN_KEY), dict) else False
    if on:
        data[SPOKEN_KEY] = {"on": True}
    else:
        data.pop(SPOKEN_KEY, None)
    staged_changes.save(project, data)
    return was


#: what each needs of the card's port (the runtime's lights and sounds)
LAMP_DATA = ("lamp_layers",)
SOUND_SITES = ("sound_lookup",)
NO_TITLE = "The app cannot tell which game this project is for."
NO_LAMPS = "The app does not know where %s keeps its insert lights yet, so it cannot recolor them."
NO_SOUND = "The app cannot add sounds of its own to %s yet, so it cannot say the scores."
NO_SPIKE3 = "Spike 3 cards cannot take this yet."


def title_refusal(prof, what):
    """Why ``prof``'s title cannot take *what* (``"cvd"``, ``"spoken"``), or ``""``."""
    if prof is None:
        return NO_TITLE
    if getattr(prof, "arch", "arm") == "a64":
        return NO_SPIKE3
    from . import mode_project as MP
    try:
        port = MP.read_port(MP.port_path(prof))
    except (OSError, MP.ModeProjectError):
        return (NO_LAMPS if what == "cvd" else NO_SOUND) % prof.label
    if what == "cvd":
        if not all(d in port.get("data", {}) for d in LAMP_DATA) or not port.get("lamp"):
            return NO_LAMPS % prof.label
        return ""
    if not all(s in port.get("site", {}) for s in SOUND_SITES) or "scores" not in port.get("data", {}) \
            and "scores32" not in port.get("data", {}):
        return NO_SOUND % prof.label
    return ""


def cfg_text(cvd_preset="", cvd_setting=0, spoken=False, spoken_setting=0, flippers=(0, 0), only=False):
    """``access.cfg``: ``cvd <default value> <row address>`` (address 0: no row, the preset always on), ``spoken <row
    address> <left flipper switch>,<right>`` (address 0: always on), ``only`` when the card carries no modes."""
    lines = ["# PAD-1589: color-blind insert colors and spoken scores (pad_mode_runtime.c \"accessibility\")"]
    if cvd_preset:
        lines.append("cvd\t%d\t0x%x" % (preset_value(cvd_preset), int(cvd_setting or 0)))
    if spoken:
        lines.append("spoken\t0x%x\t%d,%d" % (int(spoken_setting or 0), int(flippers[0] or 0), int(flippers[1] or 0)))
    if only:
        lines.append("only")
    return "\n".join(lines) + "\n"
