"""Pure helpers for the web Extract tab (``webui/tabs/extract.py``).

These were GUI-module code in the Tk build (``gui/main_window.py`` and
``gui/read_card_dialog.py``, which import tkinter at module level and go
away with the cut-over), so they live here in the web UI's own tree.  Each
one is a straight port: same inputs, same output, same wording.

Nothing in here touches the store or the UI loop; the worker-thread
functions (``probe_input``, ``collect_project_stats``, ``project_details``,
``project_game``) are safe to run off the loop.
"""

import base64
import io
import ntpath
import os
import sys
import time

# Hover text for the per-type Extract checkboxes (capabilities.
# extract_categories); an unknown key falls back to "Include <label> when
# extracting." (gui/main_window.py _EXTRACT_CATEGORY_TIPS).
EXTRACT_CATEGORY_TIPS = {
    "audio": "Decode every packed sound to an individual WAV.",
    "video": "Pull out the game's video clips (H.264 .mov).",
    "images": "Export the loose image / texture assets (PNG / DDS).",
    "text": "Export the on-screen display-text strings for editing.",
}

DEFAULT_SAFETY_TEXT = ("⚠ Remove the SSD from the pinball machine before "
                       "connecting. Always keep the original ISO as a backup.")

DEFAULT_DELTAS_HELP = (
    "Supply a full image as the Input above, then add the delta update(s) "
    "needed to reach the version you want — Extract merges them "
    "automatically, in version order.")

FDA_BODY = (
    "Direct-SSD on macOS reads raw disk blocks via Homebrew's e2fsprogs.  "
    "macOS Sonoma+ blocks this at the TCC layer until every binary involved "
    "is on the Full Disk Access list — even with admin password.\n\n"
    "To grant (one-time setup):\n"
    "   1.   System Settings → Privacy & Security → Full Disk Access.\n"
    "   2.   Click + and add each of these:\n"
    "          •   Pinball Asset Decryptor.app\n"
    "          •   debugfs  (usually /opt/homebrew/opt/e2fsprogs/sbin/debugfs "
    "on Apple Silicon, /usr/local/opt/e2fsprogs/sbin/debugfs on Intel)\n"
    "          •   e2fsck   (same folder as debugfs)\n"
    "   3.   Toggle each one ON.\n"
    "   4.   Fully quit this app (⌘Q) and reopen.\n\n"
    "Tip:  the binaries are in hidden folders.  In the Full Disk Access file "
    "picker, press ⌘⇧G and paste the full path.\n\n"
    "Already granted?  Click \"Hide this notice\" above — it'll stay hidden "
    "across restarts.  The notice auto-hides after your first successful SSD "
    "extract.")

CAPTURE_PRIMARY_HELP = (
    "Runs the game in attract mode under PinMAME and records the DMD "
    "animations + audio as the firmware renders them.  These games' "
    "animations are compressed and only appear at runtime, so capture is "
    "the extraction method.  Requires libpinmame.")
CAPTURE_COMBINED_HELP = (
    "Combined: runs the basic ROM asset extract (sprites, fonts, splash "
    "bitmaps, animation MP4s) AND the PinMAME runtime capture (per-scene "
    "cinematics with synced DCS audio) into the same output folder.  "
    "Capture requires libpinmame.dll installed.\n\n"
    "\"Simulate gameplay\" (recommended ON): drives coin + Start + Launch + "
    "the per-game scripted shot sequences (Big-O-Beam, Stroke of Luck, "
    "multiball, etc.) so the game actually enters play.  OFF = attract-mode "
    "only — leaves PinMAME idle, capturing just the attract reel.")
CAPTURE_ONLY_HELP = (
    "Capture only: PinMAME runtime capture without the static ROM asset "
    "extract.  Output is just the per-scene cinematics + DCS audio.  "
    "Faster + uses less disk than the combined run, useful when you "
    "already have the static assets or only want the live cinematics.")
CAPTURE_BASIC_HELP = (
    "Basic only: scans the ROM for raw asset bitmaps (sprites, font glyphs, "
    "splash screens, paired 4-shade composites).  Tick \"Use PinMAME\" too "
    "to ALSO record live gameplay cinematics.")
CAPTURE_NEITHER_HELP = "Tick at least one box above to run an extract."


