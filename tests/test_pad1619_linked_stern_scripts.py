"""PAD-1619: a card Stern's own updater brought up to date keeps /etc/init.d/game_monitor, /etc/init.d/game and
/etc/fstab as links into /spk/packages/spike-<version>.  The Plugins and Network tabs read them through the link
and change the file it leads to, leaving the link, as the modes and boot-menu writers do (PAD-742)."""
import shutil
import stat

import pytest

from pinball_decryptor.core import (bluetooth_card as BT, menu_network as MN, remote_buttons as B, ssh_card,
                                    wifi_card as W)
from pinball_decryptor.core import remote_send as RS
from pinball_decryptor.core.card_extras import ExtrasError
from pinball_decryptor.plugins.stern.ext4 import Ext4Reader
from tests.test_pad1554_bluetooth_plugin import _installed, plugin, store  # noqa: F401 - fixtures
from tests.test_wifi_card import build, node

STOCK = ('#!/bin/sh\n\nulimit -c unlimited\n\nwhile [ true ] ;\ndo\n\t$1\n\t/usr/local/bin/boot_display&\n'
         '\tsleep 1\n\tpkill boot_display\ndone\n')
PKG = 'spk/packages/spike-2_7_0'
MON = '/' + PKG + '/etc/init.d/game_monitor'
GAME = ('SPIKE_PATH=/usr/local/spike\n# stern-spike2.dtb\nspike2\ninsmod /usr/local/spike/8812bu.ko\n').encode()
FSTAB = b'/dev/root / auto ro 1 0\n/dev/mmcblk0p3 /games ext4 ro 0 2\n/dev/mmcblk0p5 /data ext4 rw 0 2\n'


def _linked(tmp_path, script=STOCK):
    """A card laid out the way the reporter's are: the three files in the package, links where they were."""
    files = {PKG + '/etc/init.d/game_monitor': script.encode(), PKG + '/etc/init.d/game': GAME,
             PKG + '/etc/fstab': FSTAB, 'sbin/udhcpc': b'\x7fELF udhcpc',
             'etc/passwd': b'root:x:0:0:root:/home/root:/bin/sh\n', 'etc/inittab': b'id:5:initdefault:\n'
             b'si::sysinit:/etc/init.d/rcS\nl5:5:wait:/etc/init.d/rc 5\n'}
    links = {'etc/init.d/game_monitor': MON, 'etc/init.d/game': '/' + PKG + '/etc/init.d/game',
             'etc/fstab': '../' + PKG + '/etc/fstab'}                        # one relative, as a link can be
    return build(tmp_path, extra=files, links=links)


def _link(image, path):
    with open(image, 'rb') as f:
        r = Ext4Reader(f, 1 << 20, 24 << 20)
        n = ssh_card._node(r, path)
        return r.read_symlink(n) if n is not None and stat.S_IFMT(n['mode']) == stat.S_IFLNK else None


def _reader(image):
    f = open(image, 'rb')
    return f, Ext4Reader(f, 1 << 20, 24 << 20)


def test_a_link_is_followed_to_its_file_and_a_loop_is_refused(tmp_path):
    image = build(tmp_path, extra={'a/b/real': b'here'},
                  links={'a/rel': 'b/real', 'a/abs': '/a/b/real', 'x/up': '../a/rel', 'a/loop': 'loop',
                         'a/gone': '/nowhere/file'})
    f, r = _reader(image)
    with f:
        for path in ('/a/rel', '/a/abs', '/x/up', '/a/b/real'):
            real, n = ssh_card.resolve(r, path)
            assert real == '/a/b/real' and r.read_file_bytes(n) == b'here', path
        assert ssh_card.resolve(r, '/a/gone') == ('/nowhere/file', None)
        assert ssh_card.resolve(r, '/no/such') == ('/no/such', None)
        with pytest.raises(ExtrasError, match='does not lead to a file'):
            ssh_card.resolve(r, '/a/loop')
        assert ssh_card._read(r, '/x/up') == b'here'


def test_bluetooth_goes_on_a_linked_card_into_the_file_the_link_leads_to_and_comes_off(tmp_path, store, plugin):
    image = _linked(tmp_path)
    info = BT.inspect_image(str(image))
    assert info['supported'], info['reason']
    _installed(plugin)
    out = tmp_path / 'out.raw'
    shutil.copyfile(image, out)
    assert 'is on the card' in BT.apply_to_build(str(image), str(out), {'enabled': True})
    assert _link(out, BT.MONITOR) == MON                                     # the link stays as Stern made it
    mon = node(out, MON)
    assert mon['data'].decode() == B.monitor_text(STOCK, False, bluetooth=True) and mon['mode'] & 0o7777 == 0o755
    assert BT.inspect_image(str(out))['enabled']
    BT.apply_to_build(str(image), str(out), {'enabled': False})
    assert _link(out, BT.MONITOR) == MON and node(out, MON)['data'].decode() == STOCK
    assert not BT.inspect_image(str(out))['enabled']


def test_remote_buttons_go_on_a_linked_card_the_same_way(tmp_path):
    image = _linked(tmp_path)
    assert B.inspect_image(str(image))['supported']
    out = tmp_path / 'out.raw'
    shutil.copyfile(image, out)
    B.apply_to_build(str(image), str(out), {'enabled': True})
    assert _link(out, B.MONITOR) == MON and node(out, MON)['data'].decode() == B.monitor_text(STOCK, True)
    assert B.inspect_image(str(out))['enabled']
    B.apply_to_build(str(image), str(out), {'enabled': False})
    assert _link(out, B.MONITOR) == MON and node(out, MON)['data'].decode() == STOCK


def test_a_link_to_something_that_is_not_one_plain_file_is_still_refused(tmp_path):
    image = build(tmp_path, extra={PKG + '/etc/init.d/game_monitor/x': b''},
                  links={'etc/init.d/game_monitor': MON})
    f, r = _reader(image)
    with f, pytest.raises(ExtrasError, match='link or hard-linked'):
        ssh_card.script_dest(r, B.MONITOR, 'remote-buttons')
    assert not BT.inspect_image(str(image))['supported']


def test_the_network_tab_and_wifi_and_remote_access_read_the_linked_game_and_fstab(tmp_path):
    image = _linked(tmp_path)
    f, r = _reader(image)
    with f:
        MN.inspect_root(r)                                    # refused as "not a Spike 2 card" before
        W.inspect_root(r)                                     # "unsafe type or size" before
        assert RS._fstab(r) == FSTAB                          # the link's own bytes before
        with open(image, 'rb') as g:
            p2 = next(p for p in ssh_card._partitions(g) if p[0] == 2)
            try:
                ssh_card.inspect_spike2(g, p2)
            except ExtrasError as e:                          # past the three files: this card has no SSH layout
                assert 'unsafe type' not in str(e) and 'not been qualified' not in str(e), e
