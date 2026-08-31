"""Extract the Spike 1 node-board topology straight from a game ELF.

The Spike 1 firmware carries, in its own (unstripped) symbol table, the exact
map the node-bus responder needs to make every board register as the right
*type*:

  * ``node_board_table_data``  — one 16-byte entry per expected board:
        +12 u16  board TYPE
        +14 u8   node bus ADDRESS   (<= 31)
    (entry 0 is an empty terminator; count = ``NODE_BOARD_TABLE_DATA_ENTRY_COUNT``)
  * ``node_board_type_table_data`` — one 20-byte entry per type:
        +4  u32  numeric PART NUMBER  (a 9-digit id, e.g. 520693600 = "520-6936-00")
    (count = ``NODE_BOARD_TYPE_TABLE_DATA_ENTRY_COUNT``)

The game asks each node ``NODEBUS_GetFullBoardID`` (cmd 0xf9) and feeds the part
number it reports to ``sys_node_board_type_get_from_part_number``, which matches
on ``part // 100`` (the low two digits are the board revision) to recover the
type; that type then selects the node's firmware image AND builds its switch
map.  So a responder that returns, for each node address, the part number of the
type the game *expects* there makes the whole topology validate — which clears
the "CHECK POWER DISTRIBUTION BOARD" tech alert and lets the switch matrix come
alive.  This was all reverse-engineered from the game ELF, not invented; see
docs/architecture/spike1_emulation.md.

Pure ``struct`` — no third-party ELF library — so it runs under the rig's WSL
python3 with nothing installed.  Title-agnostic: it keys off framework symbol
names (identical across titles), so GOT, Ghostbusters, etc. each yield their own
topology from their own ELF.

    from s1elf import extract_topology
    topo = extract_topology("/path/to/game")   # {addr: {"type": t, "part": n}}

CLI: ``python s1elf.py <game-elf>`` prints ``addr type part`` per board.
"""

import struct
import sys

# ELF32 little-endian only (the Spike 1 game is armel EABI5, ELFCLASS32/LSB).
_EHDR = struct.Struct("<16sHHIIIIIHHHHHH")     # e_ident..e_shstrndx
_SHDR = struct.Struct("<10I")                  # section header (40 bytes)
_SYM = struct.Struct("<IIIBBH")                # Elf32_Sym (16 bytes)
SHT_SYMTAB = 2

BOARD_ENTRY = 16       # node_board_table_data stride
TYPE_ENTRY = 20        # node_board_type_table_data stride
_BOARD_TYPE_OFF = 12   # u16 board type within a board entry
_BOARD_ADDR_OFF = 14   # u8 node address within a board entry
_TYPE_PART_OFF = 4     # u32 part number within a type entry

# ---- switch map (physical node/index -> human switch name) ----------------
# Decoded from the game's own switch-map builder + input applier (not guessed):
#   sys_node_build_switch_map (game ELF @0x743a0) walks, per switch id t:
#     nbd  = node_board_device_sw_table_data[t]          (stride 52)
#     devid= u16 @ nbd+0x22
#     dev  = node_board_device_table_data[devid]         (stride 24)
#     board= node_board_table_data[ u16 @ dev+0x10 ]     (stride 16)
#     node = u8  @ board+0x0e                            (== s1elf _BOARD_ADDR_OFF)
#   sys_node_board_device_switch_update_inputs (@0x62c2c) reads the raw node-bus
#   switch bytes with the bit position at dev+0x16 (bounded <=63: the game fatals
#   above that), byte = pos>>3, bit = pos&7 — the SAME active-low scheme the
#   responder/window inject, so (node, pos) is exactly what a click must close.
#   The human name is switch_table_data[t]+0x08 -> a localized name block whose
#   first pointer is the English string.
SWDEV_ENTRY = 52       # node_board_device_sw_table_data stride
_SWDEV_DEVID_OFF = 0x22  # u16 device id within a device-switch entry
DEV_ENTRY = 24         # node_board_device_table_data stride
_DEV_POS_OFF = 0x16    # u16 node-local bit position (<=63) within a device entry
_DEV_BOARD_OFF = 0x10  # u16 board id within a device entry
SWTAB_ENTRY = 32       # switch_table_data stride
_SWTAB_NAME_OFF = 0x08  # ptr to the switch's (localized) name block
_SW_POS_MAX = 63       # the game fatals on a bit position above this


