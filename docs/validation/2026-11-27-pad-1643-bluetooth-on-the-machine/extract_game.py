"""PAD-1643 stand-in, part 0 (Windows python, the library card is only read): the stock card's real game program,
the file /games/game leads to, written out so the stand-in machine can hold it where the real one does.

usage: extract_game.py <repo> <stock card> <out file>"""
import hashlib
import stat
import sys

repo, stock, out = sys.argv[1:4]
sys.path.insert(0, repo)
from pinball_decryptor.core import ssh_card  # noqa: E402
from pinball_decryptor.plugins.stern.ext4 import Ext4Reader  # noqa: E402

with open(stock, 'rb') as f:
    parts = ssh_card._partitions(f)
    p3 = next(p for p in parts if p[0] == 3)
    r = Ext4Reader(f, p3[2], p3[3])
    node = ssh_card._node(r, '/game')
    target = ''
    while stat.S_IFMT(node['mode']) == stat.S_IFLNK:
        target = r.read_symlink(node)
        target = target.decode() if isinstance(target, bytes) else target
        node = ssh_card._node(r, target if target.startswith('/') else '/' + target)
    digest, size = hashlib.sha256(), 0
    with open(out, 'wb') as o:
        for _off, chunk in r.read_file_chunks(node):
            o.write(chunk)
            digest.update(chunk)
            size += len(chunk)
print('GAME link %s size %d sha256 %s' % (target, size, digest.hexdigest()))
