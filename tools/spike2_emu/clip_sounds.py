#!/usr/bin/env python3
"""clip_sounds.py - which sounds a Spike 2 card's game code plays with each in-game clip.

    clip_sounds.py <card.raw> [--project <extract dir>] [--out <file.tsv>] [--located]
                   [--resolve]

Reads the card read-only (``plugins/stern/explorer.CardImage``, no mount) and prints how the
sound functions were found, then each clip's sounds best first (``plugins/stern/clip_sounds.py``
says what ``record`` / ``next`` / ``name`` / ``function`` mean; the Video tab shows the first
three, the ones the emulator census proved). The clips are the ones the
project's ``video/manifest.txt`` names when ``--project`` is given (the Video tab's), else every
clip of every scene bank under the title's ``assets/lcd``.

  --project   also name each sound by the project's ``sound_requests.tsv`` and audio files
  --out       write the whole table as TSV
  --located   ignore the build's port and find the sound functions from the request table, as
              a build without a port does (run both ways to compare)
  --resolve   map requests to idx records here, on the codec emulator (the card's firmware and
              image.bin are copied to a temp dir; the params derive is the extract's, cached),
              for a project extracted before Extract wrote sound_requests.tsv

To check a pairing on another build, play the clip's mode in the emulator with every request
logged (``sdk/sound_census.c``, or stock_probe's ``award`` hooks on the sound worker and inside
``clip_play``: PAD-455's census) and look for the request within a second of the clip.
"""
import argparse
import os
import sys
import tempfile
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, REPO)

from pinball_decryptor.plugins.stern import clip_modes as CM  # noqa: E402
from pinball_decryptor.plugins.stern import clip_sounds as CS  # noqa: E402
from pinball_decryptor.plugins.stern import video_bank as VB  # noqa: E402

T0 = time.time()


def log(msg, *_a, **_k):
    print("%6.1fs %s" % (time.time() - T0, msg))
    sys.stdout.flush()


def _banks(img, part, game, rows):
    """``{clip name: [scene dir, path]}`` of the project's banks, else of every scene.radium
    under ``/<game>/assets/lcd``."""
    dirs = CM._bank_dirs(rows) if rows else []
    if not dirs:
        todo = ["/%s/assets/lcd" % game]
        while todo:
            d = todo.pop()
            try:
                ents = img.list_dir(part, d)
            except (OSError, ValueError):
                continue
            for e in ents:
                if e.is_dir:
                    todo.append(d + "/" + e.name)
                elif e.name == "scene.radium":
                    dirs.append(d)
    out = {}
    for d in dirs:
        try:
            data = img.preview(part, "%s/scene.radium" % d, cap=64 << 20)
            bank = VB.parse(data) if data else None
        except (OSError, ValueError, VB.VideoBankError):
            bank = None
        for c in (bank.library.entries if bank else ()):
            out.setdefault(c.name, [d, c.path])
    return out


def _resolve(card, lists):
    """``{request: [idx]}`` on the codec emulator, from a copy of the card's firmware."""
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern.formats import linux_partitions
    from pinball_decryptor.plugins.stern.spike2.emulator import Spike2Emu
    work = tempfile.mkdtemp(prefix="clip_sounds_")
    with open(card, "rb") as f:
        gr, img, _r, _fw, _im = E._extract_inputs(f, linux_partitions(card), work, log)
    emu = Spike2Emu(gr, img)
    try:
        emu.boot()
        params = E._load_or_derive_params(emu, gr, img, log, None)
        with open(gr, "rb") as f:
            fw = f.read()
        return CS.resolve_requests(emu, params, lists, fw)
    finally:
        emu.close()


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("card")
    ap.add_argument("--project")
    ap.add_argument("--out")
    ap.add_argument("--located", action="store_true")
    ap.add_argument("--resolve", action="store_true")
    a = ap.parse_args(argv)
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, version, part = card_title(a.card)
    log("%s %s (partition %d)" % (game, version, part))
    rows = CM.manifest_rows(a.project) if a.project else {}
    with CardImage(a.card) as img:
        elf = img.preview(part, "/%s/game" % game, cap=256 << 20)
        fragments = CS.card_fragments(img, part, game)
        banks = _banks(img, part, game, rows)
    if not elf:
        raise SystemExit("the card's game program could not be read")
    names = sorted(banks)
    log("%d clips in %d banks, %s sound fragments" % (
        len(names), len({v[0] for v in banks.values()}), fragments))
    ctx = {}
    reading = CM.analyse(elf, names, ctx=ctx)
    log("clip modes: %d named clips, %d modes" % (len(reading.refs), len(reading.labels)))
    sr = CS.analyse(elf, names, fragments, game="" if a.located else game,
                    version="" if a.located else version, refs=reading.refs or None, ctx=ctx)
    if sr.note:
        log("note: %s" % sr.note)
    log("sound functions: %s%s, %d requests, %d constant calls" % (
        sr.origin or "none", " (%s)" % os.path.basename(sr.port) if sr.port else "", sr.count,
        sr.calls))
    for va, (name, reg, sites, const, reqs) in sorted(sr.entries.items()):
        log("  0x%08x  r%d  %-28s calls %5d  constant %5d  request ids %5d"
            % (va, reg, name, sites, const, reqs))

    req = CS.read_requests(a.project) if a.project else {}
    audio = CS.audio_files(a.project) if a.project else {}
    idx_of = {r: v["idx"] for r, v in req.items()}
    if a.resolve:
        count, lists, _t, _r = CS.request_table(elf, fragments)
        log("resolving %d requests on the codec emulator..." % count)
        idx_of = _resolve(a.card, lists)
        log("%d requests resolve to a record" % len(idx_of))

    by_how = {h: 0 for h in CS.HOWS}
    lines = []
    for clip in names:
        for s in sr.sounds_of(clip):
            by_how[s["how"]] += 1
            idx = idx_of.get(s["request"], [])
            files = [os.path.basename(audio[i]) for i in idx if i in audio]
            lines.append([clip, s["how"], "%d" % s["gap"], "%d" % s["request"], s["name"],
                          ",".join("%04d" % i for i in idx), " | ".join(files),
                          ",".join("%d" % x for x in s["sids"]), "0x%08x" % s["at"]])
    paired = len(sr.pairs)
    log("%d of %d clips have sounds: %s" % (
        paired, len(names), ", ".join("%s %d" % (h, n) for h, n in by_how.items())))
    for ln in lines:
        print("  %-40s %-8s %4s  req %5s  %-32s %s" % (ln[0][:40], ln[1], ln[2], ln[3],
                                                      ln[4][:32], ln[6] or ln[5]))
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write("clip\thow\tgap\trequest\tsound_test\tidx\tfiles\tsids\tcall\n")
            for ln in lines:
                f.write("\t".join(ln) + "\n")
        log("wrote %s" % a.out)


if __name__ == "__main__":
    main(sys.argv[1:])
