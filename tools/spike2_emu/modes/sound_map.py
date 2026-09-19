#!/usr/bin/env python3
"""sound_map.py - every sound REQUEST of one game build, down to the records it plays (item 150).

    sound_map.py <game ELF> <image.bin> <out dir> <tag> [--args <armxref args output>]...

A mode's own sound rides on a stock request (item 130): an appended record, and that
request's descriptor re-pointed at it. The request has to be one the game will not play
in the meantime. This maps every request so the candidates can be chosen at the desk and
then checked with the census (sdk/sound_census.c):

    request -> its sid chain         (the ELF's 20-byte request table, sound_requests.py)
    sid -> descriptor op11 payloads  (engine._descriptor_sites, one emulator boot)
    payload -> play key -> record    (under BOTH descriptor key masks known: 0xE0001FFF, which
                                      the engine carries, and 0xFC0003FF; the build's own is
                                      the one under which the payloads name real records -
                                      measured 2628/2628 vs 43 on Premium 1.16, 2615/2615
                                      vs 44 the other way round on Pro 1.15)

and, per request: whether its record(s) are named by any other request, the record's
channels and stock length, every constant call site (armxref.py args output on the sound
entry points, parsed here), and the Sound Test name (the menu's node id IS the request id:
both index the same sid-list block from its end - checked below, list for list).

Writes <out>/<tag>_requests.tsv and <tag>_carriers.tsv (the provisional safe list:
single sid, one record under the build's mask, a record and sid no other request names, no
constant call site; mono and stereo listed apart). The derive is cached as <out>/<tag>_params.pkl.
"""
import argparse
import collections
import os
import pickle
import re
import struct
import sys
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, REPO)

from pinball_decryptor.plugins.stern import engine as E  # noqa: E402
from pinball_decryptor.plugins.stern.info import container_counts  # noqa: E402
from pinball_decryptor.plugins.stern.spike2 import sfx_names as SN  # noqa: E402
from pinball_decryptor.plugins.stern.spike2 import sound_requests as SR  # noqa: E402
from pinball_decryptor.plugins.stern.spike2.elf import parse_elf  # noqa: E402

MASKS = {"lz": 0xE0001FFF, "gz": 0xFC0003FF}
T0 = time.time()


def log(msg, *_a, **_k):
    print("%7.1fs %s" % (time.time() - T0, msg))
    sys.stdout.flush()


def play_key(payload8, sid, mask):
    w1, w2 = struct.unpack("<II", payload8)
    return struct.pack("<II", w1, (w2 & mask) | (((sid >> 16) << 13) & 0xFFFFFFFF))


def request_table(fw, fragments):
    count, table = SR.locate_sound_requests(fw, fragments)
    if count is None:
        raise SystemExit("no request table in this ELF")
    segs, _r = parse_elf(fw)

    def va2off(va):
        for vaddr, foff, filesz, _m in segs:
            if vaddr <= va < vaddr + filesz:
                return foff + va - vaddr
        return None

    end = table + count * 20
    reqs = []
    for req in range(count):
        words = struct.unpack_from("<5I", fw, table + req * 20)
        sids = []
        # the sid list is the field that points past the record array (sound_requests.py)
        for w in words:
            o = va2off(w) if w else None
            if o is None or o < end:
                continue
            for i in range(256):
                (s,) = struct.unpack_from("<I", fw, o + 4 * i)
                if s == 0:
                    break
                sids.append(s)
            break
        reqs.append((words, sids))
    return reqs, table


def menu_by_request(fw, reqs):
    """{request: Sound Test name}, and how many menu entries agreed list for list."""
    t = SN._walk_menu_table(fw)
    if t is None:
        return {}, 0, 0
    lists, nl = t["lists"], len(t["lists"])
    out, agree, total = {}, 0, 0
    for p, name in enumerate(t["names"]):
        if not SN._is_sound_entry(name):
            continue
        nid = t["node_ids"].get(p)
        if nid is None:
            continue
        li = (nl - 1) - nid
        if not 0 <= li < nl or nid >= len(reqs):
            continue
        total += 1
        if lists[li] == reqs[nid][1]:
            agree += 1
            out[nid] = name
    return out, agree, total


ARGS_HEAD = re.compile(r"^0x([0-9a-f]+)\b.*:\s*(\d+) call site")
ARGS_LINE = re.compile(r"^\s+(bl|b)\s+0x([0-9a-f]+)\s+fn\s+(\S+).*?r0=(\S+)")


def const_calls(paths):
    """{req: [(entry, call site)]} from armxref.py args output (its header FOLLOWS its list)."""
    out = collections.defaultdict(list)
    for path in paths or ():
        pending = []
        for line in open(path, encoding="utf-8", errors="replace"):
            m = ARGS_LINE.match(line)
            if m:
                pending.append((int(m.group(2), 16), m.group(4)))
                continue
            h = ARGS_HEAD.match(line)
            if h:
                entry = int(h.group(1), 16)
                for site, r0 in pending:
                    if r0.startswith("0x"):
                        out[int(r0, 16)].append((entry, site))
                pending = []
    return out


