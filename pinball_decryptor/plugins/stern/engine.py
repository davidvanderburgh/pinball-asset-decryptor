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
import hmac
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
_DXT1_FORMAT = 4            # the radium texture-descriptor format enum for BC1


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
    """Decode every BC3/DXT5 or BC1/DXT1 scene texture to
    ``output_dir/images/scene_textures/`` as RGBA PNG.

    These are the single (non-nested, non-``ftyp``) ``scene.assets/<N>.asset``
    files — raw BC3 (``format==5``) or BC1 (``format==4``) block data whose
    width/height/format are read from the co-located ``scene.radium``
    (:func:`parse_texture_descriptor`).  A
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
        # BC3/DXT5 (16 B/4×4 block) and BC1/DXT1 (8 B/4×4 block) are supported.
        # The block-padded size is the exact, dimension-correct law (a texture
        # whose W/H aren't multiples of 4 still occupies whole 4×4 blocks); it
        # doubles as a guard that the descriptor really belongs to this asset.
        nblk = ((w + 3) // 4) * ((h + 3) // 4)
        if fmt == _DXT5_FORMAT and size == nblk * 16:
            decode = _dds.decode_bc3
        elif fmt == _DXT1_FORMAT and size == nblk * 8:
            decode = _dds.decode_bc1
        else:
            n_skip += 1
            continue
        try:
            rgba = decode(reader.read_file_bytes(node), w, h)
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
    """Find every inline BC3/DXT5 or BC1/DXT1 image in a ``scene.radium``.

    Each image is serialized as
    ``[dispW u32][dispH u32][handle u32][texW u32][texH u32][format u32]
    [0 u32][0 u32][length u32][block data]`` where
    ``length == padded4(texW) * padded4(texH)`` for BC3 (``format==5``,
    1 byte/pixel) or half that for BC1 (``format==4``, 1/2 byte/pixel).  We anchor
    on the ``format, 0, 0`` triplet and validate that the length matches the
    block-padded dimensions for that format and that the data fits — a signature
    specific enough to have no false positives.

    Returns ``[{data_off, length, fmt, tex_w, tex_h, pad_w, pad_h, disp_w,
    disp_h}]`` where decoding uses ``pad_w x pad_h`` (the full block grid)."""
    out = []
    n = len(data)
    # fmt enum byte, then "0,0" (the two trailing u32s) -> 12-byte anchor
    sigs = ((_DXT5_FORMAT, b"\x05\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"),
            (_DXT1_FORMAT, b"\x04\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"))
    for fmt, sig in sigs:
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
            want = pad_w * pad_h if fmt == _DXT5_FORMAT else pad_w * pad_h // 2
            if length != want or m + 16 + length > n:
                continue
            disp_w = struct.unpack_from("<I", data, m - 20)[0] if m >= 20 else tex_w
            disp_h = struct.unpack_from("<I", data, m - 16)[0] if m >= 20 else tex_h
            if not (0 < disp_w <= pad_w):
                disp_w = tex_w
            if not (0 < disp_h <= pad_h):
                disp_h = tex_h
            out.append(dict(data_off=m + 16, length=length, fmt=fmt,
                            tex_w=tex_w, tex_h=tex_h, pad_w=pad_w, pad_h=pad_h,
                            disp_w=disp_w, disp_h=disp_h))
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
                    decode = (_dds.decode_bc1 if im["fmt"] == _DXT1_FORMAT
                              else _dds.decode_bc3)
                    rgba = decode(raw, im["pad_w"], im["pad_h"])
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
            manifest.append("%s\t%s\t%d\t%d\t%d\t%d\t%d"
                            % (out_rel, path, im["data_off"], im["length"],
                               im["pad_w"], im["pad_h"], im["fmt"]))
            n_occ += 1
    if not manifest:
        return 0
    try:
        with open(os.path.join(tex_dir, _RADIUM_IMAGE_MANIFEST), "w",
                  encoding="utf-8") as f:
            f.write("# output\tradium card path\tdata offset\tlength\tpad_w\tpad_h\tfmt\n"
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
# Auto-transcribe / Music-ID *renamed* decode WAVs — "idx0001 - music.wav",
# "music_cat01_0001 - Battery.wav".  The bare "idx0001.wav" the decode writes is
# deliberately NOT matched (it's overwritten in place); only the renamed copies
# a prior extract left behind are.
_RENAMED_AUDIO_RE = re.compile(
    r"^(?:idx\d+|music_cat\d+_\d+) - .*\.wav$", re.IGNORECASE)


def _remove_renamed_audio_twins(audio_dir, log=None):
    """Delete stale auto-named decode WAVs left in *audio_dir* by a prior run.

    Re-extracting writes fresh bare ``idxNNNN.wav`` but the previous run's
    Auto-transcribe/Music-ID *renamed* copies (``idx0001 - music.wav``) have
    different names, so they survive — leaving two files per sound: clutter the
    GUI shows as duplicates and a hazard for the leading-index Write key.  The
    fresh decode regenerates every sound, so those renamed leftovers are always
    stale.  Removing them (the bare files are overwritten anyway) keeps one file
    per sound.  No-op on a first extract into an empty folder.
    """
    if not os.path.isdir(audio_dir):
        return
    removed = 0
    for fn in os.listdir(audio_dir):
        if _RENAMED_AUDIO_RE.match(fn):
            try:
                os.remove(os.path.join(audio_dir, fn))
                removed += 1
            except OSError:
                pass
    if removed and log:
        log("Removed %d stale auto-named audio file(s) from a previous extract "
            "(re-naming will run again if enabled)." % removed, "info")


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
            # Spine skeletons embedded verbatim in scene.radium (the 2D
            # skeletal-animation rigs) -> spine/*.json — own try/except so a
            # skeleton hiccup never blocks the other media or audio.
            try:
                from . import spine as _spine
                _spine.extract_spine(
                    reader, output_dir, log=log,
                    progress=(lambda c, t, d="": progress(
                        15, 100, d)) if progress else None,
                    cancel=cancel)
            except Exception as e:
                log("Spine extraction failed (%s); continuing." % e, "warning")
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
        # Drop a previous extract's auto-named twins so re-extracting doesn't
        # accumulate "idx0001.wav" + "idx0001 - music.wav" duplicates.
        _remove_renamed_audio_twins(audio_dir, log)
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


def _select_changed_idx_wavs(assets_dir, baseline):
    """Map ``idx -> path`` for every changed ``idxNNNN.wav`` under *assets_dir*.

    Several files can share one idx: re-extracting into a folder that still
    holds the prior run's Auto-transcribe / Music-ID *renamed* copies leaves
    both ``idx0001.wav`` and ``idx0001 - music.wav`` (identical content, same
    leading index).  Both map to ONE on-card sound at Write, so when the user
    edits one twin we must pick the EDITED file: a plain ``dict[idx] = path``
    keyed by os.walk order silently dropped the edit whenever the *unedited*
    twin was walked last.  Here we group by idx and choose the twin whose bytes
    differ from the ``.checksums.md5`` baseline; an idx with no differing twin
    is unchanged and skipped.
    """
    from ...core.checksums import md5_file
    by_idx = {}  # idx -> [path, ...]
    for root, _dirs, files in os.walk(assets_dir):
        for fn in files:
            if not fn.lower().endswith(".wav"):
                continue
            m = _WAV_RE.match(os.path.splitext(fn)[0])
            if m:
                by_idx.setdefault(int(m.group(1)), []).append(
                    os.path.join(root, fn))
    base_by_idx = {}
    for rel in baseline:
        mm = _WAV_RE.match(os.path.splitext(os.path.basename(rel))[0])
        if mm:
            base_by_idx[int(mm.group(1))] = baseline[rel]

    edits = {}
    for idx, paths in by_idx.items():
        base = base_by_idx.get(idx)
        if base is None:
            # No baseline for this idx (no .checksums.md5, or a brand-new
            # file) — treat it as an edit; one representative path is enough.
            edits[idx] = paths[-1]
            continue
        for path in paths:
            try:
                changed = md5_file(path) != base
            except OSError:
                changed = True
            if changed:
                edits[idx] = path
                break
    return edits


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

    Returns ``(writes, n_strings, overlays)`` where ``n_strings`` is the number
    of unique (radium, original) strings actually patched and ``overlays`` is
    ``{i_block: (node, {file_offset: bytes})}`` for every patched ``scene.radium``
    inode, so the caller can recompute its ``.sidx`` digest from the patched
    content."""
    from . import radium as _radium

    edits = _changed_radium_text(assets_dir)
    if not edits:
        return [], 0, {}
    nodes = _resolve_card_nodes(reader, list(edits.keys()), cancel)

    writes = []
    overlays = {}   # i_block -> (node, {file_off: bytes})
    n_strings = 0
    for card_path, pairs in edits.items():
        if cancel():
            break
        node = nodes.get(card_path)
        if node is None:
            log("Display text: radium %s wasn't found on the card; %d edit(s) "
                "skipped." % (card_path, len(pairs)), "warning")
            continue
        ib = bytes(node["i_block"])
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
            full = new_bytes.ljust(orig_len, b" ")
            for e in occs:
                if e["length"] != orig_len:
                    continue                       # paranoia: length must match
                payload = full
                for disk, n in reader.disk_ranges(node, e["offset"], orig_len):
                    writes.append((disk, payload[:n]))
                    payload = payload[n:]
                overlays.setdefault(ib, (node, {}))[1][e["offset"]] = full
            n_strings += 1
            log("Display text in %s: \"%s\" -> \"%s\" (%d occurrence(s))."
                % (card_path, original, replacement, len(occs)), "info")
    return writes, n_strings, overlays


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
        arr = np.asarray(im, dtype=np.uint8)
        payload = (_dds.encode_bc1(arr) if fmt == _DXT1_FORMAT
                   else _dds.encode_bc3(arr))
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
    pad_h, fmt), ...]`` for the radium-embedded images whose PNG differs from the
    Extract baseline.  Empty when there's no ``radium_images.txt`` manifest.
    ``fmt`` defaults to BC3/DXT5 for manifests written before the BC1 column."""
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
                fmt = int(cols[6]) if len(cols) > 6 else _DXT5_FORMAT
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
                        pad_w, pad_h, fmt))
    return out


def _radium_image_writes(reader, assets_dir, baseline, log, cancel):
    """Re-encode each edited radium-embedded image to its format (BC3/DXT5 or
    BC1/DXT1) and resolve it to a flat ``[(disk_offset, bytes), ...]`` list
    patching the bytes in place inside the ``scene.radium`` inode (same form
    ``_compute_patches`` collects, like the display-text writes).  Returns
    ``(writes, n_images)``.

    Size-neutral by construction: the PNG is the full padded block grid, so
    re-encoding yields exactly ``length`` bytes at ``data_offset``.

    Returns ``(writes, n_images, overlays)`` where ``overlays`` is
    ``{i_block: (node, {file_offset: bytes})}`` for every patched ``scene.radium``
    inode, so the caller can recompute its ``.sidx`` digest."""
    edits = _changed_radium_images(assets_dir, baseline)
    if not edits:
        return [], 0, {}
    from . import dds as _dds
    try:
        from PIL import Image
        import numpy as np
    except Exception as e:
        log("Pillow/numpy unavailable (%s); radium-image edits skipped." % e,
            "warning")
        return [], 0, {}
    nodes = _resolve_card_nodes(
        reader, list({rp for (_o, rp, *_r) in edits}), cancel)
    writes = []
    overlays = {}                  # i_block -> (node, {file_off: bytes})
    encoded = {}                   # staged PNG path -> block bytes (one PNG, many occurrences)
    patched_outputs = set()
    for output, radium_path, staged, data_off, length, pad_w, pad_h, fmt in edits:
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
            arr = np.asarray(im, dtype=np.uint8)
            payload = (_dds.encode_bc1(arr) if fmt == _DXT1_FORMAT
                       else _dds.encode_bc3(arr))
            encoded[staged] = payload
        if len(payload) != length:
            log("Radium image %s: re-encoded to %d bytes but the slot is %d; "
                "skipped." % (output, len(payload), length), "warning")
            continue
        rest = payload
        for disk, cnt in reader.disk_ranges(node, data_off, length):
            writes.append((disk, rest[:cnt]))
            rest = rest[cnt:]
        overlays.setdefault(bytes(node["i_block"]), (node, {}))[1][data_off] = payload
        patched_outputs.add(output)
    n = len(patched_outputs)
    if n:
        log("Patching %d edited radium image(s) across %d on-card occurrence(s)."
            % (n, len({(o, ro, do) for (o, ro, _s, do, *_r) in edits})), "info")
    return writes, n, overlays


def _overlay_digests(reader, disk, node, overlays):
    """Stream *node*'s bytes (from *disk* via the ext4 map), applying *overlays*
    (``{file_offset: bytes}``) in place, and return ``(HMAC-SHA1(K), MD5)`` of the
    resulting patched file — the exact digests its ``.sidx`` record should carry,
    computed without re-reading the patched output."""
    from . import sidx
    h = hmac.new(sidx.SIDX_KEY, digestmod=hashlib.sha1)
    m = hashlib.md5()
    ov = sorted(overlays.items())
    pos = 0
    for d, n in reader.disk_ranges(node, 0, node["size"]):
        disk.seek(d)
        rem = n
        while rem:
            take = min(rem, 1 << 20)
            chunk = bytearray(disk.read(take))
            for off, b in ov:
                if off + len(b) <= pos or off >= pos + take:
                    continue
                lo = max(off, pos)
                hi = min(off + len(b), pos + take)
                chunk[lo - pos:hi - pos] = b[lo - off:hi - off]
            h.update(chunk)
            m.update(chunk)
            pos += take
            rem -= take
    return h.digest(), m.digest()


def _merge_radium_overlays(dst, src):
    """Merge ``{i_block: (node, {file_off: bytes})}`` *src* into *dst* in place.

    A single ``scene.radium`` may receive both display-text and embedded-image
    edits; combining their file-relative overlays under one inode key lets the
    ``.sidx`` refresh recompute that radium's digest from the fully-patched
    content in one pass."""
    for ib, (node, ov) in src.items():
        slot = dst.setdefault(ib, (node, {}))
        slot[1].update(ov)


def _compute_sidx_writes(reader, disk_f, img_node, audio_patches, music_patches,
                         full_repl, radium_overlays, log):
    """Produce the on-disk writes that refresh the ``.sidx`` manifest records for
    every file this Write changed, so the card passes Stern SD validation.

    Covers ``image.bin`` (cat-0 audio), the per-song ``image-scNN.bin`` banks,
    full-replacement assets (video / image / texture), and in-place ``scene.radium``
    edits (display text + embedded images) via their file-relative
    ``radium_overlays`` (``{i_block: (node, {file_off: bytes})}``)."""
    from . import sidx
    sidx_path, sidx_node = sidx.find_sidx(reader)
    if sidx_node is None:
        log("No /spk/index/*.sidx manifest on the card — skipping SD-validation "
            "refresh (card may report a validation error).", "warning")
        return []
    sdata = reader.read_file_bytes(sidx_node)
    recs, _hdr_crc, sidx_fmt = sidx.parse_records(sdata)
    if not recs:
        log("Unrecognised .sidx manifest format — skipping SD-validation refresh.",
            "warning")
        return []

    # Map each file's unique extent block (i_block) -> manifest path so we can
    # resolve modified inodes to their records.
    ipath = {bytes(node["i_block"]): path.lstrip("/")
             for path, _ino, node in reader.iter_regular_files(
                 min_size=1, max_depth=20)}

    modified = {}   # manifest path -> (hmac, md5) of the patched file
    if audio_patches and img_node is not None:
        p = ipath.get(bytes(img_node["i_block"]))
        if p:
            modified[p] = _overlay_digests(reader, disk_f, img_node, audio_patches)
    if music_patches:
        banks = {}
        for sc_node, body_off, body in music_patches:
            ib = bytes(sc_node["i_block"])
            banks.setdefault(ib, [sc_node, {}])[1][body_off] = body
        for ib, (sc_node, ov) in banks.items():
            p = ipath.get(ib)
            if p:
                modified[p] = _overlay_digests(reader, disk_f, sc_node, ov)
    for node, payload in full_repl:
        p = ipath.get(bytes(node["i_block"]))
        if p:
            modified[p] = sidx.digests(bytes(payload))
    # In-place scene.radium edits (display text + embedded images): recompute the
    # digest by streaming each patched inode with its file-relative overlays.
    for ib, (node, ov) in (radium_overlays or {}).items():
        p = ipath.get(ib)
        if p:
            modified[p] = _overlay_digests(reader, disk_f, node, ov)

    out = []
    n_ok = 0
    for path, (hm, md) in modified.items():
        po = recs.get(path)
        if po is None:
            log("  .sidx has no record for %s — left stale." % path, "warning")
            continue
        for foff, b in sidx.record_field_writes(po, hm, md, sidx_fmt):
            for d, n in reader.disk_ranges(sidx_node, foff, len(b)):
                out.append((d, b[:n]))
                b = b[n:]
        n_ok += 1
    if n_ok:
        log("Refreshed %d %s SD-validation manifest record(s) (HMAC-SHA1 + MD5)."
            % (n_ok, sidx_fmt), "success")
        # NOTE: the manifest header word @0x34 (live on FINF cards, 0xffffffff on
        # FI64) is deliberately left as-is.  Firmware RE (2026-06-25) disassembled
        # both on-card .sidx parsers (/usr/local/bin/spk and spike_menu/game) and
        # the firmware ELF: none of them read offset 0x34, and a hardware test that
        # forced @0x34 -> 0xffffffff still failed — so @0x34 is not an enforced
        # integrity word.  The per-file HMAC-SHA1+MD5 records refreshed above are
        # the actual validated digests.
    return out


def _compute_patches(disk_f, parts, assets_dir, log, progress, cancel,
                     phase=None):
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

    from ...core.checksums import read_checksums
    from .spike2.emulator import audio_decode_supported

    # Only re-encode/patch what the user actually changed.  The folder is
    # normally the whole Extract output (thousands of idxNNNN.wav + the LCD
    # videos); diff each asset against the Extract baseline (.checksums.md5) so
    # an untouched (or merely Auto-transcribe-renamed) sound/clip is skipped.
    # The leading index survives a rename ("idx0651 - text.wav"); the walk is
    # recursive so Write works from the extract root or its audio/ subdir.
    baseline = read_checksums(assets_dir)
    audio_edits = _select_changed_idx_wavs(assets_dir, baseline)

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
        if baseline:
            log("Found %d edited sound(s) to write." % len(audio_edits), "info")
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
                    # Re-encode every edited cat-0 sound to its body bytes — fans
                    # across worker processes (each boots its own emulator), with
                    # a single-process fallback.  Params come from the
                    # Extract-time cache; only a cold cache boots an emulator here.
                    params = _params_for(gr_path, img_path, log, progress)
                    audio_patches, _askip = _encode_cat0_sounds(
                        gr_path, img_path, params, audio_edits, np, log,
                        progress, cancel)
                    if audio_patches is None:
                        return None, None
                    # Keep the firmware's master-directory forward-chain intact:
                    # restore the bytes its decode consumes, then verify every
                    # sound still derives valid codec params (else abort — the
                    # card would reboot on audio).  See _restore_masterdir_consumed.
                    if audio_patches and os.environ.get(
                            "PAD_STERN_SKIP_MASTERDIR_FIX") != "1":
                        audio_patches = _restore_masterdir_consumed(
                            gr_path, img_path, audio_patches, log, progress,
                            cancel)
                        if audio_patches is None:
                            return None, None
                        _assert_param_integrity(gr_path, img_path, audio_patches,
                                                params, np, log, work)

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

        # Radium edits patch the scene.radium inode in place; collect per-inode
        # file-relative overlays alongside the flat disk writes so the .sidx
        # refresh below can recompute each patched radium's digest.
        radium_overlays = {}   # i_block -> (node, {file_off: bytes})

        # Edited LCD display text -> already-flat (disk_offset, bytes) writes.
        text_writes = []
        n_text = 0
        if text_edits:
            if progress:
                progress(95, 100, "Preparing display text...")
            text_writes, n_text, _t_ov = _radium_text_writes(
                reader, assets_dir, log, cancel)
            _merge_radium_overlays(radium_overlays, _t_ov)
            if cancel():
                return None, None

        # Edited radium-embedded DXT5 images -> also already-flat (disk_offset,
        # bytes) writes (patched in place inside the scene.radium inode).
        radimg_writes = []
        n_radimg = 0
        if radimg_edits:
            if progress:
                progress(96, 100, "Preparing radium images...")
            radimg_writes, n_radimg, _i_ov = _radium_image_writes(
                reader, assets_dir, baseline, log, cancel)
            _merge_radium_overlays(radium_overlays, _i_ov)
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
        # Regenerate the .sidx manifest records for the changed files so the
        # card passes Stern's SD validation (recompute HMAC-SHA1 + MD5 with the
        # manifest's global validation key).  Best-effort: a missing /
        # unrecognised manifest never fails the Write — it just leaves the card
        # needing re-validation, exactly as before this step existed.
        full_repl = list(video_patches) + list(image_patches) + list(texture_patches)
        try:
            writes += _compute_sidx_writes(
                reader, disk_f, img_node, audio_patches, music_patches,
                full_repl, radium_overlays, log)
        except Exception as e:
            log("SD-validation manifest update failed (%s); the card may report "
                "a validation error until re-validated." % e, "warning")

        # Scene textures + radium-embedded images fold into the image count
        # (they ARE images) so the (audio, video, image, text) summary tuple
        # stays the same shape.
        return writes, (len(audio_patches) + len(music_patches),
                        len(video_patches),
                        len(image_patches) + len(texture_patches) + n_radimg,
                        n_text)
    finally:
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


# --------------------------------------------------------------------------
# Parallel re-encode (Write) — the cat-0 audio re-encode is the dominant cost of
# building an update when many sounds changed.  It's a pure-CPU emulation loop,
# so it fans across processes exactly like the decode path (_parallel_decode):
# each worker boots one emulator and re-encodes its share.  Per-sound encode is
# independent of order, so a parallel Write is byte-identical to a serial one;
# any pool failure falls back to a single in-process emulator.  Set
# PAD_STERN_SERIAL_ENCODE=1 to force the serial path (A/B verification).
# --------------------------------------------------------------------------
_FORCE_SERIAL_ENCODE = os.environ.get("PAD_STERN_SERIAL_ENCODE") == "1"


def _params_for(gr_path, img_path, log, progress):
    """Codec params for the card — from the Extract-time cache, or derived on a
    throwaway emulator if the cache is cold (rare for Write, which follows an
    Extract that already cached them).  Avoids booting an emulator on the common
    cache-hit path (the workers boot their own)."""
    fp = _fingerprint(gr_path, img_path)
    cache = _cache_path(fp)
    if os.path.exists(cache):
        try:
            params = pickle.load(open(cache, "rb"))
            log("Loaded cached codec parameters (%d sounds)." % len(params),
                "info")
            return params
        except Exception:
            pass
    from .spike2.emulator import Spike2Emu
    emu = Spike2Emu(gr_path, img_path)
    try:
        emu.boot()
        return _load_or_derive_params(emu, gr_path, img_path, log, progress)
    finally:
        emu.close()


def _encode_cat0_serial(gr_path, img_path, byidx, edits, np, log, progress,
                        cancel):
    """Single-process cat-0 re-encode (the fallback + correctness reference)."""
    from .spike2.codec import GenRecover, StereoRecover
    from .spike2.emulator import Spike2Emu
    log("Booting firmware codec engine...", "info")
    emu = Spike2Emu(gr_path, img_path)
    emu.boot()
    patches, skipped = {}, []
    gr = sr = None
    try:
        for n, (idx, wav) in enumerate(edits):
            if cancel():
                return None, None
            p = byidx[idx]
            if progress:
                progress(10 + int(n * 65 / max(len(edits), 1)), 100,
                         "Re-encoding idx %d" % idx)
            if p["chan"] == 2:
                sr = sr or StereoRecover(emu)
            else:
                gr = gr or GenRecover(emu)
            if not _recovery_valid(emu, gr, sr, p, np):
                skipped.append(idx)
                log("idx %d: re-encode isn't bit-exact for this sound's codec "
                    "(skipped -- left unchanged in the output)." % idx, "warning")
                continue
            body = (_encode_stereo(emu, sr, p, wav, np) if p["chan"] == 2
                    else _encode_mono(emu, gr, p, wav, np))
            patches[p["body_off"]] = body
            log("Re-encoded idx %d (%s, %d samples)."
                % (idx, "stereo" if p["chan"] == 2 else "mono", p["length"]),
                "info")
    finally:
        emu.close()
    return patches, sorted(skipped)


def _encode_cat0_parallel(gr_path, img_path, needed_params, edits, nworkers, np,
                          log, progress, cancel):
    """Re-encode across ``nworkers`` spawned emulator processes (each boots once).

    Returns ``(patches, skipped, remaining)``: ``remaining`` is the list of edits
    that did NOT complete (empty on full success).  A pool that never boots a
    worker raises (so the caller does a full single-process pass).  But a pool
    that dies *part way* (e.g. a worker is killed) does NOT raise -- it returns
    what already finished plus the leftover edits, so the caller can finish just
    those in a single process instead of throwing away all the parallel work and
    re-encoding everything serially (the failure that turned a ~minutes job into
    hours).  Returns ``(None, None, None)`` if cancelled."""
    import multiprocessing as mp

    from .spike2.parallel import encode_one, encode_probe, init_encode_worker
    log("Re-encoding %d sound(s) across %d process(es)..."
        % (len(edits), nworkers), "info")
    ctx = mp.get_context("spawn")
    pool = ctx.Pool(nworkers, initializer=init_encode_worker,
                    initargs=(gr_path, img_path, needed_params))
    patches, skipped, done_idx = {}, [], set()
    try:
        # Confirm a worker actually booted (a stalled/unguarded pool raises here
        # and the caller falls back to the serial path).
        pool.apply_async(encode_probe).get(timeout=300)
        done = 0
        # chunksize=1: tasks vary by >1000x in cost (sub-second SFX to 8-minute
        # songs), so hand them out one at a time -- batching would strand several
        # long songs on one worker while others idle.  edits arrive longest-first
        # (see _encode_cat0_sounds), so the big tracks start immediately.
        it = pool.imap_unordered(encode_one, edits, chunksize=1)
        while True:
            try:
                idx, body_off, body, valid = next(it)
            except StopIteration:
                break
            except Exception as e:
                # A worker died mid-run.  Keep everything finished so far and let
                # the caller re-encode only the leftovers in a single process.
                remaining = [(i, w) for (i, w) in edits if i not in done_idx]
                log("Parallel re-encode interrupted (%s); %d of %d sound(s) "
                    "already done, finishing the remaining %d in a single "
                    "process." % (e, len(done_idx), len(edits), len(remaining)),
                    "warning")
                pool.terminate()
                return patches, sorted(skipped), remaining
            done += 1
            done_idx.add(idx)
            if valid and body is not None:
                patches[body_off] = body
                log("Re-encoded idx %d." % idx, "info")
            elif body_off is not None:
                skipped.append(idx)
                log("idx %d: re-encode isn't bit-exact for this sound's codec "
                    "(skipped -- left unchanged)." % idx, "warning")
            if progress and (done % 4 == 0 or done == len(edits)):
                progress(10 + int(done * 65 / max(len(edits), 1)), 100,
                         "Re-encoding %d/%d" % (done, len(edits)))
            if cancel():
                pool.terminate()
                return None, None, None
        pool.close()
    finally:
        pool.join()
    return patches, sorted(skipped), []


def _restore_masterdir_consumed(gr_path, img_path, patches, log, progress=None,
                                cancel=None):
    """Keep each re-encoded body byte-identical to stock in the bytes the
    firmware's master-directory decode CONSUMES.

    ``MASTERDIR_DECODE`` is one continuous, forward-chained pass over every cat-0
    sound: it reads ~1 KB out of each sound's body into a running accumulator that
    sets the codec scale / predictor of that **and every later** sound.  The codec
    is many-to-one, so a re-encode that decodes bit-exact still produces *different*
    body bytes; those changed bytes desync the chain, so every later sound is then
    decoded with the wrong codec and plays as garbage — the machine reboots the
    instant any audio plays.  (Reverse-engineered + proven offline: restoring the
    consumed bytes drops downstream codec-param shifts from ~all sounds to zero.)

    Fix: after encoding, capture the exact body offsets the decode pass reads (via
    a memory-read hook over each modded sound's extent) and overwrite them with the
    original bytes, so the chain reads identical input.  The consumed bytes overlap
    real audio, so that scattered sub-window of the replaced sound reverts toward
    the original — acceptable for a call-out swap.  Mutates and returns *patches*
    (``{body_off: body}``); returns ``None`` if cancelled.
    """
    if not patches:
        return patches
    from unicorn import UC_HOOK_MEM_READ

    from .spike2 import emulator as EM
    from .spike2.emulator import Spike2Emu
    if cancel and cancel():
        return None
    if progress:
        progress(76, 100, "Preserving master-directory integrity...")
    log("Preserving master-directory forward-chain integrity "
        "(re-encode keeps the firmware's per-sound decode params valid)...",
        "info")
    reads = {off: set() for off in patches}     # body_off -> consumed file offsets

    def _mk(b0, e0, acc):
        def on_read(mu, access, addr, size, value, ud):
            o = addr - EM.DESC_BASE
            for k in range(size):
                if b0 <= o + k < e0:
                    acc.add(o + k)
        return on_read

    emu = Spike2Emu(gr_path, img_path)
    try:
        emu.boot()
        for off, body in patches.items():
            end = off + len(body)
            emu.mu.hook_add(UC_HOOK_MEM_READ, _mk(off, end, reads[off]),
                            begin=(EM.DESC_BASE + off) & ~0xfff,
                            end=((EM.DESC_BASE + end) + 0xfff) & ~0xfff)
        emu.derive_params()         # the real MASTERDIR_DECODE pass
        for off, body in patches.items():
            stock = bytes(emu.mm[off:off + len(body)])
            b = bytearray(body)
            for fo in reads[off]:
                rel = fo - off
                if 0 <= rel < len(b):
                    b[rel] = stock[rel]
            patches[off] = bytes(b)
            log("  idx@0x%x: preserved %d master-directory byte(s)."
                % (off, len(reads[off])), "info")
    finally:
        emu.close()
    return patches


def _assert_param_integrity(gr_path, img_path, patches, params, np, log,
                            work_dir):
    """Write-time safety net: apply *patches* to a temp ``image.bin`` and confirm
    the firmware's master-directory decode derives the **same** codec scale /
    predictor for every sound as the stock card.  A non-empty shift list means the
    forward chain is still broken (a card that would reboot on audio), so we raise
    rather than ship it.  Set ``PAD_STERN_SKIP_MASTERDIR_VERIFY=1`` to skip."""
    if not patches or os.environ.get("PAD_STERN_SKIP_MASTERDIR_VERIFY") == "1":
        return
    import shutil

    from .spike2.emulator import Spike2Emu
    tmp = os.path.join(work_dir, "image_verify.bin")
    shutil.copyfile(img_path, tmp)
    try:
        with open(tmp, "r+b") as f:
            for off, body in patches.items():
                f.seek(off)
                f.write(body)
        emu = Spike2Emu(gr_path, tmp)
        try:
            emu.boot()
            rows = emu.derive_params()
        finally:
            emu.close()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    stock = {p["idx"]: (p["scale"], p["pred16"]) for p in params}
    cur = {r["idx"]: (r["scale"], r["pred16"]) for r in rows}
    shifted = [i for i in stock if i in cur and stock[i] != cur[i]]
    if shifted:
        raise RuntimeError(
            "Master-directory integrity check FAILED: %d of %d sounds would "
            "decode with the wrong codec parameters (the card would reboot on "
            "audio). The re-encode could not preserve the firmware's "
            "forward-chain; aborting the write rather than producing a broken "
            "card." % (len(shifted), len(stock)))
    log("Master-directory integrity verified: all %d sounds keep valid decode "
        "parameters." % len(stock), "success")


def _encode_cat0_sounds(gr_path, img_path, params, audio_edits, np, log,
                        progress, cancel):
    """Re-encode every edited cat-0 sound to its body bytes — parallel across
    processes with a single-process fallback.  Returns ``({body_off: body},
    [skipped_idx])`` or ``(None, None)`` if cancelled."""
    byidx = {p["idx"]: p for p in params}
    for idx in sorted(set(audio_edits) - set(byidx)):
        log("idx %d not a known sound; skipping." % idx, "warning")
    # Longest sound first: re-encode time is ~linear in length and the songs
    # range from a fraction of a second to >8 minutes, so a long track is an
    # irreducible tail on a single worker.  Scheduling it first (with chunksize=1
    # below) keeps every worker busy and makes the wall-clock ≈ the longest
    # single song rather than worst-case load imbalance.  Tie-break on idx for a
    # deterministic order.
    edits = sorted(((idx, wav) for idx, wav in audio_edits.items()
                    if idx in byidx),
                   key=lambda iw: (-byidx[iw[0]].get("length", 0), iw[0]))
    if not edits:
        return {}, []

    nworkers = max(1, min((os.cpu_count() or 2) - 2, 8))
    nworkers = max(1, min(nworkers, len(edits)))
    patches, skipped, remaining = {}, [], edits
    if not _FORCE_SERIAL_ENCODE and nworkers > 1 and not cancel():
        try:
            needed = [byidx[idx] for idx, _ in edits]
            patches, skipped, remaining = _encode_cat0_parallel(
                gr_path, img_path, needed, edits, nworkers, np, log, progress,
                cancel)
            if patches is None:
                return None, None
        except Exception as e:
            # The pool never started -- fall back to a full single-process pass.
            log("Parallel re-encode unavailable (%s); using a single process."
                % e, "warning")
            patches, skipped, remaining = {}, [], edits
    # Finish any edits the parallel path didn't complete (all of them if it was
    # skipped/unavailable; just the leftovers if a worker died mid-run).  Keeping
    # the parallel results avoids re-encoding everything serially on a partial
    # failure -- the slow path that made a quick job take hours.
    if remaining:
        sp, sk = _encode_cat0_serial(
            gr_path, img_path, byidx, remaining, np, log, progress, cancel)
        if sp is None:
            return None, None
        patches.update(sp)
        skipped.extend(sk)
    skipped = sorted(set(skipped))
    if skipped:
        log("%d sound(s) skipped (re-encode unsupported for their codec): %s"
            % (len(skipped), ", ".join(map(str, skipped))), "warning")
    return patches, skipped


_MUSIC_NAME_RE = re.compile(r"music_cat(\d+)_(\d+)", re.IGNORECASE)


def _derive_encode_bank(gr_path, img_path, rev, cid, sc_path, edits, np):
    """Re-encode one bank's edited songs on a FRESH CatEmu (deriving several
    banks on one emu grinds the loader — see ``spike2/category.py``).  *edits* =
    ``[(idx, wav_path), ...]`` for this bank.  Returns ``(patches, skipped)``
    where ``patches`` = ``[(cid, idx, body_off, body), ...]`` (the parent maps
    cid back to its ext4 inode) and ``skipped`` = ``[(cid, idx), ...]``.
    Bit-identical to the serial inner loop, just per-bank so it parallelises."""
    from .spike2.category import CatEmu
    from .spike2.codec import GenRecover, StereoRecover
    patches, skipped = [], []
    emu = CatEmu(gr_path, img_path)
    rows = []
    try:
        emu.boot()
        emu.set_category_file(sc_path)
        rows = emu._derive_cat(cid, rev) or []
        byidx = {r["idx"]: r for r in rows}
        emu.mm = emu._mm_cat          # body source = this bank
        gr = sr = None
        for idx, wav in sorted(edits):
            p = byidx.get(idx)
            if p is None:                 # not a sound in that bank
                skipped.append((cid, idx))
                continue
            if p["chan"] == 2:
                sr = sr or StereoRecover(emu)
            else:
                gr = gr or GenRecover(emu)
            if not _recovery_valid(emu, gr, sr, p, np):
                skipped.append((cid, idx))
                continue
            body = (_encode_stereo(emu, sr, p, wav, np) if p["chan"] == 2
                    else _encode_mono(emu, gr, p, wav, np))
            patches.append((cid, idx, p["body_off"], bytes(body)))
    finally:
        emu.close()
    # The bank's MASTERDIR_DECODE is the same forward-chained pass as cat-0
    # (just over the bank file), so a re-encoded song desyncs the codec params
    # of later songs IN THAT BANK.  Restore the masterdir-consumed bytes and
    # verify the chain stays intact (else the music would reboot the machine).
    if patches and os.environ.get("PAD_STERN_SKIP_MASTERDIR_FIX") != "1":
        patches = _restore_bank_consumed(gr_path, img_path, rev, cid, sc_path,
                                         patches)
        _assert_bank_integrity(gr_path, img_path, rev, cid, sc_path, patches,
                               rows)
    return patches, skipped


def _restore_bank_consumed(gr_path, img_path, rev, cid, sc_path, patches):
    """Bank twin of :func:`_restore_masterdir_consumed`: keep each re-encoded
    song's masterdir-consumed bytes identical to stock so the bank's forward
    chain reads the same input.  *patches* = ``[(cid, idx, body_off, body), ...]``;
    returns the same with each body's consumed bytes restored."""
    from unicorn import UC_HOOK_MEM_READ

    from .spike2.category import DESC2, CatEmu
    reads = {bo: set() for (_c, _i, bo, _b) in patches}

    def _mk(b0, e0, acc):
        def on_read(mu, access, addr, size, value, ud):
            o = addr - DESC2
            for k in range(size):
                if b0 <= o + k < e0:
                    acc.add(o + k)
        return on_read

    emu = CatEmu(gr_path, img_path)
    try:
        emu.boot()
        emu.set_category_file(sc_path)
        for (_c, _i, bo, body) in patches:
            emu.mu.hook_add(UC_HOOK_MEM_READ, _mk(bo, bo + len(body), reads[bo]),
                            begin=(DESC2 + bo) & ~0xfff,
                            end=((DESC2 + bo + len(body)) + 0xfff) & ~0xfff)
        emu._derive_cat(cid, rev)
        out = []
        for (c, idx, bo, body) in patches:
            stock = bytes(emu._mm_cat[bo:bo + len(body)])
            b = bytearray(body)
            for fo in reads[bo]:
                rel = fo - bo
                if 0 <= rel < len(b):
                    b[rel] = stock[rel]
            out.append((c, idx, bo, bytes(b)))
        return out
    finally:
        emu.close()


def _assert_bank_integrity(gr_path, img_path, rev, cid, sc_path, patches,
                           stock_rows):
    """Bank twin of :func:`_assert_param_integrity`: apply *patches* to a temp
    copy of the bank and confirm every song still derives the same codec params,
    else raise (a card that would reboot on that bank's music).  Skipped by
    ``PAD_STERN_SKIP_MASTERDIR_VERIFY=1``."""
    if not patches or os.environ.get("PAD_STERN_SKIP_MASTERDIR_VERIFY") == "1":
        return
    import shutil

    from .spike2.category import CatEmu
    fd, tmp = tempfile.mkstemp(suffix=".scbin")
    os.close(fd)
    try:
        shutil.copyfile(sc_path, tmp)
        with open(tmp, "r+b") as f:
            for (_c, _i, bo, body) in patches:
                f.seek(bo)
                f.write(body)
        emu = CatEmu(gr_path, img_path)
        try:
            emu.boot()
            emu.set_category_file(tmp)
            rows = emu._derive_cat(cid, rev) or []
        finally:
            emu.close()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    def _key(r):
        return (r["scale"], bytes(r["_rawobj"][0x14:0x1e]))
    stock = {r["idx"]: _key(r) for r in stock_rows}
    cur = {r["idx"]: _key(r) for r in rows}
    shifted = [i for i in stock if i in cur and stock[i] != cur[i]]
    if shifted:
        raise RuntimeError(
            "Music bank %d integrity check FAILED: %d of %d songs would decode "
            "with the wrong codec parameters (the card would reboot on that "
            "bank's music); aborting the write." % (cid, len(shifted), len(stock)))


def _bank_encode_worker(args):
    """One task = re-encode a single bank's edited songs on a fresh emu.
    Top-level so it pickles across the spawn boundary."""
    gr_path, img_path, rev, cid, sc_path, edits = args
    import numpy as np
    try:
        return _derive_encode_bank(gr_path, img_path, rev, cid, sc_path, edits,
                                   np)
    except Exception:
        return ([], [(cid, idx) for idx, _ in edits])


def _run_bank_encode(tasks, log, progress, cancel):
    """Run the per-bank encode *tasks* — one process per bank (fresh emu each)
    with a single-process fallback.  Returns ``[(patches, skipped), ...]`` per
    bank, or ``None`` if cancelled."""
    nworkers = max(1, min((os.cpu_count() or 2) - 2, 8))
    nworkers = max(1, min(nworkers, len(tasks)))
    if (not _FORCE_SERIAL_ENCODE and nworkers > 1 and len(tasks) > 1
            and not cancel()):
        try:
            import multiprocessing as mp
            log("Re-encoding %d music bank(s) across %d process(es)..."
                % (len(tasks), nworkers), "info")
            ctx = mp.get_context("spawn")
            out, done = [], 0
            # maxtasksperchild=1: a fresh process per bank reclaims the large
            # unicorn mappings and never inherits another bank's state.
            with ctx.Pool(nworkers, maxtasksperchild=1) as pool:
                for res in pool.imap_unordered(_bank_encode_worker, tasks):
                    out.append(res)
                    done += 1
                    if progress:
                        progress(80 + int(done * 15 / max(len(tasks), 1)), 100,
                                 "Re-encoding music bank %d/%d"
                                 % (done, len(tasks)))
                    if cancel():
                        pool.terminate()
                        return None
            return out
        except Exception as e:
            log("Parallel music re-encode unavailable (%s); using a single "
                "process." % e, "warning")
    import numpy as np
    out = []
    for n, t in enumerate(tasks):
        if cancel():
            return None
        if progress:
            progress(80 + int(n * 15 / max(len(tasks), 1)), 100,
                     "Re-encoding music bank %d/%d" % (n + 1, len(tasks)))
        gr_path, img_path, rev, cid, sc_path, edits = t
        try:
            out.append(_derive_encode_bank(gr_path, img_path, rev, cid, sc_path,
                                           edits, np))
        except Exception as e:
            log("music_cat%02d: re-encode failed (%s); skipped." % (cid, e),
                "warning")
            out.append(([], [(cid, idx) for idx, _ in edits]))
    return out


