"""Minimal read-only ext4 reader for Spike 2 SD-card partitions.

A Spike 2 card's game-data partition is an unencrypted ext4 filesystem holding
``<game>_le/game_real`` (the firmware ELF) and ``<game>_le/image.bin`` (the
packed audio container).  This walks the filesystem just enough to:

  * locate files by name (bounded recursive search from the root inode);
  * read a file out (small files in memory, large ones streamed to a path);
  * map a file byte-range to the underlying disk byte-range(s), so a
    size-neutral edit of ``image.bin`` can be written back in place without
    rewriting the filesystem.

Supports the common ext4 layout: extent-mapped inodes (the modern default) with
a fallback to classic direct/indirect block maps; 32- and 64-bit group
descriptors.  It never writes through this class — patching is done by the
caller against the disk offsets this returns.
"""

import struct

EXT4_MAGIC = 0xEF53
EXT4_EXTENTS_FL = 0x80000
S_IFMT = 0xF000
S_IFREG = 0x8000
S_IFDIR = 0x4000
INCOMPAT_64BIT = 0x80


class Ext4Error(Exception):
    pass


class Ext4Reader:
    def __init__(self, fileobj, part_offset, part_size):
        self.f = fileobj
        self.base = part_offset
        self.size = part_size
        self._read_super()
        self._read_group_desc_layout()

    # ---- low-level disk access ---------------------------------------------
    def _read(self, off, n):
        self.f.seek(self.base + off)
        return self.f.read(n)

    def _read_super(self):
        sb = self._read(1024, 1024)
        if len(sb) < 1024 or struct.unpack_from("<H", sb, 0x38)[0] != EXT4_MAGIC:
            raise Ext4Error("not an ext2/3/4 superblock")
        self.block_size = 1024 << struct.unpack_from("<I", sb, 0x18)[0]
        self.inodes_per_group = struct.unpack_from("<I", sb, 0x28)[0]
        self.blocks_per_group = struct.unpack_from("<I", sb, 0x20)[0]
        self.inode_size = struct.unpack_from("<H", sb, 0x58)[0] or 128
        self.first_data_block = struct.unpack_from("<I", sb, 0x14)[0]
        self.inodes_count = struct.unpack_from("<I", sb, 0)[0]
        feat_incompat = struct.unpack_from("<I", sb, 0x60)[0]
        self.is_64bit = bool(feat_incompat & INCOMPAT_64BIT)
        self.desc_size = struct.unpack_from("<H", sb, 0xfe)[0] if self.is_64bit else 32
        if self.desc_size < 32:
            self.desc_size = 32

    def _read_group_desc_layout(self):
        # group descriptor table starts in the block after the superblock block
        self.gdt_block = self.first_data_block + 1

    def _group_desc_inode_table(self, group):
        off = self.gdt_block * self.block_size + group * self.desc_size
        gd = self._read(off, self.desc_size)
        it_lo = struct.unpack_from("<I", gd, 8)[0]
        it_hi = struct.unpack_from("<I", gd, 0x28)[0] if self.desc_size >= 0x2c else 0
        return it_lo | (it_hi << 32)

    # ---- inodes -------------------------------------------------------------
    def read_inode(self, ino):
        group = (ino - 1) // self.inodes_per_group
        index = (ino - 1) % self.inodes_per_group
        it_block = self._group_desc_inode_table(group)
        off = it_block * self.block_size + index * self.inode_size
        raw = self._read(off, self.inode_size)
        mode = struct.unpack_from("<H", raw, 0)[0]
        size = (struct.unpack_from("<I", raw, 4)[0]
                | (struct.unpack_from("<I", raw, 0x6c)[0] << 32))
        flags = struct.unpack_from("<I", raw, 0x20)[0]
        i_block = raw[0x28:0x28 + 60]
        return dict(mode=mode, size=size, flags=flags, i_block=i_block)

    # ---- block runs (file offset -> disk) ----------------------------------
    def _extent_runs(self, i_block):
        """Walk an extent tree -> sorted list of ``(logical_block, phys_block,
        count)`` runs."""
        runs = []

        def walk(node):
            if struct.unpack_from("<H", node, 0)[0] != 0xF30A:
                raise Ext4Error("bad extent magic")
            entries = struct.unpack_from("<H", node, 2)[0]
            depth = struct.unpack_from("<H", node, 6)[0]
            for i in range(entries):
                e = 12 + i * 12
                if depth == 0:
                    log = struct.unpack_from("<I", node, e)[0]
                    ln = struct.unpack_from("<H", node, e + 4)[0]
                    if ln > 32768:           # uninitialized extent
                        ln -= 32768
                    start = (struct.unpack_from("<I", node, e + 8)[0]
                             | (struct.unpack_from("<H", node, e + 6)[0] << 32))
                    runs.append((log, start, ln))
                else:
                    leaf = (struct.unpack_from("<I", node, e + 4)[0]
                            | (struct.unpack_from("<H", node, e + 8)[0] << 32))
                    child = self._read(leaf * self.block_size, self.block_size)
                    walk(child)
        walk(bytes(i_block))
        runs.sort()
        return runs

    def _classic_runs(self, i_block, size):
        """Direct/indirect block map (ext2/3 fallback) -> runs of 1 block."""
        ptrs = list(struct.unpack_from("<15I", i_block, 0))
        nblocks = (size + self.block_size - 1) // self.block_size
        ppb = self.block_size // 4
        out = []

        def block_ptrs(blk):
            data = self._read(blk * self.block_size, self.block_size)
            return struct.unpack_from("<%dI" % ppb, data, 0)

        log = 0

        def emit(phys):
            nonlocal log
            if phys and log < nblocks:
                out.append((log, phys, 1))
            log += 1

        for i in range(12):
            emit(ptrs[i])
        if ptrs[12]:
            for p in block_ptrs(ptrs[12]):
                emit(p)
        if ptrs[13]:
            for ip in block_ptrs(ptrs[13]):
                if ip:
                    for p in block_ptrs(ip):
                        emit(p)
        if ptrs[14]:
            for dip in block_ptrs(ptrs[14]):
                if dip:
                    for ip in block_ptrs(dip):
                        if ip:
                            for p in block_ptrs(ip):
                                emit(p)
        return out

    def _runs(self, inode):
        if inode["flags"] & EXT4_EXTENTS_FL:
            return self._extent_runs(inode["i_block"])
        return self._classic_runs(inode["i_block"], inode["size"])

    def disk_ranges(self, inode, file_off, length):
        """Map ``[file_off, file_off+length)`` to absolute disk byte ranges
        ``[(disk_offset, n), ...]``.  Requires the range to be backed by
        allocated blocks (true for a packed asset file)."""
        bs = self.block_size
        out = []
        remaining = length
        pos = file_off
        runs = self._runs(inode)
        while remaining > 0:
            lblk = pos // bs
            within = pos % bs
            run = next((r for r in runs if r[0] <= lblk < r[0] + r[2]), None)
            if run is None:
                raise Ext4Error("file offset 0x%x not allocated" % pos)
            log, phys, cnt = run
            blocks_left = cnt - (lblk - log)
            avail = blocks_left * bs - within
            take = min(avail, remaining)
            disk = self.base + (phys + (lblk - log)) * bs + within
            out.append((disk, take))
            pos += take
            remaining -= take
        return out

    # ---- file content -------------------------------------------------------
    def read_file_bytes(self, inode):
        buf = bytearray(inode["size"])
        bs = self.block_size
        for log, phys, cnt in self._runs(inode):
            for j in range(cnt):
                fo = (log + j) * bs
                if fo >= inode["size"]:
                    break
                n = min(bs, inode["size"] - fo)
                buf[fo:fo + n] = self._read((phys + j) * bs, n)
        return bytes(buf)

    def extract_file(self, inode, out_path, chunk_blocks=2048, progress=None):
        """Stream a (possibly large) file to ``out_path``."""
        bs = self.block_size
        size = inode["size"]
        written = 0
        with open(out_path, "wb") as out:
            for log, phys, cnt in self._runs(inode):
                base_fo = log * bs
                if base_fo >= size:
                    continue
                # read the contiguous run in chunks
                done = 0
                while done < cnt:
                    take = min(chunk_blocks, cnt - done)
                    fo = base_fo + done * bs
                    n = min(take * bs, size - fo)
                    if n <= 0:
                        break
                    out.seek(fo)
                    out.write(self._read((phys + done) * bs, n))
                    done += take
                    written += n
                    if progress:
                        progress(min(written, size), size)
            out.truncate(size)
        return out_path

    # ---- directory walk -----------------------------------------------------
    def _iter_dir(self, inode):
        bs = self.block_size
        for log, phys, cnt in self._runs(inode):
            for j in range(cnt):
                block = self._read((phys + j) * bs, bs)
                p = 0
                while p + 8 <= len(block):
                    child = struct.unpack_from("<I", block, p)[0]
                    rec_len = struct.unpack_from("<H", block, p + 4)[0]
                    name_len = block[p + 6]
                    if rec_len < 8:
                        break
                    if child != 0 and name_len:
                        name = block[p + 8:p + 8 + name_len]
                        ftype = block[p + 7]
                        try:
                            yield name.decode("utf-8"), child, ftype
                        except UnicodeDecodeError:
                            pass
                    p += rec_len

    def peek(self, inode, n=16):
        """Return the first ``n`` bytes of a regular file (for magic sniffing)."""
        runs = self._runs(inode)
        if not runs:
            return b""
        log, phys, cnt = runs[0]
        return self._read(phys * self.block_size, n)

    def iter_regular_files(self, root_ino=2, max_depth=9, min_size=1):
        """Yield ``(path, inode_number, inode)`` for every regular file at/under
        ``root_ino`` (depth-bounded), so callers can sniff + extract assets."""
        seen = set()
        stack = [(root_ino, 0, "")]
        while stack:
            ino, depth, path = stack.pop()
            if ino in seen or depth > max_depth:
                continue
            seen.add(ino)
            try:
                node = self.read_inode(ino)
            except Exception:
                continue
            if (node["mode"] & S_IFMT) != S_IFDIR:
                continue
            for name, child, ftype in self._iter_dir(node):
                if name in (".", ".."):
                    continue
                try:
                    cn = self.read_inode(child)
                except Exception:
                    continue
                m = cn["mode"] & S_IFMT
                if m == S_IFDIR:
                    stack.append((child, depth + 1, path + "/" + name))
                elif m == S_IFREG and cn["size"] >= min_size:
                    yield path + "/" + name, child, cn

    def is_arm_elf(self, inode, min_size=0x10000):
        """True if ``inode`` is a regular file whose first bytes are a 32-bit
        ARM ELF header (so we skip the tiny ``/game`` symlink and pick the real
        firmware binary)."""
        if (inode["mode"] & S_IFMT) != S_IFREG or inode["size"] < min_size:
            return False
        runs = self._runs(inode)
        if not runs:
            return False
        log, phys, cnt = runs[0]
        hdr = self._read(phys * self.block_size, 20)
        return (hdr[:4] == b"\x7fELF" and hdr[4] == 1            # 32-bit
                and (hdr[18] | (hdr[19] << 8)) == 40)            # EM_ARM

    def find_spike_assets(self, max_depth=6, root_ino=2):
        """Locate the Spike 2 game directory — the directory holding a regular
        ``image.bin`` — and return ``(image_inode, firmware_inode)`` (inode
        numbers).  The firmware is the ARM-ELF game binary in that same
        directory (``game_real`` or ``game``; the card ships a ``game`` ELF plus
        a top-level ``game`` symlink, so we validate the ELF magic).  Either may
        be None if not found."""
        seen = set()
        queue = [(root_ino, 0)]
        while queue:
            ino, depth = queue.pop(0)
            if ino in seen or depth > max_depth:
                continue
            seen.add(ino)
            try:
                node = self.read_inode(ino)
            except Exception:
                continue
            if (node["mode"] & S_IFMT) != S_IFDIR:
                continue
            entries = [(n, c, t) for (n, c, t) in self._iter_dir(node)
                       if n not in (".", "..")]
            byname = {}
            for n, c, t in entries:
                byname.setdefault(n, (c, t))
            if "image.bin" in byname:
                img_ino = byname["image.bin"][0]
                try:
                    img_node = self.read_inode(img_ino)
                except Exception:
                    img_node = None
                if img_node and (img_node["mode"] & S_IFMT) == S_IFREG:
                    return img_ino, self._firmware_in(entries, byname)
            queue.extend((c, depth + 1) for (_n, c, t) in entries if t in (2, 0))
        return None, None

    def _firmware_in(self, entries, byname):
        for cand in ("game_real", "game"):
            if cand in byname:
                try:
                    cn = self.read_inode(byname[cand][0])
                    if self.is_arm_elf(cn):
                        return byname[cand][0]
                except Exception:
                    pass
        for n, c, t in entries:                # fallback: any ARM ELF in the dir
            try:
                if self.is_arm_elf(self.read_inode(c)):
                    return c
            except Exception:
                pass
        return None

    def find_files(self, names, max_depth=5, root_ino=2):
        """Breadth-first search from the root for the given file names.

        Returns ``{name: inode_number}`` for whatever was found (may be partial).
        Stops as soon as all names are located.
        """
        want = set(names)
        found = {}
        seen = set()
        queue = [(root_ino, 0)]
        while queue and want:
            ino, depth = queue.pop(0)
            if ino in seen or depth > max_depth:
                continue
            seen.add(ino)
            try:
                node = self.read_inode(ino)
            except Exception:
                continue
            if (node["mode"] & S_IFMT) != S_IFDIR:
                continue
            subdirs = []
            for name, child, ftype in self._iter_dir(node):
                if name in (".", ".."):
                    continue
                if name in want and name not in found:
                    found[name] = child
                    want.discard(name)
                    if not want:
                        break
                # ftype 2 == directory (when filetype feature present); 0 == unknown
                if ftype in (2, 0):
                    subdirs.append(child)
            queue.extend((c, depth + 1) for c in subdirs)
        return found