def derive(game, image, cache):
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            return pickle.load(f)
    from pinball_decryptor.plugins.stern.spike2.emulator import Spike2Emu, collapse_shadowed
    emu = Spike2Emu(game, image)
    try:
        emu.boot()
        rows = collapse_shadowed(emu.derive_params())
    finally:
        emu.close()
    keep = [{k: v for k, v in r.items() if k != "_rawobj"} for r in rows]
    with open(cache, "wb") as f:
        pickle.dump(keep, f)
    return keep


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("game")
    ap.add_argument("image")
    ap.add_argument("out")
    ap.add_argument("tag")
    ap.add_argument("--args", action="append", help="armxref.py args output (repeatable)")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    fw = open(a.game, "rb").read()
    with open(a.image, "rb") as f:
        fragments, sounds = container_counts(f.read(0x100))
    reqs, table = request_table(fw, fragments)
    log("%d requests (table at file offset 0x%x), %s fragments, %s sounds" % (len(reqs), table, fragments, sounds))
    names, agree, total = menu_by_request(fw, reqs)
    log("Sound Test: %d of %d menu entries name a request whose sid list is identical" % (agree, total))
    calls = const_calls(a.args)
    log("constant request arguments: %d distinct requests at %d call sites"
        % (len(calls), sum(len(v) for v in calls.values())))

    sites_cache = os.path.join(a.out, "%s_sites.pkl" % a.tag)
    if os.path.exists(sites_cache):
        sites = pickle.load(open(sites_cache, "rb"))
    else:
        sites = E._descriptor_sites(a.game, a.image, log=log)
        pickle.dump(sites, open(sites_cache, "wb"))
    log("%d descriptor sites" % len(sites))
    params = derive(a.game, a.image, os.path.join(a.out, "%s_params.pkl" % a.tag))
    log("%d records" % len(params))
    by_sid = collections.defaultdict(list)
    for s in sites:
        by_sid[s.sid].append(s)

    fk = {p["findkey"]: p["idx"] for p in params if p.get("findkey")}
    prow = {p["idx"]: p for p in params}

    def records(sid, mname):
        mask = MASKS[mname]
        out = []
        for s in by_sid.get(sid, ()):
            i = fk.get(play_key(s.payload, s.sid, mask))
            if i is not None and i not in out:
                out.append(i)
        return out

    # the build's own mask: the one under which the descriptors name real records
    exact = {m: sum(1 for s in sites if play_key(s.payload, s.sid, MASKS[m]) in fk) for m in MASKS}
    best = max(exact, key=exact.get)
    log("descriptor key mask: %s - exact matches %s of %d sites"
        % (", ".join("%s 0x%08X" % (m, MASKS[m]) for m in MASKS), exact, len(sites)))
    log("this build's mask: %s 0x%08X" % (best, MASKS[best]))

    # who names each record / sid
    rec_users = collections.defaultdict(set)
    sid_users = collections.defaultdict(set)
    per = []
    for req, (words, sids) in enumerate(reqs):
        recs = {m: [] for m in MASKS}
        for sid in sids:
            sid_users[sid].add(req)
            for m in MASKS:
                for i in records(sid, m):
                    if i not in recs[m]:
                        recs[m].append(i)
        for i in recs[best]:
            rec_users[i].add(req)
        per.append((req, words, sids, recs))

    cols = ("req", "n_sids", "sids", "recs", "recs_other_mask", "masks_agree", "chan", "seconds",
            "exclusive", "sid_shared_with", "rec_shared_with", "const_calls", "menu_name", "words")
    rows = []
    for req, words, sids, recs in per:
        g, l = recs[best], recs["lz" if best == "gz" else "gz"]
        agree_m = g == l and len(g) > 0
        chans = sorted({prow[i].get("chan") for i in g if i in prow})
        secs = sum(prow[i].get("length", 0) for i in g if i in prow) / 44100.0
        sid_sh = sorted(set().union(*[sid_users[s] for s in sids]) - {req}) if sids else []
        rec_sh = sorted(set().union(*[rec_users[i] for i in g]) - {req}) if g else []
        cc = calls.get(req, [])
        rows.append({
            "req": req, "n_sids": len(sids), "sids": ",".join(map(str, sids)),
            "recs": ",".join(map(str, g)), "recs_other_mask": ",".join(map(str, l)),
            "masks_agree": int(agree_m), "chan": ",".join(map(str, chans)), "seconds": "%.2f" % secs,
            "exclusive": int(not rec_sh and not sid_sh and bool(g)),
            "sid_shared_with": ",".join(map(str, sid_sh[:12])) + ("..." if len(sid_sh) > 12 else ""),
            "rec_shared_with": ",".join(map(str, rec_sh[:12])) + ("..." if len(rec_sh) > 12 else ""),
            "const_calls": ";".join("%x@%x" % c for c in cc),
            "menu_name": names.get(req, ""),
            "words": " ".join("%08x" % w for w in words),
        })
    path = os.path.join(a.out, "%s_requests.tsv" % a.tag)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(str(r[c]) for c in cols) + "\n")
    log("wrote %s" % path)

    carriers = [r for r in rows if r["n_sids"] == 1 and r["recs"] and r["recs"].count(",") == 0
                and r["exclusive"] and not r["const_calls"]]
    path = os.path.join(a.out, "%s_carriers.tsv" % a.tag)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(cols) + "\n")
        for r in sorted(carriers, key=lambda r: (r["chan"], -float(r["seconds"]))):
            f.write("\t".join(str(r[c]) for c in cols) + "\n")
    mono = sum(1 for r in carriers if r["chan"] == "1")
    stereo = sum(1 for r in carriers if r["chan"] == "2")
    log("provisional carriers: %d (mono %d, stereo %d) -> %s" % (len(carriers), mono, stereo, path))
    stats = collections.Counter()
    for r in rows:
        stats["single sid"] += r["n_sids"] == 1
        stats["masks agree"] += r["masks_agree"]
        stats["exclusive"] += r["exclusive"]
        stats["const call"] += bool(r["const_calls"])
        stats["menu name"] += bool(r["menu_name"])
        stats["no record"] += not r["recs"]
    log("stats: %s" % dict(stats))


if __name__ == "__main__":
    main(sys.argv[1:])
