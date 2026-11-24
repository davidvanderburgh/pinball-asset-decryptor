"""Recordings of a game's own cabinet lights (PAD-1516), for the Expression lights tab.

Jim-Beam (Bond Pro 1.06): "In my Bond 1.06 Pro Project I opened the speaker light tab and saw no stock light
animations ... Would it be possible to store/copy those animations to take it to other titles like Iron Maiden?"

Most games keep no frames of their cabinet shows: Bond's light-show engine DRAWS its speaker animation (in attract a
colour gradient travelling round the rings, then whole-ring colour flashes; in a game one background colour), so
there is nothing in its program to read as Led Zeppelin's frames are (:mod:`.cab_stock`). What it shows can be
RECORDED: while the project's card runs in the emulator, the rig samples the cabinet lights' LED channels
(``tools/spike2_emu/cabrec.py``, every :data:`PERIOD` ms) into a file of the project's. A show's ``rec`` step plays a
recording on the card (``cabshow.cfg`` ``rec`` / ``recmap``, pad_mode_runtime.c ``cab_rec_colour``) and in the
tab's preview, on any cabinet: each of its lights takes the recorded light nearest its own place (:func:`source_map`),
so Bond's 23 speaker lights play on Iron Maiden's added ring. The recording is made from the owner's own card on
their own PC and stays in their project; the app ships none.

A recording is ``<project>/cab_rec/<name>.bin`` (``PADCREC1``, u32 period ms, u32 frames, u32 lights, then frames x
lights x R,G,B) and ``<name>.json`` (its source game, and each recorded light's name, lane, side and place u).
"""
import json
import os
import re
import struct

MAGIC = b"PADCREC1"
HEAD = 20
#: the sampling period: the game refreshes its LED boards about every 33 ms (tools/spike2_emu/ledframes.py)
PERIOD = 25
SECONDS_MAX = 300
DIR = "cab_rec"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.()-]{0,47}$")
#: the runtime's limit on one recording's bytes (pad_mode_runtime.c CAB_REC_MAX)
BYTES_MAX = 8 << 20


class RecError(Exception):
    """A recording that cannot be made or read, in words for the page."""


# ---- the file ----------------------------------------------------------------------------------------------------
def pack(period, lights, frames):
    """The file's bytes: *frames*, a list of bytes objects of ``lights * 3`` each."""
    body = b"".join(frames)
    return MAGIC + struct.pack("<III", int(period), len(frames), int(lights)) + body


def unpack_head(b):
    """``(period, frames, lights)`` of a recording's bytes, or None when they are not one (or are cut short)."""
    if len(b) < HEAD or b[:8] != MAGIC:
        return None
    per, n, li = struct.unpack_from("<III", b, 8)
    if not per or not n or not li or len(b) != HEAD + n * li * 3:
        return None
    return per, n, li


# ---- a project's recordings --------------------------------------------------------------------------------------
def folder(project):
    return os.path.join(project, DIR)


def paths(project, name):
    base = os.path.join(folder(project), name)
    return base + ".bin", base + ".json"


def listing(project):
    """The project's recordings: ``[{name, source, period, frames, lights, seconds, file, places}]`` (``places``: each
    recorded light's {name, lane, side, u}), by name; a broken pair is left out."""
    out = []
    d = folder(project) if project else ""
    if not d or not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        name = fn[:-5]
        b, j = paths(project, name)
        try:
            with open(j, encoding="utf-8") as f:
                meta = json.load(f)
            with open(b, "rb") as f:
                raw = f.read(HEAD)
            head = struct.unpack_from("<III", raw, 8) if len(raw) == HEAD and raw[:8] == MAGIC else None
        except (OSError, ValueError):
            continue
        if head is None or not all(head):
            continue
        per, n, li = head
        if os.path.getsize(b) != HEAD + n * li * 3 or len(meta.get("places") or []) != li:
            continue
        out.append({"name": name, "source": str(meta.get("source") or ""), "period": per, "frames": n, "lights": li,
                    "seconds": round(per * n / 1000.0, 1), "file": b, "places": meta["places"]})
    return out


