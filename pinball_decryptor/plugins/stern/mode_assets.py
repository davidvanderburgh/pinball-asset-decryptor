"""BUILD a project's modes into the files a card or the emulator needs (item 127).

A project's modes (:mod:`.mode_project`) become, in the game tree's own layout:

* the in-game HUD scene with every mode's screen added (:func:`scene_write.add_screens`),
* the in-game video bank with every mode's clip added (:func:`video_bank.add_clip`), and
  each clip file at the path the bank names,
* one runtime mode file per mode, in slot order - ``mode.cfg``, ``mode1.cfg`` .. - the
  slots ``mode.so`` reads (item 133).

Everything comes from the STOCK scenes handed in, every time, so a build never stacks on a
previous build. A mode's own END SOUND is not built here: it is a record appended to
``image.bin`` (item 130), which joins at the Write step.

Clips are rendered without ffmpeg's drawtext (not every ffmpeg has it): a title card is
drawn with PIL and its frames piped to ffmpeg as raw video, then encoded the way most
stock Godzilla clips are - H.264 Constrained Baseline 3.0, 8-bit 4:2:0, 30 fps, silent.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import mode_project as MP
from . import scene_write as SW
from . import video_bank as VB

FONTS = (r"C:\Windows\Fonts\arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf")
FPS = 30
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class ModeAssetError(ValueError):
    """A mode's asset that cannot be built as asked."""


def _rgb(hexcolor):
    return tuple(int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))


