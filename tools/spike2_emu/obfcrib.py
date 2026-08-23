#!/usr/bin/env python3
r"""obfcrib.py [crib ...] - find an obfuscated string in ANY title's ELF, with
no key and no descriptor-table address.

    obfcrib.py                       # the validation messages, the default set
    obfcrib.py "Tech Alerts"         # any plaintext you already know
    PAD_GAME=turtles_pro obfcrib.py  # gameinfo.py picks the ELF
    obfcrib.py --elf /path/to/game   # or name it, bypassing gameinfo entirely

`--elf` is not just a convenience. `gameinfo.elf()` prefers what the last run
PUBLISHED, and `dump/title` outlives the run - so after a card run ends it can
name a title directory inside an unmounted FUSE mount, and every tool that
trusts it reports "no game ELF" about a title sitting extracted in the rootfs.

WHY THIS EXISTS, next to obfstr.py and obfstr2.py. Both of those need something
this one does not:

  * `obfstr.py` dumps the descriptor table, so it needs the TABLE ADDRESS.
  * `obfstr2.py` recovers a key from ciphertext by printability, so it needs
    the BLOB ADDRESS to aim at.

On a second title neither address is known, and the strings are encrypted so
nothing can be grepped - which is what made item 62 conclude that godzilla's
validation instruments were "title-locked" and the turtles module would have to
be reverse-engineered from scratch. It did not.

THE TRICK. The obfuscation is

    out[i] = key[i & 3] ^ c[i] ^ c[i-1]        for i >= 1

so writing x[i] = c[i] ^ c[i-1] gives x[i] = key[i&3] ^ out[i]. For any two
indices in the SAME residue class mod 4 the key cancels:

    x[i] ^ x[i+4]  ==  out[i] ^ out[i+4]

That is a signature of the PLAINTEXT ALONE. A message whose text is already
known from another title therefore locates its own ciphertext in a new binary
by a plain scan, and the key drops out of the match for free. Index 0 is
excluded throughout: it is produced by a different formula
(out[0] = key[0] ^ c[0] ^ key[i2] ^ key[i3]) whose (i2,i3) pair is per-site, so
the first character is reported as the set of printable possibilities.

A crib needs ~8 characters before the signature is specific enough to avoid
coincidental hits; short ones like './game' will match everywhere and are
reported with a warning rather than silently trusted.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gameinfo

#: The eight validation strings, recovered from godzilla_pro 1.15.0. These are
#: the useful default because they are the ones that pin down a title's
#: descriptor table, and from the table everything else in the module follows.
DEFAULT = [
    'Game validation error, Update SD card',
    'Game validation error\nUpdate SD card',
    'GAME VALIDATION ERROR\n#1 UPDATE SD CARD',
    'GAME VALIDATION ERROR\n#2 UPDATE SD CARD',
    'GAME VALIDATION ERROR\n#3 UPDATE SD CARD',
    'GAME VALIDATION ERROR\n#4 %d:%d UPDATE SD CARD',
    'GAME VALIDATION ERROR\n#5 %d:%d UPDATE SD CARD',
    'GAME VALIDATION ERROR\n#6 %d:%d:%d UPDATE SD CARD',
    '/mnt/boot/zImage',
    '/bin/mount /dev/mmcblk0p1 /mnt/boot',
    '/bin/umount /mnt/boot',
]

MIN_CRIB = 8


def phdrs(d):
    """[(file_off, vaddr, filesz)] for each PT_LOAD, read from the ELF itself.

    Hard-coding one title's segment table is exactly the kind of constant this
    script exists to stop carrying.
    """
    import struct
    if d[:4] != b'\x7fELF':
        raise SystemExit('not an ELF')
    e_phoff = struct.unpack_from('<I', d, 0x1c)[0]
    e_phentsize = struct.unpack_from('<H', d, 0x2a)[0]
    e_phnum = struct.unpack_from('<H', d, 0x2c)[0]
    out = []
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        p_type, p_off, p_vaddr, _pa, p_filesz = struct.unpack_from('<5I', d, o)
        if p_type == 1:
            out.append((p_off, p_vaddr, p_filesz))
    return out


def main():
    argv = sys.argv[1:]
    path = None
    if argv and argv[0] == '--elf':
        if len(argv) < 2:
            raise SystemExit('obfcrib.py: --elf needs a path')
        path, argv = argv[1], argv[2:]
    else:
        path = gameinfo.elf()
        # A published path that no longer exists is the stale-dump/title case in
        # the header; the extracted copy is the honest second answer.
        if path and not os.path.exists(path):
            name = gameinfo.active()
            alt = os.path.join(gameinfo.root() or '', 'games', name or '', 'game')
            if os.path.exists(alt):
                print('obfcrib.py: published ELF is gone (%s)\n'
                      '            falling back to the extracted copy' % path,
                      file=sys.stderr)
                path = alt
    if not path or not os.path.exists(path):
        raise SystemExit('obfcrib.py: no game ELF (set PAD_GAME, pass --elf, '
                         'or start a run)')
    d = open(path, 'rb').read()
    segs = phdrs(d)

    def off2va(off):
        for o, va, sz in segs:
            if o <= off < o + sz:
                return va + (off - o)
        return None

    # x[i] = c[i] ^ c[i-1] over the whole file, computed once.
    x = bytearray(len(d))
    for i in range(1, len(d)):
        x[i] = d[i] ^ d[i - 1]

    cribs = argv or DEFAULT
    print('ELF: %s' % path)
    for crib in cribs:
        text = crib.encode().decode('unicode_escape').encode('latin-1') \
            if '\\' in crib else crib.encode()
        n = len(text)
        if n < MIN_CRIB:
            print('%-52r  SKIPPED - under %d chars, would match noise'
                  % (crib, MIN_CRIB))
            continue
        sig = bytes(text[k] ^ text[k + 4] for k in range(1, n - 4))
        hits = []
        for c in range(1, len(d) - n - 8):
            for k in range(1, n - 4):
                if (x[c + k] ^ x[c + k + 4]) != sig[k - 1]:
                    break
            else:
                hits.append(c)
        if not hits:
            print('%-52r  NOT FOUND' % crib)
            continue
        for c in hits:
            key = [0] * 4
            for i in range(1, n):
                key[i & 3] = x[c + i] ^ text[i]
            first = sorted({chr(key[0] ^ d[c] ^ key[a] ^ key[b])
                            for a in range(4) for b in range(4)
                            if 32 <= (key[0] ^ d[c] ^ key[a] ^ key[b]) < 127})
            va = off2va(c)
            print('%-52r  vaddr %s  key=%02x%02x%02x%02x  first=%s'
                  % (crib, ('0x%06x' % va) if va else '(not in a PT_LOAD)',
                     key[3], key[2], key[1], key[0], ''.join(first) or '?'))
        if len(hits) > 1:
            print('    ^ %d hits - a crib this short can collide; prefer the one'
                  ' whose neighbours are the rest of the table' % len(hits))
        sys.stdout.flush()


if __name__ == '__main__':
    main()