def find(project, name):
    return next((r for r in listing(project) if r["name"] == name), None)


def free_name(project, base):
    """*base* (made a valid name), or with a number after it, not yet among the project's recordings."""
    base = re.sub(r"[^A-Za-z0-9 _.()-]", " ", str(base or "")).strip()[:40] or "Recording"
    if not base[0].isalnum():
        base = "Recording " + base
    have = {r["name"] for r in listing(project)}
    name, n = base, 2
    while name in have or os.path.exists(paths(project, name)[0]):
        name = "%s %d" % (base, n)
        n += 1
    return name


def save(project, name, source, places, data):
    """The recording *data* (:func:`pack`'s bytes) as *name* in *project*, with its source game and its lights'
    *places* ([{name, lane, side, u}], one a recorded light)."""
    head = unpack_head(data)
    if head is None or head[2] != len(places):
        raise RecError("the recording came back cut short or for other lights")
    if not NAME_RE.match(name):
        raise RecError("%r is not a name a recording can have" % name)
    os.makedirs(folder(project), exist_ok=True)
    b, j = paths(project, name)
    with open(b, "wb") as f:
        f.write(data)
    with open(j, "w", encoding="utf-8") as f:
        json.dump({"source": source, "places": [{k: p[k] for k in ("name", "lane", "side", "u")} for p in places]},
                  f, indent=1)
    return find(project, name)


def remove(project, name):
    for p in paths(project, name):
        try:
            os.remove(p)
        except OSError:
            pass


def copy_into(src_project, dst_project, name):
    """PAD-1516: recording *name* of *src_project* in *dst_project* too; its name there (the same unless the other
    project has another recording of that name), or "" when *src_project* has none."""
    r = find(src_project, name)
    if r is None:
        return ""
    have = find(dst_project, name)
    with open(r["file"], "rb") as f:
        data = f.read()
    if have is not None:
        with open(have["file"], "rb") as f:
            if f.read() == data:
                return name
        name = free_name(dst_project, name)
    save(dst_project, name, r["source"], r["places"], data)
    return name


# ---- where its lights go on a cabinet ----------------------------------------------------------------------------
def _dist(a, b, ring):
    d = abs(int(a) - int(b))
    return min(d, 1000 - d) if ring else d


def source_map(places, lights):
    """Each of *lights* (the cabinet's, in the runtime's order: {lane, side, u}) -> the recorded light it plays (an
    index into *places*), -1 for none. A light takes the recorded light of its own lane nearest its place u (round
    the ring for a speaker), on its own side when the recording has that side, else on either."""
    out = []
    for L in lights:
        lane = L.get("lane")
        cand = [i for i, p in enumerate(places) if p.get("lane") == lane]
        side = L.get("side") or 0
        same = [i for i in cand if (places[i].get("side") or 0) == side]
        pool = same or cand
        if not pool:
            out.append(-1)
            continue
        out.append(min(pool, key=lambda i: (_dist(places[i].get("u", 0), L.get("u", 0), lane == 1), i)))
    return out


# ---- what the rig samples ----------------------------------------------------------------------------------------
def channels(elf):
    """For each cabinet light of the game program *elf* (:func:`.lampmap.cabinet`'s order, the runtime's), its LED
    channels as ``[(node, channel), ...]`` (R, G, B, or the one): the light's board is padled node group + 1, its
    channel the device index (the strips are wired G, R, B: Bond Pro 1.06 SPEAKER 1-G index 0, 1-R index 1, 1-B
    index 2, on node 7)."""
    from . import lampmap as LM
    t = LM.find_tables(elf)
    out = []
    for c in LM.cabinet(elf, t):
        out.append([(t["lights"][i]["group"] + 1, t["lights"][i]["index"]) for i in c["lights"]])
    return out


def map_arg(chans):
    """``cabrec.py --map``: one light a ``;``, its channels ``node:channel`` by ``,``."""
    return ";".join(",".join("%d:%d" % nc for nc in light) for light in chans)
