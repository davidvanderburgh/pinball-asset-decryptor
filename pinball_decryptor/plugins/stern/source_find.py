"""Which of a user's own files each replaced clip on a built Spike 2 card is.

The card half of :mod:`core.source_match`: it works out which clips on a
built card differ from the stock card, names each one by the project's slot
(``video/<name>`` from the extract's ``video/manifest.txt``), reads it off the
image, and hands the lot to the matcher with the files found under the user's
folders.

A modder who picked several hundred clips by hand from files named nothing
like the slots has no other way back from a card to the files behind it; with
the answers recorded as the project's replacements, the next Write re-encodes
every clip from the file it came from -- at full quality, when the Video tab's
"Best quality" is on -- instead of from the lossy copy on the card.
"""

import os
import shutil
import tempfile
import threading

from ...core import source_match, video_quality
from ...core.longpath import ext as _lp


def _manifest_map(assets_dir):
    """``{card path: slot rel}`` from the project's ``video/manifest.txt``."""
    from .engine import _read_video_manifest
    vid_dir = os.path.join(assets_dir, "video")
    return {cpath: "video/" + name
            for name, cpath in _read_video_manifest(vid_dir).items()}


def _open(image_path):
    from .engine import _linux_partitions, _locate, find_card_videos
    f = open(_lp(image_path), "rb")
    try:
        reader, _fw, _img = _locate(f, _linux_partitions(image_path))
        vids, _radiums = find_card_videos(reader)
    except Exception:
        f.close()
        raise
    return f, reader, {path: node for path, node, _brand in vids}


def replaced_clips(card, stock, cancel=None):
    """``(reader, file, [(card path, node)])`` for every clip on *card* whose
    bytes differ from the same path on *stock* (or which *stock* lacks).  The
    caller closes *file*."""
    cancel = cancel or (lambda: False)
    sf, sreader, snodes = _open(stock)
    try:
        cf, creader, cnodes = _open(card)
        out = []
        for path in sorted(cnodes):
            if cancel():
                raise source_match.Cancelled()
            node = cnodes[path]
            sn = snodes.get(path)
            if sn is not None and sn["size"] == node["size"]:
                # A same-size clip is only a replacement if its bytes say so.
                if (sreader.read_file_bytes(sn)
                        == creader.read_file_bytes(node)):
                    continue
            out.append((path, node))
        return creader, cf, out
    finally:
        sf.close()


def find_video_sources(card, stock, assets_dir, roots, cache_dir=None,
                       log=None, progress=None, cancel=None):
    """Match every replaced clip on *card* to a file under *roots*.

    Returns a dict:

    ``matches``   ``{slot rel: core.source_match.Match}``
    ``clips``     ``{slot rel: core.source_match.Clip}`` (card clip facts)
    ``unnamed``   card paths replaced on *card* that this project has no slot
                  for (a different title or version than the extract)
    ``sources``   how many candidate files were found under *roots*
    """
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)
    progress = progress or (lambda *a: None)
    names = _manifest_map(assets_dir)
    if not names:
        raise ValueError(
            "This project has no extracted videos to name the clips by. "
            "Extract the card's videos into the project first.")

    log("Comparing %s with the stock card..." % os.path.basename(card), "info")
    reader, cf, replaced = replaced_clips(card, stock, cancel)
    tmp = tempfile.mkdtemp(prefix="pad_srcfind_")
    try:
        clips, nodes, unnamed = [], {}, []
        for path, node in replaced:
            rel = names.get(path)
            if rel is None:
                unnamed.append(path)
                continue
            q = video_quality.read_clip_quality(
                lambda o, n, _nd=node: reader.read_range(_nd, o, n),
                node["size"], card_path=path)
            clips.append(source_match.Clip(
                key=rel, path="", duration=q.duration,
                width=q.width, height=q.height, fps=q.fps,
                bitrate=q.bitrate))
            nodes[rel] = node
        log("%d clip(s) on that card are replacements%s."
            % (len(clips), (" (%d more this project has no slot for)"
                            % len(unnamed)) if unnamed else ""), "info")
        if not clips:
            return {"matches": {}, "clips": {}, "unnamed": unnamed,
                    "sources": 0}

        log("Looking for video files under %s..."
            % "; ".join(roots), "info")
        paths = []
        for root in roots:
            paths += source_match.list_video_files(root, cancel)
        # Never offer the project's own slot files: they are the stock clips,
        # or the conversions a Write left there -- what this search is
        # getting away from.  Anything else in the project folder is fair
        # game (a real TMNT project keeps its sources in .assets/).
        own = os.path.normcase(os.path.join(os.path.abspath(assets_dir),
                                            "video")) + os.sep
        paths = [p for p in paths
                 if not os.path.normcase(os.path.abspath(p)).startswith(own)]
        progress(0, 0, "Checking %d file(s)..." % len(paths))
        sources = source_match.probe_sources(paths, progress, cancel)
        log("%d video file(s) to compare against." % len(sources), "info")

        read_lock = threading.Lock()

        def clip_fp(clip, sample_fps):
            node = nodes[clip.key]
            out = os.path.join(tmp, "%s_%s.mp4" % (abs(hash(clip.key)),
                                                   threading.get_ident()))
            with read_lock:          # one file handle: reads take turns
                reader.extract_file(node, out)
            try:
                return source_match.fingerprint(out, clip.width, clip.height,
                                                cancel=cancel,
                                                sample_fps=sample_fps)
            finally:
                try:
                    os.remove(out)
                except OSError:
                    pass

        matches = source_match.find_sources(
            clips, sources, clip_fp,
            cache=source_match.FingerprintCache(cache_dir),
            progress=progress, cancel=cancel)
        found = sum(1 for m in matches.values() if m.best is not None)
        sure = sum(1 for m in matches.values() if m.sure)
        log("Found the source of %d of %d clip(s) (%d certain, %d worth a "
            "look)." % (found, len(clips), sure, found - sure),
            "success" if found else "warning")
        return {"matches": matches,
                "clips": {c.key: c for c in clips},
                "unnamed": unnamed, "sources": len(sources)}
    finally:
        cf.close()
        shutil.rmtree(tmp, ignore_errors=True)
