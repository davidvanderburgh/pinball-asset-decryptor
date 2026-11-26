"""PAD-1587 proof: a minimal JJP Wonka project (one changed system file) with remote access on."""
import hashlib
import io
import os
import subprocess
import sys

WT = r'C:\Users\david\Documents\development\pad-triage\work\tickets\PAD-1587'
sys.path.insert(0, WT)
from PIL import Image, ImageDraw  # noqa: E402

from pinball_decryptor.core import card_extras  # noqa: E402

PROJ = r'C:\tmp\PAD-1587\proj'
REL = 'system/jjpe/gen1/miscfiles/graphics/JJP_logo_message.png'
client_pub = open(r'C:\tmp\PAD-1587\client_key.pub', encoding='ascii').read().strip()

os.makedirs(os.path.join(PROJ, os.path.dirname(REL)), exist_ok=True)
stock = subprocess.run(['wsl', '-u', 'root', '-e', '/usr/sbin/debugfs', '-R', 'cat /' + REL[len('system/'):],
                        '/var/tmp/jjp_Wonka-v03.03/sda3.raw'], capture_output=True).stdout
assert stock[:8] == b'\x89PNG\r\n\x1a\n', stock[:40]
with open(os.path.join(PROJ, '.checksums.md5'), 'w', encoding='utf-8', newline='\n') as f:
    f.write('%s  %s\n' % (hashlib.md5(stock).hexdigest(), REL))
im = Image.open(io.BytesIO(stock)).convert('RGBA')
d = ImageDraw.Draw(im)
w, h = im.size
d.rectangle([0, h - 40, w, h], fill=(200, 0, 0, 255))
d.text((10, h - 32), 'PAD-1587 SENT OVER THE NETWORK', fill=(255, 255, 255, 255))
out = io.BytesIO()
im.save(out, 'PNG')
with open(os.path.join(PROJ, REL), 'wb') as f:
    f.write(out.getvalue())
card_extras.save(PROJ, True, client_pub)
print('stock', len(stock), hashlib.sha1(stock).hexdigest())
print('changed', len(out.getvalue()), hashlib.sha1(out.getvalue()).hexdigest())
print('config keys:', len(card_extras.configuration(PROJ)['public_keys'].splitlines()))
