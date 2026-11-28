"""PAD-1643 Spike 3 stand-in, part 1 (WSL python3): the real Fallout LE 0.82 card's system partition, unlocked
with the user's own key on the Windows side (ssh_spike3.export_rootfs; the library card is only read), given
remote access for this proof's own PAD key the way a build gives it (ssh_card.prepare_rootfs), and its twin with
the plugin put on the way a card write puts it (bluetooth_card.prepare_rootfs).

usage: make_s3.py <repo> <work> <unlocked system partition>"""
import os
import shutil
import sys
from pathlib import Path

repo, work, plain = sys.argv[1:4]
sys.path.insert(0, repo)
from pinball_decryptor.core import bluetooth_card as BT, card_plugins as P, pad_ssh_key  # noqa: E402
from pinball_decryptor.core import ssh_card as S  # noqa: E402

pad_ssh_key.KEY_DIR = os.path.join(work, 'pc')
mine = pad_ssh_key.public_line().strip()
machine = os.path.join(work, 'machine.img')
shutil.copyfile(plain, machine)
for n in ('w1', 'w2'):
    os.makedirs(os.path.join(work, n), exist_ok=True)
S.prepare_rootfs(Path(machine), Path(work) / 'w1', {'enabled': True, 'public_keys': mine}, platform='stern-spike3')
print('machine: remote access put on the unlocked system partition (%d MB)' % (os.path.getsize(machine) >> 20))
shutil.copyfile(machine, os.path.join(work, 'before.img'))
twin = os.path.join(work, 'twin.img')
shutil.copyfile(machine, twin)
tag, members = P.files(BT.PLUGIN, 'arm64')
BT.prepare_rootfs(Path(twin), Path(work) / 'w2', True, members, tag, platform=BT.SPIKE3)
print('twin: plugin %s put on as a card write puts it' % tag)