class _Elf:
    """Minimal ELF32-LE reader: symbol table + virtual-address reads."""

    def __init__(self, data):
        if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
            raise ValueError("not an ELF32 little-endian file")
        self.data = data
        (_, _type, _mach, _ver, _entry, _phoff, shoff, _flags, _ehsize,
         _phes, _phn, shentsize, shnum, shstrndx) = _EHDR.unpack_from(data, 0)
        self.sections = []
        for i in range(shnum):
            (name, styp, flags, addr, off, size, link, info, align,
             entsize) = _SHDR.unpack_from(data, shoff + i * shentsize)
            self.sections.append(dict(name=name, type=styp, addr=addr,
                                      off=off, size=size, link=link,
                                      entsize=entsize))
        self.syms = self._read_symbols()

    def _read_symbols(self):
        out = {}
        for sh in self.sections:
            if sh["type"] != SHT_SYMTAB:
                continue
            strtab = self.sections[sh["link"]]
            base, end = sh["off"], sh["off"] + sh["size"]
            stroff = strtab["off"]
            for o in range(base, end, _SYM.size):
                st_name, st_value, _sz, _info, _oth, _shndx = \
                    _SYM.unpack_from(self.data, o)
                if not st_name or not st_value:
                    continue
                nend = self.data.index(b"\x00", stroff + st_name)
                name = self.data[stroff + st_name:nend].decode("latin1")
                # first definition wins (globals over locals is close enough)
                out.setdefault(name, st_value)
        return out

    def read_vaddr(self, vaddr, n):
        """Bytes at a virtual address, from whichever PROGBITS section maps it."""
        for sh in self.sections:
            if sh["off"] == 0 or sh["addr"] == 0:
                continue
            if sh["addr"] <= vaddr < sh["addr"] + sh["size"]:
                start = sh["off"] + (vaddr - sh["addr"])
                return self.data[start:start + n]
        raise ValueError("vaddr 0x%x not in any section" % vaddr)

    def read_u32(self, vaddr):
        return struct.unpack("<I", self.read_vaddr(vaddr, 4))[0]

    def read_u16(self, vaddr):
        return struct.unpack("<H", self.read_vaddr(vaddr, 2))[0]

    def read_u8(self, vaddr):
        return self.read_vaddr(vaddr, 1)[0]

    def read_cstr(self, vaddr, maxn=48):
        """A printable NUL-terminated string at vaddr, or None."""
        try:
            b = self.read_vaddr(vaddr, maxn)
        except ValueError:
            return None
        i = b.find(b"\x00")
        s = b[: i if i >= 0 else maxn]
        if s and all(9 <= c < 127 for c in s):
            return s.decode("latin1")
        return None


def extract_topology(path):
    """Return ``{node_addr: {"type": int, "part": int}}`` for a game ELF.

    ``part`` is the numeric board part number the responder should report for
    that node in its cmd-0xf9 reply.  Raises on a non-Spike-1 / stripped ELF or
    a missing table symbol (the caller falls back to a bare responder)."""
    with open(path, "rb") as f:
        elf = _Elf(f.read())
    s = elf.syms
    need = ("node_board_table_data", "NODE_BOARD_TABLE_DATA_ENTRY_COUNT",
            "node_board_type_table_data",
            "NODE_BOARD_TYPE_TABLE_DATA_ENTRY_COUNT")
    missing = [n for n in need if n not in s]
    if missing:
        raise ValueError("ELF lacks node-board table symbols: %s"
                         % ", ".join(missing))

    n_boards = elf.read_u32(s["NODE_BOARD_TABLE_DATA_ENTRY_COUNT"])
    n_types = elf.read_u32(s["NODE_BOARD_TYPE_TABLE_DATA_ENTRY_COUNT"])
    if not (0 < n_boards <= 64) or not (0 < n_types <= 256):
        raise ValueError("implausible table counts: boards=%d types=%d"
                         % (n_boards, n_types))

    board_blob = elf.read_vaddr(s["node_board_table_data"],
                                n_boards * BOARD_ENTRY)
    type_blob = elf.read_vaddr(s["node_board_type_table_data"],
                               n_types * TYPE_ENTRY)

    type_part = []
    for t in range(n_types):
        off = t * TYPE_ENTRY + _TYPE_PART_OFF
        type_part.append(struct.unpack_from("<I", type_blob, off)[0])

    # The 16-byte board entry was RE-LAID-OUT between framework eras:
    #   * 0.52-era (GOT/GBLE/KISS):  [u32][u32 name][u32] [u16 type @12][u8 addr @14][u8]
    #   * 0.18-era (WWE LE 1.35):    [u32 name][u32]      [u16 type @8][u16] [u32 addr @12]
    # Decoding WWE with the 0.52 offsets read the addr word's halves as
    # type/addr and yielded ONE bogus board — so the responder's identify
    # scan handed out nothing, the game never set any node's scan-enable
    # flag, and the matrix was never polled (cmd 0x11 stuck at one per
    # node).  Decode BOTH layouts and keep whichever yields more valid,
    # distinct boards; ties go to the 0.52 layout (the previously verified
    # behaviour).  Part numbers ride the 0.52 type table only — the 0.18
    # type table has yet another stride, and WWE's boot accepts part 0.
    def _decode(layout):
        topo = {}
        for i in range(n_boards):
            base = i * BOARD_ENTRY
            if layout == "v52":
                btype = struct.unpack_from("<H", board_blob,
                                           base + _BOARD_TYPE_OFF)[0]
                addr = board_blob[base + _BOARD_ADDR_OFF]
            else:
                btype = struct.unpack_from("<H", board_blob, base + 8)[0]
                addr = struct.unpack_from("<I", board_blob, base + 12)[0]
            if btype == 0 or btype > 0xFF or addr > 31:
                continue
            part = (type_part[btype]
                    if layout == "v52" and btype < n_types else 0)
            topo[addr] = {"type": btype, "part": part}
        return topo

    v52, v18 = _decode("v52"), _decode("v18")
    return v52 if len(v52) >= len(v18) else v18


