"""PAD-1467: the network options without a build of the project: "Keep my network settings" on a flash
(core/network_keep.py), and straight onto an attached card or the machine (core/network_apply.py); and what each
Network tab panel says about how its settings reach a card."""
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from pinball_decryptor.core import card_extras, network_apply as A, network_keep as K, remote_buttons as B, wifi_card as W
from pinball_decryptor.core.card_extras import ExtrasError
from tests.test_remote_buttons import STOCK, _card
from tests.test_wifi_card import node


def _project(tmp_path, ssh=True, wifi=None, buttons=None):
    project = tmp_path / 'project'
    project.mkdir(exist_ok=True)
    (project / '.staged_changes.json').write_text(json.dumps(
        {'extras': {'ssh': {'enabled': ssh, 'public_keys': ''}}, 'modes': {'kept': 'out'}}))
    if wifi is not None:
        card_extras.save_wifi(str(project), *wifi)
    if buttons is not None:
        card_extras.save_buttons(str(project), buttons)
    return project


def test_keep_my_network_settings_carries_only_what_is_on(tmp_path):
    project = _project(tmp_path, wifi=(True, True), buttons=False)
    assert set(K.options(str(project))) == {'ssh', 'wifi'}                    # buttons is off: not carried
    assert K.names(str(project)) == ['remote access', 'Wi-Fi start-up (and the newer adapter driver for 5 GHz)']
    assert K.said(str(project)) == 'remote access and Wi-Fi start-up (and the newer adapter driver for 5 GHz)'
    staged = tmp_path / 'staged'; staged.mkdir()
    K.stage_project(str(project), str(staged))
    data = json.loads((staged / '.staged_changes.json').read_text())
    assert set(data) == {'extras'} and set(data['extras']) == {'ssh', 'wifi'}  # nothing else of the project comes
    assert data['extras']['wifi'] == {'enabled': True, 'band5': True}
    empty = tmp_path / 'empty'; empty.mkdir()
    assert K.options(str(empty)) == {} and K.said(str(empty)) == '' and K.options('') == {}
    with pytest.raises(ExtrasError):
        K.stage_project(str(empty), str(staged))
    image = tmp_path / 'card.raw'; image.write_bytes(b'x')
    out = K.staged_path(str(image))
    assert os.path.dirname(out) == str(tmp_path) and os.path.basename(out) == '.card.pad-network.raw'
    for name in ('', '.pad-build.json', '.ssh-pending'):
        Path(out + name).write_bytes(b'y')
    K.clean(out)
    assert image.exists() and not [p for p in tmp_path.iterdir() if '.pad-network' in p.name]


def test_the_flash_dialog_offers_the_tick_and_the_flash_takes_it():
    root = Path(K.__file__).resolve().parents[1]
    dialog = (root / 'webui/write_dialogs.py').read_text(encoding='utf-8')
    assert 'def keeping_network(self):' in dialog and 'skip["keep_network"] = True' in dialog
    assert 'not self.building' in dialog.split('def keeping_network(self):')[1].split('def ')[0]   # a build carries them
    js = (root / 'webui/static/js/tabs/write_dialogs.js').read_text(encoding='utf-8')
    assert 'f.net_offered' in js and 'set("keep_network", v)' in js
    pipe = (root / 'plugins/stern/pipeline.py').read_text(encoding='utf-8')
    assert 'network_keep.clean(staged)' in pipe and 'def _with_network(self):' in pipe
    app = (root / 'app.py').read_text(encoding='utf-8')
    assert 'extra["network_from"]' in app and 'if not keep_network:' in app   # the refusal gives way to the tick


def test_each_panel_says_how_its_settings_reach_a_card():
    on = lambda panel: [w['key'] for w in A.ways(panel) if w['on']]            # noqa: E731
    assert on('score_feed') == ['build', 'send']                               # a build, always
    assert on('wifi') == on('buttons') == ['build', 'send', 'card', 'machine']
    assert on('remote_access') == ['build', 'send', 'card']
    assert all(len(A.ways(p)) == 4 and all(w['label'] and w['hint'] for w in A.ways(p)) for p in A.WAYS)
    assert 'needs a build' in A.WAY_NOTES['score_feed'] and '2.4GHz' in A.WAY_NOTES['wifi']
    js = (Path(K.__file__).resolve().parents[1] / 'webui/static/js/tabs/network.js').read_text(encoding='utf-8')
    for panel in A.WAYS:
        assert 'panel="%s"' % panel in js, panel
    assert 'Put on the attached card' in js and 'Put on my machine now' in js
    assert js.count('<${Direct} n=${n} kind=') == 2                            # Wi-Fi and Remote buttons, not Score feed


