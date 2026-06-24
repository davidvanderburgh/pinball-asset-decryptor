"""Spike 2 audio engine — orchestration over the self-contained codec engine.

Ties together the pure-Python ext4 reader (:mod:`.ext4`) and the unicorn codec
oracle (:mod:`.spike2`):

  * **extract_all** — locate ``game_real`` + ``image.bin`` in the card's ext
    partitions, boot the firmware, derive (and cache) every sound's decode
    params, then decode each sound to a per-sound WAV.
  * **write_image** — re-encode the edited WAVs (size-neutral) and patch the
    sound bodies back into the card image in place (the ext4 file→disk offset
    map lets us overwrite only the changed bytes).

Everything the engine needs derives from ``game_real`` + ``image.bin`` alone —
no bundled per-title blobs.  The per-card params table is derived once (~1-2
min) and cached by a fingerprint of those two files, so re-runs are fast.

Heavy deps (unicorn, capstone, numpy) are imported lazily inside the functions,
so importing this module (which happens at plugin discovery) never requires
them — a missing dep is reported by the manufacturer's prerequisite probe.
"""

import hashlib
import os
import pickle
import re
import struct
import tempfile
import wave

# The engine is wired; a missing unicorn/numpy is surfaced via the plugin's
# prerequisite probe + a lazy import error, not by hiding the tabs.
AVAILABLE = True

_WAV_RE = re.compile(r"(?:idx)?0*(\d+)", re.IGNORECASE)
# Per-song music-bank WAVs (image-scNN.bin banks). EXTRACT-ONLY: Write re-encodes
# only the cat-0 sounds (idxNNNN.wav) back into image.bin — music_catNN_* live in
# separate image-scNN.bin banks Write doesn't patch.  The prefix survives an
# Auto-transcribe / Music-ID rename ("music_cat01_0001 - Battery.wav"), so it's
# the stable per-song key.
_MUSIC_WAV_RE = re.compile(r"(music_cat\d+_\d+)", re.IGNORECASE)


# --------------------------------------------------------------------------
# params cache (fingerprint of game_real + image.bin master-dir region)
# --------------------------------------------------------------------------
def _fingerprint(game_real_path, image_path):
    h = hashlib.sha256()
    with open(game_real_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    with open(image_path, "rb") as f:
        h.update(f.read(0x20000))   # header + master-directory source region
    return h.hexdigest()


def _cache_path(fp):
    d = os.path.join(tempfile.gettempdir(), "pinball_spike2_params")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, fp[:32] + ".pkl")


def _load_or_derive_params(emu, game_real_path, image_path, log, progress):
    fp = _fingerprint(game_real_path, image_path)
    cache = _cache_path(fp)
    if os.path.exists(cache):
        try:
            params = pickle.load(open(cache, "rb"))
            log("Loaded cached codec parameters (%d sounds)." % len(params), "info")
            return params
        except Exception:
            pass
    log("Deriving codec parameters from the firmware (one-time per card, "
        "~2-5 min)...", "info")
    if progress:
        progress(0, 0, "Deriving codec parameters...")
    params = emu.derive_params()
    try:
        pickle.dump(params, open(cache, "wb"))
    except Exception:
        pass
    log("Derived parameters for %d sounds." % len(params), "success")
    return params


# --------------------------------------------------------------------------
# locating + extracting the card's game_real / image.bin
# --------------------------------------------------------------------------
def _locate(disk_f, partitions):
    """Find the Spike 2 game directory (the one holding ``image.bin``) and its
    firmware ELF across the card's ext partitions (largest first).  Returns
    ``(reader, firmware_inode, image_inode)``.

    On the card the firmware binary is the ``game`` ELF sitting next to
    ``image.bin`` (with a top-level ``game`` *symlink* the locator skips by
    validating the ELF magic)."""
    from .ext4 import Ext4Reader
    img_only = None
    for off, size in partitions:
        try:
            r = Ext4Reader(disk_f, off, size)
        except Exception:
            continue
        img_ino, fw_ino = r.find_spike_assets()
        if img_ino is not None and fw_ino is not None:
            return r, r.read_inode(fw_ino), r.read_inode(img_ino)
        if img_ino is not None and img_only is None:
            img_only = (r, r.read_inode(img_ino))
    if img_only is not None:
        raise FileNotFoundError(
            "Found image.bin but not the game firmware ELF next to it on the "
            "card.")
    raise FileNotFoundError(
        "Could not find image.bin (with its game firmware) on the card.")


def _extract_inputs(disk_f, partitions, work_dir, log, read_progress=None):
    """Extract the firmware ELF + ``image.bin`` from the (already-open) card to
    ``work_dir``.  Returns ``(game_real_path, image_bin_path, reader, fw_node,
    img_node)``.  The caller owns ``disk_f`` and must keep it open as long as it
    uses ``reader`` (e.g. for video extraction or in-place patching), then close
    it.  ``read_progress`` (if given) is called ``(cur, total)`` while streaming
    image.bin."""
    reader, fw_node, img_node = _locate(disk_f, partitions)
    gr_path = os.path.join(work_dir, "game_real")
    img_path = os.path.join(work_dir, "image.bin")
    log("Extracting firmware (%.1f MB)..." % (fw_node["size"] / 1e6), "info")
    reader.extract_file(fw_node, gr_path)
    log("Extracting image.bin (%.0f MB)..." % (img_node["size"] / 1e6), "info")
    reader.extract_file(img_node, img_path, progress=read_progress)
    return gr_path, img_path, reader, fw_node, img_node


_ASSET_REF = re.compile(rb"\d+\.asset/\d+\.asset")
_IDENT = re.compile(rb"[A-Za-z][A-Za-z0-9_]{2,80}")
_RADIUM_SKIP = {"Video", "video", "in_game_videos"}


def _parse_radium(data):
    """Map ``asset_ref -> name`` from a ``scene.radium``: each LCD video asset is
    named by the scene-element identifier immediately preceding its
    ``N.asset/M.asset`` reference (verified contiguous on the TMNT card)."""
    import bisect
    names = [(m.start(), m.group().decode("latin1"))
             for m in _IDENT.finditer(data)]
    name_offs = [p for p, _ in names]
    out = {}
    for m in _ASSET_REF.finditer(data):
        ref = m.group().decode()
        if ref in out:
            continue
        j = bisect.bisect_left(name_offs, m.start()) - 1
        while j >= 0:
            nm = names[j][1]
            if nm not in _RADIUM_SKIP and ".asset" not in nm:
                out[ref] = nm
                break
            j -= 1
    return out


def _sanitize_title(name, maxlen=64):
    keep = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name).strip("_")
    return keep[:maxlen] or "video"


