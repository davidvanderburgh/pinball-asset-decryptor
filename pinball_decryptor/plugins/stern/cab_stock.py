"""The game's own expression light shows, read off its program (PAD-1063; docs/plans/pad1040_expression_shows.md).

BEN (Discord): "does the existing Stern expression lighting patterns show up? Or is it just for user added ones?"
David: bring them in.

Led Zeppelin and Rush keep a show for each of their songs IN the game program, as frames: the class ExpressionLights
looks up the request a channel is playing in a table of rows ``{u16 request, u16 0, u32 period ms, u32 frames,
u32 ORIGINAL frames, u32 REMIX frames}`` (Led Zeppelin LE 1.22: 20 rows at 0x56952c, 25 ms a frame, two requests a
song), and paints frame ``song position / period``: one RGB byte triple for each blade pixel, ``EXPRESSIVE LIGHTING
n`` being pixel n - 1 (L 1..48, R 49..96). The speaker lights are no frames of their own: speaker n is the average of
a few blade pixels (``speakers[n - 1]``, four or eight, the sum shifted as the game does). The operator's EXPRESSION
LIGHTS MODE picks the set: 1 ORIGINAL SHOWS, 2 REMIX SHOWS, 3 ALL SHOWS (either, at random). The game dims both by
its brightness settings after (90% as shipped), as it does the card's own shows.

The two pointers are zero in the file: a static initialiser fills them, so it is run here (unicorn, calls skipped)
as :func:`.lampmap.shot_lamps` runs the cshot builder. The frames are the program's own, so a card's show plays them
from the game's memory (``cabshow.cfg`` ``songs`` / ``songspk``, pad_mode_runtime.c "SONG SHOWS"): nothing of the
game's is copied onto the card. Emulator-proven on Led Zeppelin LE 1.22: three snapshots of the game's own show are
these frames exactly, blades and speakers, at 90%.
"""
import re
import struct

ROW = 0x14
#: a row as the file has it (the two pointers zero, or already in the file); a lookahead, so a match one byte early
#: cannot swallow the table's start
_ROW_RE = re.compile(rb"(?=(?:[\x01-\xff][\x00-\x1f]|\x00[\x01-\x1f])\x00\x00[\x0a-\x64]\x00\x00\x00..[\x00-\x04]\x00"
                     rb".{8})", re.S)
SETS = ("original", "remix")
SET_WORDS = {"original": "Original", "remix": "Remix"}


def _rows_at(elf, off):
    """The rows from file offset *off* on: [(request, period, frames, original, remix)]."""
    out = []
    while off + ROW <= len(elf.b):
        req, z, per, n, a, b = struct.unpack_from("<HHIIII", elf.b, off)
        if not (req and z == 0 and 10 <= per <= 100 and 200 <= n <= 300000):
            break
        if (a or b) and (elf.off(a) is None or elf.off(b) is None):
            break
        out.append((req, per, n, a, b))
        off += ROW
    return out


def find_table(elf):
    """``(table va, rows)`` of the program's song shows, or ``(None, [])``: the first run of three rows or more."""
    for m in _ROW_RE.finditer(elf.b):
        off = m.start()
        if off % 4:
            continue
        rows = _rows_at(elf, off)
        if len(rows) < 3:
            continue
        for foff, va, fsz, _m, _f in elf.loads:
            if foff <= off < foff + fsz:
                return va + off - foff, rows
    return None, []


def _builders(elf, lo, hi):
    """The functions that build an address in [lo, hi) with movw/movt: their entries (a push with lr before)."""
    from .lampmap import _movt, _movw
    w = elf.words
    out = []
    for k in range(1, len(w)):
        top = _movt(w[k])
        if top is None or top != (lo >> 16) and top != ((hi - 1) >> 16):
            continue
        rd = (w[k] >> 12) & 15
        for j in range(k - 1, max(0, k - 12), -1):
            low = _movw(w[j], rd)
            if low is not None:
                if lo <= (low | top << 16) < hi:
                    a = k
                    while a > 0 and not ((w[a] & 0xFFFF0000) == 0xE92D0000 and w[a] & 0x4000):
                        a -= 1
                    fn = elf.tva + 4 * a
                    if fn not in out:
                        out.append(fn)
                break
    return out