def extract_switch_map(path):
    """Return ``{(node, index): name}`` for a game ELF: the human name of every
    switch, keyed by the (node address, node-local bit position) a click must
    close.  Title-agnostic (framework symbols + offsets decoded from the game's
    own build/apply code — see the module notes above).

    Best-effort: returns ``{}`` if the ELF lacks the switch symbols, and simply
    skips any individual switch whose chain doesn't resolve (an unmapped or
    name-less entry), so a partial map is better than none."""
    with open(path, "rb") as f:
        elf = _Elf(f.read())
    s = elf.syms
    need = ("SWITCH_TABLE_DATA_ENTRY_COUNT", "switch_table_data",
            "node_board_device_sw_table_data", "node_board_device_table_data",
            "node_board_table_data")
    if any(n not in s for n in need):
        return {}
    try:
        count = elf.read_u32(s["SWITCH_TABLE_DATA_ENTRY_COUNT"])
    except ValueError:
        return {}
    if not (0 < count <= 512):
        return {}
    swdev = s["node_board_device_sw_table_data"]
    dev = s["node_board_device_table_data"]
    board = s["node_board_table_data"]
    swtab = s["switch_table_data"]

    out = {}
    for t in range(1, count):                    # entry 0 is the INVALID sentinel
        try:
            devid = elf.read_u16(swdev + SWDEV_ENTRY * t + _SWDEV_DEVID_OFF)
            if devid == 0:
                continue
            dev_e = dev + DEV_ENTRY * devid
            pos = elf.read_u16(dev_e + _DEV_POS_OFF) & 0xFF
            if pos > _SW_POS_MAX:
                continue
            boardid = elf.read_u16(dev_e + _DEV_BOARD_OFF)
            node = elf.read_u8(board + BOARD_ENTRY * boardid + _BOARD_ADDR_OFF)
            if node > 31:
                continue
            name_block = elf.read_u32(swtab + SWTAB_ENTRY * t + _SWTAB_NAME_OFF)
            # the block's first pointer is the English name; fall back to a
            # direct string if the field points straight at one.
            name = elf.read_cstr(elf.read_u32(name_block)) or elf.read_cstr(name_block)
        except (ValueError, struct.error):
            continue
        if name:
            out[(node, pos)] = name
    return out


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: s1elf.py [--switches] <game-elf>", file=sys.stderr)
        return 2
    if argv[0] == "--switches":
        import json
        smap = extract_switch_map(argv[1])
        # JSON keys must be strings: "node,index"
        print(json.dumps({"%d,%d" % k: v for k, v in sorted(smap.items())},
                         indent=0))
        return 0
    topo = extract_topology(argv[0])
    print("addr type part        part_string")
    for addr in sorted(topo):
        t = topo[addr]
        p = t["part"]
        s9 = "%09d" % p if p else "0"
        pretty = "%s-%s-%s" % (s9[:3], s9[3:7], s9[7:]) if p else "-"
        print("%4d %4d %-11d %s" % (addr, t["type"], p, pretty))
    return 0


if __name__ == "__main__":
    sys.exit(main())
