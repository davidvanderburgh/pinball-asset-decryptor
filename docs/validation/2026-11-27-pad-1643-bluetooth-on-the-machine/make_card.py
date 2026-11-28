"""PAD-1643 stand-in, part 1 (WSL python3): a small Spike 2 card from the stock Godzilla Pro 1.16 card's real boot +
system partitions, with remote access on for this proof's own PAD key (the app's own ssh_card.apply_to_build).

usage: make_card.py <repo> <work> <stock card>"""
import os
import struct
import subprocess
import sys

repo, work, stock = sys.argv[1:4]
sys.path.insert(0, repo)
from pinball_decryptor.core import pad_ssh_key  # noqa: E402
from pinball_decryptor.core import ssh_card as S  # noqa: E402

MiB = 1 << 20


def entry(ptype, start, count):
    return struct.pack('<B3sB3sII', 0, b'\0' * 3, ptype, b'\0' * 3, start, count)


def fs(name, size):
    tree = os.path.join(work, name + '-tree')
    os.makedirs(tree, exist_ok=True)
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
data, dump = fs('data', 8 * MiB), fs('dump', 8 * MiB)
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

card = os.path.join(work, 'machine.raw')
pad_ssh_key.KEY_DIR = os.path.join(work, 'pc')
mine = pad_ssh_key.public_line().strip()
import shutil; shutil.copyfile(base, card)
S.apply_to_build(base, card, {'enabled': True, 'public_keys': mine})
st = S.inspect_image(card)
print('card: remote access on=%s, lets in this PC=%s' % (st['enabled'], mine.split()[1] in st['public_keys']))
print('P2 offset/size', p2[0] * 512, p2[1] * 512)

# PAD-1643: the card as it was (to compare with after the plugin is taken off again), and its twin with the plugin
# put on the way a card write puts it (bluetooth_card.apply_to_build), to compare the machine's card with
from pinball_decryptor.core import bluetooth_card as BT  # noqa: E402
shutil.copyfile(card, os.path.join(work, 'before.raw'))
twin = os.path.join(work, 'twin.raw')
shutil.copyfile(card, twin)
print('twin:', BT.apply_to_build(card, twin, {'enabled': True}))
st = BT.inspect_image(twin)
print('twin: plugin on=%s release=%s' % (st['enabled'], st['release']))
