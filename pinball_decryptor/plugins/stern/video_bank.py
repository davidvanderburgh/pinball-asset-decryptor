"""ADD a clip to a Spike 2 in-game VIDEO BANK scene: a clip of a mode's OWN (item 132).

EMULATOR-PROVEN on Godzilla Pro 1.15 (2026-09-16), NOT hardware-proven: a title-card clip
added here as ``KaijuRush_Clip`` played full screen when KAIJU RUSH started, in a game,
and a stock clip still played through the grown bank. Playing alone does not reach the
glass - ``mode.so`` draws the video player every tick (``tools/spike2_emu/modes/hook.h``
``gz_clip_draw``).

Godzilla Pro 1.15 plays every in-game clip by NAME through one call,
``0x528a4(name, loop, crop label)``, on the VideoSurface of one scene:
``auto_loaded/60ed7e50.../scene.radium``, whose Video is called "video.in_game_videos".
That scene maps each name to a clip, and each clip names its file under
``scene.assets``. So a clip the card never shipped is one more entry in that map
plus the file it names - no stock clip is replaced, and no stock entry moves.

THE GRAMMAR, read off the stock file and walked to its last byte (strings
``[u64 len][latin1]``; ids u32, top bit set on first occurrence)::

    u8 1
    library    [u64 n] n x (u32 symbol key | u32 poly name id "Video" | u32 ptr id | Video)
    Video      u32 symbol | name | u32 w | u32 h | u32 | u8
               | [u64 n] n x (name, u32 clip id; first time: | path | u32 file size)
    u64 0 | u64 0 | stage u32 w | u32 h | f32 fps | f32 r g b a
    root       u32 symbol | name | u32 frames | [u64 n][nodes] | u64 | u64
               | labels [u64 n] n x (name, u32 frame)
    node       u32 ptr id | name | u32 flag | keyframes [u64 n](u32, u8) | [u64 0]
               | tracks [u64 n](u32, 64 B) | components [u64 n](u32 frame, u32 poly name
               id, u32 object id, Video) | [u64 0]

The clip map appears TWICE: in the library, where each clip is registered with its
path and size, and in the VideoSurface node's component, which names the same clips
by bare id. Both maps are ``std::map<std::string, ...>``, stored sorted by the name's
bytes, and an added clip goes into both at its sorted place. The root's four frames are
crops (Normal, ScoreFrame, SquareCrop, LetterboxCrop), not clips.

A file that does not walk EXACTLY to its end under this grammar is refused. The size
field is the clip file's byte count (all 598 stock entries match their files).
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field

FLAG = 0x80000000

GODZILLA_PRO_BANK = "60ed7e5036b8ce09d35a3e101ea6fc1380b37d97"


class VideoBankError(ValueError):
    """Not a video bank this module can walk, or a clip it will not add."""


@dataclass
class Clip:
    name: str
    clip_id: int
    path: str | None      # library entries only
    size: int | None
    start: int            # offset of the entry's name
    end: int


@dataclass
class VideoMap:
    count_at: int
    entries: list = field(default_factory=list)


@dataclass
class Bank:
    video_name: str
    width: int
    height: int
    library: VideoMap
    surface: VideoMap
    surface_node: str
    labels: list
    max_id: int


class _Reader:
    def __init__(self, data):
        self.d = data
        self.o = 0

    def need(self, n):
        if self.o + n > len(self.d):
            raise VideoBankError("ran off the end at 0x%x" % self.o)

    def u8(self):
        self.need(1)
        v = self.d[self.o]
        self.o += 1
        return v

    def u32(self):
        self.need(4)
        v = struct.unpack_from("<I", self.d, self.o)[0]
        self.o += 4
        return v

    def u64(self):
        self.need(8)
        v = struct.unpack_from("<Q", self.d, self.o)[0]
        self.o += 8
        return v

    def skip(self, n):
        self.need(n)
        self.o += n

    def string(self, cap=4096):
        n = self.u64()
        if n > cap:
            raise VideoBankError("a %d-byte string at 0x%x" % (n, self.o - 8))
        self.need(n)
        s = self.d[self.o:self.o + n].decode("latin1")
        self.o += n
        return s


def _video(r, registered, ids):
    """One Video body. ``registered`` maps clip id -> Clip for the library's clips;
    the surface's map must name only those."""
    r.u32()
    name = r.string()
    w, h = r.u32(), r.u32()
    r.u32()
    r.u8()
    vm = VideoMap(count_at=r.o)
    for _ in range(r.u64()):
        start = r.o
        cname = r.string()
        cid = r.u32()
        if cid & FLAG:
            cid &= ~FLAG
            path = r.string()
            size = r.u32()
            if cid in registered:
                raise VideoBankError("clip id %d registered twice" % cid)
            ids.append(cid)
            clip = Clip(cname, cid, path, size, start, r.o)
            registered[cid] = clip
        else:
            if cid not in registered or registered[cid].name != cname:
                raise VideoBankError("%r refers to clip id %d, which is not that clip" % (cname, cid))
            clip = Clip(cname, cid, None, None, start, r.o)
        vm.entries.append(clip)
    _marked(r, ids)
    return name, w, h, vm