class Machine:
    """A stand-in machine: a dict of files, the shell words the app sends answered from it."""

    def __init__(self, files=None, kernel=W.KERNEL, links=None):
        self.files = dict(files or {})
        self.files.setdefault(W.HOOK, b'hook')
        self.files.setdefault(B.MONITOR, STOCK.encode())
        self.files.setdefault(W.MODULE, b'\x7fELF stern\x00version=v5.3.1\x00')
        self.kernel, self.links, self.ran, self.rebooted, self.sftp, self.corrupt = kernel, dict(links or {}), [], 0, self, False

    def open(self, path, mode):
        m = self
        if 'r' in mode:
            if path not in m.files:
                raise IOError(path)
            import io
            return io.BytesIO(m.files[path])

        class F:
            def __init__(s):
                s.buf = b''

            def write(s, data):
                s.buf += data

            def __enter__(s):
                return s

            def __exit__(s, *a):
                m.files[path] = (s.buf[:-1] + b'!') if m.corrupt else s.buf
        return F()

    def sh(self, script, timeout=60, check=True):
        self.ran.append(script)
        if script.startswith('uname -r'):
            return 0, self.kernel + '\n' + ''.join('have %s\n' % p for p in list(self.files) + list(self.links)
                                                    if "'%s'" % p in script)
        if script.startswith('echo "$(readlink'):
            return 0, '\n'.join(self.links.get(p.split("'")[1], '') for p in script.split('; ')) + '\n'
        if 'remount,rw' in script:
            return 0, 'PAD_RW\n'
        if script.startswith('sha1sum '):
            return 0, ''.join('%s %s\n' % (hashlib.sha1(self.files[p]).hexdigest(), p)
                              for p in script[8:].replace("'", '').split())
        if 'PAD_PUT' in script:
            for step in script.split(' && '):
                words = step.replace("'", '').split()
                if words[:2] == ['mv', '-f']:
                    self.files[words[3]] = self.files.pop(words[2])
                elif words[:1] == ['ln']:
                    self.links[words[3]] = words[2]
                elif words[:2] == ['rm', '-f']:
                    self.files.pop(words[2], None); self.links.pop(words[2], None)
            return 0, 'PAD_PUT\n'
        if script.startswith('rm -f '):
            for p in script[6:].replace("'", '').split():
                self.files.pop(p, None)
        return 0, ''

    def reboot(self):
        self.rebooted += 1


def test_straight_onto_the_machine_checks_every_file_then_restarts_it():
    m = Machine()
    assert A.to_machine(m, wifi={'enabled': True, 'band5': True}, buttons={'enabled': True}) == 'done'
    assert m.rebooted == 1 and m.files[W.OVERRIDE] == W.CONTENT
    assert m.files[W.MODULE] == W.new_module_bytes() and m.files[B.SO] == B.shim_bytes()
    assert m.files[B.MONITOR].decode() == B.monitor_text(STOCK, True) and m.links[W.LINK] == W.LINK_TARGET
    assert not [p for p in m.files if p.endswith('.pad-new')]
    assert any('remount,ro' in r for r in m.ran)
    # the same again: nothing differs, nothing is written and the machine is not restarted
    before = len(m.ran)
    assert A.to_machine(m, wifi={'enabled': True, 'band5': True}, buttons={'enabled': True}) == 'already'
    assert m.rebooted == 1 and not any('remount,rw' in r for r in m.ran[before:])
    # off again: the script back as Stern's, the shim gone, Stern's driver from the original card
    stern = b'\x7fELF stern original'
    with pytest.raises(ExtrasError):
        A.to_machine(m, wifi={'enabled': False, 'band5': False})               # ours is on it, and no Stern's given
    assert A.to_machine(m, wifi={'enabled': False, 'band5': False}, buttons={'enabled': False}, stern_module=stern) == 'done'
    assert m.files[W.MODULE] == stern and W.OVERRIDE not in m.files and B.SO not in m.files
    assert m.files[B.MONITOR].decode() == STOCK and W.LINK not in m.links and W.HELPER not in m.files and m.rebooted == 2


def test_straight_onto_the_machine_refuses_before_it_changes_anything():
    m = Machine(kernel='4.1.15-other')
    with pytest.raises(ExtrasError, match='kernel'):
        A.to_machine(m, wifi={'enabled': True, 'band5': True})
    assert not any('remount' in r for r in m.ran) and m.rebooted == 0
    m = Machine()
    m.corrupt = True                                                          # a file that arrives changed
    with pytest.raises(ExtrasError, match='did not arrive'):
        A.to_machine(m, buttons={'enabled': True})
    assert m.files[B.MONITOR] == STOCK.encode() and B.SO not in m.files and m.rebooted == 0
    assert not [p for p in m.files if p.endswith('.pad-new')]
    with pytest.raises(ExtrasError, match='nothing to put'):
        A.to_machine(Machine())
    m = Machine(files={B.MONITOR: b'#!/bin/sh\nexec /games/game\n'})
    with pytest.raises(ExtrasError, match='not one this app knows'):
        A.to_machine(m, buttons={'enabled': True})


def test_straight_onto_a_card_image_and_off_again(tmp_path):
    # a card the app knows as a Spike 2 system (what remote access checks before it opens one)
    image = _card(tmp_path, extra={'etc/passwd': b'root:x:0:0:root:/home/root:/bin/sh\n',
                                   'etc/fstab': b'/dev/mmcblk0p5 /data ext3 defaults 0 0\n',
                                   'etc/inittab': b'l5:5:wait:/etc/init.d/rc 5\n'})
    card = tmp_path / 'mine.raw'
    shutil.copyfile(image, card)
    said = []
    assert A.to_card(str(card), wifi={'enabled': True, 'band5': True}, buttons={'enabled': True},
                     log=lambda t, l='info': said.append(t)) == 'done'
    assert W.inspect_image(str(card))['band5'] and B.inspect_image(str(card))['enabled']
    assert node(card, B.SO)['data'] == B.shim_bytes() and 'remote buttons' in said[-1]
    assert A.to_card(str(card), wifi={'enabled': True, 'band5': True}, buttons={'enabled': True}) == 'already'
    assert A.to_card(str(card), wifi={'enabled': False, 'band5': False}, buttons={'enabled': False},
                     stern_from=str(image)) == 'done'
    assert not W.inspect_image(str(card))['enabled'] and not B.inspect_image(str(card))['enabled']
    assert node(card, B.MONITOR)['data'].decode() == STOCK and node(card, W.MODULE)['data'] == node(image, W.MODULE)['data']
    with pytest.raises(ExtrasError, match='nothing to put'):
        A.to_card(str(card))