def capture_help(caps, basic, capture):
    """(text, kind) for the grey help paragraph under the capture rows
    (``_update_capture_help_text``); kind "err" is the red variant."""
    if caps is not None and caps.capture and not caps.extract:
        return CAPTURE_PRIMARY_HELP, ""
    if basic and capture:
        return CAPTURE_COMBINED_HELP, ""
    if capture and not basic:
        return CAPTURE_ONLY_HELP, ""
    if basic and not capture:
        return CAPTURE_BASIC_HELP, ""
    return CAPTURE_NEITHER_HELP, "err"


def admin_body_text(mfr):
    """Body copy for the "Administrator required" panel
    (``_admin_body_text``)."""
    noun = getattr(mfr, "direct_medium_noun", "SSD") if mfr else "SSD"
    ssd_label = (getattr(mfr, "extract_ssd_label", "From SSD")
                 if mfr else "From SSD")
    return (
        f"Reading directly from the {noun} needs Windows Administrator "
        "privileges — Windows gates raw disk access behind elevation. "
        "Close the app, right-click the \"Pinball Asset Decryptor\" "
        "shortcut, choose \"Run as administrator\", then re-select "
        f"\"{ssd_label}\" — your drive and output folder are remembered.")


def input_label(mfr):
    """The Input row's noun: the plugin's ``extract_input_label`` ("Card
    image"), else its primary extension (".zip"), else "Input"."""
    noun = getattr(mfr, "extract_input_label", None)
    if noun:
        return noun
    spec = getattr(mfr, "input_spec", None)
    exts = spec.extensions if spec is not None else ()
    primary = exts[0] if exts else "file"
    return primary if primary.startswith(".") else "Input"


def input_filetypes(mfr):
    """The Browse filter (``_input_filetypes``)."""
    spec = getattr(mfr, "input_spec", None) if mfr is not None else None
    if spec is None or not spec.extensions:
        return [("All files", "*.*")]
    joined = " ".join(f"*{ext}" for ext in spec.extensions)
    return [(spec.label, joined), ("All files", "*.*")]


def deltas_summary(paths):
    """The chosen-deltas line (``_refresh_deltas_display``)."""
    n = len(paths)
    if not n:
        return "No updates added"
    names = ", ".join(os.path.basename(p) for p in paths)
    return f"{n} update(s): {names}" if len(names) <= 70 \
        else f"{n} update(s) added"


def find_checksums_ancestor(path, max_levels=3):
    """The nearest ancestor (up to *max_levels* hops) holding
    ``.checksums.md5``, or None (``_find_checksums_ancestor``)."""
    current = path
    for _ in range(max_levels):
        parent = os.path.dirname(current)
        if not parent or parent == current:
            return None
        if os.path.isfile(os.path.join(parent, ".checksums.md5")):
            return parent
        current = parent
    return None


# ----------------------------------------------------------------------
# detection (worker thread)
# ----------------------------------------------------------------------
def probe_input(mfr, manufacturers, path):
    """Everything the tab derives from the Extract input path, collected
    off the UI loop: the current plugin's detection (and its title caption),
    other plugins that claim the file, whether its audio exports, and the
    game-aware decode-DMD / merge-deltas gates.  Mirrors ``_set_badge``,
    ``_refresh_extract_audio_support`` and ``_on_extract_input_changed``;
    every plugin call is guarded the way those were."""
    path = (path or "").strip()
    res = {"path": path, "exists": False, "game": None, "era": "",
           "caption": None, "others": [], "audio_supported": True,
           "decode_applies": False, "decode_label": "",
           "chain_applies": False, "size": None}
    if mfr is None:
        res["audio_supported"] = False
        return res
    try:
        res["decode_applies"] = bool(mfr.decode_dmd_applies(path))
    except Exception:                                   # noqa: BLE001
        res["decode_applies"] = False
    if res["decode_applies"]:
        try:
            res["decode_label"] = mfr.decode_dmd_label_for(path) or ""
        except Exception:                               # noqa: BLE001
            res["decode_label"] = getattr(mfr, "decode_dmd_label", "") or ""
    try:
        res["chain_applies"] = bool(mfr.chain_deltas_applies(path))
    except Exception:                                   # noqa: BLE001
        res["chain_applies"] = False
    if not path or not os.path.isfile(path):
        return res
    res["exists"] = True
    try:
        res["size"] = os.path.getsize(path)
    except OSError:
        res["size"] = None
    try:
        res["audio_supported"] = bool(mfr.audio_export_supported(path))
    except Exception:                                   # noqa: BLE001
        res["audio_supported"] = False
    try:
        game = mfr.detect(path)
    except Exception:                                   # noqa: BLE001
        game = None
    if game:
        res["game"] = game
        res["era"] = getattr(game, "era", "") or ""
        # the caption is only meaningful under the era the file belongs to;
        # the caller re-probes after an era switch, so skip it here then
        if not (res["era"] and hasattr(mfr, "set_era")
                and getattr(mfr, "_era", "") != res["era"]):
            try:
                res["caption"] = mfr.title_caption(path, game)
            except Exception:                           # noqa: BLE001
                res["caption"] = getattr(game, "display", None)
        return res
    for m in manufacturers:
        if m.key == mfr.key:
            continue
        try:
            g = m.detect(path)
        except Exception:                               # noqa: BLE001
            continue
        if g:
            res["others"].append((m, g))
    return res