def _marked(r, ids):
    """A Video's SECOND list (item 164): clips with frame markers, empty on Godzilla. Each is a
    name and an object id; on the id's first occurrence (FLAG) its body follows - f32 fps, then
    [u64 n] n x (u32 frame, marker name). Munsters 1.28 ("EndOfBallBonus": Pause, Explosion),
    Star Wars LE 1.30 and ELG 1.10 ("SW5_SCENE_001": MUSIC_START), John Wick 1.01."""
    for _ in range(r.u64()):
        r.string()
        mid = r.u32()
        if mid & FLAG:
            ids.append(mid & ~FLAG)
            r.skip(4)
            for _m in range(r.u64()):
                r.u32()
                r.string()


def parse(data):
    """Walk a video bank scene. Raises VideoBankError unless it walks to its last byte."""
    r = _Reader(data)
    ids = []
    registered = {}
    if r.u8() != 1:
        raise VideoBankError("does not start with the 1 byte a scene starts with")
    if r.u64() != 1:
        raise VideoBankError("a video bank's library holds exactly one Video")
    r.u32()
    name_id = r.u32()
    if not name_id & FLAG or r.string() != "Video":
        raise VideoBankError("the library's one entry is not a Video")
    name_id &= ~FLAG
    ptr = r.u32()
    ids.append(ptr & ~FLAG)
    vname, w, h, library = _video(r, registered, ids)
    r.u64()
    r.skip(4 + 4 + 4 + 16)                              # stage w, h, fps, rgba
    r.u32()
    r.string()
    r.u32()
    surface = None
    surface_node = None
    for _ in range(r.u64()):
        nptr = r.u32()
        ids.append(nptr & ~FLAG)
        nname = r.string()
        r.u32()
        r.skip(5 * r.u64())
        if r.u64():
            raise VideoBankError("node %r has a list; a video bank's node has none" % nname)
        r.skip(68 * r.u64())
        for _ in range(r.u64()):
            r.u32()
            ptype = r.u32()
            obj = r.u32()
            if ptype != name_id:
                raise VideoBankError("node %r carries a component that is not a Video" % nname)
            ids.append(obj & ~FLAG)
            if surface is not None:
                raise VideoBankError("more than one Video component")
            _, _, _, surface = _video(r, registered, ids)
            surface_node = nname
        if r.u64():
            raise VideoBankError("node %r has a frame map" % nname)
    r.u64()
    labels = []
    for _ in range(r.u64()):
        labels.append((r.string(), r.u32()))
    if r.o != len(data):
        raise VideoBankError("the walk ended at 0x%x of 0x%x bytes" % (r.o, len(data)))
    if surface is None:
        raise VideoBankError("no VideoSurface component")
    if [c.clip_id for c in surface.entries] != [c.clip_id for c in library.entries]:
        raise VideoBankError("the surface's clips are not the library's clips")
    return Bank(vname, w, h, library, surface, surface_node, labels, max(ids))