def extract_videos(reader, output_dir, log=None, progress=None, cancel=None):
    """Extract every directly-stored video (H.264 in an MP4/QuickTime ``ftyp``
    container) from the card's asset tree to ``output_dir/video/``.

    Spike 2 stores LCD videos verbatim as ``.asset`` files; this sniffs the
    ``ftyp`` magic so it catches them regardless of name/extension, and names
    each one from its scene's ``scene.radium`` (e.g. ``Cowabunga_Background``).
    A ``manifest.txt`` records each output name -> original card path."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    log("Scanning for video assets...", "info")
    vids = []
    radiums = {}   # hash-dir path -> scene.radium inode
    for path, ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            return 0
        if path.endswith("/scene.radium"):
            radiums[path[:-len("/scene.radium")]] = node
        elif node["size"] >= 0x1000:
            b = reader.peek(node, 12)
            if len(b) >= 12 and b[4:8] == b"ftyp":
                vids.append((path, node, b[8:12]))
    if not vids:
        log("No video assets found.", "info")
        return 0

    radium_cache = {}

    def _title_for(path):
        if "/scene.assets/" not in path:
            return None
        hashdir, ref = path.rsplit("/scene.assets/", 1)
        rn = radiums.get(hashdir)
        if rn is None:
            return None
        if hashdir not in radium_cache:
            try:
                radium_cache[hashdir] = (_parse_radium(reader.read_file_bytes(rn))
                                         if rn["size"] <= 0x2000000 else {})
            except Exception:
                radium_cache[hashdir] = {}
        return radium_cache[hashdir].get(ref)

    vid_dir = os.path.join(output_dir, "video")
    os.makedirs(vid_dir, exist_ok=True)
    log("Extracting %d video(s)..." % len(vids), "info")
    manifest = []
    used = {}
    named = 0
    for i, (path, node, brand) in enumerate(vids):
        if cancel():
            break
        if progress:
            progress(i, len(vids), "Extracting video %d/%d" % (i + 1, len(vids)))
        ext = ".mov" if brand == b"qt  " else ".mp4"
        title = _title_for(path)
        base = _sanitize_title(title) if title else ("video_%04d" % (i + 1))
        if title:
            named += 1
        k = used.get(base, 0)
        used[base] = k + 1
        fname = (base if k == 0 else "%s_%d" % (base, k + 1)) + ext
        reader.extract_file(node, os.path.join(vid_dir, fname))
        manifest.append("%s\t%s\t%d" % (fname, path, node["size"]))
    try:
        with open(os.path.join(vid_dir, "manifest.txt"), "w", encoding="utf-8") as f:
            f.write("# output\tcard path\tbytes\n" + "\n".join(manifest) + "\n")
    except Exception:
        pass
    log("Extracted %d video(s) to %s (%d named from scene data)."
        % (len(manifest), vid_dir, named), "success")
    return len(manifest)


_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga", ".webp")


def extract_images(reader, output_dir, log=None, progress=None, cancel=None):
    """Extract every loose image file from the card's asset tree to
    ``output_dir/images/``, preserving the card's directory structure (so names
    stay unique and grouped, e.g. ``images/<game>/assets/.../Login/Avatar.png``).

    Spike 2 stores LCD UI images as plain ``.png`` files on the ext4 filesystem
    (not packed inside ``.asset``), so they extract — and later patch back — like
    any loose file.  A ``manifest.txt`` records each output path -> original card
    path so Write can map an edited image back to its inode."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    log("Scanning for image assets...", "info")
    imgs = []
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            return 0
        if path.lower().endswith(_IMAGE_EXTS):
            imgs.append((path, node))
    if not imgs:
        log("No image assets found.", "info")
        return 0

    img_dir = os.path.join(output_dir, "images")
    os.makedirs(img_dir, exist_ok=True)
    log("Extracting %d image(s)..." % len(imgs), "info")
    manifest = []
    for i, (path, node) in enumerate(imgs):
        if cancel():
            break
        if progress:
            progress(i, len(imgs), "Extracting image %d/%d" % (i + 1, len(imgs)))
        rel = path.lstrip("/")                       # card path without leading /
        out_path = os.path.join(img_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        reader.extract_file(node, out_path)
        manifest.append("%s\t%s\t%d" % (rel, path, node["size"]))
    try:
        with open(os.path.join(img_dir, "manifest.txt"), "w",
                  encoding="utf-8") as f:
            f.write("# output\tcard path\tbytes\n" + "\n".join(manifest) + "\n")
    except Exception:
        pass
    log("Extracted %d image(s) to %s." % (len(manifest), img_dir), "success")
    return len(manifest)


# --------------------------------------------------------------------------
# Scene-texture extract: the BC3/DXT5 "DDS" glyph/sprite atlases packed as the
# non-ftyp scene.assets/<N>.asset files (their dims live in the scene.radium).
# --------------------------------------------------------------------------
_TEXTURE_MANIFEST = "manifest.txt"
_TEXTURE_DIR = ("images", "scene_textures")
_DXT5_FORMAT = 5            # the radium texture-descriptor format enum for BC3


def parse_texture_descriptor(radium, ref):
    """Read ``(width, height, format)`` for a ``<N>.asset`` scene texture from its
    inline descriptor in the co-located ``scene.radium``, or ``None``.

    Each texture reference is serialized as
    ``[handle u32 (top byte 0x80)][width u32][height u32][format u32]
    [next-handle u32][len u64][name ascii]`` — so the 16 bytes before the name's
    8-byte length prefix are ``width, height, format, handle``.  We key off the
    handle's ``0x80`` top byte (the same framing :mod:`.radium` uses for named
    handles) to avoid matching a stray ``N.asset`` substring."""
    key = struct.pack("<Q", len(ref)) + ref.encode("latin1")
    i = radium.find(key)
    while i >= 0:
        if i >= 16 and radium[i - 1] == 0x80:
            w, h, fmt = struct.unpack_from("<III", radium, i - 16)
            if 0 < w <= 8192 and 0 < h <= 8192:
                return w, h, fmt
        i = radium.find(key, i + 1)
    return None


def extract_scene_textures(reader, output_dir, log=None, progress=None,
                           cancel=None):
    """Decode every BC3/DXT5 scene texture to ``output_dir/images/scene_textures/``
    as RGBA PNG.

    These are the single (non-nested, non-``ftyp``) ``scene.assets/<N>.asset``
    files — raw BC3 block data whose width/height/format are read from the
    co-located ``scene.radium`` (:func:`parse_texture_descriptor`).  A
    ``manifest.txt`` records ``output -> card path, bytes, w, h, format`` so Write
    can re-encode an edited PNG back to the exact original slot."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    from . import dds as _dds
    try:
        from PIL import Image
    except Exception:
        log("Pillow not available; scene-texture extraction skipped.", "warning")
        return 0
    log("Scanning for scene textures...", "info")
    textures = []                  # (card_path, node, ref)
    radiums = {}                   # scene_dir -> scene.radium node
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            return 0
        if path.endswith("/scene.radium"):
            radiums[path[:-len("/scene.radium")]] = node
        elif "/scene.assets/" in path and path.endswith(".asset"):
            ref = path.rsplit("/scene.assets/", 1)[1]
            if "/" in ref or node["size"] < 16:
                continue           # nested N.asset/M.asset = video, not a texture
            b = reader.peek(node, 8)
            if len(b) >= 8 and b[4:8] == b"ftyp":
                continue
            textures.append((path, node, ref))
    if not textures:
        log("No scene textures found.", "info")
        return 0

    tex_dir = os.path.join(output_dir, *_TEXTURE_DIR)
    os.makedirs(tex_dir, exist_ok=True)
    radium_cache = {}

    def _descriptor(path, ref):
        scene_dir = path.rsplit("/scene.assets/", 1)[0]
        rn = radiums.get(scene_dir)
        if rn is None:
            return None
        if scene_dir not in radium_cache:
            try:
                radium_cache[scene_dir] = (reader.read_file_bytes(rn)
                                           if rn["size"] <= 0x4000000 else b"")
            except Exception:
                radium_cache[scene_dir] = b""
        return parse_texture_descriptor(radium_cache[scene_dir], ref)

    log("Extracting %d scene texture(s)..." % len(textures), "info")
    manifest = []
    used = {}
    n_ok = n_skip = 0
    for i, (path, node, ref) in enumerate(textures):
        if cancel():
            break
        if progress:
            progress(i, len(textures),
                     "Texture %d/%d" % (i + 1, len(textures)))
        desc = _descriptor(path, ref)
        if desc is None:
            n_skip += 1
            continue
        w, h, fmt = desc
        size = node["size"]
        # Only BC3/DXT5 (1 byte/pixel) is supported so far; the size guard also
        # rejects a descriptor that didn't really belong to this asset.
        if fmt != _DXT5_FORMAT or w * h != size:
            n_skip += 1
            continue
        try:
            rgba = _dds.decode_bc3(reader.read_file_bytes(node), w, h)
            im = Image.fromarray(rgba, "RGBA")
        except Exception as e:
            log("Texture %s: decode failed (%s); skipped." % (ref, e), "warning")
            n_skip += 1
            continue
        scene8 = path.rsplit("/scene.assets/", 1)[0].rsplit("/", 1)[1][:8]
        base = "%s_%s" % (scene8, os.path.splitext(ref)[0])
        k = used.get(base, 0)
        used[base] = k + 1
        name = base if k == 0 else "%s_%d" % (base, k + 1)
        out_rel = "scene_textures/%s.png" % name
        im.save(os.path.join(output_dir, "images", *out_rel.split("/")))
        manifest.append("%s\t%s\t%d\t%d\t%d\t%d"
                        % (out_rel, path, size, w, h, fmt))
        n_ok += 1
    try:
        with open(os.path.join(tex_dir, _TEXTURE_MANIFEST), "w",
                  encoding="utf-8") as f:
            f.write("# output\tcard path\tbytes\twidth\theight\tformat\n"
                    + "\n".join(manifest) + "\n")
    except Exception:
        pass
    log("Extracted %d scene texture(s) to %s (%d skipped)."
        % (n_ok, tex_dir, n_skip), "success")
    return n_ok


# --------------------------------------------------------------------------
# Radium-embedded images: the BC3/DXT5 "display-system" bitmaps stored INLINE
# in a scene.radium (the song-title text glyphs like "ROCK AND ROLL" PB shows
# under a scene) — not a scene.assets file.  Same codec, patched in place.
# --------------------------------------------------------------------------
_RADIUM_IMAGE_MANIFEST = "radium_images.txt"

# Scene-graph element-TYPE keywords — skipped when naming an image after its
# nearest scene element (we want the instance id like "Song_Progress", not the
# generic type tag that precedes it).
_RADIUM_ELEM_TYPES = {"Bitmap", "Sprite", "Animation", "Font", "Pattern",
                      "Group", "Node", "Scene", "Mask", "Particle", "Text",
                      "Video", "VideoSurface", "Material", "Shader"}
_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]+$")


def _padded4(x):
    return ((x + 3) // 4) * 4


def _nearest_element_name(data, before_off, window=512):
    """The nearest scene-element instance id (e.g. ``Song_Progress``,
    ``unnamed_instance_4``) appearing as a length-prefixed string just before
    *before_off*, skipping element-TYPE keywords.  ``""`` when none — used to
    give each radium image an organizing name rather than a bare hash."""
    lo = max(0, before_off - window)
    best = ""
    i = lo
    while i + 8 <= before_off:
        ln = struct.unpack_from("<Q", data, i)[0]
        if 1 <= ln <= 64 and i + 8 + ln <= before_off:
            body = data[i + 8:i + 8 + ln]
            if all(32 <= b < 127 for b in body):
                s = body.decode("latin1")
                if s not in _RADIUM_ELEM_TYPES and _IDENT_RE.match(s):
                    best = s            # keep the last (nearest) match
                i += 8 + ln
                continue
        i += 1
    return best


def parse_radium_images(data):
    """Find every inline BC3/DXT5 image in a ``scene.radium``.

    Each image is serialized as
    ``[dispW u32][dispH u32][handle u32][texW u32][texH u32][format u32=5]
    [0 u32][0 u32][length u32][BC3 data]`` where
    ``length == padded4(texW) * padded4(texH)`` (BC3 = 1 byte/pixel).  We anchor
    on the ``format=5, 0, 0`` triplet and validate that the length matches the
    block-padded dimensions and that the data fits — a signature specific enough
    to have no false positives.

    Returns ``[{data_off, length, tex_w, tex_h, pad_w, pad_h, disp_w, disp_h}]``
    where decoding uses ``pad_w x pad_h`` (the full BC3 grid)."""
    out = []
    n = len(data)
    sig = b"\x05\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"   # fmt=5, 0, 0
    i = data.find(sig)
    while i >= 0:
        m = i
        i = data.find(sig, i + 1)
        if m < 8 or m + 16 > n:
            continue
        tex_w = struct.unpack_from("<I", data, m - 8)[0]
        tex_h = struct.unpack_from("<I", data, m - 4)[0]
        if not (0 < tex_w <= 8192 and 0 < tex_h <= 8192):
            continue
        length = struct.unpack_from("<I", data, m + 12)[0]
        pad_w, pad_h = _padded4(tex_w), _padded4(tex_h)
        if length != pad_w * pad_h or m + 16 + length > n:
            continue
        disp_w = struct.unpack_from("<I", data, m - 20)[0] if m >= 20 else tex_w
        disp_h = struct.unpack_from("<I", data, m - 16)[0] if m >= 20 else tex_h
        if not (0 < disp_w <= pad_w):
            disp_w = tex_w
        if not (0 < disp_h <= pad_h):
            disp_h = tex_h
        out.append(dict(data_off=m + 16, length=length, tex_w=tex_w, tex_h=tex_h,
                        pad_w=pad_w, pad_h=pad_h, disp_w=disp_w, disp_h=disp_h))
    return out


def extract_radium_images(reader, output_dir, log=None, progress=None,
                          cancel=None):
    """Decode every inline DXT5 image from the card's ``scene.radium`` files to
    ``output_dir/images/scene_textures/`` as RGBA PNG (full padded grid, so a
    re-encode is byte-for-byte size-neutral).

    The SAME image is drawn from many scenes/keyframes, so images are
    **deduplicated by content** — one PNG per unique image — while the
    ``radium_images.txt`` manifest records **every** on-card occurrence (a row
    per ``radium card path + data offset``).  Editing one PNG therefore patches
    all of its occurrences at Write, so the change shows everywhere in-game (the
    same all-occurrences rule the display-text replace uses)."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    from . import dds as _dds
    from ...core.checksums import md5_file  # noqa: F401  (kept for parity)
    import hashlib
    try:
        from PIL import Image
    except Exception:
        log("Pillow not available; radium-image extraction skipped.", "warning")
        return 0
    log("Scanning radium scenes for embedded images...", "info")
    radiums = []
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            return 0
        if path.endswith(_RADIUM_EXT) and node["size"] >= 32:
            radiums.append((path, node))
    if not radiums:
        return 0

    tex_dir = os.path.join(output_dir, *_TEXTURE_DIR)
    os.makedirs(tex_dir, exist_ok=True)
    manifest = []                 # one row per occurrence
    by_hash = {}                  # content hash -> output rel path (PNG written once)
    n_unique = n_occ = 0
    for ri, (path, node) in enumerate(radiums):
        if cancel():
            break
        if progress:
            progress(ri, len(radiums),
                     "Radium %d/%d" % (ri + 1, len(radiums)))
        try:
            data = reader.read_file_bytes(node)
        except Exception:
            continue
        imgs = parse_radium_images(data)
        for im in imgs:
            raw = data[im["data_off"]:im["data_off"] + im["length"]]
            h = hashlib.md5(raw).hexdigest()
            out_rel = by_hash.get(h)
            if out_rel is None:
                try:
                    rgba = _dds.decode_bc3(raw, im["pad_w"], im["pad_h"])
                    pic = Image.fromarray(rgba, "RGBA")
                except Exception as e:
                    log("Radium image %s: decode failed (%s); skipped."
                        % (h[:8], e), "warning")
                    continue
                # Name by nearest scene-element id + dimensions + a short content
                # hash: the element id (e.g. "Song_Progress") organizes the slot
                # list, the dims separate text banners (462x66) from atlases
                # (512x512), and the hash dedupes identical glyphs.
                elem = _nearest_element_name(data, im["data_off"] - 36)
                bits = ["radimg"]
                if elem:
                    bits.append(_sanitize_title(elem, 40))
                bits.append("%dx%d" % (im["tex_w"], im["tex_h"]))
                bits.append(h[:8])
                out_rel = "scene_textures/%s.png" % "_".join(bits)
                pic.save(os.path.join(output_dir, "images", *out_rel.split("/")))
                by_hash[h] = out_rel
                n_unique += 1
            manifest.append("%s\t%s\t%d\t%d\t%d\t%d"
                            % (out_rel, path, im["data_off"], im["length"],
                               im["pad_w"], im["pad_h"]))
            n_occ += 1
    if not manifest:
        return 0
    try:
        with open(os.path.join(tex_dir, _RADIUM_IMAGE_MANIFEST), "w",
                  encoding="utf-8") as f:
            f.write("# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\n"
                    + "\n".join(manifest) + "\n")
    except Exception:
        pass
    log("Extracted %d unique embedded radium image(s) (%d on-card occurrence(s)) "
        "to %s." % (n_unique, n_occ, tex_dir), "success")
    return n_unique


# --------------------------------------------------------------------------
# display-text extract: editable LCD strings inside the .radium scene files
# --------------------------------------------------------------------------
_RADIUM_EXT = ".radium"
# The editable strings manifest format (text/strings.tsv) lives in the core
# text_manifest module so the Replace Text GUI tab and this engine -- which read
# and write the same file -- can't drift apart.


def extract_radium_text(reader, output_dir, log=None, progress=None, cancel=None):
    """Extract every editable LCD display-text string from the card's
    ``.radium`` scene files into an editable manifest under
    ``output_dir/text/``.

    Spike 2 stores on-screen UI text inside ``*.radium`` scene files on the
    ext4 data partition.  For each radium we enumerate its ``display-text``
    strings (see :mod:`.radium`), dedupe by value (the same string repeats many
    times -- once per keyframe of the parent ``Sprite`` timeline), and write a
    human-editable TSV ``text/strings.tsv`` with columns
    ``radium_card_path``, ``original``, ``replacement`` (replacement left blank;
    the user fills in only the strings to change).  Radiums with no display text are
    skipped.  Write later re-enumerates the unchanged on-card radium to find the
    authoritative offsets, so only the (path, original) key is load-bearing.

    Returns the number of unique (radium, string) rows written."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    from . import radium as _radium

    log("Scanning .radium scene files for display text...", "info")
    rads = []
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            return 0
        if path.lower().endswith(_RADIUM_EXT):
            rads.append((path, node))
    if not rads:
        log("No .radium scene files found.", "info")
        return 0

    rows = []                    # (card_path, original)
    manifest = []                # (card_path, n_unique, n_occurrences)
    for i, (path, node) in enumerate(rads):
        if cancel():
            break
        if progress:
            progress(i, len(rads), "Scanning radium %d/%d" % (i + 1, len(rads)))
        try:
            data = reader.read_file_bytes(node)
        except Exception as e:
            log("Couldn't read %s (%s); skipped." % (path, e), "warning")
            continue
        dts = _radium.display_texts(data)
        if not dts:
            continue
        seen = set()
        n_occ = 0
        for e in dts:
            n_occ += 1
            text = e["text"]
            if text in seen:
                continue
            seen.add(text)
            rows.append((path, text))
        manifest.append((path, len(seen), n_occ))

    if not rows:
        log("No editable display text found in %d .radium file(s)."
            % len(rads), "info")
        return 0

    from ...core import text_manifest
    text_dir = os.path.join(output_dir, text_manifest.RELDIR)
    try:
        # replacement column left BLANK -- the user fills in only the strings
        # they want to change (blank = leave unchanged), so the manifest never
        # looks like every row is already duplicated.
        text_manifest.save(output_dir, [
            {"path": card_path, "original": original, "replacement": ""}
            for card_path, original in rows])
    except Exception as e:
        log("Couldn't write display-text manifest (%s)." % e, "warning")
        return 0
    try:
        with open(os.path.join(text_dir, "manifest.txt"), "w",
                  encoding="utf-8") as f:
            f.write("# radium card path\tunique strings\toccurrences\n")
            for card_path, nuniq, nocc in manifest:
                f.write("%s\t%d\t%d\n" % (card_path, nuniq, nocc))
    except Exception:
        pass
    log("Extracted %d editable display-text string(s) from %d radium scene(s) "
        "to %s." % (len(rows), len(manifest), text_dir), "success")
    return len(rows)


def _write_wav(path, L, R, stereo):
    import numpy as np
    chans = [L, R] if stereo else [L]
    n = len(chans[0])
    inter = np.empty(n * len(chans), np.int16)
    for i, c in enumerate(chans):
        inter[i::len(chans)] = np.clip(c, -32768, 32767).astype(np.int16)
    w = wave.open(path, "wb")
    w.setnchannels(len(chans)); w.setsampwidth(2); w.setframerate(44100)
    w.writeframes(inter.tobytes()); w.close()


# --------------------------------------------------------------------------
# public API (called by the pipelines)
# --------------------------------------------------------------------------
def extract_all(image_path, partitions, output_dir, log=None, progress=None,
                cancel=None, phase=None, open_disk=None, log_line=None,
                music_banks=True, do_audio=True, do_video=True,
                do_images=True, do_text=True):
    """Decode every cat-0 sound in the card image to ``output_dir`` as WAV
    (under ``audio/``) and extract videos (under ``video/``).

    ``music_banks`` ALSO decodes the per-category ``image-scNN.bin`` banks — the
    licensed songs / extra sound sets the six multi-category titles (Metallica,
    D&D, Rush, Deadpool, Foo Fighters, John Wick) keep outside cat-0.  Each bank
    is derived + decoded on its own fresh emulator across a process pool (one
    task per bank — see :func:`spike2.category.extract_category_audio_parallel`),
    so Metallica's 24 songs finish in ~2 min and titles without banks are a fast
    no-op.  On by default; the few multi-cat builds the loader can't drive skip
    their banks gracefully (cat-0 audio is unaffected).

    ``open_disk`` (a zero-arg callable returning a fresh seekable byte stream)
    overrides how the disk is opened — Direct-SD passes one that returns a
    :class:`.rawdevice.RawDeviceFile` over the physical card; the default opens
    the image file at ``image_path``.  Everything downstream (game_real +
    image.bin are streamed to a temp dir, then decoded) is identical either way.

    ``log_line`` (``cb(key, text, level)``) drives the live per-sound decode
    progress — one in-place-updated line per sound; omitted → no live lines.
    """
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    phase = phase or (lambda i: None)
    from .spike2.emulator import Spike2Emu, audio_decode_supported

    def _read_prog(c, t):
        if progress:
            progress(int(c * 5 / max(t, 1)), 100, "Reading image.bin")

    work = tempfile.mkdtemp(prefix="spike2_")
    emu = None
    disk_f = open_disk() if open_disk is not None else open(image_path, "rb")
    try:
        os.makedirs(output_dir, exist_ok=True)
        gr_path, img_path, reader, _fw, _img = _extract_inputs(
            disk_f, partitions, work, log, _read_prog)
        if cancel():
            return 0

        # videos + images first (quick file copies) so they appear before the
        # long audio decode
        phase(2)  # Extract video
        if do_video:
            try:
                extract_videos(reader, output_dir, log=log,
                               progress=(lambda c, t, d="": progress(
                                   5 + int(c * 8 / max(t, 1)), 100, d)) if progress else None,
                               cancel=cancel)
            except Exception as e:
                log("Video extraction failed (%s); continuing." % e, "warning")
        if cancel():
            return 0

        phase(3)  # Extract images
        if do_images:
            try:
                extract_images(reader, output_dir, log=log,
                               progress=(lambda c, t, d="": progress(
                                   13 + int(c * 2 / max(t, 1)), 100, d)) if progress else None,
                               cancel=cancel)
            except Exception as e:
                log("Image extraction failed (%s); continuing." % e, "warning")
            if cancel():
                return 0
            # Scene textures (BC3/DXT5 glyph/sprite atlases inside scene.assets)
            # — decoded to editable PNGs; an own try/except so a texture hiccup
            # never blocks the loose-PNG or audio extraction.
            try:
                extract_scene_textures(reader, output_dir, log=log,
                                       progress=(lambda c, t, d="": progress(
                                           15, 100, d)) if progress else None,
                                       cancel=cancel)
            except Exception as e:
                log("Scene-texture extraction failed (%s); continuing." % e,
                    "warning")
            if cancel():
                return 0
            # DXT5 images embedded inline in the radium scenes (the song-title
            # text glyphs like "ROCK AND ROLL") — same codec, patched in place.
            try:
                extract_radium_images(reader, output_dir, log=log,
                                      progress=(lambda c, t, d="": progress(
                                          15, 100, d)) if progress else None,
                                      cancel=cancel)
            except Exception as e:
                log("Radium-image extraction failed (%s); continuing." % e,
                    "warning")
        if cancel():
            return 0

        # editable LCD display text (.radium scenes) -> text/strings.tsv
        if do_text:
            try:
                extract_radium_text(reader, output_dir, log=log, cancel=cancel)
            except Exception as e:
                log("Display-text extraction failed (%s); continuing." % e,
                    "warning")
            if cancel():
                return 0

        phase(4)  # Decode audio
        if not do_audio:
            log("Audio extraction skipped (unchecked).", "info")
            phase(5)  # Checksums
            return 0
        if not audio_decode_supported(gr_path):
            log("Audio decode isn't supported for this title yet: its game "
                "firmware uses a Spike 2 codec the engine can't locate a "
                "single decode path for (e.g. a dual-path codec), so the "
                "per-sound keystream can't be derived. Video + image "
                "extraction completed normally.", "warning")
            phase(5)  # Checksums
            return 0
        log("Booting firmware codec engine...", "info")
        emu = Spike2Emu(gr_path, img_path)
        emu.boot()
        params = _load_or_derive_params(emu, gr_path, img_path, log, progress)
        emu.close()
        emu = None   # decode runs in worker processes (or a fresh emu on fallback)

        audio_dir = os.path.join(output_dir, "audio")
        os.makedirs(audio_dir, exist_ok=True)
        total = len(params)
        ok = None
        nworkers = max(1, min((os.cpu_count() or 2) - 2, 8))
        if nworkers > 1 and not cancel():
            try:
                log("Decoding %d sounds across %d processes..." % (total, nworkers), "info")
                ok = _parallel_decode(gr_path, img_path, params, audio_dir,
                                      log, progress, cancel, nworkers,
                                      log_line=log_line)
            except Exception as e:
                log("Parallel decode unavailable (%s); using a single process."
                    % e, "warning")
                ok = None
        if ok is None:
            emu = Spike2Emu(gr_path, img_path)
            emu.boot()
            ok = _serial_decode(emu, params, audio_dir, log, progress, cancel,
                                log_line=log_line)
        log("Decoded %d/%d sounds to %s" % (ok, total, audio_dir), "success")
        if music_banks and not cancel():
            if emu is not None:
                emu.close(); emu = None    # free the cat-0 emu before booting CatEmu
            ok += _extract_category_banks(reader, gr_path, img_path, work,
                                          audio_dir, log, progress, cancel)
        return ok
    finally:
        if emu is not None:
            emu.close()
        disk_f.close()
        _rmtree(work)


def _extract_category_banks(reader, gr_path, img_path, work, audio_dir, log,
                            progress, cancel):
    """Extract the card's ``image-scNN.bin`` banks to ``work`` and decode each to
    WAV under ``audio/`` (named ``music_catNN_idx.wav`` so the existing
    AcoustID auto-naming can title the songs).  Returns the count decoded; 0 (and
    a clean skip) when there are no banks or the build can't be driven."""
    from .spike2.category import extract_category_audio_parallel
    sc_paths = []
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            break
        base = path.rsplit("/", 1)[-1]
        if base.startswith("image-sc") and base.endswith(".bin"):
            op = os.path.join(work, base)
            reader.extract_file(node, op)
            sc_paths.append(op)
    if not sc_paths:
        return 0
    log("Extracting %d per-category music bank(s) — the licensed songs / extra "
        "sounds outside image.bin." % len(sc_paths), "info")

    def _prog(c, t):
        if progress:
            progress(min(100, int(c * 100 / max(t, 1))), 100,
                     "Decoding music bank %d/%d" % (c, t))
    n = extract_category_audio_parallel(gr_path, img_path, sc_paths, audio_dir,
                                        log=log, progress=_prog, cancel=cancel)
    log("Decoded %d per-category music sound(s)." % n, "success")
    return n


def _serial_progress_cb(p, emit):
    """Throttled per-block callback that emits a ``prog`` event for a long sound
    in the single-process path (mirrors the parallel workers, minus the queue).
    Short sounds never tick (they finish before the threshold)."""
    import time
    t0 = time.monotonic()
    st = {"last": 0.0}
    length = p.get("length", 0); chan = p.get("chan", 1)

    def cb(cur, nmax):
        now = time.monotonic()
        if now - t0 < 2.5 or now - st["last"] < 3.0:
            return
        st["last"] = now
        emit(("prog", p["idx"], cur / max(nmax, 1), length, chan))
    return cb


def _serial_decode(emu, params, audio_dir, log, progress, cancel, log_line=None):
    total = len(params)
    ok = 0

    def emit(msg):
        _emit_decode(msg, log, log_line)

    for i, p in enumerate(params):
        if cancel():
            log("Cancelled after %d sounds." % ok, "info")
            break
        if progress:
            progress(15 + int(i * 85 / max(total, 1)), 100,
                     "Decoding sound %d/%d" % (i + 1, total))
        length = p.get("length", 0); chan = p.get("chan", 1)
        emit(("start", p["idx"], length, chan))
        try:
            r = emu.decode(p, cancel=cancel,
                           progress=_serial_progress_cb(p, emit))
        except Exception as e:
            log("idx %d: decode failed (%s)" % (p["idx"], e), "warning")
            continue
        if r is None:
            continue
        L, R, stereo = r
        _write_wav(os.path.join(audio_dir, "idx%04d.wav" % p["idx"]), L, R, stereo)
        emit(("done", p["idx"], length, chan))
        ok += 1
    return ok


def _dur_str(length, chan):
    """``(stereo 4:31)`` from a per-channel sample count + channel count."""
    secs = int(length / 44100.0)
    return "(%s %d:%02d)" % ("stereo" if chan == 2 else "mono",
                             secs // 60, secs % 60)


def _bar(frac, width=12):
    n = max(0, min(width, int(round(frac * width))))
    return "[" + "#" * n + "." * (width - n) + "]"


def _decode_line(msg):
    """``(key, text, level)`` for a worker decode event (start/prog/done).

    The key is per-sound (``dec<idx>``) so the GUI rewrites ONE line per sound
    in place — the bar animates from start → done instead of spamming a line per
    tick."""
    kind = msg[0]
    if kind == "start":
        _, idx, length, chan = msg
        return ("dec%d" % idx,
                "    idx%04d %s %s   0%%" % (idx, _dur_str(length, chan), _bar(0)),
                "info")
    if kind == "prog":
        _, idx, frac, length, chan = msg
        return ("dec%d" % idx,
                "    idx%04d %s %s %3d%%"
                % (idx, _dur_str(length, chan), _bar(frac), int(frac * 100)),
                "info")
    # done
    _, idx, length, chan = msg
    return ("dec%d" % idx,
            "    idx%04d %s decoded" % (idx, _dur_str(length, chan)), "success")


def _emit_decode(msg, log, log_line):
    """Forward a decode event: an in-place keyed line when ``log_line`` is wired
    (the GUI), else a plain appended line for the ``done`` events only (so a
    non-GUI caller's log gets one concise line per finished sound, not a tick
    flood)."""
    if log_line is not None:
        key, text, level = _decode_line(msg)
        log_line(key, text, level)
    elif msg[0] == "done":
        _, text, level = _decode_line(msg)
        log(text, level)


def _parallel_decode(gr_path, img_path, params, audio_dir, log, progress, cancel,
                     nworkers, log_line=None):
    """Decode across ``nworkers`` spawned emulator processes (each boots once,
    decodes its share, writes WAVs directly).  Raises on any pool failure so the
    caller can fall back to a single process.

    A shared queue carries per-sound start/progress/done events from the
    workers; a daemon thread drains it and forwards each to ``_emit_decode`` so
    the GUI shows one in-place, animating line per sound (the long music tracks
    no longer look stalled)."""
    import multiprocessing as mp
    import threading

    from .spike2.parallel import decode_to_wav, init_worker, probe

    # Decode in natural (master-directory) order so the short sounds finish
    # first and WAVs stream into the output folder right away — the live
    # per-sound progress below surfaces the long music tracks (which would
    # otherwise look stalled) without reordering the queue, so we don't trade
    # away that "files appear as it goes" feedback.
    tasks = [(p, os.path.join(audio_dir, "idx%04d.wav" % p["idx"])) for p in params]
    total = len(tasks)
    ctx = mp.get_context("spawn")
    # Manager queue: picklable across spawn (a plain mp.Queue isn't), so it can
    # ride in the pool initargs to every worker.
    mgr = ctx.Manager()
    prog_q = mgr.Queue()
    pool = ctx.Pool(nworkers, initializer=init_worker,
                    initargs=(gr_path, img_path, prog_q))
    stop_forward = threading.Event()

    def _forward():
        while not stop_forward.is_set():
            try:
                msg = prog_q.get(timeout=0.3)
            except Exception:
                continue
            if msg is None:
                break
            try:
                _emit_decode(msg, log, log_line)
            except Exception:
                pass
    fwd = threading.Thread(target=_forward, daemon=True)
    fwd.start()

    ok = 0
    try:
        # Confirm a worker actually booted within a generous window; a stalled
        # pool (e.g. an unguarded entry re-running the GUI) raises here and the
        # caller falls back to a single process.
        pool.apply_async(probe).get(timeout=180)
        i = 0
        for idx, good in pool.imap_unordered(decode_to_wav, tasks, chunksize=4):
            ok += good
            i += 1
            if progress and (i % 4 == 0 or i == total):
                progress(15 + int(i * 85 / max(total, 1)), 100,
                         "Decoding sound %d/%d" % (i, total))
            if cancel():
                log("Cancelled after %d sounds." % ok, "info")
                break
        pool.close()
    finally:
        stop_forward.set()
        try:
            prog_q.put(None)
        except Exception:
            pass
        fwd.join(timeout=1.0)
        pool.terminate()
        pool.join()
        try:
            mgr.shutdown()
        except Exception:
            pass
    return ok


# --------------------------------------------------------------------------
# Replace-Video: size-neutral in-place patch of the loose .asset clips
# --------------------------------------------------------------------------
_VIDEO_MANIFEST = "manifest.txt"


def _pad_isobmff(data, target):
    """Pad an MP4/MOV (ISO-BMFF / QuickTime) byte string up to exactly *target*
    bytes by appending a trailing ``free`` box, which compliant demuxers skip —
    the original ``moov``/``mdat`` are left untouched.  ``len(data)`` must be
    ``<= target``."""
    pad = target - len(data)
    if pad <= 0:
        return data[:target]
    if pad < 8:
        # Too small for a box header; a few trailing bytes after a complete
        # file are ignored by MP4/MOV demuxers.
        return data + b"\x00" * pad
    if pad < 0x1_0000_0000:
        return data + pad.to_bytes(4, "big") + b"free" + b"\x00" * (pad - 8)
    # 64-bit box: size word = 1, then the real size as an 8-byte largesize.
    return (data + (1).to_bytes(4, "big") + b"free"
            + pad.to_bytes(8, "big") + b"\x00" * (pad - 16))


def _changed_videos(assets_dir, baseline):
    """Return ``[(fname, card_path, staged_path), ...]`` for the videos under
    ``assets_dir/video`` whose current bytes differ from the Extract baseline
    (``.checksums.md5``).  Empty when there's no ``video/manifest.txt`` (an
    audio-only extract, or Write pointed at a subfolder)."""
    from ...core.checksums import md5_file
    vid_dir = os.path.join(assets_dir, "video")
    manifest = os.path.join(vid_dir, _VIDEO_MANIFEST)
    if not os.path.isfile(manifest):
        return []
    out = []
    with open(manifest, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 2:
                continue
            fname, card_path = cols[0], cols[1]
            staged = os.path.join(vid_dir, fname)
            if not os.path.isfile(staged):
                continue
            base = baseline.get("video/" + fname)
            try:
                if base is not None and md5_file(staged) == base:
                    continue           # untouched since extract
            except OSError:
                pass
            out.append((fname, card_path, staged))
    return out


def _resolve_card_nodes(reader, card_paths, cancel):
    """One filesystem pass: ``{card_path: inode}`` for the wanted card paths.
    Shared by the video + image in-place patch paths."""
    want = set(card_paths)
    found = {}
    if not want:
        return found
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            break
        if path in want:
            found[path] = node
            if len(found) == len(want):
                break
    return found


def _fit_video_payload(staged_path, target, work_dir, log):
    """Return exactly *target* bytes to overwrite the original ``.asset``, or
    ``None`` if the replacement can't be made to fit.  A clip ``<= target``
    pads up with a trailing free box; a larger clip is re-encoded down to the
    byte budget first (and skipped if even that overshoots)."""
    with open(staged_path, "rb") as f:
        data = f.read()
    name = os.path.basename(staged_path)
    if len(data) <= target:
        return _pad_isobmff(data, target)

    from ...core.video import detect_video_info, shrink_video_to_size
    tmp = os.path.join(work_dir, "fit_" + name)
    info = detect_video_info(staged_path)
    ok, detail = shrink_video_to_size(staged_path, tmp, target,
                                      original_info=info)
    if not ok:
        log("Video %s is %d bytes but the original slot is only %d and it "
            "couldn't be shrunk to fit (%s); skipped (left unchanged). Use a "
            "shorter / lower-resolution clip."
            % (name, len(data), target, detail), "warning")
        return None
    try:
        with open(tmp, "rb") as f:
            shrunk = f.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if len(shrunk) > target:
        log("Video %s still too large after re-encode; skipped." % name,
            "warning")
        return None
    log("Video %s re-encoded to fit (%d -> %d bytes of %d)."
        % (name, len(data), len(shrunk), target), "info")
    return _pad_isobmff(shrunk, target)


def _prepare_video_patches(reader, video_edits, work_dir, log, cancel):
    """Resolve each changed video to its card inode and size-fit its bytes.
    Returns ``([(node, payload), ...], n_skipped)`` where every payload is
    exactly the inode's size, ready for an in-place ``disk_ranges`` write."""
    nodes = _resolve_card_nodes(reader, [cp for (_f, cp, _s) in video_edits],
                                cancel)
    patches = []
    skipped = 0
    for fname, card_path, staged in video_edits:
        if cancel():
            break
        node = nodes.get(card_path)
        if node is None:
            log("Video %s: its original (%s) wasn't found on the card; "
                "skipped." % (fname, card_path), "warning")
            skipped += 1
            continue
        payload = _fit_video_payload(staged, node["size"], work_dir, log)
        if payload is None:
            skipped += 1
            continue
        patches.append((node, payload))
        log("Video %s: ready to patch (%d bytes)." % (fname, node["size"]),
            "info")
    return patches, skipped


# --------------------------------------------------------------------------
# Replace-Image: size-neutral in-place patch of the loose .png files
# --------------------------------------------------------------------------
_IMAGE_MANIFEST = "manifest.txt"


def _pad_image(data, target):
    """Pad image bytes up to exactly *target* by appending trailing zero bytes,
    which image decoders ignore after the data's end marker (PNG ``IEND`` /
    JPEG ``EOI`` / GIF trailer).  ``len(data)`` must be ``<= target``."""
    pad = target - len(data)
    if pad <= 0:
        return data[:target]
    return data + b"\x00" * pad


def _changed_images(assets_dir, baseline):
    """Return ``[(output, card_path, staged_path), ...]`` for the images under
    ``assets_dir/images`` whose current bytes differ from the Extract baseline
    (``.checksums.md5``).  Empty when there's no ``images/manifest.txt``.
    *output* is the forward-slash path under ``images/`` (mirrors the card)."""
    from ...core.checksums import md5_file
    img_dir = os.path.join(assets_dir, "images")
    manifest = os.path.join(img_dir, _IMAGE_MANIFEST)
    if not os.path.isfile(manifest):
        return []
    out = []
    with open(manifest, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 2:
                continue
            output, card_path = cols[0], cols[1]
            staged = os.path.join(img_dir, *output.split("/"))
            if not os.path.isfile(staged):
                continue
            base = baseline.get("images/" + output)
            try:
                if base is not None and md5_file(staged) == base:
                    continue           # untouched since extract
            except OSError:
                pass
            out.append((output, card_path, staged))
    return out


def _changed_music_banks(assets_dir, baseline):
    """Per-song music-bank WAVs (``music_catNN_*.wav``) whose bytes differ from
    the Extract baseline — i.e. the user edited/replaced a song.  These live in
    the ``image-scNN.bin`` banks that Write can't re-encode yet, so the caller
    surfaces a clear "skipped" warning instead of silently dropping the edit.
    The ``music_catNN_MMMM`` prefix survives an Auto-transcribe / Music-ID
    rename, so it's the stable per-song key.  Empty when there's no baseline."""
    from ...core.checksums import md5_file
    base = {}
    for rel in baseline:
        mm = _MUSIC_WAV_RE.match(os.path.splitext(os.path.basename(rel))[0])
        if mm:
            base[mm.group(1).lower()] = baseline[rel]
    if not base:
        return []
    changed = []
    for root, _dirs, files in os.walk(assets_dir):
        for fn in files:
            if not fn.lower().endswith(".wav"):
                continue
            mm = _MUSIC_WAV_RE.match(os.path.splitext(fn)[0])
            if not mm:
                continue
            path = os.path.join(root, fn)
            try:
                if md5_file(path) != base.get(mm.group(1).lower()):
                    changed.append(path)
            except OSError:
                changed.append(path)
    return changed


# --------------------------------------------------------------------------
# Replace display text: size-neutral in-place patch of the .radium strings
# --------------------------------------------------------------------------
def _changed_radium_text(assets_dir):
    """Parse ``text/strings.tsv`` and return the user's edits grouped by radium:
    ``{radium_card_path: [(original, replacement), ...]}`` for every row whose
    ``replacement`` differs from ``original``.

    The first two columns (card path, original) are the stable key (the on-card
    radium is unchanged, so its offsets are re-derived at Write time); only rows
    that were actually edited are returned.  Empty when there's no manifest."""
    from ...core import text_manifest
    return text_manifest.changed(assets_dir)


def _radium_text_writes(reader, assets_dir, log, cancel):
    """Resolve the user's display-text edits to a flat list of in-place writes
    ``[(disk_offset, bytes), ...]`` (same form ``_compute_patches`` collects).

    For each changed radium: resolve its inode, read it back, **re-enumerate**
    the unchanged on-card bytes for the authoritative offsets, and for every
    edit ``(original -> replacement)`` patch **all** display-text occurrences
    whose value equals ``original``.  A replacement is rejected (skipped with a
    warning, the radium left unchanged) unless it fits the original's byte
    budget; it is space-padded to the exact original length so the file size and
    every other offset stay byte-identical.

    Returns ``(writes, n_strings)`` where ``n_strings`` is the number of unique
    (radium, original) strings actually patched."""
    from . import radium as _radium

    edits = _changed_radium_text(assets_dir)
    if not edits:
        return [], 0
    nodes = _resolve_card_nodes(reader, list(edits.keys()), cancel)

    writes = []
    n_strings = 0
    for card_path, pairs in edits.items():
        if cancel():
            break
        node = nodes.get(card_path)
        if node is None:
            log("Display text: radium %s wasn't found on the card; %d edit(s) "
                "skipped." % (card_path, len(pairs)), "warning")
            continue
        data = reader.read_file_bytes(node)
        occ_by_text = {}
        for e in _radium.enumerate_strings(data):
            if e["kind"] == "display-text":
                occ_by_text.setdefault(e["text"], []).append(e)
        for original, replacement in pairs:
            orig_bytes = original.encode("latin1", "replace")
            new_bytes = replacement.encode("latin1", "replace")
            orig_len = len(orig_bytes)
            if len(new_bytes) > orig_len:
                log("Display text in %s: \"%s\" -> \"%s\" is %d bytes but the "
                    "original is only %d; skipped (left unchanged). Use a "
                    "shorter replacement." % (card_path, original, replacement,
                                              len(new_bytes), orig_len),
                    "warning")
                continue
            occs = occ_by_text.get(original)
            if not occs:
                log("Display text in %s: \"%s\" wasn't found in the current "
                    "radium; skipped." % (card_path, original), "warning")
                continue
            payload = new_bytes.ljust(orig_len, b" ")
            for e in occs:
                if e["length"] != orig_len:
                    continue                       # paranoia: length must match
                for disk, n in reader.disk_ranges(node, e["offset"], orig_len):
                    writes.append((disk, payload[:n]))
                    payload = payload[n:]
                payload = new_bytes.ljust(orig_len, b" ")   # reset for next occ
            n_strings += 1
            log("Display text in %s: \"%s\" -> \"%s\" (%d occurrence(s))."
                % (card_path, original, replacement, len(occs)), "info")
    return writes, n_strings


def _fit_image_payload(staged_path, target, work_dir, log):
    """Return exactly *target* bytes to overwrite the original ``.png``, or
    ``None`` if the replacement can't be made to fit.  An image ``<= target``
    pads up with trailing bytes; a larger one is re-compressed (max deflate,
    then fewer colours) down to the byte budget first."""
    with open(staged_path, "rb") as f:
        data = f.read()
    name = os.path.basename(staged_path)
    if len(data) <= target:
        return _pad_image(data, target)

    from ...core.image import detect_image_info, recompress_image_to_size
    tmp = os.path.join(work_dir, "fitimg_" + name)
    info = detect_image_info(staged_path)
    ok, detail = recompress_image_to_size(staged_path, tmp, target,
                                          original_info=info)
    if not ok:
        log("Image %s is %d bytes but the original slot is only %d and it "
            "couldn't be shrunk to fit (%s); skipped (left unchanged). Use a "
            "simpler image." % (name, len(data), target, detail), "warning")
        return None
    try:
        with open(tmp, "rb") as f:
            shrunk = f.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if len(shrunk) > target:
        log("Image %s still too large after re-encode; skipped." % name,
            "warning")
        return None
    log("Image %s re-compressed to fit (%d -> %d bytes of %d)."
        % (name, len(data), len(shrunk), target), "info")
    return _pad_image(shrunk, target)


def _prepare_image_patches(reader, image_edits, work_dir, log, cancel):
    """Resolve each changed image to its card inode and size-fit its bytes.
    Returns ``([(node, payload), ...], n_skipped)`` — each payload is exactly
    the inode's size, ready for an in-place ``disk_ranges`` write."""
    nodes = _resolve_card_nodes(reader, [cp for (_o, cp, _s) in image_edits],
                                cancel)
    patches = []
    skipped = 0
    for output, card_path, staged in image_edits:
        if cancel():
            break
        node = nodes.get(card_path)
        if node is None:
            log("Image %s: its original (%s) wasn't found on the card; "
                "skipped." % (output, card_path), "warning")
            skipped += 1
            continue
        payload = _fit_image_payload(staged, node["size"], work_dir, log)
        if payload is None:
            skipped += 1
            continue
        patches.append((node, payload))
        log("Image %s: ready to patch (%d bytes)." % (output, node["size"]),
            "info")
    return patches, skipped


# --------------------------------------------------------------------------
# Replace scene textures: re-encode an edited PNG back to BC3 and patch the
# original scene.assets/<N>.asset in place (size-neutral by construction).
# --------------------------------------------------------------------------
def _changed_scene_textures(assets_dir, baseline):
    """Return ``[(output, card_path, staged_png, w, h, fmt), ...]`` for the scene
    textures under ``images/scene_textures`` whose PNG bytes differ from the
    Extract baseline.  Empty when there's no texture manifest."""
    from ...core.checksums import md5_file
    tex_dir = os.path.join(assets_dir, *_TEXTURE_DIR)
    manifest = os.path.join(tex_dir, _TEXTURE_MANIFEST)
    if not os.path.isfile(manifest):
        return []
    out = []
    with open(manifest, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 6:
                continue
            output, card_path = cols[0], cols[1]
            try:
                w, h, fmt = int(cols[3]), int(cols[4]), int(cols[5])
            except ValueError:
                continue
            staged = os.path.join(assets_dir, "images", *output.split("/"))
            if not os.path.isfile(staged):
                continue
            base = baseline.get("images/" + output)
            try:
                if base is not None and md5_file(staged) == base:
                    continue                   # untouched since extract
            except OSError:
                pass
            out.append((output, card_path, staged, w, h, fmt))
    return out


def _prepare_texture_patches(reader, texture_edits, log, cancel):
    """Re-encode each edited PNG to BC3 at its original dimensions and resolve it
    to its card inode.  Returns ``([(node, payload), ...], n_skipped)`` — each
    payload is exactly the inode's size (same W×H + DXT5 ⇒ identical byte
    length), ready for an in-place ``disk_ranges`` write."""
    from . import dds as _dds
    try:
        from PIL import Image
        import numpy as np
    except Exception as e:
        if texture_edits:
            log("Pillow/numpy unavailable (%s); scene-texture edits skipped." % e,
                "warning")
        return [], len(texture_edits)
    nodes = _resolve_card_nodes(
        reader, [cp for (_o, cp, _s, _w, _h, _f) in texture_edits], cancel)
    patches = []
    skipped = 0
    for output, card_path, staged, w, h, fmt in texture_edits:
        if cancel():
            break
        node = nodes.get(card_path)
        if node is None:
            log("Texture %s: its original (%s) wasn't found on the card; "
                "skipped." % (output, card_path), "warning")
            skipped += 1
            continue
        try:
            im = Image.open(staged).convert("RGBA")
        except Exception as e:
            log("Texture %s: can't read PNG (%s); skipped." % (output, e),
                "warning")
            skipped += 1
            continue
        if im.size != (w, h):
            log("Texture %s is %dx%d but the original is %dx%d; skipped "
                "(scene textures must keep their exact dimensions). Resize your "
                "image to %dx%d." % (output, im.size[0], im.size[1], w, h, w, h),
                "warning")
            skipped += 1
            continue
        payload = _dds.encode_bc3(np.asarray(im, dtype=np.uint8))
        if len(payload) != node["size"]:
            log("Texture %s: re-encoded to %d bytes but the slot is %d; skipped."
                % (output, len(payload), node["size"]), "warning")
            skipped += 1
            continue
        patches.append((node, payload))
        log("Texture %s: ready to patch (%dx%d, %d bytes)."
            % (output, w, h, node["size"]), "info")
    return patches, skipped


def _changed_radium_images(assets_dir, baseline):
    """Return ``[(output, radium_card_path, staged, data_off, length, pad_w,
    pad_h), ...]`` for the radium-embedded images whose PNG differs from the
    Extract baseline.  Empty when there's no ``radium_images.txt`` manifest."""
    from ...core.checksums import md5_file
    tex_dir = os.path.join(assets_dir, *_TEXTURE_DIR)
    manifest = os.path.join(tex_dir, _RADIUM_IMAGE_MANIFEST)
    if not os.path.isfile(manifest):
        return []
    out = []
    with open(manifest, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 6:
                continue
            output, radium_path = cols[0], cols[1]
            try:
                data_off, length = int(cols[2]), int(cols[3])
                pad_w, pad_h = int(cols[4]), int(cols[5])
            except ValueError:
                continue
            staged = os.path.join(assets_dir, "images", *output.split("/"))
            if not os.path.isfile(staged):
                continue
            base = baseline.get("images/" + output)
            try:
                if base is not None and md5_file(staged) == base:
                    continue                   # untouched since extract
            except OSError:
                pass
            out.append((output, radium_path, staged, data_off, length,
                        pad_w, pad_h))
    return out


def _radium_image_writes(reader, assets_dir, baseline, log, cancel):
    """Re-encode each edited radium-embedded image to BC3 and resolve it to a
    flat ``[(disk_offset, bytes), ...]`` list patching the bytes in place inside
    the ``scene.radium`` inode (same form ``_compute_patches`` collects, like the
    display-text writes).  Returns ``(writes, n_images)``.

    Size-neutral by construction: the PNG is the full padded BC3 grid, so
    re-encoding yields exactly ``length`` bytes at ``data_offset``."""
    edits = _changed_radium_images(assets_dir, baseline)
    if not edits:
        return [], 0
    from . import dds as _dds
    try:
        from PIL import Image
        import numpy as np
    except Exception as e:
        log("Pillow/numpy unavailable (%s); radium-image edits skipped." % e,
            "warning")
        return [], 0
    nodes = _resolve_card_nodes(
        reader, list({rp for (_o, rp, *_r) in edits}), cancel)
    writes = []
    encoded = {}                   # staged PNG path -> BC3 bytes (one PNG, many occurrences)
    patched_outputs = set()
    for output, radium_path, staged, data_off, length, pad_w, pad_h in edits:
        if cancel():
            break
        node = nodes.get(radium_path)
        if node is None:
            log("Radium image %s: its scene (%s) wasn't found on the card; "
                "skipped." % (output, radium_path), "warning")
            continue
        payload = encoded.get(staged)
        if payload is None:
            try:
                im = Image.open(staged).convert("RGBA")
            except Exception as e:
                log("Radium image %s: can't read PNG (%s); skipped."
                    % (output, e), "warning")
                continue
            if im.size != (pad_w, pad_h):
                log("Radium image %s is %dx%d but must stay %dx%d; skipped "
                    "(don't resize — edit in place)."
                    % (output, im.size[0], im.size[1], pad_w, pad_h), "warning")
                continue
            payload = _dds.encode_bc3(np.asarray(im, dtype=np.uint8))
            encoded[staged] = payload
        if len(payload) != length:
            log("Radium image %s: re-encoded to %d bytes but the slot is %d; "
                "skipped." % (output, len(payload), length), "warning")
            continue
        rest = payload
        for disk, cnt in reader.disk_ranges(node, data_off, length):
            writes.append((disk, rest[:cnt]))
            rest = rest[cnt:]
        patched_outputs.add(output)
    n = len(patched_outputs)
    if n:
        log("Patching %d edited radium image(s) across %d on-card occurrence(s)."
            % (n, len({(o, ro, do) for (o, ro, _s, do, *_r) in edits})), "info")
    return writes, n
    """Diff *assets_dir* against the Extract baseline, re-encode / size-fit the
    edits, and resolve them to a flat list of absolute on-disk writes
    ``[(disk_offset, bytes), ...]`` (offsets relative to the start of
    ``disk_f`` — i.e. of the whole card image / device).

    ``disk_f`` is an already-open seekable byte stream over the card image OR
    the physical card; the caller owns it (it must stay open for the duration of
    this call) and closes it afterwards.  This is the shared core of both the
    file Write (:func:`write_image`) and the Direct-SD Write
    (:func:`write_device`), so the exact same patch set is produced whether the
    destination is an image copy or the card itself.

    Returns ``(writes, counts)`` where ``counts`` is ``(n_audio, n_video,
    n_image, n_text)``; returns ``(None, None)`` if cancelled.  Raises
    ``FileNotFoundError`` when there's nothing to write and ``RuntimeError``
    when nothing could be re-encoded / fit."""
    phase = phase or (lambda i: None)

    import numpy as np

    from ...core.checksums import md5_file, read_checksums
    from .spike2.codec import GenRecover, StereoRecover
    from .spike2.emulator import Spike2Emu, audio_decode_supported

    # Every idxNNNN.wav under assets_dir (the leading index survives an
    # Auto-transcribe rename, e.g. "idx0651 - text.wav"); scan recursively so the
    # user can point Write at the extract root or its audio/ subdir.
    all_wavs = {}
    for root, _dirs, files in os.walk(assets_dir):
        for fn in files:
            if not fn.lower().endswith(".wav"):
                continue
            m = _WAV_RE.match(os.path.splitext(fn)[0])
            if m:
                all_wavs[int(m.group(1))] = os.path.join(root, fn)
    # Only re-encode/patch what the user actually changed.  The folder is
    # normally the whole Extract output (thousands of WAVs + the LCD videos);
    # diff each asset against the Extract baseline (.checksums.md5) so an
    # untouched (or merely Auto-transcribe-renamed) sound/clip is skipped.
    baseline = read_checksums(assets_dir)
    base_by_idx = {}
    for rel in baseline:
        mm = _WAV_RE.match(os.path.splitext(os.path.basename(rel))[0])
        if mm:
            base_by_idx[int(mm.group(1))] = baseline[rel]
    audio_edits = {}
    if all_wavs:
        if base_by_idx:
            for idx, path in all_wavs.items():
                try:
                    if md5_file(path) != base_by_idx.get(idx):
                        audio_edits[idx] = path
                except OSError:
                    audio_edits[idx] = path
        else:
            audio_edits = dict(all_wavs)

    video_edits = _changed_videos(assets_dir, baseline)
    image_edits = _changed_images(assets_dir, baseline)
    texture_edits = _changed_scene_textures(assets_dir, baseline)
    radimg_edits = _changed_radium_images(assets_dir, baseline)
    # Per-song music banks (music_catNN_*.wav) edited by the user — re-encoded
    # back into their image-scNN.bin banks (see _compute_music_patches).
    music_edits = _changed_music_banks(assets_dir, baseline)
    # Edited LCD display strings (text/strings.tsv rows where replacement !=
    # original) — patched size-neutral, in place, into their .radium scenes.
    text_edits = _changed_radium_text(assets_dir)

    if (not audio_edits and not music_edits and not video_edits
            and not image_edits and not texture_edits and not radimg_edits
            and not text_edits):
        raise FileNotFoundError(
            "Nothing to write: every sound (idxNNNN.wav / music_catNN_*.wav) "
            "still matches the Extract baseline (.checksums.md5) and no replaced "
            "videos or images and no edited display text (text/strings.tsv) were "
            "found under %s. Edit a sound, change a display string, or assign a "
            "Replace Video / Replace Image asset first, then Write." % assets_dir)
    if audio_edits:
        if base_by_idx:
            log("Found %d edited sound(s) of %d to write."
                % (len(audio_edits), len(all_wavs)), "info")
        else:
            log("No .checksums.md5 baseline found; re-encoding all %d sound(s)."
                % len(audio_edits), "warning")
    if music_edits:
        log("Found %d edited music-bank song(s) to re-encode." % len(music_edits),
            "info")
    if video_edits:
        log("Found %d replaced video(s) to write." % len(video_edits), "info")
    if image_edits:
        log("Found %d replaced image(s) to write." % len(image_edits), "info")
    if texture_edits:
        log("Found %d edited scene texture(s) to write." % len(texture_edits),
            "info")
    if radimg_edits:
        log("Found %d edited radium image(s) to write." % len(radimg_edits),
            "info")
    if text_edits:
        log("Found edited display text in %d radium scene(s) to write."
            % len(text_edits), "info")

    def _read_prog(c, t):
        if progress:
            progress(int(c * 10 / max(t, 1)), 100, "Reading image.bin")

    work = tempfile.mkdtemp(prefix="spike2_")
    emu = None
    try:
        audio_patches = {}     # body_off -> bytes (inside image.bin)
        music_patches = []     # (sc_node, body_off, bytes) inside image-scNN.bin
        img_node = None
        reader = None
        gr_path = img_path = None
        if audio_edits or music_edits:
            phase(1)  # Re-encode audio (Direct-SD phase index; no-op for file Write)
            gr_path, img_path, reader, _fw_node, img_node = _extract_inputs(
                disk_f, parts, work, log, _read_prog)
            if cancel():
                return None, None
            if not audio_decode_supported(gr_path):
                # This title's audio codec can't be re-encoded.  If the user
                # only edited video/images, carry on and write those; otherwise
                # it's a hard error.
                msg = (
                    "Audio re-encode isn't supported for this title yet: its "
                    "game firmware uses a Spike 2 codec the engine can't locate "
                    "a single decode path for (e.g. a dual-path codec), so the "
                    "per-sound keystream can't be derived.")
                if not video_edits and not image_edits:
                    raise RuntimeError(msg)
                log(msg + "  Writing only the replaced video(s) / image(s).",
                    "warning")
                audio_edits = {}
                music_edits = []
            else:
                if audio_edits:
                    log("Booting firmware codec engine...", "info")
                    emu = Spike2Emu(gr_path, img_path)
                    emu.boot()
                    params = _load_or_derive_params(emu, gr_path, img_path, log,
                                                    progress)
                    byidx = {p["idx"]: p for p in params}

                    # re-encode each edited cat-0 sound into its body bytes
                    skipped = []
                    gr = sr = None
                    for n, (idx, wav_path) in enumerate(sorted(audio_edits.items())):
                        if cancel():
                            return None, None
                        if idx not in byidx:
                            log("idx %d not a known sound; skipping." % idx, "warning")
                            continue
                        p = byidx[idx]
                        if progress:
                            progress(10 + int(n * 65 / max(len(audio_edits), 1)), 100,
                                     "Re-encoding idx %d" % idx)
                        if p["chan"] == 2:
                            sr = sr or StereoRecover(emu)
                        else:
                            gr = gr or GenRecover(emu)
                        # Verify the keystream recovery actually round-trips for
                        # THIS sound before trusting its re-encode -- skip (never
                        # patch) sounds whose codec variant the analytic encode
                        # can't yet reproduce bit-exact, so Write can't silently
                        # corrupt them (see _recovery_valid).
                        if not _recovery_valid(emu, gr, sr, p, np):
                            skipped.append(idx)
                            log("idx %d: re-encode isn't bit-exact for this sound's "
                                "codec (skipped -- left unchanged in the output)."
                                % idx, "warning")
                            continue
                        if p["chan"] == 2:
                            body = _encode_stereo(emu, sr, p, wav_path, np)
                        else:
                            body = _encode_mono(emu, gr, p, wav_path, np)
                        audio_patches[p["body_off"]] = body
                        log("Re-encoded idx %d (%s, %d samples)."
                            % (idx, "stereo" if p["chan"] == 2 else "mono",
                               p["length"]), "info")
                    if skipped:
                        log("%d sound(s) skipped (re-encode unsupported for their "
                            "codec): %s"
                            % (len(skipped), ", ".join(map(str, skipped))), "warning")
                    # cat-0 emu done; free it before the per-bank music CatEmus.
                    emu.close()
                    emu = None

                # Per-song music banks (image-scNN.bin) — re-encode each edited
                # song back into its bank (own fresh CatEmu per bank).
                if music_edits:
                    if progress:
                        progress(80, 100, "Re-encoding music bank(s)...")
                    music_patches = _compute_music_patches(
                        reader, gr_path, img_path, music_edits, work, log,
                        progress, cancel, np)
                    if cancel():
                        return None, None

        # A video / image / text-only write (or one whose audio turned out
        # unsupported) still needs a reader to resolve the loose-file inodes.
        if reader is None:
            reader, _fw_node, _img_node = _locate(disk_f, parts)

        # Edited LCD display text -> already-flat (disk_offset, bytes) writes.
        text_writes = []
        n_text = 0
        if text_edits:
            if progress:
                progress(95, 100, "Preparing display text...")
            text_writes, n_text = _radium_text_writes(
                reader, assets_dir, log, cancel)
            if cancel():
                return None, None

        # Edited radium-embedded DXT5 images -> also already-flat (disk_offset,
        # bytes) writes (patched in place inside the scene.radium inode).
        radimg_writes = []
        n_radimg = 0
        if radimg_edits:
            if progress:
                progress(96, 100, "Preparing radium images...")
            radimg_writes, n_radimg = _radium_image_writes(
                reader, assets_dir, baseline, log, cancel)
            if cancel():
                return None, None

        video_patches = []     # (inode, payload bytes == inode size)
        if video_edits:
            if progress:
                progress(86, 100, "Preparing video...")
            video_patches, _vskip = _prepare_video_patches(
                reader, video_edits, work, log, cancel)
            if cancel():
                return None, None

        image_patches = []     # (inode, payload bytes == inode size)
        if image_edits:
            if progress:
                progress(92, 100, "Preparing images...")
            image_patches, _iskip = _prepare_image_patches(
                reader, image_edits, work, log, cancel)
            if cancel():
                return None, None

        texture_patches = []   # (inode, payload bytes == inode size)
        if texture_edits:
            if progress:
                progress(94, 100, "Preparing scene textures...")
            texture_patches, _tskip = _prepare_texture_patches(
                reader, texture_edits, log, cancel)
            if cancel():
                return None, None

        if (not audio_patches and not music_patches and not video_patches
                and not image_patches and not texture_patches
                and not radimg_writes and not text_writes):
            raise RuntimeError(
                "Nothing could be written: no sound re-encoded, no replaced "
                "video or image could be fit to its original slot, and no "
                "display-text edit fit its original string (the card image was "
                "not modified).")

        # Flatten every patch to absolute (disk_offset, bytes) writes via the
        # ext4 file->disk map.  The offsets are relative to the start of the
        # card image / device, so the same list applies whether we patch an
        # image copy (write_image) or the card itself (write_device).
        # Display-text writes are already (disk_offset, bytes) (the radium-text
        # helper resolved them through disk_ranges itself).
        writes = list(text_writes) + list(radimg_writes)
        for body_off, body in audio_patches.items():
            for disk, n in reader.disk_ranges(img_node, body_off, len(body)):
                writes.append((disk, body[:n]))
                body = body[n:]
        # Music songs patch their OWN bank inode (image-scNN.bin), not image.bin.
        for sc_node, body_off, body in music_patches:
            for disk, n in reader.disk_ranges(sc_node, body_off, len(body)):
                writes.append((disk, body[:n]))
                body = body[n:]
        for node, payload in video_patches + image_patches + texture_patches:
            off = 0
            for disk, n in reader.disk_ranges(node, 0, len(payload)):
                writes.append((disk, payload[off:off + n]))
                off += n
        # Scene textures + radium-embedded images fold into the image count
        # (they ARE images) so the (audio, video, image, text) summary tuple
        # stays the same shape.
        return writes, (len(audio_patches) + len(music_patches),
                        len(video_patches),
                        len(image_patches) + len(texture_patches) + n_radimg,
                        n_text)
    finally:
        if emu is not None:
            emu.close()
        _rmtree(work)


def _apply_writes(out, writes):
    """Apply ``[(disk_offset, bytes), ...]`` to an open seekable destination
    (an image copy opened ``r+b``, or a writable :class:`.rawdevice.RawDeviceFile`
    over the card)."""
    for disk, b in writes:
        out.seek(disk)
        out.write(b)


def write_image(original_path, assets_dir, output_path, log=None, progress=None,
                cancel=None):
    """Patch a copy of the card image at ``output_path`` with the user's edits
    (size-neutral, in place): re-encoded cat-0 audio bodies inside ``image.bin``,
    re-encoded per-song music bodies inside their ``image-scNN.bin`` banks,
    replaced LCD videos written over their original ``.asset`` files, and
    replaced UI images written over their original ``.png`` files.  Any kind of
    edit may be absent — a video/image-only write skips the firmware emulator
    entirely."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    import shutil

    parts = _linux_partitions(original_path)
    disk_f = open(original_path, "rb")
    try:
        writes, counts = _compute_patches(
            disk_f, parts, assets_dir, log, progress, cancel)
    finally:
        disk_f.close()
    if writes is None:                          # cancelled mid-compute
        return 0

    # copy the card image, then patch the changed bytes in place
    log("Copying card image to output...", "info")
    if progress:
        progress(0, 0, "Copying image...")
    shutil.copyfile(original_path, output_path)
    with open(output_path, "r+b") as out:
        _apply_writes(out, writes)
        out.flush()
        os.fsync(out.fileno())
    n_audio, n_video, n_image, n_text = counts
    log("Wrote patched image: %s (%d sound(s), %d video(s), %d image(s), "
        "%d display string(s))."
        % (output_path, n_audio, n_video, n_image, n_text), "success")
    return n_audio + n_video + n_image + n_text


def device_partitions(device_path, partition_override=None, log=None):
    """Confirm a raw device is a Spike 2 card and return its ext partitions
    ``[(byte_offset, byte_size), ...]`` (largest first) for ``_locate`` to
    search — the Direct-SD twin of :func:`formats.linux_partitions`.

    Reads only the device's MBR (sector-aligned).  Honors an optional 1-based
    MBR partition override.  Raises ``RuntimeError`` if the device can't be read
    (e.g. without Administrator) or doesn't carry the Spike 2 signature, so we
    never extract/write the wrong drive."""
    log = log or (lambda *a, **k: None)
    from .formats import (is_spike_card_parts, linux_partitions_from_parts,
                          parse_mbr_partitions_bytes)
    from .rawdevice import read_mbr

    mbr = read_mbr(device_path)
    if not mbr:
        raise RuntimeError(
            "Couldn't read the selected drive (%s). On Windows, Direct SD needs "
            "Administrator — re-launch as administrator and try again."
            % device_path)
    parts_raw = parse_mbr_partitions_bytes(mbr)
    if not is_spike_card_parts(parts_raw):
        raise RuntimeError(
            "The selected drive isn't a Stern Spike 2 SD card — its partition "
            "table doesn't match the Spike 2 signature. Double-check the drive "
            "selection (and that the card was removed from the machine and "
            "connected to this PC).")
    if partition_override is not None:
        match = [(lba * 512, sectors * 512)
                 for (idx, _t, lba, sectors) in parts_raw
                 if idx == partition_override - 1]
        if match:
            log("Using forced partition #%d." % partition_override, "info")
            return match
        log("Forced partition #%d not found on the card; auto-discovering "
            "instead." % partition_override, "warning")
    return linux_partitions_from_parts(parts_raw)


def write_device(device_path, assets_dir, log=None, progress=None, cancel=None,
                 phase=None, partition_override=None):
    """Direct-SD twin of :func:`write_image`: patch the user's edits straight
    onto the physical card (size-neutral, in place) — no intermediate image.

    Verifies the device carries the Spike 2 partition signature first (so we
    never write to the wrong drive), computes the identical patch set via
    :func:`_compute_patches`, then writes those exact byte ranges back to the
    card with a sector-aligned :class:`.rawdevice.RawDeviceFile`.  Needs the
    Administrator/root handle the GUI already gates the Direct-SD button on."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    phase = phase or (lambda i: None)
    from .rawdevice import RawDeviceFile

    phase(0)  # Scan
    parts = device_partitions(device_path, partition_override, log=log)

    with RawDeviceFile(device_path, writable=False) as disk_f:
        writes, counts = _compute_patches(
            disk_f, parts, assets_dir, log, progress, cancel, phase=phase)
    if writes is None:                          # cancelled mid-compute
        return 0

    phase(2)  # Write to SD card
    log("Writing changes directly to the SD card (in place)...", "info")
    if progress:
        progress(0, 0, "Writing to SD card...")
    with RawDeviceFile(device_path, writable=True) as out:
        _apply_writes(out, writes)
        out.flush()
    n_audio, n_video, n_image, n_text = counts
    log("Wrote to SD card: %d sound(s), %d video(s), %d image(s), "
        "%d display string(s)."
        % (n_audio, n_video, n_image, n_text), "success")
    return n_audio + n_video + n_image + n_text


# --------------------------------------------------------------------------
# encode helpers
# --------------------------------------------------------------------------
def _load_wav(path, want_stereo, np):
    w = wave.open(path, "rb")
    n = w.getnframes(); ch = w.getnchannels(); sr = w.getframerate()
    a = np.frombuffer(w.readframes(n), np.int16).astype(np.int64)
    w.close()
    a = a.reshape(-1, ch)
    if sr != 44100 and len(a):
        idx = np.clip((np.arange(int(len(a) * 44100 / sr)) * sr / 44100).astype(int),
                      0, len(a) - 1)
        a = a[idx]
    if want_stereo:
        return a if ch == 2 else np.repeat(a, 2, axis=1)
    return a.mean(1).astype(np.int64) if ch == 2 else a[:, 0]


def _fit(a, length, np):
    a = np.asarray(a, np.int64)
    if len(a) > length:
        a = a[:length]
    if len(a) < length:
        a = np.concatenate([a, np.zeros(length - len(a), np.int64)])
    return a


def _amplitude_fit(samples, rng, np, headroom=0.97):
    pk = int(np.abs(samples).max()) if len(samples) else 0
    if pk <= 0:
        return samples
    return (samples.astype(np.float64) * (rng * headroom / pk)).astype(np.int64)


_MONO_RANGE = 11147
_STEREO_RANGE = 21452


class _BodyOverlay:
    """Read-through overlay on the image.bin mmap: returns patched bytes for one
    body offset so a freshly re-encoded body can be decoded back *without*
    copying the whole multi-GB image.  Used by :func:`_recovery_valid` to verify
    a sound's re-encode round-trips before Write trusts it."""

    def __init__(self, mm):
        self._mm = mm
        self.patch = None      # (file_off, bytes) or None

    def __getitem__(self, sl):
        data = bytearray(self._mm[sl])
        if self.patch is not None and isinstance(sl, slice):
            off, b = self.patch
            start = sl.start or 0
            lo = max(off, start)
            hi = min(off + len(b), start + len(data))
            if lo < hi:
                data[lo - start:hi - start] = b[lo - off:hi - off]
        return bytes(data)

    def size(self):
        return self._mm.size()

    def close(self):
        self._mm.close()


def _recovery_valid(emu, gr, sr, p, np, nblk=4):
    """True iff re-encoding the sound's *own* decoded audio reproduces it
    bit-exact over the first ``nblk`` blocks.

    The analytic re-encode recovers a per-sample keystream by driving the codec;
    that recovery is exact for the codecs validated so far but does not yet model
    every variant (e.g. multi-band sounds, where the companding fires several
    times per output sample and the captured keystream interleaves).  This
    self-test catches such sounds so Write can skip them rather than patch a body
    that would decode to noise -- protecting both the newly-located titles and
    any multi-band sound in an already-supported title.  Any failure to drive the
    recovery (e.g. no companding site located) is treated as 'not valid' so the
    sound is skipped, never written blind."""
    secs = (nblk * 200 + 200) / 44100.0
    try:
        out0 = emu.decode(p, max_secs=secs)
        if out0 is None:
            return False
        L0 = np.asarray(out0[0], np.int64); R0 = np.asarray(out0[1], np.int64)
        stereo = out0[2]
        nb = min(nblk, (len(L0) + 199) // 200)
        if nb == 0:
            return False
        # Re-encode only the first ``nb`` blocks (truncate the target so
        # encode_sound stops there) and compare over that range; encode_sound
        # applies the build's body-word offset so the self-test sees the same
        # bytes a full Write would lay down.
        cmp_n = nb * 200
        if stereo:
            body = sr.encode_sound(p, L0[:cmp_n], R0[:cmp_n])
        else:
            body = gr.encode_sound(p, L0[:cmp_n])
        if not isinstance(emu.mm, _BodyOverlay):
            emu.mm = _BodyOverlay(emu.mm)
        emu.mm.patch = (p["body_off"], bytes(body))
        try:
            out1 = emu.decode(p, max_secs=secs)
        finally:
            emu.mm.patch = None
        if out1 is None:
            return False
        L1 = np.asarray(out1[0], np.int64); R1 = np.asarray(out1[1], np.int64)
        m = min(len(L0), len(L1), cmp_n)
        if int(np.count_nonzero(L0[:m] != L1[:m])):
            return False
        if stereo:
            mr = min(len(R0), len(R1), cmp_n)
            if int(np.count_nonzero(R0[:mr] != R1[:mr])):
                return False
        return True
    except Exception:
        return False


def _encode_mono(emu, gr, p, wav_path, np):
    length = p["length"]
    s = _load_wav(wav_path, False, np)
    s = _amplitude_fit(s, _MONO_RANGE, np)
    tgt = _fit(np.clip(s, -_MONO_RANGE, _MONO_RANGE), length, np)
    return gr.encode_sound(p, tgt)


def _encode_stereo(emu, sr, p, wav_path, np):
    length = p["length"]
    a = _load_wav(wav_path, True, np)
    a = _amplitude_fit(a, _STEREO_RANGE, np)
    L = _fit(np.clip(a[:, 0], -_STEREO_RANGE, _STEREO_RANGE), length, np)
    R = _fit(np.clip(a[:, 1], -_STEREO_RANGE, _STEREO_RANGE), length, np)
    return sr.encode_sound(p, L, R)


_MUSIC_NAME_RE = re.compile(r"music_cat(\d+)_(\d+)", re.IGNORECASE)


def _compute_music_patches(reader, gr_path, img_path, music_edits, work, log,
                           progress, cancel, np):
    """Re-encode each edited per-song music bank back into its ``image-scNN.bin``
    (size-neutral) and return ``[(sc_node, body_off, body_bytes), ...]`` for the
    songs that re-encode bit-exact.

    Mirrors the cat-0 audio re-encode, with two differences forced by where the
    songs live: each song's body is in a SEPARATE bank file (so every patch
    carries its own ext4 inode, not ``image.bin``'s), and the params are derived
    per bank on a fresh :class:`CatEmu` (deriving several banks on one emu
    accumulates state that grinds the loader — see ``spike2/category.py``).  A
    song whose re-encode isn't bit-exact (``_recovery_valid``) is skipped with a
    warning, never written blind.  ``music_edits`` = the edited
    ``music_catNN_MMMM*.wav`` paths."""
    from .spike2.category import CatEmu, _find_revalidate, read_category_id
    from .spike2.codec import GenRecover, StereoRecover

    # group edits by category id; idx = the sound's index within that bank
    by_cat = {}
    for wav in music_edits:
        m = _MUSIC_NAME_RE.match(os.path.basename(wav))
        if not m:
            continue
        by_cat.setdefault(int(m.group(1)), []).append((int(m.group(2)), wav))
    if not by_cat:
        return []

    # resolve + extract each needed image-scNN.bin (the body source AND the
    # inode we patch).
    sc = {}     # catid -> (sc_node, local_path)
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            return []
        rid = read_category_id(path.rsplit("/", 1)[-1])
        if rid in by_cat and rid not in sc:
            local = os.path.join(work, os.path.basename(path))
            reader.extract_file(node, local)
            sc[rid] = (node, local)
    if not sc:
        log("None of the edited songs' banks (image-scNN.bin) were found on the "
            "card; left unchanged.", "warning")
        return []

    rev = _find_revalidate(
        gr_path, img_path,
        sorted((cid, local) for cid, (_n, local) in sc.items()), log)
    if rev is None:
        log("Couldn't drive the category loader to re-encode the music bank(s); "
            "the edited song(s) were left unchanged.", "warning")
        return []

    patches, skipped = [], []
    for cid in sorted(by_cat):
        if cid not in sc:
            log("music_cat%02d: bank not on the card; %d edit(s) skipped."
                % (cid, len(by_cat[cid])), "warning")
            continue
        if cancel():
            return patches
        sc_node, local = sc[cid]
        emu = CatEmu(gr_path, img_path)
        try:
            emu.boot()
            emu.set_category_file(local)
            rows = emu._derive_cat(cid, rev) or []
            byidx = {r["idx"]: r for r in rows}
            emu.mm = emu._mm_cat          # body source = this bank
            gr = sr = None
            for idx, wav in sorted(by_cat[cid]):
                if cancel():
                    return patches
                p = byidx.get(idx)
                if p is None:
                    log("music_cat%02d_%04d isn't a sound in that bank; skipped."
                        % (cid, idx), "warning")
                    continue
                if p["chan"] == 2:
                    sr = sr or StereoRecover(emu)
                else:
                    gr = gr or GenRecover(emu)
                if not _recovery_valid(emu, gr, sr, p, np):
                    skipped.append((cid, idx))
                    log("music_cat%02d_%04d: re-encode isn't bit-exact for this "
                        "song's codec (skipped — left unchanged)." % (cid, idx),
                        "warning")
                    continue
                if p["chan"] == 2:
                    body = _encode_stereo(emu, sr, p, wav, np)
                else:
                    body = _encode_mono(emu, gr, p, wav, np)
                patches.append((sc_node, p["body_off"], body))
                log("Re-encoded music_cat%02d_%04d (%s, %d samples)."
                    % (cid, idx, "stereo" if p["chan"] == 2 else "mono",
                       p["length"]), "info")
        finally:
            emu.close()
    if skipped:
        log("%d music song(s) skipped (re-encode not bit-exact)." % len(skipped),
            "warning")
    return patches


# --------------------------------------------------------------------------
def _linux_partitions(path):
    from .formats import linux_partitions
    return linux_partitions(path)


def _rmtree(path):
    import shutil
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass
