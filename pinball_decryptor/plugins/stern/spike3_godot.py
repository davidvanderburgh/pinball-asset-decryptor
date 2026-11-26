"""The Godot game's pictures and clips on a Spike 3 card: Extract and Write
(PAD-1621).

Pokemon (LE and Pro) draws its pokedex, its battles and its arena screens
with a Godot 4 game, and every picture and clip of those is in one resource
pack, ``<game>/assets/godot/main.pck`` (:mod:`.godot_pck`), not in the Spike 2
asset tree the rest of the extract reads.  Here:

* **Extract** puts each texture out as a PNG under ``images/godot/``, named
  from its source in the Godot project (``images/godot/scenes/pokedex_cine/
  gfx/001_BULBASAUR.png``), and each clip as itself under ``video/godot/``.
  ``images/godot/manifest.txt`` and ``video/godot/manifest.txt`` give each
  file's pack (card path) and its entry in the pack, so the Spike 2 write
  core, which reads ``images/manifest.txt`` / ``video/manifest.txt``, never
  takes them for files of its own.
* **Write** rebuilds a pack whose files were changed: an edited PNG becomes
  the texture again (its size, its format, every mip level), a clip goes in
  as it is, and the new pack goes onto the card whole
  (:func:`.spike3_write.write_card`'s grown files, its SD-validation record
  refreshed with the rest).
"""

from __future__ import annotations

import os

from . import godot_pck as G

IMAGE_DIR = ("images", "godot")
VIDEO_DIR = ("video", "godot")
MANIFEST = "manifest.txt"
#: enough of a file to tell a pack
_HEAD = 0x60


def card_packs(reader):
    """``[(card path, node), ...]`` for every Godot pack on the volume."""
    out = []
    for path, _ino, node in reader.iter_regular_files(min_size=_HEAD,
                                                      max_depth=8):
        if path.lower().endswith(".pck") \
                and G.is_pack(reader.read_range(node, 0, 4)):
            out.append((path, node))
    return out


def node_reader(reader, node):
    return lambda off, n: reader.read_range(node, off, n)


def _picture_name(source):
    """The PNG a texture's source comes out as (its own name for a PNG)."""
    stem, ext = os.path.splitext(source)
    return source if ext.lower() == ".png" else stem + ext.replace(".", "_") + ".png"


def extract_packs(packs, output_dir, want_images=True, want_video=True,
                  log=None, progress=None, cancel=None):
    """Every picture and clip of the Godot *packs* (``[(card path, read)]``,
    ``read(offset, n)`` reading the pack) into the project.  Returns
    ``(pictures, clips)``."""
    log = log or (lambda *a, **k: None)
    progress = progress or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    n_img = n_vid = 0
    img_rows, vid_rows = [], []
    for card_path, read in packs:
        if not G.is_pack(read(0, 4)):
            continue
        try:
            pack = G.parse(read)
        except G.PckError as e:
            log("Godot pack %s: %s; its pictures and clips are not "
                "extracted." % (card_path, e), "warning")
            continue
        sub = () if len(packs) == 1 else (
            os.path.splitext(os.path.basename(card_path))[0],)
        jobs = []
        if want_images:
            for entry, source in sorted(G.texture_sources(pack, read).items(),
                                        key=lambda kv: kv[1]):
                jobs.append(("img", entry, source))
        if want_video:
            for e in pack.entries:
                if e.path.lower().endswith(G.VIDEO_EXTS) and G.readable(e):
                    jobs.append(("vid", e.path, e.path))
        if not jobs:
            continue
        log("Godot pack %s: %d picture(s) and clip(s) to extract..."
            % (card_path, len(jobs)), "info")
        skipped = 0
        taken = set()
        for i, (kind, entry, source) in enumerate(jobs):
            if cancel():
                return n_img, n_vid
            e = pack.by_path[entry]
            if kind == "img":
                rel = "/".join(IMAGE_DIR[1:] + sub) + "/" + _picture_name(source)
                if rel.lower() in taken:
                    stem, ext = os.path.splitext(rel)
                    rel = "%s_%s%s" % (stem, os.path.basename(entry)[-13:-5], ext)
                taken.add(rel.lower())
                try:
                    im = G.decode_texture(read(e.offset, e.size))
                except Exception:                          # noqa: BLE001
                    im = None
                if im is None:
                    skipped += 1
                    continue
                out = os.path.join(output_dir, IMAGE_DIR[0], *rel.split("/"))
                os.makedirs(os.path.dirname(out), exist_ok=True)
                im.save(out, "PNG", compress_level=1)
                img_rows.append((rel, card_path, entry, im.width, im.height))
                n_img += 1
            else:
                rel = "/".join(VIDEO_DIR[1:] + sub) + "/" + source
                out = os.path.join(output_dir, VIDEO_DIR[0], *rel.split("/"))
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with open(out, "wb") as f:
                    off, left = e.offset, e.size
                    while left:
                        b = read(off, min(left, 4 << 20))
                        if not b:
                            break
                        f.write(b)
                        off += len(b)
                        left -= len(b)
                vid_rows.append((rel, card_path, entry))
                n_vid += 1
            progress(i + 1, len(jobs), "Godot %d/%d" % (i + 1, len(jobs)))
        if skipped:
            log("Godot pack %s: %d texture(s) are not pictures PAD can "
                "rebuild (GPU-compressed), left out." % (card_path, skipped),
                "info")
    _write_manifest(output_dir, IMAGE_DIR, img_rows,
                    "# images/<file>\tpack on the card\tits entry\twidth\theight")
    _write_manifest(output_dir, VIDEO_DIR, vid_rows,
                    "# video/<file>\tpack on the card\tits entry")
    if n_img or n_vid:
        log("Extracted the Godot game's %d picture(s) and %d clip(s) "
            "(images/godot, video/godot)." % (n_img, n_vid), "success")
    return n_img, n_vid


def _write_manifest(output_dir, where, rows, header):
    path = os.path.join(output_dir, *where, MANIFEST)
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(header + "\n")
        for r in rows:
            f.write("\t".join(str(c) for c in r) + "\n")


def read_manifest(assets_dir, where):
    """The rows of a Godot manifest: ``[(rel under images/ or video/, pack,
    entry), ...]``."""
    path = os.path.join(assets_dir, *where, MANIFEST)
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if len(cols) >= 3:
                    out.append((cols[0], cols[1], cols[2]))
    except OSError:
        pass
    return out


def changed(assets_dir, baseline):
    """``{pack card path: [(kind, entry, file), ...]}`` for the project's
    Godot pictures and clips that differ from the Extract baseline."""
    from .engine import _scan_md5
    out = {}
    for kind, where in (("img", IMAGE_DIR), ("vid", VIDEO_DIR)):
        for rel, pack, entry in read_manifest(assets_dir, where):
            path = os.path.join(assets_dir, where[0], *rel.split("/"))
            if not os.path.isfile(path):
                continue
            base = baseline.get(where[0] + "/" + rel)
            if base is not None and _scan_md5(assets_dir, path) == base:
                continue
            out.setdefault(pack, []).append((kind, entry, path))
    return out


class Plan:
    def __init__(self):
        self.jobs = []          # [(card path relative, staged pack)]
        self.n_image = 0
        self.n_video = 0


def plan_write(assets_dir, reader, baseline, work_dir, log, cancel=None):
    """The rebuilt packs a Write puts onto the card, or ``None`` when no
    Godot picture or clip changed."""
    from PIL import Image
    from .spike3_extract import _node_at
    cancel = cancel or (lambda: False)
    todo = changed(assets_dir, baseline)
    if not todo:
        return None
    plan = Plan()
    os.makedirs(work_dir, exist_ok=True)
    for card_path, items in sorted(todo.items()):
        node = _node_at(reader, card_path)
        if node is None:
            raise G.PckError("the card has no %s" % card_path)
        read = node_reader(reader, node)
        pack = G.parse(read)
        subs = {}
        resized = 0
        for kind, entry, path in items:
            if cancel():
                return None
            e = pack.by_path.get(entry)
            if e is None:
                raise G.PckError("%s has no %s" % (card_path, entry))
            if kind == "img":
                orig = read(e.offset, e.size)
                with Image.open(path) as im:
                    im.load()
                    tex = G.Texture(orig)
                    if im.size != (tex.width, tex.height):
                        resized += 1
                    subs[entry] = G.encode_texture(im, orig)
                plan.n_image += 1
            else:
                with open(path, "rb") as f:
                    subs[entry] = f.read()
                plan.n_video += 1
        staged = os.path.join(work_dir, "godot_%d_%s" % (
            len(plan.jobs), os.path.basename(card_path)))
        with open(staged, "wb") as f:
            G.rewrite(pack, read, f, subs)
        log("Godot pack %s rebuilt with %d changed picture(s) and clip(s)%s."
            % (card_path, len(subs),
               (" (%d picture(s) scaled to the size of the one they replace)"
                % resized) if resized else ""), "info")
        plan.jobs.append((card_path.lstrip("/"), staged))
    return plan