# ----------------------------------------------------------------------
# project stats (worker thread) - the Project Info popup's rows
# ----------------------------------------------------------------------
def human_size(n):
    """``MainWindow._pex_human``: "512 B", "3.4 MB"."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return ("%d %s" % (int(size), unit) if unit == "B"
                    else "%.1f %s" % (size, unit))
        size /= 1024.0
    return "%d B" % int(n)


def collect_project_stats(folder):
    """The Project Info popup's rows for *folder*, ``[(name, value), ...]``
    (``MainWindow._collect_project_stats``, unchanged)."""
    from ..core import project_file, staged_changes, staged_originals

    audio_ext = {".wav", ".ogg", ".mp3", ".flac"}
    video_ext = {".mp4", ".webm", ".avi", ".mov", ".mkv", ".m4v",
                 ".mpg", ".mpeg"}
    image_ext = {".png", ".jpg", ".jpeg", ".webp", ".dds", ".bmp", ".gif"}
    counts = {"audio": [0, 0], "video": [0, 0],
              "image": [0, 0], "other": [0, 0]}
    total_files = 0
    total_bytes = 0
    for root_, _dirs, files in os.walk(folder):
        rel = os.path.relpath(root_, folder)
        in_hidden = (rel != "." and any(
            p.startswith(".") for p in rel.split(os.sep)))
        for fn in files:
            try:
                sz = os.path.getsize(os.path.join(root_, fn))
            except OSError:
                continue
            total_files += 1
            total_bytes += sz
            if in_hidden or fn.startswith("."):
                continue
            ext = os.path.splitext(fn)[1].lower()
            kind = ("audio" if ext in audio_ext
                    else "video" if ext in video_ext
                    else "image" if ext in image_ext else "other")
            counts[kind][0] += 1
            counts[kind][1] += sz

    def _files(kind):
        n, sz = counts[kind]
        return "%d file(s)  —  %s" % (n, human_size(sz)) if n else "none"

    try:
        data = staged_changes.load(folder)
        staged = sum(len(data.get(k) or {})
                     for k in ("audio", "video", "image"))
    except Exception:                                   # noqa: BLE001
        staged = 0
    try:
        built = len(list(staged_originals.snapshot_rels(folder)))
    except Exception:                                   # noqa: BLE001
        built = 0
    if staged or built:
        changed = []
        if staged:
            changed.append("%d staged for the next build" % staged)
        if built:
            changed.append("%d changed by earlier builds" % built)
        changed = ";  ".join(changed)
    else:
        changed = "nothing changed yet"

    anchor = project_file.anchor_path(folder)
    started = ""
    try:
        src = anchor if os.path.isfile(anchor) else folder
        started = time.strftime("%Y-%m-%d",
                                time.localtime(os.stat(src).st_ctime))
    except OSError:
        pass

    rows = [("Audio", _files("audio")),
            ("Video", _files("video")),
            ("Images", _files("image")),
            ("Other files", _files("other")),
            ("Total", "%d file(s)  —  %s on disk"
                      % (total_files, human_size(total_bytes))),
            ("Changed", changed)]
    if started:
        rows.append(("Project started", started))
    return rows


def project_details(folder, manufacturers=(), current=None):
    """What the "This project" card says about *folder* besides the stats:
    is it a project (hidden anchor), archived, does it hold an extract
    (the ``.checksums.md5`` baseline), which image it was extracted from
    and when (``.extract_source.json``), and which game that is.

    The game comes from the PROJECT, never from whatever the Extract input
    box holds right now: the image the extract recorded (else the anchor's
    stock image), detected by the anchor's manufacturer (else *current*)
    and captioned with ``title_caption`` - the same caption the title bar
    uses for that image.  Empty when the image is gone or not recognised.
    """
    from ..core import extract_source, project_file
    out = {"is_project": False, "archived": False, "baseline": False,
           "source_name": "", "extracted": "", "game": ""}
    anchor = None
    try:
        out["is_project"] = bool(project_file.has_anchor(folder))
    except Exception:                                   # noqa: BLE001
        out["is_project"] = False
    if out["is_project"]:
        try:
            anchor = project_file.load_anchor(folder)
            out["archived"] = bool(anchor.get("archived"))
        except (OSError, ValueError, Exception):        # noqa: BLE001
            anchor = None
            out["archived"] = False
    out["baseline"] = os.path.isfile(os.path.join(folder, ".checksums.md5"))
    rec = extract_source.read_extract_source(folder) or {}
    out["source_name"] = str(rec.get("input_name") or "")
    try:
        mtime = os.path.getmtime(
            os.path.join(folder, extract_source.SIDE_CAR))
        out["extracted"] = time.strftime("%Y-%m-%d", time.localtime(mtime))
    except OSError:
        out["extracted"] = ""
    mfr = current
    key = (anchor or {}).get("manufacturer") or ""
    if key:
        mfr = next((m for m in manufacturers or ()
                    if getattr(m, "key", None) == key), None)
    sources = [rec.get("input_path"), (anchor or {}).get("stock_image")]
    out["game"] = project_game(mfr, [s for s in sources
                                     if isinstance(s, str) and s])
    return out


_GAME_CACHE = {}


def project_game(mfr, sources):
    """The title caption of the first of *sources* (image paths) that is a
    file *mfr* recognises, or "".  A raw device path is skipped (a card
    read in place records no image), and the answer is cached per file
    signature so re-counting a project does not re-read its image."""
    if mfr is None:
        return ""
    from ..core.rawdevice import is_device_path
    for path in sources:
        if is_device_path(path) or not os.path.isfile(path):
            continue
        try:
            st = os.stat(path)
        except OSError:
            continue
        sig = (getattr(mfr, "key", ""), os.path.normcase(
            os.path.abspath(path)), st.st_size, int(st.st_mtime))
        if sig in _GAME_CACHE:
            return _GAME_CACHE[sig]
        try:
            game = mfr.detect(path)
        except Exception:                               # noqa: BLE001
            game = None
        caption = ""
        if game:
            try:
                caption = mfr.title_caption(path, game) or ""
            except Exception:                           # noqa: BLE001
                caption = getattr(game, "display", "") or ""
        if len(_GAME_CACHE) > 64:
            _GAME_CACHE.clear()
        _GAME_CACHE[sig] = caption
        if caption:
            return caption
    return ""


# ----------------------------------------------------------------------
# live DMD frames
# ----------------------------------------------------------------------
DMD_AMBER = (255, 130, 0)


def render_dmd_png(data, w, h, depth, color=DMD_AMBER):
    """A libpinmame RAW DMD frame as a PNG data URL at one pixel per dot
    (the page scales it up with ``image-rendering: pixelated``).  Same
    per-level amber LUT as the Tk preview's ``_render_pinmame_frame``;
    None when Pillow is missing or the frame is malformed."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        levels = max(1, (1 << int(depth)) - 1)
        r, g, b = color
        lut = bytearray(256 * 3)
        for i in range(256):
            lv = min(i, levels)
            ratio = lv / levels
            lut[3 * i] = int(r * ratio)
            lut[3 * i + 1] = int(g * ratio)
            lut[3 * i + 2] = int(b * ratio)
        n = int(w) * int(h)
        src = bytes(data[:n])
        if len(src) < n:
            return None
        rgb = bytearray(n * 3)
        j = 0
        for px in src:
            k = 3 * px
            rgb[j] = lut[k]
            rgb[j + 1] = lut[k + 1]
            rgb[j + 2] = lut[k + 2]
            j += 3
        img = Image.frombytes("RGB", (int(w), int(h)), bytes(rgb))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False)
        return "data:image/png;base64," + base64.b64encode(
            buf.getvalue()).decode("ascii")
    except Exception:                                   # noqa: BLE001
        return None