def _font(size):
    for path in FONTS:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _fit_font(draw, text, max_w, start):
    size = start
    while size > 12:
        f = _font(size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 4
    return _font(12)


# ---- the screen's art ------------------------------------------------------------------
def panel_art(title, panel_color="#146e28", title_color="#ffe600", w=640, h=160):
    """The generated screen panel: a rounded panel with the title on it, as RGBA."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, w - 5, h - 5), radius=28, fill=_rgb(panel_color) + (235,),
                        outline=_rgb(title_color) + (255,), width=8)
    font = _fit_font(d, title, w - 60, 92)
    tw = d.textlength(title, font=font)
    top = (h - (font.size if hasattr(font, "size") else 12)) / 2 - 10
    d.text(((w - tw) / 2, top), title, font=font, fill=_rgb(title_color) + (255,))
    return np.asarray(img)


def load_art(path, max_w=1360, max_h=768):
    """A user's PNG as RGBA, padded to the multiple of 4 BC3 needs."""
    img = Image.open(path).convert("RGBA")
    if img.width > max_w or img.height > max_h:
        img.thumbnail((max_w, max_h))
    w, h = (img.width + 3) // 4 * 4, (img.height + 3) // 4 * 4
    if (w, h) != img.size:
        pad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        pad.paste(img, (0, 0))
        img = pad
    return np.asarray(img)


# ---- the clip -----------------------------------------------------------------------------
def _encode_args(ffmpeg, out):
    return [ffmpeg, "-v", "error", "-y"], ["-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0",
                                           "-pix_fmt", "yuv420p", "-b:v", "2500k", "-g", str(FPS), "-an",
                                           "-movflags", "+faststart", "-f", "mp4", out]


def title_frames(title, w, h, seconds, panel_color, title_color):
    """The title card's frames as RGB arrays: the title over the panel colour, with a
    bar in the title colour sweeping across so it reads as video, not a still."""
    base = Image.new("RGB", (w, h), _rgb(panel_color))
    d = ImageDraw.Draw(base)
    font = _fit_font(d, title, int(w * 0.9), max(24, int(h * 0.22)))
    tw = d.textlength(title, font=font)
    bbox = d.textbbox((0, 0), title, font=font)
    th = bbox[3] - bbox[1]
    text_xy = ((w - tw) / 2, (h - th) / 2 - bbox[1])
    bar_w = max(4, w // 22)
    n = max(1, int(round(seconds * FPS)))
    bar = np.array(_rgb(title_color), dtype=np.uint8)
    text_layer = Image.new("L", (w, h), 0)
    ImageDraw.Draw(text_layer).text(text_xy, title, font=font, fill=255,
                                    stroke_width=max(2, h // 96))
    stroke = np.asarray(text_layer) > 0
    fill_layer = Image.new("L", (w, h), 0)
    ImageDraw.Draw(fill_layer).text(text_xy, title, font=font, fill=255)
    fill = np.asarray(fill_layer) > 0
    background = np.asarray(base).copy()
    for i in range(n):
        frame = background.copy()
        x = int(-bar_w + (w + bar_w) * i / max(1, n - 1))
        frame[:, max(0, x):max(0, min(w, x + bar_w))] = bar
        frame[stroke] = 0
        frame[fill] = bar
        yield frame


def render_title_clip(out, title, w, h, seconds, panel_color, title_color, ffmpeg):
    head, tail = _encode_args(ffmpeg, out)
    cmd = head + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (w, h), "-r", str(FPS),
                  "-i", "-"] + tail
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=_NO_WINDOW)
    try:
        for frame in title_frames(title, w, h, seconds, panel_color, title_color):
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode("utf-8", "replace")
    if proc.wait() != 0 or not os.path.isfile(out):
        raise ModeAssetError("ffmpeg could not encode the title clip: %s" % err.strip()[-300:])


def convert_clip(src, out, w, h, ffmpeg, max_seconds=30):
    """A user's own video, made into what the bank plays: the bank's size (letterboxed,
    never stretched), 30 fps, silent, and no longer than ``max_seconds``."""
    head, tail = _encode_args(ffmpeg, out)
    vf = ("scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,fps=%d"
          % (w, h, w, h, FPS))
    cmd = head + ["-i", src, "-t", str(max_seconds), "-vf", vf] + tail
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NO_WINDOW)
    if r.returncode != 0 or not os.path.isfile(out):
        raise ModeAssetError("ffmpeg could not convert %s: %s"
                             % (os.path.basename(src), (r.stderr or "").strip()[-300:]))


# ---- clips made once, side by side, and kept -------------------------------------------------
# A build used to encode its clips one after another, inside the loop that adds each to the video
# bank (6 ffmpeg runs, 4.4 s of a Godzilla Try it, every time). The bank only needs each clip's
# size, so the clips are made first, up to CLIP_WORKERS at once, and each is kept under a digest of
# everything that goes into it (the source video's bytes or the title card's words, colours, length
# and font, the bank's frame size, the encoder and its arguments): a clip made before is copied, not
# encoded again. The bytes are the ones the loop made: the same encoder on the same input.
#: ``PAD_CLIP_CACHE=0``: no clip is kept between builds (they are still made side by side).
CLIP_CACHE_ENV = "PAD_CLIP_CACHE"
CLIP_WORKERS = 4
#: Clips kept at most; the least recently used go first.
CLIP_CACHE_KEEP = 40
#: Bump when a clip's encode changes in a way its key does not show.
_CLIP_REV = 1


@dataclass(frozen=True)
class ClipJob:
    """One clip a build puts in the bank: a title card or a person's own video, at the bank's size."""
    kind: str                    # "title" | "file"
    w: int
    h: int
    title: str = ""
    seconds: float = 0.0
    panel_color: str = ""
    title_color: str = ""
    src: str = ""


def clip_cache_dir():
    """Where made clips are kept: the temp dir, under a ``spike2_`` name like the other build
    scratch, so the app's clean-up knows it."""
    return os.path.join(tempfile.gettempdir(), "spike2_clip_cache")


_DIGESTS = {}
_DIGESTS_LOCK = threading.Lock()


def _file_digest(path):
    """sha256 of a file's bytes, worked out once per (path, size, mtime) in this process."""
    st = os.stat(path)
    key = (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns)
    with _DIGESTS_LOCK:
        got = _DIGESTS.get(key)
    if got is None:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
        got = h.hexdigest()
        with _DIGESTS_LOCK:
            _DIGESTS[key] = got
    return got


def _tool_identity(path):
    try:
        st = os.stat(path)
        return (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns)
    except (OSError, TypeError, ValueError):
        return (str(path),)


def clip_key(job, ffmpeg):
    """The digest a made clip is kept under: everything the encode reads."""
    parts = [_CLIP_REV, job.kind, job.w, job.h, FPS, _encode_args("ffmpeg", "OUT"),
             _tool_identity(ffmpeg)]
    if job.kind == "title":
        font = next((p for p in FONTS if os.path.exists(p)), "")
        parts += [job.title, float(job.seconds), job.panel_color, job.title_color,
                  _tool_identity(font) if font else "default font"]
    else:
        try:
            parts += [_file_digest(job.src), 30]
        except OSError:
            parts += ["missing", job.src]     # the encode says what is wrong with it
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()


def _encode_clip(job, out, ffmpeg):
    if job.kind == "title":
        render_title_clip(out, job.title, job.w, job.h, job.seconds, job.panel_color,
                          job.title_color, ffmpeg)
    else:
        convert_clip(job.src, out, job.w, job.h, ffmpeg)


def _prune_clip_cache(folder, keep=CLIP_CACHE_KEEP):
    try:
        names = [n for n in os.listdir(folder) if n.endswith(".mp4") and ".tmp" not in n]
        names.sort(key=lambda n: os.path.getmtime(os.path.join(folder, n)))
        for n in (names[:-keep] if len(names) > keep else ()):
            os.remove(os.path.join(folder, n))
    except OSError:
        pass


def make_clips(jobs, ffmpeg, workers=CLIP_WORKERS, progress=None):
    """Make every clip of ``jobs`` (:class:`ClipJob`), those not kept from an earlier build up to
    ``workers`` at a time. Returns ``(made, scratch)``: ``{job: path of its clip}`` and a folder
    the caller removes when done (``None`` when the clips are in the cache). ``progress(done,
    total, words)`` after each clip. Raises the first job's :class:`ModeAssetError`, in job order."""
    jobs = list(dict.fromkeys(jobs))
    if not jobs:
        return {}, None
    keep = os.environ.get(CLIP_CACHE_ENV, "1") != "0"
    folder = scratch = None
    if keep:
        folder = clip_cache_dir()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            keep = False
    if not keep:
        folder = scratch = tempfile.mkdtemp(prefix="spike2_clips_")
    made, todo = {}, []
    for job in jobs:
        path = os.path.join(folder, clip_key(job, ffmpeg) + ".mp4")
        if keep and os.path.isfile(path) and os.path.getsize(path) > 0:
            try:
                os.utime(path, None)          # recently used: kept longest
            except OSError:
                pass
            made[job] = path
        else:
            todo.append((job, path))
    done = [len(made)]
    lock = threading.Lock()

    def one(item):
        job, path = item
        tmp = "%s.%d.%d.tmp.mp4" % (path[:-4], os.getpid(), threading.get_ident())
        try:
            _encode_clip(job, tmp, ffmpeg)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        with lock:
            done[0] += 1
            if progress is not None:
                progress(done[0], len(jobs), "Making the modes' clips (%d of %d)..."
                         % (done[0], len(jobs)))
        return path

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(todo)))) as pool:
            futures = [(job, pool.submit(one, (job, path))) for job, path in todo]
            first_error = None
            for job, fut in futures:
                try:
                    made[job] = fut.result()
                except Exception as e:                      # noqa: BLE001
                    if first_error is None:
                        first_error = e
        if first_error is not None:
            if scratch:
                shutil.rmtree(scratch, ignore_errors=True)
            raise first_error
    if keep:
        _prune_clip_cache(folder)
    return made, scratch