def _run_init(elf, fn, table, n):
    """Run the function at *fn* (calls skipped, each returning 0); the rows' (original, remix) after, or None."""
    try:
        from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UcError
        from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0
    except ImportError:
        return None
    mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    for off, va, fsz, msz, _f in elf.loads:
        lo = va & ~0xFFF
        mu.mem_map(lo, ((va + msz + 0xFFF) & ~0xFFF) - lo)
        mu.mem_write(va, elf.b[off:off + fsz])
    mu.mem_map(0x90000000, 0x100000)
    mu.mem_map(0xA0000000, 0x1000)
    mu.reg_write(UC_ARM_REG_SP, 0x900F0000)
    mu.reg_write(UC_ARM_REG_LR, 0xA0000000)
    steps = [0]

    def on_code(uc, addr, _size, _u):
        steps[0] += 1
        if addr == 0xA0000000 or steps[0] > 200000:
            uc.emu_stop()
            return
        ins = struct.unpack("<I", bytes(uc.mem_read(addr, 4)))[0]
        if ((ins & 0x0F000000) == 0x0B000000 and ins >> 28 != 0xF) or (ins & 0x0FFFFFF0) == 0x012FFF30:
            uc.reg_write(UC_ARM_REG_R0, 0)
            uc.reg_write(UC_ARM_REG_PC, addr + 4)

    mu.hook_add(UC_HOOK_CODE, on_code)
    try:
        mu.emu_start(fn, 0xA0000000)
    except UcError:
        pass
    raw = bytes(mu.mem_read(table, n * ROW))
    out = [struct.unpack_from("<II", raw, k * ROW + 12) for k in range(n)]
    if not all(a and b and elf.off(a) is not None and elf.off(b) is not None for a, b in out):
        return None
    return out


def _stride(rows, ptrs):
    """The bytes of a frame: the arrays lie end to end, so the gap from one row's frames to the next is its frames
    times the stride (the most common such stride; 0 when none fits)."""
    starts = sorted({p for pair in ptrs for p in pair})
    frames = {}
    for (_r, _p, n, _a, _b), pair in zip(rows, ptrs):
        for p in pair:
            frames[p] = n
    votes = {}
    for a, b in zip(starts, starts[1:]):
        if (b - a) % frames[a] == 0 and (b - a) // frames[a] % 3 == 0:
            s = (b - a) // frames[a]
            votes[s] = votes.get(s, 0) + 1
    return max(votes, key=votes.get) if votes else 0