def _compute_music_patches(reader, gr_path, img_path, music_edits, work, log,
                           progress, cancel, np):
    """Re-encode each edited per-song music bank back into its ``image-scNN.bin``
    (size-neutral) and return ``[(sc_node, body_off, body_bytes), ...]`` for the
    songs that re-encode bit-exact.

    Each song's body lives in a SEPARATE bank file (so every patch carries its
    own ext4 inode, not ``image.bin``'s), and each bank is derived on its own
    fresh :class:`CatEmu` (deriving several banks on one emu accumulates state
    that grinds the loader).  Because a fresh emu per bank is required anyway,
    the banks fan across processes — one task per bank — for a big speedup when
    many songs changed (Metallica = 24 banks).  A song whose re-encode isn't
    bit-exact (``_recovery_valid``) is skipped, never written blind."""
    from .spike2.category import _find_revalidate, read_category_id

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
    for cid in sorted(set(by_cat) - set(sc)):
        log("music_cat%02d: bank not on the card; %d edit(s) skipped."
            % (cid, len(by_cat[cid])), "warning")
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

    # one task per bank; biggest banks first so a long song isn't pure tail
    # latency (bank file size ≈ decoded length).
    cids = sorted(
        (c for c in by_cat if c in sc),
        key=lambda c: (os.path.getsize(sc[c][1])
                       if os.path.exists(sc[c][1]) else 0),
        reverse=True)
    tasks = [(gr_path, img_path, rev, c, sc[c][1], by_cat[c]) for c in cids]
    results = _run_bank_encode(tasks, log, progress, cancel)
    if results is None:
        return []

    patches, skipped = [], []
    for bank_patches, bank_skipped in results:
        for (cid, idx, body_off, body) in bank_patches:
            patches.append((sc[cid][0], body_off, body))
            log("Re-encoded music_cat%02d_%04d." % (cid, idx), "info")
        skipped.extend(bank_skipped)
    if skipped:
        log("%d music song(s) skipped (re-encode not bit-exact or not in the "
            "bank)." % len(skipped), "warning")
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
