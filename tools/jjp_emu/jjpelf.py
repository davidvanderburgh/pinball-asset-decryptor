#!/usr/bin/env python3
"""Read symbols out of a JJP game ELF whose section headers are stripped.

The retail binary is Sentinel LDK Envelope-wrapped: the section table is
replaced by a single ``protect`` PROGBITS entry (``e_shnum`` = 2), so ``nm``,
``readelf -s`` and every ordinary tool return nothing at all.  The *dynamic*
symbol table survives, though, because the loader needs it - it is simply not
reachable through section headers.  This module rebuilds it from ``PT_DYNAMIC``.

Two details matter and are easy to get wrong:

* The symbol count comes from ``DT_HASH``'s ``nchain``.  There is no other
  bound; walking until "it looks wrong" runs off the end of ``.dynsym`` into
  unrelated bytes and throws on the first string lookup.
* Symbol *values* are absolute.  The binary is ``ET_EXEC`` (non-PIE, base
  0x400000), so an address read here is the same address in a running process -
  no ASLR slide to add.  That is what makes the live-memory tools work.
"""

import struct


class GameElf:
    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as fh:
            self.data = fh.read()
        d = self.data
        if d[:4] != b'\x7fELF':
            raise ValueError(f"{path}: not an ELF")
        self.machine, = struct.unpack_from('<H', d, 0x12)
        self.etype, = struct.unpack_from('<H', d, 0x10)
        phoff = struct.unpack_from('<Q', d, 0x20)[0]
        phentsize, phnum = struct.unpack_from('<HH', d, 0x36)

        self.loads = []
        dyn_off = None
        for i in range(phnum):
            o = phoff + i * phentsize
            ptype, = struct.unpack_from('<I', d, o)
            off, vaddr, _paddr, filesz = struct.unpack_from('<QQQQ', d, o + 8)
            if ptype == 1:                      # PT_LOAD
                self.loads.append((vaddr, off, filesz))
            elif ptype == 2:                    # PT_DYNAMIC
                dyn_off = off
        if dyn_off is None:
            raise ValueError(f"{path}: no PT_DYNAMIC")

        symtab = strtab = syment = hashv = strsz = None
        p = dyn_off
        while True:
            tag, val = struct.unpack_from('<Qq', d, p)
            p += 16
            if tag == 0:
                break
            elif tag == 4:  hashv = val         # DT_HASH
            elif tag == 5:  strtab = val        # DT_STRTAB
            elif tag == 6:  symtab = val        # DT_SYMTAB
            elif tag == 10: strsz = val         # DT_STRSZ
            elif tag == 11: syment = val        # DT_SYMENT
        if None in (symtab, strtab, syment, hashv, strsz):
            raise ValueError(f"{path}: incomplete DT_ entries")

        so, st, ho = self.v2o(symtab), self.v2o(strtab), self.v2o(hashv)
        _nbucket, nchain = struct.unpack_from('<II', d, ho)
        self.nsyms = nchain

        self.syms = {}       # name -> (addr, size)
        self.by_addr = {}    # addr -> name (first wins)
        for i in range(nchain):
            o = so + i * syment
            nm, _info, _other, _shndx, value, size = struct.unpack_from('<IBBHQQ', d, o)
            if not nm or nm >= strsz:
                continue
            end = d.index(b'\0', st + nm)
            name = d[st + nm:end].decode('latin1')
            self.syms[name] = (value, size)
            if value:
                self.by_addr.setdefault(value, name)

    def v2o(self, vaddr):
        """Virtual address -> file offset, or None if not in a PT_LOAD."""
        for va, off, sz in self.loads:
            if va <= vaddr < va + sz:
                return off + (vaddr - va)
        return None

    def addr(self, name):
        return self.syms[name][0]

    def size(self, name):
        return self.syms[name][1]

    def read(self, vaddr, n):
        """Read from the FILE image (zeroed for .bss-style objects)."""
        o = self.v2o(vaddr)
        if o is None:
            return b'\x00' * n
        return self.data[o:o + n]

    def names_matching(self, prefix):
        return sorted(n for n in self.syms if n.startswith(prefix))