def switch_matrix(script):
    """The switch-matrix grid for the active capture script
    (``_build_switch_matrix``): a title and the named + unlabeled WPC
    positions, each ``{"sw", "text", "tip", "label"}``."""
    raw = script.profile.get("raw", {}) if script else {}
    named_by_sw = {int(sw): name for name, sw in raw.items()}
    named_entries = sorted(raw.items(), key=lambda kv: int(kv[1]))
    unknown = []
    for sw_n in range(11, 89):
        if sw_n in named_by_sw:
            continue
        if sw_n % 10 == 0 or sw_n % 10 > 8:
            continue
        unknown.append(sw_n)
    if not named_entries and not unknown:
        return {"title": "Switch matrix (no switches defined)",
                "named": [], "unknown": []}
    named = []
    for name, sw in named_entries:
        sw_n = int(sw)
        short = name.replace("sw", "", 1).strip()
        named.append({"sw": sw_n, "text": f"{sw_n:>2} {short[:8]}",
                      "tip": f"sw#{sw_n} — {short}", "label": short})
    unk = [{"sw": s, "text": f"{s:>2}  ?",
            "tip": f"sw#{s} (col {s // 10}, row {s % 10}) — unlabeled "
                   "standard WPC position",
            "label": f"sw#{s}"} for s in unknown]
    title = (f"Switch matrix — {getattr(script, 'title', '')} "
             f"({len(named_entries)} named + {len(unknown)} unlabeled WPC "
             "positions, click to press)")
    return {"title": title, "named": named, "unknown": unk}