def _place_clip(job, local, made, ffmpeg):
    """Put ``job``'s clip at ``local``: a copy of the one :func:`make_clips` made, or (a job it
    did not make) encoded here."""
    src = made.get(job) if made else None
    if src and os.path.isfile(src):
        shutil.copyfile(src, local)
    else:
        _encode_clip(job, local, ffmpeg)


def _title_job(title, parsed, seconds, panel_color, title_color):
    return ClipJob("title", parsed.width, parsed.height, title=title, seconds=float(seconds),
                   panel_color=panel_color, title_color=title_color)


def _file_job(path, parsed):
    return ClipJob("file", parsed.width, parsed.height, src=path)


def _first_clip_job(project, slug, spec, parsed):
    if spec.clip == "title":
        return _title_job(spec.clip_title or spec.name, parsed, spec.clip_seconds,
                          spec.panel_color, spec.title_color)
    return _file_job(os.path.join(MP.mode_folder(project, slug), spec.clip_file), parsed)


def _second_clip_job(project, slug, spec, parsed):
    """Item 141's second clip as a job, or ``None`` when the mode adds none."""
    kind = (spec.clip_both or {}).get("clip") if isinstance(spec.clip_both, dict) else None
    if spec.clip == "none" or kind not in ("title", "file"):
        return None
    if kind == "title":
        return _title_job(spec.clip_both.get("title") or spec.name, parsed,
                          spec.clip_both.get("seconds", 4.0), spec.panel_color, spec.title_color)
    return _file_job(os.path.join(MP.mode_folder(project, slug), spec.clip_both["file"]), parsed)


