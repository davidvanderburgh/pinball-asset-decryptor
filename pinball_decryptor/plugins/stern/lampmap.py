"""The playfield inserts of a Spike 2 game, read out of its program, as port `lamp` lines.

The library behind ``tools/spike2_emu/modes/sdk/lamp_map.py`` (the command line) and the port
drafting in :mod:`.portgen`, kept in the package so the app can read a card's inserts itself.

WHAT THE GAME KEEPS (read on Godzilla Premium/LE 1.16 and Pro 1.15, item mode-leds):

  LIGHT   one channel of one LED: the unit a light show writes. A light id is an index into a
          static array of 24-byte records; the u16 at +0x0e is the DEVICE the light drives. The
          game's lamp slots (585 on Pro 1.15, 592 on Premium 1.16) are indexed by light id.
  DEVICE  a 48-byte record in the game's device table (the one devicexy.py reads): +0x0c the
          name ("LEFT RAMP-R"), +0x18 the picture it is drawn on ("playfield"), +0x1c the I/O
          group and index (group 6 = node board 8, group 7 = node 9 on Godzilla), +0x20 the
          class (3 = LED), +0x28 x, y on that picture.
  LAMP    a FIXTURE: 8-byte records {u16 *lights, kind}. Kind 1, 4, 5 = one light; 2 = three
          (red, green, blue); 3 = six. `blele --lt <lamp>` names a lamp.
  SHOT    the game's own shot table: one `cshot` object per shot bit (the bit its shot
          dispatch hands the modes), whose u16 at +0x10 is the lamp the game lights for that
          shot. Built by a static initialiser, so it is read by running that function in
          unicorn (optional: without unicorn every lamp gets shot 0 and a comment says why).

The tables are found by the shape of the game's own accessors (bounds-check against a count,
then base + index * 24 / 48 / 8) and then CHECKED: a light table is only taken if its lights
resolve to LED devices whose names carry -R/-G/-B where the lamp table says red, green, blue.

A `lamp` line (MODE_SDK.md):
    lamp <light ids: R,G,B or one> <shot mask or 0> <the game's name for the insert>
"""
import re
import struct

KIND_LIGHTS = {1: 1, 4: 1, 5: 1, 2: 3, 3: 6}