def _speaker_groups(elf, fn, pixels):
    """The blade pixels each speaker light averages, off the show's own code (the function at *fn*): a dataflow of
    its byte loads, adds, shifts and stores off one base; [] when it cannot be read."""
    try:
        import capstone
        from capstone import arm as A
    except ImportError:
        return []
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    md.detail = True
    off = elf.off(fn)
    if off is None:
        return []
    regs, stores = {}, {}
    for ins in md.disasm(elf.b[off:off + 0x2000], fn):
        if ins.address != fn and ins.mnemonic == "push":
            break                                       # the next function
        ops = ins.operands
        m = ins.mnemonic
        if m == "ldrb" and len(ops) == 2 and ops[1].type == A.ARM_OP_MEM and ops[1].mem.index == 0:
            regs[ops[0].reg] = {(ops[1].mem.base, ops[1].mem.disp)}
        elif m == "add" and len(ops) == 3 and ops[1].type == A.ARM_OP_REG and ops[2].type == A.ARM_OP_REG:
            a, b = regs.get(ops[1].reg), regs.get(ops[2].reg)
            regs[ops[0].reg] = (a | b) if a and b else set()
        elif m == "lsr" and len(ops) in (2, 3) and ops[1].type == A.ARM_OP_REG:     # capstone 5: the shift on op 1
            regs[ops[0].reg] = set(regs.get(ops[1].reg) or ())
        elif m == "strb" and len(ops) == 2 and ops[1].type == A.ARM_OP_MEM and ops[1].mem.index == 0:
            src = regs.get(ops[0].reg)
            if src and len(src) >= 4:
                stores[(ops[1].mem.base, ops[1].mem.disp)] = src
        elif ops and ops[0].type == A.ARM_OP_REG and m not in ("str", "strh", "cmp", "cmn", "tst", "push"):
            regs.pop(ops[0].reg, None)
    if not stores:
        return []
    base = {b for b, _d in stores}
    if len(base) != 1:
        return []
    base = base.pop()
    srcs = [d for s in stores.values() for b, d in s if b == base]
    p0, s0 = min(srcs), min(d for _b, d in stores)
    groups = {}
    for (_b, d), src in stores.items():
        j, c = divmod(d - s0, 3)
        px = {(s - p0) // 3 for _b, s in src}
        if {(s - p0) % 3 for _b, s in src} != {c} or max(px) >= pixels:
            return []
        groups.setdefault(j, set()).update(px)
    if sorted(groups) != list(range(len(groups))):
        return []
    return [sorted(groups[j]) for j in range(len(groups))]


def read(elf):
    """The game's own song shows: ``{"table", "rows": [{"row", "request", "period", "frames", "original",
    "remix"}], "pixels", "speakers"}``, or None when the program keeps none (*elf*: a :class:`.lampmap.Elf` or the
    program's bytes)."""
    from . import lampmap as _LM
    if isinstance(elf, (bytes, bytearray, memoryview)):
        elf = _LM.Elf(elf)
    table, rows = find_table(elf)
    if table is None:
        return None
    n = len(rows)
    ptrs = [(a, b) for _r, _p, _n, a, b in rows] if all(a and b for _r, _p, _n, a, b in rows) else None
    fns = _builders(elf, table, table + n * ROW)
    for fn in fns:
        if ptrs is None:
            ptrs = _run_init(elf, fn, table, n)
    if ptrs is None:
        return None
    stride = _stride(rows, ptrs)
    if not stride:
        return None
    pixels = stride // 3
    for (_r, _p, frames, _a, _b), pair in zip(rows, ptrs):
        for p in pair:
            if elf.off(p + frames * stride - 1) is None:
                return None
    speakers = []
    for fn in fns:
        speakers = _speaker_groups(elf, fn, pixels)
        if speakers:
            break
    return {"table": table, "pixels": pixels, "speakers": speakers,
            "rows": [{"row": k, "request": r, "period": per, "frames": nf, "original": a, "remix": b}
                     for k, ((r, per, nf, _x, _y), (a, b)) in enumerate(zip(rows, ptrs))]}


def frames(elf, stock, row, which="original"):
    """The frames of *row*'s show in set *which*: bytes, ``frames * pixels * 3`` of them (R, G, B a pixel)."""
    from . import lampmap as _LM
    if isinstance(elf, (bytes, bytearray, memoryview)):
        elf = _LM.Elf(elf)
    r = stock["rows"][row]
    o = elf.off(r[which if which in SETS else "original"])
    return elf.b[o:o + r["frames"] * stock["pixels"] * 3]


def speaker_colour(frame, group):
    """A speaker light's (R, G, B) for one frame (bytes), as the game averages its blade pixels."""
    sh = max(0, len(group).bit_length() - 1)
    return tuple(sum(frame[3 * i + c] for i in group) >> sh for c in range(3))


def songs(stock):
    """The game's shows a song at a time: ``[{"req", "period", "frames", "ms"}]``, one for each pair of frames (Led
    Zeppelin plays each song by two requests over the same frames: the first is kept)."""
    out, seen = [], set()
    for r in (stock or {}).get("rows", ()):
        key = (r["original"], r["remix"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"req": r["request"], "period": r["period"], "frames": r["frames"],
                    "ms": r["period"] * r["frames"]})
    return out


def request_slots(card, requests, log=None):
    """``{request: slot}``: the sound slot (record) each song request of *card* plays first, off its request table
    and play tables (reads the card's program and sound bank: seconds). A request it cannot place is left out."""
    import shutil
    import tempfile
    from . import engine as E
    from .mode_write import request_sids
    log = log or (lambda *a: None)
    work = tempfile.mkdtemp(prefix="pad_cabstock_")
    try:
        parts = E._linux_partitions(card)
        with open(E._lp(card), "rb") as disk_f:
            gr, img, _r, _fw, _img = E._extract_inputs(disk_f, parts, work, log)
            params = E._params_for(gr, img, log, None)
            sites = E._card_descriptor_sites(gr, img, log, card_key=E._card_sites_key(disk_f, gr, img))
            plays = E._sound_id_plays(params, sites, E._desc_key_mask(params, sites))
        with open(gr, "rb") as f:
            elf = f.read()
        with open(img, "rb") as f:
            head = f.read(1 << 16)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out = {}
    for req in requests:
        for sid in request_sids(elf, head, req):
            idxs = plays.get(sid) or []
            if idxs and idxs[0] is not None:
                out[req] = idxs[0]
                break
    return out


def pixel_of(name):
    """The frame pixel a cabinet light shows (blade n: n - 1), ``("speaker", n - 1)`` for a speaker light, or None."""
    from .lampmap import cabinet_role
    got = cabinet_role(name)
    if got is None:
        return None
    role, _side, num = got
    return ("blade", num - 1) if role == "blade" else ("speaker", num - 1)
