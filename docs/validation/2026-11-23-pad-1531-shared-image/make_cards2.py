"""PAD-1531 stand-in proof, part 2 (run under WSL python3 after make_cards.py): existing remote access people set up
for themselves keeps working.

  D  one person, two computers with PAD: the desktop sets the card up, then the laptop does; asked about the
     desktop's key, the laptop answers Keep
  E  the same, but the laptop answers Take it off
  F  someone who already had remote access (set up from their desktop) rebuilds their card from their project, with
     Keep remote access on

usage: make_cards2.py <repo> <work>"""
import os
import shutil
import sys

repo, work = sys.argv[1:3]
sys.path.insert(0, repo)
from pinball_decryptor.core import card_extras, pad_ssh_key, remote_setup  # noqa: E402
from pinball_decryptor.core import ssh_card as S  # noqa: E402

stock = os.path.join(work, 'stock.raw')
D, E, F = (os.path.join(work, n + '.raw') for n in 'DEF')


def as_pc(name):
    pad_ssh_key.KEY_DIR = os.path.join(work, name)
    return pad_ssh_key.public_line().strip()


desktop, laptop = as_pc('desktop'), as_pc('laptop')
names = {desktop.split()[1]: 'desktop', laptop.split()[1]: 'laptop'}


def trusts(path):
    keys = S.inspect_image(path)['public_keys']
    return sorted(n for b, n in names.items() if b in keys)


shutil.copyfile(stock, D)
as_pc('desktop')
print('D desktop setup:', remote_setup.set_up(D))
as_pc('laptop')
res = remote_setup.set_up(D)
print('D laptop setup asks about:', [card_extras.key_name(k) for k in remote_setup.asked(res) or []],
      '(card unchanged until answered)')
print('D laptop answers Keep:', remote_setup.set_up(D, keep_others=True), '-> card trusts', trusts(D))
print('D laptop presses again (kept key now saved with its project):', remote_setup.set_up(D, own=desktop))

shutil.copyfile(stock, E)
as_pc('desktop'); remote_setup.set_up(E)
as_pc('laptop')
print('E laptop answers Take it off:', remote_setup.set_up(E, keep_others=False), '-> card trusts', trusts(E))

as_pc('desktop')
own = os.path.join(work, 'own.raw')
shutil.copyfile(stock, own)
remote_setup.set_up(own)                                    # the card they already had
project = os.path.join(work, 'project'); os.makedirs(project, exist_ok=True)
card_extras.save(project, True, '')                         # what one-button setup saves with the project
shutil.copyfile(own, F)
S.apply_to_build(own, F, card_extras.configuration(project))
print('F rebuilt from the project:', S.inspect_image(F)['enabled'], '-> card trusts', trusts(F))
