"""PAD-1467: remote buttons (core/remote_buttons.py): a Spike 2 machine's coin-door service buttons pressed from
the PC through a shim preloaded into the game, the coin door respected."""
import hashlib
import importlib.util
import json
import shutil
import time
from pathlib import Path

import pytest

from pinball_decryptor.core import card_extras, remote_buttons as B, staged_changes
from pinball_decryptor.core.card_extras import ExtrasError
from tests.test_wifi_card import build, node, sha
from tests.webui_harness import web_app

STOCK = ('#!/bin/sh\n\nulimit -c unlimited\n\nwhile [ true ] ;\ndo\n\t$1\n\t/usr/local/bin/boot_display&\n'
         '\tsleep 1\n\tpkill boot_display\ndone\n')
ROOT = Path(B.__file__).resolve().parents[2]


def _modehook():
    spec = importlib.util.spec_from_file_location('modehook_for_test', ROOT / 'tools/spike2_emu/modehook.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_start_up_script_takes_the_block_from_every_form_and_gives_each_back():
    mh = _modehook()
    assert (B.HOOK_LINES, B.MENU_HOOK_LINES, B.ALL_HOOK_LINES, B.RUN_LINE, B.SO) == (
        mh.HOOK_LINES, mh.MENU_HOOK_LINES, mh.ALL_HOOK_LINES, mh.RUN_LINE, mh.BUTTONS_SO)   # one definition, twice
    modes = mh.hook_game_monitor(STOCK, menu=False)
    menu = mh.hook_game_monitor(STOCK, menu=True)
    on = B.monitor_text(STOCK, True)
    assert '\n'.join(B.ALL_HOOK_LINES) in on and on.count('$1') == 2 and '\t' + 'sleep 1' in on
    assert B.monitor_text(modes, True) == on == B.monitor_text(menu, True) == B.monitor_text(on, True)
    assert B.monitor_text(on, False) == STOCK
    assert B.monitor_text(on, False, mode=True) == modes and B.monitor_text(on, False, menu=True, mode=True) == menu
    # the block preloads each object only when it is there, the buttons between the menu and the mode runtime
    lines = B.ALL_HOOK_LINES
    assert lines.index(next(l for l in lines if B.MENU_SO in l)) < lines.index(next(l for l in lines if B.SO in l)) \
        < lines.index(next(l for l in lines if B.MODE_SO in l))
    # a mode install on a card with remote buttons keeps them, and its own questions still answer
    assert mh.has_hook(on) and mh.has_buttons_hook(on) and mh.hook_game_monitor(on) == on
    assert mh.strip_hook(on) == STOCK and 'remote-buttons hook' in mh.describe(on)
    with pytest.raises(ExtrasError, match='not one this app knows'):
        B.monitor_text('#!/bin/sh\nexec /games/game\n', True)


def test_the_bundled_shim_is_the_one_committed_and_needs_no_library():
    data = B.shim_bytes()
    assert hashlib.sha256(data).hexdigest() == B.SHIM_SHA256 and data[:4] == b'\x7fELF' and len(data) < 16384
    assert data[18:20] == b'\x28\x00'                                         # an ARM object
    assert b'libc.so' not in data and b'/run/pad-buttons' in data and b'/dump/' not in data   # no log in this one
    src = (B.RESOURCES / 'pad-buttons.c').read_text(encoding='utf-8')
    assert 'the coin door is not open: no press' in src and 'MAX_AHEAD_CS 300' in src


def test_a_press_is_one_line_and_only_with_the_door_open():
    assert B.BITS == dict(enter=8, plus=9, minus=10, back=11) and (B.DOOR_BIT, B.DOOR_OPEN) == (23, 1)
    script = B.press_script('enter')
    assert 'echo "100 $((u + 15)) 23 1" > /run/pad-buttons' in script and '/proc/uptime' in script
    assert '"a00 $((u + 15)) 23 1"' in B.press_script(['plus', 'back'])
    assert '$((u + 250))' in B.press_script('back', 5000)                     # never held past the shim's cap
    with pytest.raises(ExtrasError):
        B.press_script('start')
    open_word, closed_word = 'ffffffffffffffff', 'ffff7fffffffffff'
    assert B.parse_status('up 5000\n4980 %s\n' % open_word) == dict(ready=True, door_open=True, reason='', need='')
    closed = B.parse_status('up 5000\n4980 %s\n' % closed_word)
    assert closed['ready'] and not closed['door_open'] and 'coin door is closed' in closed['reason']
    assert closed['need'] == 'door'
    assert not B.parse_status('up 5000\nnone\n')['ready']
    assert not B.parse_status('up 9000\n4980 %s\n' % open_word)['ready']      # a state file from a game long gone

    class M:
        def __init__(self, state):
            self.state, self.ran = state, []

        def sh(self, script, timeout=20, check=True):
            self.ran.append(script)
            return 0, self.state

    m = M('up 5000\n4990 %s\n' % open_word)
    assert B.press(m, 'plus')['ok'] and len(m.ran) == 2 and '"200 ' in m.ran[1]
    m = M('up 5000\n4990 %s\n' % closed_word)
    assert not B.press(m, 'plus')['ok'] and len(m.ran) == 1                   # asked, never pressed
    m = M('up 5000\nnone\n')
    res = B.press(m, 'plus')
    assert not res['ok'] and res['reason'] == B.NOT_ON_CARD and len(m.ran) == 1


def test_project_choice_roundtrip_and_digest(tmp_path):
    project = tmp_path / 'project'; project.mkdir()
    assert card_extras.load_buttons(str(project)) is None and card_extras.digest(str(project)) is None
    assert card_extras.save_buttons(str(project), True) == {'enabled': True}
    assert staged_changes.load(str(project))['extras']['buttons'] == {'enabled': True}
    on = card_extras.digest(str(project))
    card_extras.save_buttons(str(project), False)
    assert card_extras.load_buttons(str(project)) == {'enabled': False} and card_extras.digest(str(project)) != on
    with pytest.raises(ExtrasError):
        card_extras.save_buttons(str(project), 'yes')
    (project / '.staged_changes.json').write_text(json.dumps({'extras': {'buttons': {'enabled': 'yes'}}}))
    with pytest.raises(ExtrasError):
        card_extras.load_buttons(str(project))


def _card(tmp_path, script=STOCK, extra=None):
    files = {'etc/init.d/game_monitor': script.encode()}
    files.update(extra or {})
    return build(tmp_path, extra=files)


def test_on_puts_the_shim_and_the_block_on_the_card_and_off_puts_it_back(tmp_path):
    image = _card(tmp_path)
    assert B.inspect_image(str(image)) == dict(B.inspect_image(str(image)), supported=True, enabled=False)
    out = tmp_path / 'out.raw'
    shutil.copyfile(image, out)
    before = sha(image)
    text = B.apply_to_build(str(image), str(out), {'enabled': True})
    assert 'Back, Minus, Plus and Enter' in text and sha(image) == before
    assert B.inspect_image(str(out))['enabled']
    so, mon = node(out, B.SO), node(out, B.MONITOR)
    assert so['data'] == B.shim_bytes() and so['mode'] & 0o7777 == 0o755 and so['uid'] == 0
    assert mon['data'].decode() == B.monitor_text(STOCK, True) and mon['mode'] & 0o7777 == 0o755
    assert B.apply_to_build(str(image), str(out), {'enabled': True}) == text          # already there: no rewrite
    assert B.apply_to_build(str(image), str(out), {'enabled': False}) == B.note(False)
    assert node(out, B.SO) is None and node(out, B.MONITOR)['data'].decode() == STOCK
    assert not B.inspect_image(str(out))['enabled']


def test_off_on_a_card_with_modes_gives_the_mode_block_back(tmp_path):
    mh = _modehook()
    modes = mh.hook_game_monitor(STOCK, menu=False)
    image = _card(tmp_path, modes, {'usr/local/padmode/mode.so': b'\x7fELF mode'})
    out = tmp_path / 'out.raw'
    shutil.copyfile(image, out)
    B.apply_to_build(str(image), str(out), {'enabled': True})
    assert node(out, B.MONITOR)['data'].decode() == B.monitor_text(modes, True)
    B.apply_to_build(str(image), str(out), {'enabled': False})
    assert node(out, B.MONITOR)['data'].decode() == modes and node(out, B.MODE_SO)['data'] == b'\x7fELF mode'


def test_a_start_up_script_that_is_not_known_is_left_alone(tmp_path):
    image = _card(tmp_path, '#!/bin/sh\nexec /games/game\n')
    info = B.inspect_image(str(image))
    assert not info['supported'] and 'not one this app knows' in info['reason']
    project = tmp_path / 'project'; project.mkdir()
    card_extras.save_buttons(str(project), False)
    assert B.validate_request(str(image), str(project)) is None               # off asks nothing of such a card
    card_extras.save_buttons(str(project), True)
    with pytest.raises(ExtrasError, match='not one this app knows'):
        B.validate_request(str(image), str(project))


def test_flash_only_needs_a_build_that_carries_the_choice(tmp_path):
    image = _card(tmp_path)
    project = tmp_path / 'project'; project.mkdir()
    B.guard_flash(str(project), str(image))                                   # nothing chosen: nothing asked
    card_extras.save_buttons(str(project), True)
    with pytest.raises(ExtrasError, match='Build the complete image first'):
        B.guard_flash(str(project), str(image))
    out = tmp_path / 'out.raw'
    shutil.copyfile(image, out)
    B.apply_to_build(str(image), str(out), {'enabled': True})
    B.guard_flash(str(project), str(out))


def test_not_a_spike2_card_and_the_offer(tmp_path):
    class Mfr:
        key, _era = 'stern', 'spike2'
    assert B.offered(Mfr())
    Mfr._era = 'spike3'
    assert not B.offered(Mfr()) and not B.offered(None)
    junk = tmp_path / 'x.raw'; junk.write_bytes(b'\0' * 4096)
    assert not B.inspect_image(str(junk))['supported']


def _wait(w, done):
    for _ in range(300):
        w.drain()
        if done(w.state('network')):
            return
        time.sleep(0.02)
    raise AssertionError('never settled')


def test_network_tab_saves_the_choice_and_presses_a_button(tmp_path, monkeypatch):
    from pinball_decryptor.core import pad_ssh_key, remote_send, ssh_card
    with web_app(tmp_path, mfr='stern') as w:
        w.window.current_mfr._era = 'spike2'
        project = tmp_path / 'project'; project.mkdir()
        image = tmp_path / 'source.raw'; image.write_bytes(b'card')
        monkeypatch.setattr(ssh_card, 'inspect_image', lambda path: dict(supported=True, reason='', platform='stern-spike2',
                                                                        enabled=False, public_keys=''))
        monkeypatch.setattr(B, 'inspect_image', lambda path, **k: dict(supported=True, reason='', enabled=False))
        monkeypatch.setattr(pad_ssh_key, 'KEY_DIR', tmp_path / 'keys')
        w.run(w.window.write_assets_var.set, str(project))
        w.run(w.window.write_upd_var.set, str(image))
        svc = w.window.service('network')
        w.run(svc.on_show)
        st = w.state('network')
        assert st['buttons_offered'] and st['buttons_supported'] and not st['buttons_enabled']
        assert [k for k, _l in st['buttons_labels']] == ['back', 'minus', 'plus', 'enter']
        assert any(r[0] == 'Coin door' for r in st['buttons_details']) and st['buttons_now'] == 'no remote buttons (as shipped)'
        assert w.call('network.configure_buttons', True, str(project))
        assert card_extras.load_buttons(str(project)) == {'enabled': True} and w.state('network')['buttons_enabled']
        assert w.call('network.configure_buttons', True, str(tmp_path)) is False     # not this tab's project

        w.call('network.set_address', '192.168.1.40')
        ran = []

        class M:
            state = 'up 5000\n4990 ffffffffffffffff\n'

            def sh(self, script, timeout=20, check=True):
                ran.append(script)
                return 0, self.state

            def close(self):
                ran.append('closed')
        monkeypatch.setattr(remote_send, 'connect', lambda a: M())
        assert w.call('network.press_button', 'enter')
        _wait(w, lambda s: not s.get('buttons_busy'))
        assert '"100 ' in ran[1] and ran[-1] == 'closed' and not w.state('network')['buttons_note']
        M.state = 'up 5000\n4990 ffff7fffffffffff\n'
        del ran[:]
        assert w.call('network.press_button', 'back')
        _wait(w, lambda s: not s.get('buttons_busy'))
        st = w.state('network')
        # PAD-1634: what is in the way is said plainly, not as the user's error
        assert len(ran) == 2 and st['buttons_kind'] == '' and 'coin door is closed' in st['buttons_note']
        assert st['buttons_need'] == 'door'
        assert w.call('network.press_button', 'start') is False
    js = (ROOT / 'pinball_decryptor/webui/static/js/tabs/network.js').read_text(encoding='utf-8')
    assert 'network.press_button' in js and 'Put remote buttons on cards I write from this project' in js


# ---- PAD-1634: what is in the way of the buttons, and the step that fits, where the buttons are ----
def test_what_is_in_the_way_is_one_thing_and_names_no_other_page():
    """David, of "This machine's card has no remote buttons (or its game is not running). Tick Remote buttons
    below and write the card, or Send to machine." on My machines: "the red text here doesn't make sense in this
    context"."""
    assert '[ -f %s ]' % B.SO in B.STATUS
    none = B.parse_status('up 5000\ncard off\nnone\n')
    assert none == dict(ready=False, door_open=False, reason=B.NOT_ON_CARD, need='install')
    assert B.parse_status('up 5000\nnone\n')['need'] == 'install'            # a machine that says nothing of it
    late = B.parse_status('up 5000\ncard on\nnone\n')
    assert late == dict(ready=False, door_open=False, reason=B.NOT_ANSWERING, need='wait')
    assert B.parse_status('up 9000\ncard on\n4980 ffffffffffffffff\n')['need'] == 'wait'     # a game long gone
    assert B.parse_status('up 5000\ncard on\n4990 ffffffffffffffff\n')['need'] == ''
    for text in (B.NOT_ON_CARD, B.NOT_ANSWERING, B.DOOR_CLOSED):
        assert 'below' not in text and 'Tick' not in text and ' or ' not in text.split('.')[0]
    core = (ROOT / 'pinball_decryptor/webui/static/js/core/buttons_need.js').read_text(encoding='utf-8')
    assert 'call("network.buttons_turn_on")' in core and 'n.buttons_need === "install"' in core
    for page in ('tabs/network.js', 'shell.js'):
        js = (ROOT / 'pinball_decryptor/webui/static/js' / page).read_text(encoding='utf-8')
        assert '<${ButtonsNeed} n=${n}' in js and 'buttons_need.js"' in js
        assert 'box beside this card' not in js
    # the choice for cards you write sits under the screen and its buttons, not a column away
    js = (ROOT / 'pinball_decryptor/webui/static/js/tabs/network.js').read_text(encoding='utf-8')
    assert js.index('<${MachineScreen} n=${n} />') < js.index('<${RemoteButtonsOption} n=${n} />') \
        < js.index('<${MachineCare} n=${n} />')


def test_remote_buttons_go_on_the_machine_from_under_its_buttons(tmp_path, monkeypatch):
    from pinball_decryptor.core import network_apply, pad_ssh_key, rawdevice, remote_send, ssh_card
    with web_app(tmp_path, mfr='stern') as w:
        w.window.current_mfr._era = 'spike2'
        project = tmp_path / 'project'; project.mkdir()
        monkeypatch.setattr(ssh_card, 'inspect_image', lambda path: dict(supported=False, reason='x', enabled=False,
                                                                        public_keys=''))
        monkeypatch.setattr(pad_ssh_key, 'KEY_DIR', tmp_path / 'keys')
        # the project's card is the card in the reader (David's): the box is not greyed with "needs a regular
        # card image file, not a device"
        monkeypatch.setattr(rawdevice, 'is_device_path', lambda p: str(p).startswith('DEVICE'))
        w.run(w.window.write_assets_var.set, str(project))
        w.run(w.window.write_upd_var.set, 'DEVICE1')
        svc = w.window.service('network')
        w.run(svc.on_show)
        st = w.state('network')
        assert st['buttons_supported'] and not st['buttons_reason'] and "this computer's reader" in st['buttons_hint']
        w.call('network.set_address', '192.168.1.40')
        ran, put = [], []

        class M:
            def sh(self, script, timeout=20, check=True):
                ran.append(script)
                return 0, 'up 5000\ncard off\nnone\n'

            def close(self):
                ran.append('closed')
        monkeypatch.setattr(remote_send, 'connect', lambda a: M())
        # a press finds the card has none: said plainly, and the step is offered
        assert w.call('network.press_button', 'enter')
        _wait(w, lambda s: not s.get('buttons_busy'))
        st = w.state('network')
        assert (st['buttons_note'], st['buttons_kind'], st['buttons_need']) == (B.NOT_ON_CARD, '', 'install')
        # not without a yes
        w.answers.append('no')
        assert w.call('network.buttons_turn_on') is False and not put

        def to_machine(m, *, wifi=None, buttons=None, stern_module=None, log=None, restart=True):
            put.append((wifi, buttons, restart))
            return 'done'
        monkeypatch.setattr(network_apply, 'to_machine', to_machine)
        w.answers.append('yes')
        assert w.call('network.buttons_turn_on')
        _wait(w, lambda s: not s.get('buttons_busy'))
        st = w.state('network')
        assert put == [(None, {'enabled': True}, True)] and 'restart' in w.asked[-1]['message']
        assert st['buttons_kind'] == 'ok' and st['buttons_need'] == '' and 'restarting' in st['buttons_note']
        # the next card or Send built from the project keeps them
        assert card_extras.load_buttons(str(project)) == {'enabled': True} and st['buttons_enabled']
        # a failure says so and leaves the step on offer
        monkeypatch.setattr(network_apply, 'to_machine',
                            lambda m, **k: (_ for _ in ()).throw(ExtrasError('no room')))
        w.answers.append('yes')
        assert w.call('network.buttons_turn_on')
        _wait(w, lambda s: not s.get('buttons_busy'))
        st = w.state('network')
        assert st['buttons_kind'] == 'err' and 'no room' in st['buttons_note'] and st['buttons_need'] == 'install'