def _code_clip_job(project, slug, spec, parsed):
    return _file_job(os.path.join(MP.mode_folder(project, slug), spec.clip), parsed)


# ---- the whole build -----------------------------------------------------------------------
LCD = "assets/lcd/auto_loaded"


@dataclass
class ModeBuild:
    """What a build wrote, as game-tree relative paths under ``out_dir``."""
    out_dir: str
    slots: list = field(default_factory=list)       # [(slot, slug, name)]
    files: list = field(default_factory=list)       # game-tree relative paths written
    mode_files: list = field(default_factory=list)  # runtime mode file names, slot order
    new_files: list = field(default_factory=list)   # of `files`, the ones a stock card lacks
    port: str = ""                                  # "game.port" in padmode/ when the title's port shipped (item 148)


def mode_file_name(slot):
    return "mode.cfg" if slot == 0 else "mode%d.cfg" % slot


def build(project, stock_hud, stock_bank, out_dir, ffmpeg=None, only=None, code=None, prof=None,
          progress=None, stock_font=b""):
    """Build every mode in ``project`` (or the slugs in ``only``) from the stock scenes.

    ``stock_hud`` / ``stock_bank`` are the stock bytes of the title's HUD scene and video
    bank; ``stock_font`` the card's system scene whose full font a HUD with too few glyphs
    takes for its screens' words (item 164, :func:`.scene_write.carried_font`), or ``b""``. Writes ``out_dir/<game tree path>`` and ``out_dir/padmode/<mode files>``, and
    returns a :class:`ModeBuild`. Refuses - naming every reason - if any mode is invalid.

    ``code`` is the project's CODE modes with their own assets (``[(slug, CodeAssets)]``,
    :mod:`.code_modes`): their screens and clips go into the same HUD scene and bank, in the same
    pass, after the form modes'. A project of code modes only builds for ``prof`` (its card's
    title, :func:`.code_modes.profile_for`).

    The clips are made before the bank is built, side by side and kept between builds
    (:func:`make_clips`); ``progress(done, total, words)`` follows them."""
    found, broken = MP.list_modes(project)
    if broken:
        raise ModeAssetError("these modes could not be read: %s"
                             % ", ".join("%s (%s)" % b for b in broken))
    if only is not None:
        found = [(s, m) for s, m in found if s in only]
    code = list(code or ())
    if not found and not code:
        raise ModeAssetError("there are no modes to build")
    if len(found) > MP.MAX_MODES:
        raise ModeAssetError("a card holds at most %d modes" % MP.MAX_MODES)
    found = _modes_for_the_card(project, found)
    problems = []
    for slug, spec in found:
        for p in MP.validate(spec, MP.mode_folder(project, slug)):
            problems.append("%s: %s" % (spec.name, p))
    if code:
        from . import code_modes as CM
        for slug, cspec in code:
            problems += CM.validate(cspec, MP.mode_folder(project, slug))
    if problems:
        raise ModeAssetError(" ".join(problems))
    titles = {spec.title for _, spec in found}
    if len(titles) > 1:
        raise ModeAssetError("every mode on a card must be for the same game")
    if titles:
        prof = MP.profile(titles.pop())
    elif prof is None:
        from . import code_modes as CM
        prof = CM.profile_for(project, code)
        if prof is None:
            raise ModeAssetError(CM.NO_TITLE)
    result = ModeBuild(out_dir=out_dir)

    def write(rel, data):
        path = os.path.join(out_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        result.files.append(rel)
        return path

    # the screens, all in one pass over the stock HUD scene
    screens = []
    for slug, spec in found:
        if not spec.screen or not prof.can("screen"):
            continue
        names = MP.asset_names(slug)
        folder = MP.mode_folder(project, slug)
        art = (load_art(os.path.join(folder, spec.screen_art)) if spec.screen_art
               else panel_art(spec.screen_title or spec.name, spec.panel_color, spec.title_color))
        screens.append(dict(name=names["screen_node"], art_rgba=art,
                            words="%s A SHOT" % "{:,}".format(int(spec.award)),
                            words_name=names["screen_text"].split(".", 1)[1]))
    screens += _code_screens(project, code, prof)

    # the clips: made first (side by side, kept between builds), then one after another into
    # the stock bank
    clips = [(slug, spec) for slug, spec in found if spec.clip != "none" and prof.can("clip")]
    code_clips = [(slug, c) for slug, c in code if c.clip and prof.can("clip")]
    # item 164: a title whose video bank IS the scene its screens go in (JP The Pin 1.05 draws one
    # scene) gets the clips first and then the screens, onto the grown bank - the bank's walk
    # refuses anything but clips, and the screens' offsets are moved past what the clips added
    shared = bool(screens) and bool(clips or code_clips) and prof.lcd("hud") == prof.lcd("bank")
    # item 164: a title that draws no video bank in play (The Munsters) names its HUD as the bank,
    # and the clips go into the HUD in a Video grafted there, with the screens in the same pass
    if (clips or code_clips) and prof.lcd("hud") == prof.lcd("bank") and SW.grafts_video(stock_hud):
        _build_grafted(project, prof, stock_hud, screens, clips, code_clips, out_dir, ffmpeg,
                       result, write, progress, stock_font)
        clips = code_clips = []
        screens = []
    if screens and not shared:
        hud, _infos = SW.add_screens(stock_hud, screens, font_source=stock_font)
        write("%s/scene.radium" % prof.lcd("hud"), hud)

    def with_screens(bank):
        return SW.add_screens(bank, screens, stock=stock_bank, font_source=stock_font)[0] if shared else bank
    made, scratch = {}, None
    if clips or code_clips:
        if not ffmpeg:
            raise ModeAssetError("building a clip needs ffmpeg, and none was found")
        size = VB.parse(stock_bank)
        jobs = []
        for slug, spec in clips:
            jobs.append(_first_clip_job(project, slug, spec, size))
            jobs.append(_second_clip_job(project, slug, spec, size))
        jobs += [_code_clip_job(project, slug, c, size) for slug, c in code_clips]
        made, scratch = make_clips([j for j in jobs if j is not None], ffmpeg, progress=progress)
    try:
        if code_clips and not clips:
            bank, _parsed = _add_code_clips(project, code_clips, stock_bank, VB.parse(stock_bank),
                                            prof, out_dir, ffmpeg, result, made)
            write("%s/scene.radium" % prof.lcd("bank"), with_screens(bank))
            code_clips = []
        if clips:
            bank = stock_bank
            parsed = VB.parse(bank)
            for slug, spec in clips:
                names = MP.asset_names(slug)
                path = VB.next_path(parsed)
                rel = "%s/scene.assets/%s" % (prof.lcd("bank"), path)
                local = os.path.join(out_dir, *rel.split("/"))
                os.makedirs(os.path.dirname(local), exist_ok=True)
                _place_clip(_first_clip_job(project, slug, spec, parsed), local, made, ffmpeg)
                result.files.append(rel)
                result.new_files.append(rel)
                bank, _info = VB.add_clip(bank, names["clip"], os.path.getsize(local), path)
                parsed = VB.parse(bank)
                bank, parsed = _add_second_clip(project, slug, spec, bank, parsed, prof, out_dir,
                                                ffmpeg, result, made)
            if code_clips:
                bank, parsed = _add_code_clips(project, code_clips, bank, parsed, prof, out_dir,
                                               ffmpeg, result, made)
            write("%s/scene.radium" % prof.lcd("bank"), with_screens(bank))
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)

    # the runtime mode files, in slot order, beside the tree rather than in it: on a card
    # they go to p2 (/usr/local/padmode), in the rig to /dump
    for slot, (slug, spec) in enumerate(found):
        name = mode_file_name(slot)
        path = os.path.join(out_dir, "padmode", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(MP.runtime_cfg(spec, slug))
        result.mode_files.append(name)
        result.slots.append((slot, slug, spec.name))
    os.makedirs(os.path.join(out_dir, "padmode"), exist_ok=True)   # a project of code modes only
    _ship_port(prof, out_dir, result)
    return result


def _ship_port(prof, out_dir, result):
    """Item 148: the title's port beside the mode files, as ``padmode/game.port`` - the
    runtime arms on no other (MODE_SDK.md "Ports"), so a build for TMNT ships TMNT's."""
    src = MP.port_path(prof)
    if not src or not os.path.isfile(src):
        raise ModeAssetError("the port for %s (%s) is missing, and the runtime arms on no other"
                             % (prof.label, prof.port or "none named"))
    with open(src, "rb") as f:
        data = f.read()
    with open(os.path.join(out_dir, "padmode", "game.port"), "wb") as f:
        f.write(data)
    result.port = "game.port"


def _modes_for_the_card(project, found):
    """Item 148: the modes as the PROJECT'S CARD runs them. A mode keeps the title it was
    made for in ``mode.json`` (every mode made before item 148 says Godzilla Pro 1.15), but
    the card decides the port, the shot masks and the scenes, so each mode is matched to
    the card's port by shot name. Refuses a card whose build has no port, and a mode that
    names a shot the card's game does not have (the Modes tab shows it for that game, so
    the person picks again) - never a build with shots quietly left out. A project that
    names no card, or whose card cannot be read, builds each mode for its own title."""
    card, prof = MP.project_profile(project, probe=True)
    if card is None or not card.game_dir:
        return found
    if prof is None:
        raise ModeAssetError(MP.NO_PORT_HELP % MP.title_label(card.game_dir, card.version))
    out, problems = [], []
    for slug, spec in found:
        new, dropped = MP.retarget(spec, prof)
        if dropped:
            problems.append(MP.retarget_refusal(spec, dropped, prof))
        out.append((slug, new))
    if problems:
        raise ModeAssetError(" ".join(problems))
    return out


def _add_second_clip(project, slug, spec, bank, parsed, prof, out_dir, ffmpeg, result, made=None):
    """Item 141: a mode's SECOND clip (``clip_both`` a title card or a video file), added to
    the bank as :func:`MP.second_clip_name`. "same" plays the first clip again and adds
    nothing. Returns the bank and its parse. ``made``: the clips :func:`make_clips` made."""
    job = _second_clip_job(project, slug, spec, parsed)
    if job is None:
        return bank, parsed
    path = VB.next_path(parsed)
    rel = "%s/scene.assets/%s" % (prof.lcd("bank"), path)
    local = os.path.join(out_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(local), exist_ok=True)
    _place_clip(job, local, made, ffmpeg)
    result.files.append(rel)
    result.new_files.append(rel)
    bank, _info = VB.add_clip(bank, MP.second_clip_name(slug), os.path.getsize(local), path)
    return bank, VB.parse(bank)


# ---- a CODE mode's own screen and clip (the intricate modes' own audio and video) --------------
def code_words_at(art):
    """Where a code mode's words go when its picture carries a band for them (``words_on_art``):
    14 px above the picture's bottom edge, so the text box (40 px above its line, 8 below) sits on
    the darkened band :func:`.code_modes.compose_art` gives the picture."""
    h = int(np.asarray(art).shape[0])
    return (20.0, float(h - 14))


def _code_screens(project, code, prof):
    """The screens of the project's code modes, for :func:`build`'s one pass over the HUD scene:
    each named after its folder (``PadMode_<slug>_Screen``, the names a code mode looks for), its
    picture or a generated panel, and its words on the picture's band or under it. The words start
    as the mode's name; the mode writes its own from then on."""
    out = []
    for slug, spec in code or ():
        if not spec.screen or not prof.can("screen"):
            continue
        names = MP.asset_names(slug)
        folder = MP.mode_folder(project, slug)
        art = (load_art(os.path.join(folder, spec.screen_art)) if spec.screen_art
               else panel_art(spec.name, spec.panel_color, spec.title_color))
        out.append(dict(name=names["screen_node"], art_rgba=art, words=spec.name,
                        words_name=names["screen_text"].split(".", 1)[1],
                        words_at=code_words_at(art) if (spec.screen_art and spec.words_on_art) else None))
    return out


def _add_code_clips(project, code_clips, bank, parsed, prof, out_dir, ffmpeg, result, made=None):
    """The code modes' start clips into the bank, after the form modes' (``PadMode_<slug>_Clip``),
    each made into the bank's format like a form mode's own video. Returns the bank and its parse.
    ``made``: the clips :func:`make_clips` made."""
    for slug, spec in code_clips:
        names = MP.asset_names(slug)
        path = VB.next_path(parsed)
        rel = "%s/scene.assets/%s" % (prof.lcd("bank"), path)
        local = os.path.join(out_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(local), exist_ok=True)
        _place_clip(_code_clip_job(project, slug, spec, parsed), local, made, ffmpeg)
        result.files.append(rel)
        result.new_files.append(rel)
        bank, _info = VB.add_clip(bank, names["clip"], os.path.getsize(local), path)
        parsed = VB.parse(bank)
    return bank, parsed


@dataclass
class _Frame:
    """A clip's frame size, where the bank's parse would give it."""
    width: int
    height: int


def _build_grafted(project, prof, stock_hud, screens, clips, code_clips, out_dir, ffmpeg, result,
                   write, progress=None, stock_font=b""):
    """Item 164: every clip into a Video grafted into the HUD scene (:func:`scene_write.add_screens`
    ``clips``), each file at ``<hud>/scene.assets/<n>.asset``, and the screens in the same pass."""
    if not ffmpeg:
        raise ModeAssetError("building a clip needs ffmpeg, and none was found")
    frame = _Frame(*SW.video_size(stock_hud))
    todo = []
    for slug, spec in clips:
        todo.append((_first_clip_job(project, slug, spec, frame), MP.asset_names(slug)["clip"]))
        second = _second_clip_job(project, slug, spec, frame)
        if second is not None:
            todo.append((second, MP.second_clip_name(slug)))
    todo += [(_code_clip_job(project, slug, c, frame), MP.asset_names(slug)["clip"])
             for slug, c in code_clips]
    made, scratch = make_clips([job for job, _name in todo], ffmpeg, progress=progress)
    entries = []
    try:
        for n, (job, name) in enumerate(todo, 1):
            path = "%d.asset" % n
            rel = "%s/scene.assets/%s" % (prof.lcd("hud"), path)
            local = os.path.join(out_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(local), exist_ok=True)
            _place_clip(job, local, made, ffmpeg)
            result.files.append(rel)
            result.new_files.append(rel)
            entries.append((name, path, os.path.getsize(local)))
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)
    hud, _infos = SW.add_screens(stock_hud, screens, clips=entries, font_source=stock_font)
    write("%s/scene.radium" % prof.lcd("hud"), hud)
