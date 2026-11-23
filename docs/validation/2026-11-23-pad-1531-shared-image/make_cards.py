"""PAD-1531 stand-in proof, part 1 (run under WSL python3): three small Spike 2 cards from a stock card's real
boot + system partitions, with a /data and /dump a machine in use would have.

  A  the builder's own card: remote access on, letting in the builder's key (an image they then share)
  B  A after the recipient's one-button "Set up remote access on this card" (recipient's own PAD key)
  C  a build for sharing made from A

usage: make_cards.py <repo> <work> <stock card>"""
import os
import shutil
import struct
import subprocess
import sys

repo, work, stock = sys.argv[1:4]
sys.path.insert(0, repo)
from pinball_decryptor.core import pad_ssh_key, remote_setup, share_build  # noqa: E402
from pinball_decryptor.core import ssh_card as S  # noqa: E402

MiB = 1 << 20


def entry(ptype, start, count):
    return struct.pack('<B3sB3sII', 0, b'\0' * 3, ptype, b'\0' * 3, start, count)


def fs(name, size, files):
    tree = os.path.join(work, name + '-tree')
    for rel, data in files.items():
        p = os.path.join(tree, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(data)
    img = os.path.join(work, name + '.img')
    with open(img, 'wb') as f:
        f.truncate(size)
    subprocess.run(['mke2fs', '-q', '-t', 'ext4', '-F', '-d', tree, img], check=True)
    return open(img, 'rb').read()


with open(stock, 'rb') as f:
    mbr = f.read(512)
    p1 = struct.unpack_from('<II', mbr, 446 + 8)
    p2 = struct.unpack_from('<II', mbr, 462 + 8)
    head_end = p2[0] + p2[1]
    f.seek(0)
    head = f.read(head_end * 512)
data = fs('data', 8 * MiB, {'dropbear/dropbear_ed25519_host_key': os.urandom(83),
                            'nv/deadpool_le/NVM': b'builder settings, scores and wifi network' * 50})
dump = fs('dump', 8 * MiB, {'log/connectivity/game.log': b'builder machine 192.168.1.20\n' * 50})
p3, ext = head_end, head_end + 2048
p5, ebr2 = ext + 2048, ext + 2048 + 16384
p6, end = ebr2 + 2048, ebr2 + 2048 + 16384
table = entry(0x0c, *p1) + entry(0x83, *p2) + entry(0x83, p3, 2048) + entry(0x0f, ext, end - ext)
ebr1 = bytearray(512); ebr1[510:] = b'\x55\xaa'
ebr1[446:478] = entry(0x83, 2048, 16384) + entry(0x05, ebr2 - ext, end - ebr2)
ebr_2 = bytearray(512); ebr_2[510:] = b'\x55\xaa'
ebr_2[446:462] = entry(0x83, 2048, 16384)
base = os.path.join(work, 'stock.raw')
with open(base, 'wb') as f:
    f.truncate(end * 512)
    f.write(head)
    f.seek(446); f.write(table)
    for lba, blob in ((p3, b'GAME' * 1024), (ext, ebr1), (p5, data), (ebr2, ebr_2), (p6, dump)):
        f.seek(lba * 512); f.write(blob)

A, B, C = (os.path.join(work, n + '.raw') for n in 'ABC')
# the builder
pad_ssh_key.KEY_DIR = os.path.join(work, 'builder')
builder = pad_ssh_key.public_line().strip()
shutil.copyfile(base, A)
S.apply_to_build(base, A, {'enabled': True, 'public_keys': builder})
print('A builder card:', S.inspect_image(A)['enabled'], S.inspect_image(A)['public_keys'].split()[2:])
# the builder makes a build for sharing from it
shutil.copyfile(A, C)
said = S.apply_to_build(A, C, {'enabled': False, 'public_keys': '', 'share': True})
st = S.inspect_image(C)
print('C shared build:', said)
print('C reads back: remote on=%s keys=%r machine data=%r' % (st['enabled'], st['public_keys'],
                                                               share_build.machine_data(C)))
# the recipient: A arrives, one-button setup with their own PAD key
pad_ssh_key.KEY_DIR = os.path.join(work, 'recipient')
recipient = pad_ssh_key.public_line().strip()
shutil.copyfile(A, B)
print('B before setup, look():', remote_setup.look(B))
remote_setup.set_up(B, log=lambda t, l='info': print('  setup [%s] %s' % (l, t)))
keys = S.inspect_image(B)['public_keys']
print('B after setup trusts: builder=%s recipient=%s' % (builder.split()[1] in keys, recipient.split()[1] in keys))
print('P2 offset/size', p2[0] * 512, p2[1] * 512)