class Elf:
    def __init__(self, path_or_bytes, name=None):
        if isinstance(path_or_bytes, (bytes, bytearray, memoryview)):
            self.b = bytes(path_or_bytes)
            self.path = name or "the game program"
        else:
            self.path = path_or_bytes
            with open(path_or_bytes, "rb") as f:
                self.b = f.read()
        b = self.b
        if b[:4] != b"\x7fELF":
            raise SystemExit("%s: not an ELF" % self.path)
        phoff, = struct.unpack_from("<I", b, 0x1C)
        phentsize, phnum = struct.unpack_from("<HH", b, 0x2A)
        self.loads = []
        for i in range(phnum):
            t, off, va, _pa, fsz, msz, flags, _al = struct.unpack_from("<8I", b, phoff + i * phentsize)
            if t == 1:
                self.loads.append((off, va, fsz, msz, flags))
        text = [l for l in self.loads if l[4] & 1][0]
        self.toff, self.tva, self.tsz = text[0], text[1], text[2]
        self.words = struct.unpack_from("<%dI" % (self.tsz // 4), b, self.toff)

    def off(self, va):
        for off, v, fsz, _m, _f in self.loads:
            if v <= va < v + fsz:
                return off + va - v
        return None

    def u32(self, va):
        o = self.off(va)
        return struct.unpack_from("<I", self.b, o)[0] if o is not None and o + 4 <= len(self.b) else None

    def u16(self, va):
        o = self.off(va)
        return struct.unpack_from("<H", self.b, o)[0] if o is not None else None

    def cstr(self, va, cap=96):
        o = self.off(va) if va else None
        if o is None:
            return None
        end = self.b.find(b"\0", o, o + cap)
        if end <= o:
            return None
        s = self.b[o:end]
        return s.decode("latin1") if all(32 <= c < 127 for c in s) else None


def _movw(w, rd=None):
    if (w & 0x0FF00000) != 0x03000000 or (rd is not None and (w >> 12) & 15 != rd):
        return None
    return ((w >> 4) & 0xF000) | (w & 0xFFF)


def _movt(w, rd=None):
    if (w & 0x0FF00000) != 0x03400000 or (rd is not None and (w >> 12) & 15 != rd):
        return None
    return ((w >> 4) & 0xF000) | (w & 0xFFF)


def _accessors(elf, scale_word):
    """(pointer global, count global) of every `movw r3,#p; add r0,r0,r0,lsl#1; movt r3,#p;
    ldr r3,[r3]; add r0,r3,r0,lsl #n` accessor, with the count its bounds check loads."""
    w = elf.words
    out = []
    for k in range(8, len(w) - 5):
        if w[k + 1] != 0xE0800080 or w[k + 3] != 0xE5933000 or w[k + 4] != scale_word:
            continue
        lo, hi = _movw(w[k], 3), _movt(w[k + 2], 3)
        if lo is None or hi is None:
            continue
        cnt = None
        for j in range(k - 1, k - 8, -1):
            h = _movt(w[j], 3)
            if h is not None and _movw(w[j - 1], 3) is not None:
                cnt = _movw(w[j - 1], 3) | (h << 16)
                break
        out.append((lo | (hi << 16), cnt))
    return out


def _lamp_accessors(elf):
    """(table, count global) of `movw rC,#n; movt rC,#n; ...; movw r3,#t; movt r3,#t;
    add r0, r3, r0, lsl #3` - the lamp table's accessor."""
    w = elf.words
    out = []
    for k in range(8, len(w) - 1):
        if w[k] != 0xE0830180:
            continue
        lo, hi = _movw(w[k - 2], 3), _movt(w[k - 1], 3)
        if lo is None or hi is None:
            continue
        cnt = None
        for j in range(k - 3, k - 9, -1):
            h = _movt(w[j])
            if h is not None and _movw(w[j - 1]) is not None and (w[j] >> 12) & 15 == (w[j - 1] >> 12) & 15:
                cnt = _movw(w[j - 1]) | (h << 16)
                break
        if cnt is not None:
            out.append((lo | (hi << 16), cnt))
    return out


def _device(elf, dev_tab, dev):
    va = dev_tab + 48 * dev
    o = elf.off(va)
    if o is None or o + 48 > len(elf.b):
        return None
    name = elf.cstr(struct.unpack_from("<I", elf.b, o + 0x0C)[0])
    image = elf.cstr(struct.unpack_from("<I", elf.b, o + 0x18)[0]) or ""
    grp, idx = struct.unpack_from("<hh", elf.b, o + 0x1C)
    cls = struct.unpack_from("<H", elf.b, o + 0x20)[0]
    x, y = struct.unpack_from("<hh", elf.b, o + 0x28)
    return dict(dev=dev, name=name, image=image, group=grp, index=idx, cls=cls, x=x, y=y)


def _read_lights(elf, light_tab, dev_tab, limit=2000):
    lights = [None]
    k = 1
    while k < limit:
        o = elf.off(light_tab + 24 * k)
        if o is None:
            break
        dev = struct.unpack_from("<H", elf.b, o + 0x0E)[0]
        if dev == 0:
            break
        d = _device(elf, dev_tab, dev)
        if d is None or not d["name"]:
            break
        lights.append(d)
        k += 1
    return lights


def _read_lamps(elf, lamp_tab, count):
    lamps = []
    unknown = 0
    for i in range(count):
        o = elf.off(lamp_tab + 8 * i)
        if o is None:
            return None
        p, kind = struct.unpack_from("<II", elf.b, o)
        n = KIND_LIGHTS.get(kind, 0)
        if i and not n:
            # a kind this reader does not know (Deadpool Pro 1.16, TMNT Pro 1.59: kind 6, whose
            # words are no light list) is left without lights; many of them = not a lamp table
            unknown += 1
            if unknown > max(2, count // 20):
                return None
        po = elf.off(p) if p else None
        ids = list(struct.unpack_from("<%dH" % n, elf.b, po)) if n and po is not None else []
        lamps.append(dict(lamp=i, kind=kind, lights=ids))
    return lamps


def _suffix(name):
    m = re.search(r"\s*-\s*([RGB])$", name or "")      # "LEFT RAMP-R"; Venom: "TOPPER BIKE - R"
    return m.group(1) if m else None


def _stem(name):
    return re.sub(r"\s*-\s*[RGB]$", "", name or "").strip()


def find_tables(elf):
    """{'light_tab', 'dev_tab', 'lamp_tab', 'lamp_count'} - checked, or SystemExit saying why."""
    best = None
    for lp, _lc in _accessors(elf, 0xE0830180):
        lt = elf.u32(lp)
        if not lt:
            continue
        for dp, _dc in _accessors(elf, 0xE0830200):
            dt = elf.u32(dp)
            if not dt:
                continue
            lights = _read_lights(elf, lt, dt, limit=40)
            leds = sum(1 for d in lights[1:] if d and d["cls"] == 3)
            if leds >= 20 and (best is None or leds > best[0]):
                best = (leds, lt, dt)
    if best is None:
        raise SystemExit("%s: no light table found (no accessor whose lights resolve to LED devices)" % elf.path)
    _n, lt, dt = best
    lights = _read_lights(elf, lt, dt)
    for tab, cntva in _lamp_accessors(elf):
        cnt = elf.u32(cntva)
        if not cnt or cnt > 4000:
            continue
        lamps = _read_lamps(elf, tab, cnt)
        if not lamps:
            continue
        rgb = [l for l in lamps if l["kind"] == 2]
        good = 0
        for l in rgb:
            names = [lights[i]["name"] if 0 < i < len(lights) else None for i in l["lights"]]
            if sorted(_suffix(n) or "" for n in names) == ["B", "G", "R"] and len({_stem(n) for n in names}) == 1:
                good += 1
        if rgb and good >= 0.9 * len(rgb):
            return dict(light_tab=lt, dev_tab=dt, lamp_tab=tab, lamp_count=cnt, lights=lights, lamps=lamps)
        # a title whose inserts are all one colour each (Star Wars ELG 1.10): no RGB lamp to check,
        # so its single lamps must name LED lights instead
        mono = [l for l in lamps if len(l["lights"]) == 1]
        named = sum(1 for l in mono if 0 < l["lights"][0] < len(lights) and lights[l["lights"][0]]["cls"] == 3)
        if not rgb and len(mono) >= 20 and named >= 0.9 * len(mono):
            return dict(light_tab=lt, dev_tab=dt, lamp_tab=tab, lamp_count=cnt, lights=lights, lamps=lamps)
    raise SystemExit("%s: no lamp table whose RGB lamps are one fixture's -R, -G, -B" % elf.path)


# ---- the game's shot table (cshot) ----------------------------------------------------------
def _cshot_vptr(elf):
    """The vptr of class cshot: its typeinfo name "5cshot", the typeinfo that points at it,
    and the vtable whose word -1 is that typeinfo."""
    at = elf.b.find(b"5cshot\0")
    if at < 0:
        return None
    name_va = None
    for off, va, fsz, _m, _f in elf.loads:
        if off <= at < off + fsz:
            name_va = va + at - off
    ti = None
    for off, va, fsz, _m, _f in elf.loads:
        for k in range(0, fsz - 8, 4):
            if struct.unpack_from("<I", elf.b, off + k + 4)[0] == name_va:
                ti = va + k
                break
        if ti:
            break
    if ti is None:
        return None
    for off, va, fsz, _m, _f in elf.loads:
        for k in range(4, fsz - 8, 4):
            if struct.unpack_from("<I", elf.b, off + k)[0] == ti and \
                    struct.unpack_from("<I", elf.b, off + k - 4)[0] == 0:
                return va + k + 4
    return None


def shot_lamps(elf):
    """{shot mask bit: lamp id} from the game's cshot objects, or (None, why)."""
    vptr = _cshot_vptr(elf)
    if vptr is None:
        return None, "no class cshot in this program"
    vtab = vptr - 8
    # the static initialiser that builds them: it loads the vtable address with movw/movt
    fn = None
    w = elf.words
    for k in range(1, len(w)):
        hi = _movt(w[k])
        if hi is None:
            continue
        rd = (w[k] >> 12) & 15
        for j in range(k - 1, max(0, k - 6), -1):
            lo = _movw(w[j], rd)
            if lo is not None:
                if lo | (hi << 16) in (vtab, vptr):
                    a = k
                    while a > 0 and not ((w[a] & 0xFFFF0000) == 0xE92D0000 and w[a] & 0x4000):
                        a -= 1
                    fn = elf.tva + 4 * a
                break
        if fn:
            break
    if fn is None:
        return None, "the code that builds the cshot objects was not found"
    try:
        from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UcError
        from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0
    except ImportError:
        return None, "unicorn is not installed (pip install unicorn), so the shot table was not read"
    mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    for off, va, fsz, msz, _f in elf.loads:
        lo = va & ~0xFFF
        mu.mem_map(lo, ((va + msz + 0xFFF) & ~0xFFF) - lo)
        mu.mem_write(va, elf.b[off:off + fsz])
    mu.mem_map(0x90000000, 0x100000)
    mu.mem_map(0xA0000000, 0x1000)
    mu.reg_write(UC_ARM_REG_SP, 0x900F0000)
    mu.reg_write(UC_ARM_REG_LR, 0xA0000000)
    writes = set()
    steps = [0]

    def on_code(uc, addr, _size, _u):
        steps[0] += 1
        if addr == 0xA0000000 or steps[0] > 500000:
            uc.emu_stop()
            return
        ins = struct.unpack("<I", bytes(uc.mem_read(addr, 4)))[0]
        if ((ins & 0x0F000000) == 0x0B000000 and ins >> 28 != 0xF) or (ins & 0x0FFFFFF0) == 0x012FFF30:
            uc.reg_write(UC_ARM_REG_R0, 0)          # a call: skipped, returns 0
            uc.reg_write(UC_ARM_REG_PC, addr + 4)

    def on_write(uc, _acc, addr, size, value, _u):
        if size == 4 and value == vptr:
            writes.add(addr)

    mu.hook_add(UC_HOOK_CODE, on_code)
    mu.hook_add(UC_HOOK_MEM_WRITE, on_write)
    try:
        mu.emu_start(fn, 0xA0000000)
    except UcError:
        pass
    out = {}
    for a in sorted(writes):
        raw = bytes(mu.mem_read(a, 24))
        mask = struct.unpack_from("<Q", raw, 8)[0]
        lamp = struct.unpack_from("<H", raw, 0x10)[0]
        if mask and not mask & (mask - 1) and lamp:
            out[mask] = lamp
    if not out:
        return None, "the cshot initialiser at 0x%x ran but set no shot lamp" % fn
    return out, "read from %d cshot objects built by 0x%x" % (len(writes), fn)


# ---- output ---------------------------------------------------------------------------------
_NOT_PLAYFIELD = ("system/", "topper", "backpanel", "back_panel", "speaker", "cabinet", "front", "backbox")


def playfield_image(t):
    """The picture a title draws its playfield inserts on: Godzilla's is "playfield", but each
    title names its own ("Test/beatles_playfield", "TestMode/Rodeo_LE_Service_Playfield_...").
    The picture whose name says playfield with the most lights; else the busiest picture that
    is not the cabinet, the speaker panel, a topper or a back panel; else "" (Deadpool LE draws
    its playfield lights on no picture)."""
    count = {}
    for d in t["lights"]:
        if d:
            count[d["image"]] = count.get(d["image"], 0) + 1
    named = [i for i in count if "playfield" in i.lower()]
    if named:
        return max(named, key=lambda i: count[i])
    rest = [i for i in count if i and not any(w in i.lower() for w in _NOT_PLAYFIELD)]
    if rest:
        return max(rest, key=lambda i: count[i])
    return ""


def inserts(elf, image=None):
    """[{lamp, name, lights (R,G,B order), shot mask, group, index, x, y}] for every lamp drawn
    on `image` (None: the title's playfield picture, :func:`playfield_image`), plus how the
    shot masks were found."""
    t = find_tables(elf)
    if image is None:
        image = playfield_image(t)
    lights, lamps = t["lights"], t["lamps"]
    bits, how = shot_lamps(elf)
    by_lamp = {}
    for mask, lamp in (bits or {}).items():
        by_lamp[lamp] = by_lamp.get(lamp, 0) | mask
    out = []
    order = {"R": 0, "G": 1, "B": 2}
    by_stem = {}
    for l in lamps:
        ids = [i for i in l["lights"] if 0 < i < len(lights)]
        if not ids:
            continue
        devs = [lights[i] for i in ids]
        if not all(d["image"] == image for d in devs):
            continue
        if len(ids) == 3:
            if sorted(_suffix(d["name"]) or "" for d in devs) != ["B", "G", "R"]:
                continue
            ids = sorted(ids, key=lambda i: order[_suffix(lights[i]["name"])])
        elif len(ids) != 1:
            continue
        name = _stem(lights[ids[0]]["name"])
        d0 = lights[ids[0]]
        suf = _suffix(d0["name"]) if len(ids) == 1 else None
        if suf and name in by_stem:
            # one channel of a fixture the game keeps as one lamp per colour (BUILDING FIRE
            # LEFT 1-R and -G): the channels join the fixture's line, at their colour's place
            ins = by_stem[name]
            ins["lights"][order[suf]] = ids[0]
            ins["lamps"].append(l["lamp"])
            ins["shot"] |= by_lamp.get(l["lamp"], 0)
            continue
        if suf:
            rgb = [0, 0, 0]
            rgb[order[suf]] = ids[0]
            ids = rgb
        ins = dict(lamp=l["lamp"], lamps=[l["lamp"]], name=name, lights=ids, shot=by_lamp.get(l["lamp"], 0),
                   group=d0["group"], index=d0["index"], x=d0["x"], y=d0["y"])
        if suf:
            by_stem[name] = ins
        out.append(ins)
    return out, how, t


def lamp_line(ins):
    """One port line: `lamp <lights> <shot mask> <name>  # where it is`."""
    return "lamp %-12s %-14s %s  # lamp %s, I/O group %d index %d, at %d,%d" % (
        ",".join(map(str, ins["lights"])), "0x%x" % ins["shot"] if ins["shot"] else "0",
        ins["name"], "+".join(map(str, ins["lamps"])), ins["group"], ins["index"], ins["x"], ins["y"])


def port_lines(elf, image=None):
    ins, how, t = inserts(elf, image)
    if image is None:
        image = playfield_image(t)
    lines = ["# ---- lamps: lamp <light ids R,G,B | one> <shot mask> <name> - read by lamp_map.py ----",
             "# %d inserts on the %s picture; light table 0x%x, device table 0x%x, lamp table 0x%x (%d lamps)"
             % (len(ins), image, t["light_tab"], t["dev_tab"], t["lamp_tab"], t["lamp_count"]),
             "# shot masks: %s" % how]
    lines += [lamp_line(i) for i in ins]
    return lines


def parse_lamp(rest):
    """A `lamp` line's words after the key -> (lights tuple, mono, shot mask, name), or None.
    The runtime's own reading (pad_mode_runtime.c lamp_line): up to three ids joined by commas,
    a number, the name to the end of the line, a ` #` comment dropped."""
    m = re.match(r"\s*(\d+(?:\s*,\s*\d+){0,2})\s+(0[xX][0-9a-fA-F]+|\d+)\s+(.*)$", rest)
    if not m:
        return None
    ids = [int(x) for x in m.group(1).split(",")]
    name = re.split(r"\s+#", m.group(3), maxsplit=1)[0].strip()
    if not name or not any(ids):
        return None
    lights = tuple(ids + [0] * (3 - len(ids)))
    return lights, len(ids) == 1, int(m.group(2), 0), name