# ----------------------------------------------------------------------
# Save card as image (gui/read_card_dialog.py)
# ----------------------------------------------------------------------
def fmt_size(n):
    """Decimal GB/MB size string (matches how card capacity is
    advertised)."""
    if not n:
        return "unknown"
    if n >= 10 ** 9:
        return "%.2f GB" % (n / 10 ** 9)
    if n >= 10 ** 6:
        return "%.1f MB" % (n / 10 ** 6)
    return "%d bytes" % n


def default_image_name(drive, noun):
    """A file name for the picked card that says what it came off."""
    base = (getattr(drive, "model", "") or noun or "card").strip()
    safe = "".join(c if (c.isalnum() or c in " -_") else "_" for c in base)
    safe = "-".join(safe.split()) or "card"
    size = getattr(drive, "size_bytes", None)
    if size:
        safe += "-%dGB" % round(size / 10 ** 9)
    return safe + ".raw"


def destination_is_on(drive, folder, platform=None):
    """True when *folder* sits on one of *drive*'s own mounted volumes
    (Windows drive letters only, as the Tk dialog checked)."""
    if (platform or sys.platform) != "win32":
        return False
    letters = (getattr(drive, "mount_label", "") or "").split()
    try:
        head = ntpath.splitdrive(ntpath.abspath(folder))[0]
    except (OSError, ValueError):
        return False
    head = head.rstrip(":").upper()
    return bool(head) and any(
        l.rstrip(":").upper() == head for l in letters)


def read_card_readout(card, image_path, noun):
    """(text, kind) for the card-size vs free-space line; kind is "", "err"
    or "ok" (``ReadCardDialog._render_readout``)."""
    if card is None:
        return "Pick the %s to read." % noun, ""
    card_size = getattr(card, "size_bytes", None)
    path = (image_path or "").strip()
    folder = os.path.dirname(os.path.abspath(path)) if path else ""
    free = None
    if folder and os.path.isdir(folder):
        try:
            import shutil
            free = shutil.disk_usage(folder).free
        except OSError:
            free = None
    if not card_size:
        return ("Card size unknown — it is checked before the read starts.",
                "")
    if free is None:
        return ("Card %s  →  image file of the same size."
                % fmt_size(card_size), "")
    if free < card_size:
        return ("⚠ Card %s, but only %s free in %s — the image won't fit. "
                "Pick somewhere with more room."
                % (fmt_size(card_size), fmt_size(free), folder), "err")
    return ("Card %s  →  %s free in %s   ✓ fits"
            % (fmt_size(card_size), fmt_size(free), folder), "ok")