def _sorted_at(vm, name):
    key = name.encode("latin1")
    for c in vm.entries:
        if c.name.encode("latin1") > key:
            return c.start
    last = vm.entries[-1] if vm.entries else None
    return last.end if last else vm.count_at + 8


def next_path(bank):
    """The next unused ``<dir>/<n>.asset`` in the directory the stock clips share. A bank whose
    clips sit at the top of ``scene.assets`` (item 164: Munsters' and Iron Maiden's one-clip
    background banks, ``2.asset`` itself) gets the next unused ``<n>.asset`` beside them."""
    if bank.library.entries and all("/" not in c.path for c in bank.library.entries):
        used = [int(c.path[:-6]) for c in bank.library.entries
                if c.path.endswith(".asset") and c.path[:-6].isdigit()]
        return "%d.asset" % (max(used, default=-1) + 1)
    dirs = {c.path.rsplit("/", 1)[0] for c in bank.library.entries}
    if len(dirs) != 1:
        raise VideoBankError("the clips are in %d directories; name the path" % len(dirs))
    d = dirs.pop()
    used = set()
    for c in bank.library.entries:
        leaf = c.path.rsplit("/", 1)[1]
        if leaf.endswith(".asset") and leaf[:-6].isdigit():
            used.add(int(leaf[:-6]))
    return "%s/%d.asset" % (d, max(used, default=-1) + 1)


def add_clip(data, name, size, path=None):
    """Add a clip ``name`` whose file is ``size`` bytes at ``scene.assets/<path>``.

    Returns (new bytes, info). info names the clip id, the path to put the file at and
    the new file's md5."""
    bank = parse(data)
    try:
        raw = name.encode("latin1")
    except UnicodeEncodeError:
        raise VideoBankError("a clip name is latin-1") from None
    if not raw or any(b < 0x21 or b > 0x7E for b in raw):
        raise VideoBankError("a clip name is printable ASCII with no spaces: %r" % name)
    if any(c.name == name for c in bank.library.entries):
        raise VideoBankError("the bank already has a clip called %r" % name)
    if not 0 < size < 0x100000000:
        raise VideoBankError("a clip's size field is a u32; got %d" % size)
    path = path or next_path(bank)
    if any(c.path == path for c in bank.library.entries):
        raise VideoBankError("a stock clip already lives at %s" % path)
    cid = bank.max_id + 1
    lib_entry = (struct.pack("<Q", len(raw)) + raw + struct.pack("<I", FLAG | cid)
                 + struct.pack("<Q", len(path)) + path.encode("latin1") + struct.pack("<I", size))
    surf_entry = struct.pack("<Q", len(raw)) + raw + struct.pack("<I", cid)
    lib_at = _sorted_at(bank.library, name)
    surf_at = _sorted_at(bank.surface, name)
    new = bytearray(data)
    # the surface map is later in the file: splice it first so lib_at stays true
    new[surf_at:surf_at] = surf_entry
    struct.pack_into("<Q", new, bank.surface.count_at, len(bank.surface.entries) + 1)
    new[lib_at:lib_at] = lib_entry
    struct.pack_into("<Q", new, bank.library.count_at, len(bank.library.entries) + 1)
    new = bytes(new)
    check = parse(new)
    if len(check.library.entries) != len(bank.library.entries) + 1:
        raise VideoBankError("the grown bank does not read back with one more clip")
    info = {"name": name, "clip_id": cid, "path": path, "size": size,
            "clips": len(check.library.entries), "md5": hashlib.md5(new).hexdigest()}
    return new, info
