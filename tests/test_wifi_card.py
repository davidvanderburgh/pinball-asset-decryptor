"""PAD-1467: the Wi-Fi start-up choice (core/wifi_card.py): the card's own hook reads one file for the driver name."""
import hashlib
import os
import shutil
import struct
import subprocess

import pytest

from pinball_decryptor.core import card_extras, staged_changes, wifi_card as W
from pinball_decryptor.core.card_extras import ExtrasError
from pinball_decryptor.plugins.stern.ext4 import Ext4Reader

TOOLS = os.environ.get('PAD_E2FSPROGS_DIR', '/opt/homebrew/opt/e2fsprogs/sbin')
HOOK = '''#!/bin/sh
if [ "$MODE" = "start" ] ; then
	if [ -s "/etc/wpa_supplicant/driver.$IFACE" ]; then
		IF_WPA_DRIVER=$(cat "/etc/wpa_supplicant/driver.$IFACE")
	fi
fi
'''


def build(tmp_path, hook=HOOK, supplicant=b'\x7fELF drivers: nl80211 wext', extra=None):
    mk = shutil.which('mke2fs') or TOOLS + '/mke2fs'
    if not os.path.exists(mk):
        pytest.skip('real filesystem tools required')
    tree = tmp_path / 'tree'
    for d in ['etc/init.d', 'etc/network/if-pre-up.d', 'usr/local/spike', 'usr/sbin']:
        (tree / d).mkdir(parents=True, exist_ok=True)
    (tree / 'etc/init.d/game').write_text('SPIKE_PATH=/usr/local/spike\n# stern-spike2.dtb\n')
    if hook is not None:
        (tree / 'etc/network/if-pre-up.d/wpa-supplicant').write_bytes(hook.encode())
    (tree / 'usr/sbin/wpa_supplicant').write_bytes(supplicant)
    for rel, data in (extra or {}).items():
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_bytes(data)
    fs = tmp_path / 'root.img'
    with fs.open('wb') as f:
        f.truncate(24 << 20)
    subprocess.run([mk, '-q', '-t', 'ext3', '-F', '-d', str(tree), str(fs)], check=True)
    image = tmp_path / 'card.raw'
    mbr = bytearray(512); mbr[510:] = b'\x55\xaa'
    struct.pack_into('<B3sB3sII', mbr, 446, 0, b'\0' * 3, 0x0c, b'\0' * 3, 8, 2040)
    struct.pack_into('<B3sB3sII', mbr, 462, 0, b'\0' * 3, 0x83, b'\0' * 3, 2048, fs.stat().st_size // 512)
    with image.open('wb') as f:
        f.write(mbr); f.seek(1 << 20); f.write(fs.read_bytes()); f.write(b'GAME-DATA' * 1024)
    return image


@pytest.fixture
def card(tmp_path):
    return build(tmp_path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def node(image, path):
    with open(image, 'rb') as f:
        r = Ext4Reader(f, 1 << 20, 24 << 20)
        n = W.ssh_card._node(r, path)
        return n and dict(n, data=r.read_file_bytes(n) if n['mode'] & 0o100000 else None)


def test_on_writes_the_one_file_and_off_puts_the_card_back(card, tmp_path):
    out = tmp_path / 'out.raw'
    shutil.copyfile(card, out)
    before, tail = sha(card), out.read_bytes()[(1 << 20) + (24 << 20):]
    assert W.inspect_image(str(card)) == {'supported': True, 'reason': '', 'enabled': False,
                                          'partition': (2, 0x83, 1 << 20, 24 << 20)}
    said = []
    note = W.apply_to_build(str(card), str(out), {'enabled': True}, log=lambda t, k: said.append(t))
    assert 'nl80211' in note and said == [note]
    assert sha(card) == before                                   # the original is never written
    assert out.read_bytes()[:1 << 20] == card.read_bytes()[:1 << 20]
    assert out.read_bytes()[(1 << 20) + (24 << 20):] == tail       # nothing outside the system partition moved
    f = node(out, W.OVERRIDE)
    assert f['data'] == b'nl80211,wext\n' and f['mode'] == 0o100644 and not f['uid'] and not f['gid']
    assert node(out, W.DIR)['mode'] == 0o040755
    assert W.inspect_image(str(out))['enabled'] is True
    # the hook the card ships is untouched: the change is the file alone
    assert node(out, W.HOOK)['data'] == HOOK.encode()
    # on again: nothing to write, the same line
    stamp = sha(out)
    assert W.apply_to_build(str(card), str(out), {'enabled': True}) == note and sha(out) == stamp
    # off: the file and the folder PAD made are gone
    assert W.apply_to_build(str(card), str(out), {'enabled': False}) == "Wi-Fi start-up: as Stern ships it."
    assert node(out, W.OVERRIDE) is None and node(out, W.DIR) is None
    assert W.inspect_image(str(out))['enabled'] is False
    assert W.apply_to_build(str(card), str(out), {'enabled': False}) == ''
    assert W.apply_to_build(str(card), str(out), None) == ''


def test_a_card_without_the_hook_is_left_alone(tmp_path):
    for i, kw in enumerate((dict(hook=None), dict(hook='#!/bin/sh\nexit 0\n'),
                            dict(supplicant=b'\x7fELF drivers: wext only'))):
        sub = tmp_path / str(i); sub.mkdir()
        image = build(sub, **kw)
        info = W.inspect_image(str(image))
        assert not info['supported'] and info['reason'] == W.NO_HOOK and not info['enabled']
        out = sub / 'out.raw'
        shutil.copyfile(image, out)
        stamp = sha(out)
        with pytest.raises(ExtrasError):
            W.apply_to_build(str(image), str(out), {'enabled': True})
        assert sha(out) == stamp


def test_a_driver_setting_that_is_not_ours_is_not_overwritten(tmp_path):
    image = build(tmp_path, extra={'etc/wpa_supplicant/driver.wlan0': b'wired\n'})
    info = W.inspect_image(str(image))
    assert not info['supported'] and 'wired' in info['reason'] and 'will not be overwritten' in info['reason']
    out = tmp_path / 'out.raw'
    shutil.copyfile(image, out)
    with pytest.raises(ExtrasError):
        W.apply_to_build(str(image), str(out), {'enabled': False})
    assert node(out, W.OVERRIDE)['data'] == b'wired\n'


def test_off_keeps_a_settings_folder_that_holds_something_else(tmp_path):
    image = build(tmp_path, extra={'etc/wpa_supplicant/driver.wlan0': b'nl80211,wext\n',
                                   'etc/wpa_supplicant/other.conf': b'x\n'})
    assert W.inspect_image(str(image))['enabled'] is True
    out = tmp_path / 'out.raw'
    shutil.copyfile(image, out)
    W.apply_to_build(str(image), str(out), {'enabled': False})
    assert node(out, W.OVERRIDE) is None and node(out, W.DIR + '/other.conf')['data'] == b'x\n'


def test_not_a_spike2_card_and_the_offer():
    info = W.inspect_image(os.devnull)
    assert not info['supported'] and not info['enabled']

    class M:
        key = 'stern'
    m = M()
    assert W.offered(m)
    m._era = 'spike3'
    assert not W.offered(m)
    m._era, m.key = 'spike2', 'jjp'
    assert not W.offered(m)


def test_project_choice_roundtrip_and_build_request(card, tmp_path):
    project = tmp_path / 'project'; project.mkdir()
    assert card_extras.load_wifi(str(project)) is None
    assert W.validate_request(str(card), str(project)) is None and card_extras.digest(str(project)) is None
    card_extras.save_wifi(str(project), True)
    assert staged_changes.load(str(project))['extras'] == {'wifi': {'enabled': True}}
    assert W.validate_request(str(card), str(project)) == {'enabled': True}
    on = card_extras.digest(str(project))
    card_extras.save_wifi(str(project), False)
    off = card_extras.digest(str(project))
    assert on and off and on != off                              # a changed choice makes the last build stale
    with pytest.raises(ExtrasError):
        card_extras.save_wifi(str(project), 'yes')
    # remote access beside it is kept, and a project that never set Wi-Fi keeps the digest it had
    other = tmp_path / 'other'; other.mkdir()
    card_extras.save(str(other), False, '')
    alone = card_extras.digest(str(other))
    card_extras.save_wifi(str(other), True)
    assert card_extras.load(str(other)) == {'enabled': False, 'public_keys': ''}
    assert card_extras.digest(str(other)) != alone
    data = staged_changes.load(str(other)); del data['extras']['wifi']
    staged_changes.save(str(other), data, strict=True)
    assert card_extras.digest(str(other)) == alone
    data['extras']['wifi'] = {'enabled': 1}
    staged_changes.save(str(other), data, strict=True)
    with pytest.raises(ExtrasError):
        card_extras.load_wifi(str(other))


def test_flash_only_needs_a_build_that_carries_the_choice(card, tmp_path):
    project = tmp_path / 'project'; project.mkdir()
    W.guard_flash(str(project), str(card))                       # never set: nothing to guard
    card_extras.save_wifi(str(project), True)
    with pytest.raises(ExtrasError, match='Build the complete image first'):
        W.guard_flash(str(project), str(card))
    out = tmp_path / 'out.raw'
    shutil.copyfile(card, out)
    W.apply_to_build(str(card), str(out), {'enabled': True})
    W.guard_flash(str(project), str(out))
    card_extras.save_wifi(str(project), False)
    W.guard_flash(str(project), str(card))
    with pytest.raises(ExtrasError):
        W.guard_flash(str(project), str(out))


def test_off_on_a_card_that_cannot_carry_it_asks_nothing_of_the_build(tmp_path):
    image = build(tmp_path, hook=None)
    project = tmp_path / 'project'; project.mkdir()
    card_extras.save_wifi(str(project), False)
    assert W.validate_request(str(image), str(project)) is None
    card_extras.save_wifi(str(project), True)
    with pytest.raises(ExtrasError):
        W.validate_request(str(image), str(project))
