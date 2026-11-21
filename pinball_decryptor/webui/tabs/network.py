"""Network: what a card does with the owner's home network (PR #38 review, David's call).

Two things only matter once the machine is plugged into the owner's network (the connection Insider Connected
uses), and are set once and built onto the card: the **score feed** (PAD-1204: each game's final scores posted to a
server of the owner's own; moved here from Play options, whose other options change how the game plays) and
**remote access** (SSH, PR #38 by mattlqx: a computer on that network logs in to the machine and copies files to and
from it, no SD card pulled; emulator-qualified Stern Spike 2 and Spike 3 cards only).

The score feed's state and actions stay the Modes service's (``modes.set_score_feed``; this tab asks it to publish
for the project, as Play options does for its options). Remote access is this tab's own: the project's
``.staged_changes.json`` ``extras.ssh`` record (core/card_extras.py; the key stays as the PR wrote it).

PAD-1467 adds the **Wi-Fi start-up** choice (``extras.wifi``, core/wifi_card.py): a Spike 2 card whose Wi-Fi program
talks to the adapter the current way, so the machine joins the network at the first attempt."""

import os
import threading
import time

from .base import TabService, rpc
from .. import compat
from ...core import card_extras, pad_ssh_key, remote_buttons, ssh_card, wifi_card

#: PAD-1397: Send to machine, said for someone who has never heard of it
SEND_INTRO = ("Changes go to the machine over your network instead of writing the SD card: only the files that "
              "differ are copied. While it updates, the machine's screen says PAD is updating it and how far "
              "along (a game being played ends), then the game restarts. Use Send to machine on the Write tab "
              "after you change "
              "something, or send a whole card image here (a new code version, a custom code card or a "
              "multi-boot card). Set up the machine's card for remote access first, from this computer.")

#: the page's lead: what the tab is for, said to someone who has never heard of either
INTRO = "For a machine connected to your home network, by the same cable or Wi-Fi Insider Connected uses."


def _game_name(game):
    """``deadpool_le`` -> ``Deadpool LE`` (PAD-1427: the card's game folder, said as a title)."""
    if not game:
        return ''
    words = game.replace('-', '_').split('_')
    return ' '.join(w.upper() if w.lower() in ('le', 'pro', 'prem', 'se', 'ce') else w.capitalize()
                    for w in words if w)


def _machines_state():
    """The machines this computer knows, for the picker: ``[{'address', 'label'}]`` (PAD-1427: David has many)."""
    return [{'address': m['address'],
             'label': '%s at %s' % (_game_name(m['game']) or 'A machine', m['address'])}
            for m in pad_ssh_key.machines()]


def _found_line(rec):
    """One machine a scan found, said plainly; one that doesn't let this computer in says what it is
    (PAD-1430: its server's own name, so a PC or a Raspberry Pi is told apart from a pinball machine's card)."""
    if rec.get('lets_in'):
        return '%s at %s' % (_game_name(rec.get('game')) or 'A machine', rec['address'])
    banner = (rec.get('banner') or '').replace('SSH-2.0-', '').strip()
    note = rec.get('note') or "doesn't let this computer in"
    if 'dropbear' in banner.lower():
        what = 'looks like a pinball machine card (%s) but %s: was its card set up from another computer?' % (
            banner, note)
    elif banner:
        what = 'runs %s, so it is a computer or other device, not a pinball machine; %s' % (banner, note)
    else:
        what = note
    return '%s %s' % (rec['address'], what)


def _scan_scope(report):
    """``'1022 addresses on 192.168.4.0/22, the 57 devices this computer knew of first'``: what a scan looked at
    (PAD-1430)."""
    if not report or not report.get('addresses'):
        return ''
    known = report.get('known') or 0
    careful = report.get('careful') or 0
    return '%d addresses on %s%s%s' % (report['addresses'], ', '.join(report.get('networks') or []),
                                       ', the %d devices this computer knew of first, unhurried' % known
                                       if known else '',
                                       # PAD-1456
                                       ', then the %d that didn\'t answer once more, slowly' % careful
                                       if careful else '')


def _careful_note(count):
    """What the scan says while it asks again, slowly (PAD-1456)."""
    from ...core import machine_scan
    secs = machine_scan.careful_seconds(count)
    when = 'up to about %d minutes' % round(secs / 60.0) if secs >= 90 else 'up to a minute'
    return ("No machine on the quick look; a machine just switched on is easily missed by one. Looking again, "
            "more slowly, at the %d addresses that didn't answer (%s)..." % (count, when))


class NetworkTab(TabService):
    ns = 'network'
    key = 'Network'
    label = 'Network'
    group = 'Make'
    icon = 'globe'

    def __init__(self, window):
        super().__init__(window)
        self._visible = False
        self.set(intro=INTRO, project='', source='', supported=False,
                 reason='Select a card image and project first.',
                 enabled=False, public_keys='', error='', running=False, send_intro=SEND_INTRO,
                 address=pad_ssh_key.last_address(), check='', check_kind='', checking=False, known=False,
                 # PAD-1427: remote access on a card with one button, and the machine found by a scan
                 cards=[], cards_state='', card='', setup_busy=False, setup_note='', setup_kind='', setup_pct=0,
                 scanning=False, scan_pct=0, scan_note='', scan_kind='', found=[],
                 machine_game=_game_name(pad_ssh_key.machine()['game']), machines=_machines_state())
        self._card_seq = 0
        self._scan_cancel = False
        self._found = {}

    def rail_needs(self):
        # PAD-1427: setting up a card and finding the machine need no project (only its builds' setting does)
        return 'none'

    def _project(self):
        return self.window.write_assets_var.get().strip()

    def _source(self):
        return self.window.write_upd_var.get().strip()

    def _inspect(self):
        mfr = self.mfr
        if not ssh_card.offered(mfr):
            return dict(supported=False, reason='Remote access works on Stern Spike 2 and Spike 3 cards only.',
                        enabled=False, public_keys='')
        if not self._source():
            # PAD-1399: no card picked yet read as "needs a regular card image file, not a device"
            return dict(supported=False, reason='Select the card image first (Select card tab).',
                        enabled=False, public_keys='')
        return ssh_card.inspect_image(self._source())

    def _inspect_wifi(self):
        """PAD-1467: whether the picked card can take the Wi-Fi start-up choice, and what it has now."""
        if not wifi_card.offered(self.mfr):
            return dict(supported=False, reason=wifi_card.NOT_SPIKE2, enabled=False, band5=False,
                        band5_supported=False, band5_reason=wifi_card.NOT_SPIKE2)
        if not self._source():
            # David: "the checkboxes are grayed out because you need to select a card first? Why?"  No card image
            # is needed to choose: a build checks the card it builds from, and the two direct routes check the
            # attached card or the machine when the option goes on.  Only a card that WAS picked and cannot take
            # it greys the box.
            return dict(supported=True, reason='', enabled=False, band5=False, band5_supported=True,
                        band5_reason='', stern_module=True, unpicked=True)
        return wifi_card.inspect_image(self._source())

    def _inspect_buttons(self):
        if not remote_buttons.offered(self.mfr):
            return dict(supported=False, reason=remote_buttons.NOT_SPIKE2, enabled=False)
        if not self._source():
            return dict(supported=True, reason='', enabled=False, unpicked=True)     # as the Wi-Fi boxes
        return remote_buttons.inspect_image(self._source())

    #: PAD-1467: the Wi-Fi and remote-buttons ticks with no project open: kept for this session, for the two
    #: direct routes (a build needs a project, and saves them there)
    _unsaved = {}

    @staticmethod
    def _choice_hint(info, project):
        """What to know about a tick made without a project or a card image picked ('' when both are)."""
        if not os.path.isdir(project or ''):
            return ('No project is open: these ticks are for the two buttons below. Open a project to save them '
                    'for the cards you build.')
        if info.get('unpicked'):
            return ('No card image is picked yet: the card, or the machine, is checked when the option is put '
                    'on it.')
        return ''

    def _publish_buttons(self, project):
        """PAD-1467: the remote-buttons choice and the four buttons (core/remote_buttons.py)."""
        info = self._inspect_buttons()
        on, error = info.get('enabled', False), ''
        try:
            rec = card_extras.load_buttons(project) if os.path.isdir(project) else self._unsaved.get('buttons')
            if rec is not None:
                on = rec['enabled']
        except card_extras.ExtrasError as e:
            error = str(e)
        self.set(buttons_offered=remote_buttons.offered(self.mfr), buttons_enabled=bool(on), buttons_error=error,
                 buttons_supported=bool(info['supported']), buttons_reason=info['reason'],
                 buttons_hint=self._choice_hint(info, project),
                 buttons_details=[list(row) for row in remote_buttons.DETAILS],
                 buttons_now='' if info.get('unpicked') else remote_buttons.describe(info),
                 buttons_labels=[list(pair) for pair in remote_buttons.LABELS])

    def _publish_feed(self):
        modes = self.window.service('modes')
        if modes is None:
            return
        try:
            modes._publish_feed(modes.project())
        except Exception:                                   # noqa: BLE001 - the card just stays as it was
            pass

    def publish(self):
        self._publish_feed()
        project = self._project()
        info = self._inspect()
        enabled, keys, error = info.get('enabled', False), info.get('public_keys', ''), ''
        try:
            rec = card_extras.load(project)
            if rec is not None:
                enabled, keys = rec['enabled'], rec['public_keys']
                card_extras.configuration(project)
        except card_extras.ExtrasError as e:
            error = str(e)
        wifi = self._inspect_wifi()
        wifi_on, wifi_band, wifi_error = wifi.get('enabled', False), wifi.get('band5', False), ''
        try:
            rec = card_extras.load_wifi(project) if os.path.isdir(project) else self._unsaved.get('wifi')
            if rec is not None:
                wifi_on, wifi_band = rec['enabled'], rec['band5']
        except card_extras.ExtrasError as e:
            wifi_error = str(e)
        unpicked = bool(wifi.get('unpicked'))
        self.set(wifi_details=[list(row) for row in wifi_card.DETAILS],
                 wifi_now='' if unpicked else wifi_card.describe(wifi),
                 wifi_band5=bool(wifi_on and wifi_band),
                 wifi_band5_supported=bool(wifi['supported'] and wifi.get('band5_supported')),
                 wifi_band5_reason=wifi.get('band5_reason', '') if wifi['supported'] else '',
                 wifi_band_details=[list(row) for row in wifi_card.BAND_DETAILS],
                 wifi_band_now='' if unpicked else wifi_card.describe_band(wifi),
                 wifi_hint=self._choice_hint(wifi, project),
                 wifi_compare=dict(head=list(wifi_card.COMPARE_HEAD), rows=[list(r) for r in wifi_card.COMPARE],
                                   note=wifi_card.COMPARE_NOTE),
                 wifi_adapters=dict(head=list(wifi_card.ADAPTER_HEAD), rows=[list(r) for r in wifi_card.ADAPTERS],
                                    note=wifi_card.ADAPTER_NOTE))
        self._publish_buttons(project)
        from ...core import network_apply
        self.set(ways={k: network_apply.ways(k) for k in network_apply.WAYS},
                 way_notes=dict(network_apply.WAY_NOTES))
        self.set(wifi_offered=wifi_card.offered(self.mfr), wifi_enabled=wifi_on, wifi_error=wifi_error,
                 wifi_supported=bool(wifi['supported']), wifi_reason=wifi['reason'])
        self.set(project=project, source=self._source(), supported=bool(info['supported'] and os.path.isdir(project)),
                 reason=info['reason'] if project else 'Select a project folder on the Extract tab first.',
                 enabled=enabled, public_keys=keys, error=error, offered=ssh_card.offered(self.mfr),
                 known=self._known())

    # ---- PAD-1427: remote access on a card with one button
    @rpc
    def refresh_cards(self):
        """List the cards plugged into this computer (an SD card reader), the likeliest picked."""
        self._card_seq += 1
        seq = self._card_seq
        self.set(cards_state='detecting')

        def work():
            try:
                from ...core.drives import list_physical_drives, pick_best_game_ssd, visible_drives
                drives = list_physical_drives()
                best = pick_best_game_ssd(drives, prefer='sd_card')[0]
                shown = visible_drives(drives, prefer='sd_card', keep=(best,) if best is not None else ())
            except Exception:                                   # noqa: BLE001 - said as "no cards"
                shown, best = [], None
            self.ctx.loop.post(self._cards_found, seq, shown, best)
        threading.Thread(target=work, daemon=True, name='pad-network-cards').start()
        return True

    def _cards_found(self, seq, shown, best):
        if seq != self._card_seq:
            return
        cards = [{'display': d.display, 'device': d.device_path} for d in shown]
        keep = self.get('card') if any(c['device'] == self.get('card') for c in cards) else ''
        pick = keep or (best.device_path if best is not None else (cards[0]['device'] if len(cards) == 1 else ''))
        self.set(cards=cards, cards_state='ok' if cards else 'none', card=pick)

    @rpc
    def pick_card(self, device):
        self.set(card=device or '', setup_note='', setup_kind='')
        return True

    @rpc
    def set_up_card(self):
        """Put remote access on the plugged-in card picked (asked first)."""
        device = self.get('card')
        if not device or self.get('setup_busy') or self.get('running'):
            return False
        shown = next((c['display'] for c in self.get('cards') or [] if c['device'] == device), device)
        if not compat.messagebox.askyesno(
                'Set up remote access',
                "Put remote access on the card in %s?\n\nPAD adds a small program to the card's system files "
                "that lets this computer in over your network, so Send to machine can reach the machine. The game, "
                "its settings and high scores stay as they are.\n\nYour computer may ask for administrator "
                "access to change the card." % shown, icon='warning'):
            return False
        return self._set_up(device)

    @rpc
    def set_up_image(self):
        """Put remote access on a card image file, in place (asked first)."""
        if self.get('setup_busy') or self.get('running'):
            return False
        path = self.window.ask_open('remote_access_image', 'Select the card image to set up remote access on',
                                    filetypes=[('SD card images', '*.raw *.img'), ('All files', '*.*')])
        if not path:
            return False
        if not compat.messagebox.askyesno(
                'Set up remote access',
                "Put remote access on %s?\n\nThe image file itself is changed: write it to the machine's card "
                "afterwards as usual." % os.path.basename(path)):
            return False
        return self._set_up(path)

    def _set_up(self, path):
        from ...core import remote_setup
        self.set(setup_busy=True, setup_pct=0, setup_note='Starting...', setup_kind='')
        project = self._project()
        loop = self.ctx.loop

        def log(text, level='info'):
            loop.post(self.log, text, level)
            loop.post(lambda: self.set(setup_note=text))

        last = [-1]

        def progress(done, total, msg=''):
            pct = int(done * 100 / total) if total else 0
            if pct != last[0]:
                last[0] = pct
                loop.post(lambda: self.set(setup_pct=pct))

        def work():
            try:
                res = remote_setup.set_up_with_privileges(path, log=log, progress=progress)
                image = os.path.isfile(path)
                where = os.path.basename(path) if image else 'The card'
                text = ('%s already had remote access, and it lets this computer in.' % where if res == 'already'
                        else '%s has remote access now.' % where)
                text += (" Write it to the machine's card, then use Find my machine." if image else
                         ' Put the card back in the machine, switch it on, then use Find my machine.')
                kind = 'ok'
            except Exception as e:                              # noqa: BLE001 - said, never raised into the UI
                text, kind = str(e) or e.__class__.__name__, 'err'
            loop.post(self._set_up_done, text, kind, project)
        threading.Thread(target=work, daemon=True, name='pad-remote-setup').start()
        return True

    def _set_up_done(self, text, kind, project):
        if kind == 'ok' and project and project == self._project() and self._inspect().get('supported'):
            # a card written later from this project keeps remote access, or the machine would lose it again
            try:
                rec = card_extras.load(project)
                if rec is None or not rec['enabled']:
                    card_extras.save(project, True, rec['public_keys'] if rec else '')
                    self.publish()
            except card_extras.ExtrasError:
                pass
        # last: the project's setting is saved before the page reads the setup as done
        self.set(setup_busy=False, setup_note=text, setup_kind=kind, setup_pct=100 if kind == 'ok' else 0)

    # ---- PAD-1427: find the machine on the network
    @rpc
    def scan(self):
        if self.get('scanning'):
            return False
        self._scan_cancel = False
        self.set(scanning=True, scan_pct=0, scan_note='Looking over your network...', scan_kind='', found=[])
        loop = self.ctx.loop

        def progress(done, total):
            pct = int(done * 100 / total) if total else 0
            loop.post(lambda: self.set(scan_pct=pct))

        def note(count):
            text = _careful_note(count)
            loop.post(lambda: self.set(scan_note=text))

        def work():
            from ...core import machine_scan
            report = {}
            try:
                found, err = machine_scan.scan(progress=progress, cancel=lambda: self._scan_cancel,
                                               report=report, note=note), ''
            except Exception as e:                              # noqa: BLE001
                found, err = [], str(e) or e.__class__.__name__
            loop.post(self._scanned, found, err, report)
        threading.Thread(target=work, daemon=True, name='pad-network-scan').start()
        return True

    @rpc
    def scan_state(self):
        return bool(self.get('scanning'))

    def _scanned(self, found, err, report=None):
        from ...core import machine_scan
        scope = _scan_scope(report)
        looked = (' Looked at %s.' % scope) if scope else ''
        ours = [r for r in found if r['lets_in']]
        rows = [dict(address=r['address'], lets_in=False, game='', line=_found_line(r))
                for r in found if not r['lets_in']]
        # every machine that lets this computer in is remembered (David: "I can have MANY machines on my
        # network"), each by its identity: one found at a new address is the same machine, moved
        known = {m['address'] for m in pad_ssh_key.machines()}
        for r in ours:
            if r.get('host_key'):
                pad_ssh_key.forget_host(r['address'], machine_scan.PORT)
                pad_ssh_key.remember_host(r['address'], machine_scan.PORT, *r['host_key'])
            pad_ssh_key.remember_machine(r['address'], r.get('host_key'), r.get('game') or '', make_current=False)
        current = pad_ssh_key.last_address()
        if ours and current not in {m['address'] for m in pad_ssh_key.machines()} | {r['address'] for r in ours}:
            current = ''
        if ours and not current:
            pad_ssh_key.select_machine(ours[0]['address'])
        self.set(scanning=False, scan_pct=100, found=rows if not ours else [])
        self._show_machine()
        new = [r for r in ours if r['address'] not in known]
        if err:
            self.set(scan_note="Couldn't look over the network: %s" % err, scan_kind='err')
        elif len(ours) == 1:
            self.set(scan_note='Found %s at %s, and remembered it.' % (
                _game_name(ours[0].get('game')) or 'a machine', ours[0]['address']), scan_kind='ok')
        elif ours:
            self.set(scan_note='Found %d machines (%s), and remembered them%s. Pick the one to send to.' % (
                len(ours), ', '.join(_game_name(r.get('game')) or r['address'] for r in ours),
                '' if len(new) == len(ours) else ', %d of them new' % len(new)), scan_kind='ok')
        elif found:
            self.set(scan_note=("Found no machine that lets this computer in, only the %d other device%s with "
                                "remote login listed below.%s Is the machine switched on and finished starting "
                                "up, on the same network as this computer (not a guest network), and was its card "
                                "set up for remote access from this computer?"
                                % (len(found), '' if len(found) == 1 else 's', looked)),
                     scan_kind='err')
        else:
            self.set(scan_note=("Found no device with remote login at all.%s Is the machine switched on and finished "
                                "starting up, on the same network as this computer (not a guest network), and was "
                                "its card set up for remote access?" % looked), scan_kind='err')

    @rpc
    def use_machine(self, address):
        """Make the known machine at *address* the one Send to machine (and Check connection) uses."""
        if not pad_ssh_key.select_machine(address):
            return False
        self.set(check='', check_kind='')
        self._show_machine()
        return True

    def _show_machine(self):
        rec = pad_ssh_key.machine()
        self.set(address=rec['address'], machine_game=_game_name(rec['game']), machines=_machines_state())
        self.set(known=self._known())

    # ---- PAD-1397: Send to machine
    def _known(self):
        from ...core import remote_send
        try:
            host, port = remote_send.parse_address(self.get('address'))
        except remote_send.SendError:
            return False
        return pad_ssh_key.host_key(host, port) is not None

    @rpc
    def set_address(self, address):
        address = (address or '').strip()
        pad_ssh_key.remember_address(address)
        self.set(check='', check_kind='')
        self._show_machine()
        return True

    @rpc
    def check_connection(self):
        """Log in and say what the machine runs, on a worker (a machine that isn't there takes seconds)."""
        if self.get('checking'):
            return False
        address = self.get('address')
        self.set(checking=True, check='Connecting...', check_kind='')

        def work():
            from ...core import remote_send
            try:
                from ...core import machine_scan
                host, port = remote_send.parse_address(address)
                m = remote_send.connect(address)
                try:
                    out = m.describe()
                    host, port = getattr(m, 'host', host), getattr(m, 'port', port)
                finally:
                    m.close()
                where = machine_scan.address_of({'address': host}, port)
                game = machine_scan.game_of(out)
                pad_ssh_key.remember_machine(where, pad_ssh_key.host_key(host, port), game,
                                             make_current=where == address or pad_ssh_key.last_address() == address)
                text, kind = ('Connected: the machine runs %s, and lets this computer in.'
                              % (_game_name(game) or 'a game'), 'ok')
                if where != address:
                    text += ' It is at %s now.' % where
            except remote_send.Unreachable as e:
                # PAD-1430: a typed address (no identity to look for) or one the router moved: look over the
                # network for any machine that lets this computer in, and say what was found
                # PAD-1456: the text taken now (``e`` is gone by the time the loop runs a lambda), and the
                # careful pass said too when the quick look finds nothing
                reason, loop = str(e), self.ctx.loop
                loop.post(lambda: self.set(check='%s Looking over your network for it...' % reason))

                def note(count):
                    text = '%s %s' % (reason, _careful_note(count))
                    loop.post(lambda: self.set(check=text))
                loop.post(self._check_by_scan, reason, *self._scan_for_check(note))
                return
            except remote_send.SendError as e:
                text, kind = str(e), 'err'
            except Exception as e:                      # noqa: BLE001 - said, never raised into the UI
                text, kind = 'Could not connect: %s' % e, 'err'
            self.ctx.loop.post(self._checked, text, kind)
        threading.Thread(target=work, daemon=True, name='pad-send-check').start()
        return True

    def _checked(self, text, kind):
        self.set(checking=False, check=text, check_kind=kind)
        self._show_machine()

    @staticmethod
    def _scan_for_check(note=None):
        """``(found, err, report)``: a whole scan, on the Check connection worker."""
        from ...core import machine_scan
        report = {}
        try:
            return machine_scan.scan(report=report, note=note), '', report
        except Exception as e:                          # noqa: BLE001 - said, never raised into the UI
            return [], str(e) or e.__class__.__name__, report

    def _check_by_scan(self, reason, found, err, report):
        """The machine didn't answer at its address: what a scan found instead (PAD-1430)."""
        ours = [r for r in found if r['lets_in']]
        self._scanned(found, err, report)
        if len(ours) == 1:
            pad_ssh_key.select_machine(ours[0]['address'])
            text, kind = ('%s Found %s at %s instead, which lets this computer in, and switched to it.' % (
                reason, _game_name(ours[0].get('game')) or 'your machine', ours[0]['address']), 'ok')
        elif ours:
            text, kind = ('%s Found %d machines that let this computer in (%s): pick the one to use above.' % (
                reason, len(ours), ', '.join(_found_line(r) for r in ours)), 'err')
        else:
            text, kind = '%s %s' % (reason, self.get('scan_note') or ''), 'err'
        self._checked(text.strip(), kind)

    @rpc
    def forget_machine(self):
        from ...core import remote_send
        try:
            host, port = remote_send.parse_address(self.get('address'))
        except remote_send.SendError:
            return False
        pad_ssh_key.forget_host(host, port)
        pad_ssh_key.forget_machine(self.get('address'))
        self.set(check="Forgotten. Find my machine finds it again, with its identity taken afresh.",
                 check_kind='')
        self._show_machine()
        return True

    @rpc
    def send_image(self):
        """Pick any card image and send it to the machine (the full Send when it isn't a build of the card the
        machine runs)."""
        if self.get('running'):
            return False
        fn = self.window.cb.get('on_send_image')
        address = self.get('address')
        if fn is None:
            return False
        if not address:
            compat.messagebox.showinfo('Send to machine', "Enter the machine's network address first.")
            return False
        path = self.window.ask_open('send_image', 'Select the card image to send to the machine',
                                    filetypes=[('SD card images', '*.raw *.img'), ('All files', '*.*')])
        if not path:
            return False
        game = self.get('machine_game')
        which = ('%s (at %s)' % (game, address)) if game else ('the machine at %s' % address)
        if not compat.messagebox.askyesno(
                'Send to machine',
                "Make %s run %s?\n\nA game being played on it ends: its screen shows PAD updating it until "
                "it is done. Only the files that differ are copied. The machine's own "
                'settings, audits and high scores stay as they are. If the image is another version or card, '
                'the machine restarts when it is done; leave it switched on until then.'
                % (which, os.path.basename(path)), icon='warning'):
            return False
        fn(path, address)
        return True

    # ------------------------------------------------------------------ PAD-1467: the machine's own screen
    # David: "the remote screenshot feature is actually really useful. can we build that into the network tab
    # too?" and "or even if we can do a 'screen share' live feed that would be killer" (core/machine_screen.py)
    def _screen_file(self):
        import tempfile
        folder = os.path.join(tempfile.gettempdir(), 'pad-webui-screen')
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, 'machine-screen.png')

    def _screen_shown(self, png, width, height, note):
        """A picture to show and to save: written where the page can load it, and said."""
        self._screen_png = png
        path = self._screen_file()
        try:
            with open(path, 'wb') as f:
                f.write(png)
        except OSError as e:
            self.set(screen_busy=False, screen_note='The picture could not be shown: %s' % e, screen_kind='err')
            return
        self.set(screen_busy=False, screen_path=path, screen_seq=int(self.get('screen_seq') or 0) + 1,
                 screen_note='%s (%d x %d).' % (note, width, height), screen_kind='ok')

    @rpc
    def capture_screen(self):
        """One picture of what the machine's screen shows now, on a worker."""
        if self.get('screen_busy') or self.get('screen_live') or not self.get('address'):
            return False
        address = self.get('address')
        self.set(screen_busy=True, screen_note='Reading the machine\'s screen...', screen_kind='')

        def work():
            import time as _time
            from ...core import machine_screen, remote_send
            try:
                m = remote_send.connect(address)
                try:
                    png, w, h = machine_screen.capture(m)
                finally:
                    m.close()
            except (machine_screen.ScreenError, remote_send.SendError) as e:
                text = str(e)
                self.ctx.loop.post(lambda: self.set(screen_busy=False, screen_note=text, screen_kind='err'))
                return
            except Exception as e:                      # noqa: BLE001 - said, never raised into the UI
                text = "Could not read the machine's screen: %s" % e
                self.ctx.loop.post(lambda: self.set(screen_busy=False, screen_note=text, screen_kind='err'))
                return
            self.ctx.loop.post(self._screen_shown, png, w, h, 'Captured at %s' % _time.strftime('%H:%M:%S'))
        threading.Thread(target=work, daemon=True, name='pad-screen-capture').start()
        return True

    @rpc
    def save_screen(self):
        """Save the picture on show (during a live view, the frame of that moment) as a PNG."""
        png = getattr(self, '_screen_png', None)
        live = getattr(self, '_live', None)
        if self.get('screen_live') and live and live.get('raw'):
            from ...core import machine_screen
            try:
                png = machine_screen.encode(live['raw'], live['geo'])
            except Exception:                           # noqa: BLE001 - the last captured picture is kept
                pass
        if not png:
            return False
        import time as _time
        path = self.window.ask_save('machine_screen', "Save the picture of the machine's screen",
                                    initialfile='machine-screen-%s.png' % _time.strftime('%Y%m%d-%H%M%S'),
                                    defaultextension='.png', filetypes=[('PNG picture', '*.png')])
        if not path:
            return False
        try:
            with open(path, 'wb') as f:
                f.write(png)
        except OSError as e:
            self.set(screen_note='The picture could not be saved: %s' % e, screen_kind='err')
            return False
        self.set(screen_note='Saved to %s.' % path, screen_kind='ok')
        return True

    def live_frame(self, seq, timeout):
        """For the page server's ``/screen``: ``(seq, jpeg)`` of a frame newer than *seq*, ``(seq, None)`` when
        none came within *timeout*, ``None`` once the live view has ended."""
        live = getattr(self, '_live', None)
        if not live:
            return None
        with live['cond']:
            if live['seq'] == seq and not live['done']:
                live['cond'].wait(timeout)
            if live['done']:
                return None
            if live['seq'] == seq:
                return seq, None
            return live['seq'], live['jpeg']

    @rpc
    def start_live(self):
        """The machine's screen, live, until Stop (or this tab is left, or the machine's side ends)."""
        if self.get('screen_busy') or self.get('screen_live') or not self.get('address') or self.get('running'):
            return False
        address = self.get('address')
        live = dict(cond=threading.Condition(), seq=0, jpeg=None, raw=None, geo=None, done=False, stop=False,
                    machine=None)
        self._live = live
        self.set(screen_live=True, screen_live_id=int(self.get('screen_live_id') or 0) + 1,
                 screen_note='Connecting...', screen_kind='', screen_rate='')

        def work():
            import time as _time
            from ...core import machine_screen, remote_send
            text, kind, last = 'Live view stopped.', 'ok', None
            m = view = None
            try:
                m = remote_send.connect(address)
                live['machine'] = m          # a button pressed during the live view uses its connection
                view = machine_screen.LiveView(m)
                live['geo'] = view.geo
                how = 'plain connection' if view.plain else 'encrypted connection, slower'
                stamps, said = [], 0.0
                for raw in view.frames():
                    if live['stop']:
                        break
                    jpeg = machine_screen.encode(raw, view.geo, 'JPEG')
                    rec = live.get('rec')
                    if rec is not None and len(rec) < 1800 and _time.monotonic() - live.get('rec_t', 0) < 300:
                        rec.append((_time.monotonic(), jpeg))
                    with live['cond']:
                        live['jpeg'], live['raw'] = jpeg, raw
                        live['seq'] += 1
                        live['cond'].notify_all()
                    last = raw
                    now = _time.monotonic()
                    stamps = [t for t in stamps if now - t <= 4.0] + [now]
                    if now - said > 2.0:
                        said = now
                        note = 'Live: %.1f frames a second (%s).' % (machine_screen.frame_rate(stamps, now), how)
                        self.ctx.loop.post(lambda note=note: self.get('screen_live') and self.set(screen_note=note))
                else:
                    text = "Live view ended: the machine stopped sending its screen."
            except (machine_screen.ScreenError, remote_send.SendError) as e:
                text, kind = str(e), 'err'
            except Exception as e:                      # noqa: BLE001 - said, never raised into the UI
                text, kind = 'Live view stopped: %s' % e, 'err'
            finally:
                live['machine'] = None
                for thing in (view, m):
                    try:
                        if thing is not None:
                            thing.close()
                    except Exception:                   # noqa: BLE001
                        pass
                with live['cond']:
                    live['done'] = True
                    live['cond'].notify_all()
            png = None
            if last is not None:
                try:
                    png = machine_screen.encode(last, live['geo'])
                except Exception:                       # noqa: BLE001
                    png = None
            self.ctx.loop.post(self._live_ended, live, text, kind, png)
        threading.Thread(target=work, daemon=True, name='pad-screen-live').start()
        return True

    def _live_ended(self, live, text, kind, png):
        if live.get('rec'):
            self._last_rec = live.pop('rec')     # a recording outlives its live view until it is saved
        if getattr(self, '_live', None) is live:
            self._live = None
        self.set(screen_live=False)
        if png and live.get('geo'):
            self._screen_shown(png, live['geo']['width'], live['geo']['height'],
                               text.rstrip('.') + '; the last frame is kept')
            if kind == 'err':
                self.set(screen_kind='err')
        else:
            self.set(screen_note=text, screen_kind=kind)

    @rpc
    def stop_live(self):
        live = getattr(self, '_live', None)
        if not live:
            return False
        live['stop'] = True
        return True

    # ------------------------------------------------------------------ PAD-1467: looking after the machine
    # David: "grabbing logs from the machine would be very useful. what else?" ... "make all of these"
    # (core/machine_care.py): status, logs, settings and scores, restart, the mode log
    def _care(self, what, work, ok_text=None):
        """Run ``work(machine)`` on a worker with a connection of its own; its answer (a line to show, or None) or
        the error is said under the Machine care buttons.  One at a time."""
        if self.get('care_busy') or not self.get('address') or self.get('running'):
            return False
        address = self.get('address')
        self.set(care_busy=what, care_note='', care_kind='', care_pct=None)

        def run():
            from ...core import machine_care, remote_send
            text, kind = ok_text or '', 'ok'
            try:
                m = remote_send.connect(address)
                try:
                    said = work(m)
                finally:
                    m.close()
                if said:
                    text = said
            except (machine_care.CareError, remote_send.SendError) as e:
                text, kind = str(e), 'err'
            except Exception as e:                      # noqa: BLE001 - said, never raised into the UI
                text, kind = '%s did not finish: %s' % (what, e), 'err'
            self.ctx.loop.post(lambda: self.set(care_busy='', care_note=text, care_kind=kind, care_pct=None))
        threading.Thread(target=run, daemon=True, name='pad-machine-care').start()
        return True

    def _care_name(self, what):
        from ...core import machine_care
        return machine_care.file_stem(self.get('machine_game_key') or self.get('machine_game') or 'machine', what)

    @rpc
    def machine_status(self):
        def work(m):
            from ...core import machine_care
            rows = machine_care.status(m)
            self.ctx.loop.post(lambda: self.set(care_status=[list(r) for r in rows]))
            return 'Read from the machine at %s.' % time.strftime('%H:%M:%S')
        return self._care('Reading the status', work)

    @rpc
    def grab_logs(self):
        if self.get('care_busy') or not self.get('address'):
            return False
        path = self.window.ask_save('machine_logs', "Save the machine's logs", initialfile=self._care_name('logs') + '.zip',
                                    defaultextension='.zip', filetypes=[('Zip file', '*.zip')])
        if not path:
            return False

        def work(m):
            from ...core import machine_care
            files, size = machine_care.grab_logs(m, path)
            return 'Saved %d files (%s) to %s.' % (files, machine_care._human(size), path)
        return self._care('Collecting the logs', work)

    @rpc
    def backup_settings(self):
        if self.get('care_busy') or not self.get('address'):
            return False
        path = self.window.ask_save('machine_settings', "Save the machine's settings, audits and high scores",
                                    initialfile=self._care_name('settings') + '.zip', defaultextension='.zip',
                                    filetypes=[('Settings backup', '*.zip')])
        if not path:
            return False

        def work(m):
            from ...core import machine_care
            res = machine_care.backup_settings(m, path)
            return 'Saved the settings, audits and high scores of %s (%d files) to %s.' % (
                _game_name(res['game']) or res['game'] or 'the machine', res['files'], path)
        return self._care('Backing up the settings', work)

    @rpc
    def restore_settings(self):
        if self.get('care_busy') or not self.get('address'):
            return False
        path = self.window.ask_open('machine_settings', 'Pick a settings backup to put back on the machine',
                                    filetypes=[('Settings backup', '*.zip'), ('All files', '*.*')])
        if not path:
            return False
        from ...core import machine_care
        try:
            manifest, _raw = machine_care.read_backup(path)
        except machine_care.CareError as e:
            self.set(care_note=str(e), care_kind='err')
            return False
        if not compat.messagebox.askyesno(
                'Restore settings',
                "Put the settings, audits and high scores saved on %s back on the machine?\n\nA game being "
                "played ends: the machine's game is held for a few seconds and starts again. What the machine has "
                'now is replaced; it is kept on the machine once, beside the restored ones.'
                % manifest.get('taken', 'an unknown date'), icon='warning'):
            return False

        def work(m):
            res = machine_care.restore_settings(m, path)
            return 'Put back %d settings files; the game has started again.' % res['files']
        return self._care('Restoring the settings', work)

    @rpc
    def restart_game(self):
        if self.get('care_busy') or not self.get('address'):
            return False
        if not compat.messagebox.askyesno('Restart the game', 'Restart the game on the machine? A game being played '
                                          'ends.', icon='warning'):
            return False

        def work(m):
            from ...core import machine_care
            line = machine_care.restart_game(m)
            return ('The game restarted.' if 'RESTARTED' in line
                    else "The game wasn't running." if 'NOT_RUNNING' in line else 'The game was stopped; it had not '
                    'started again after 40 s.')
        return self._care('Restarting the game', work)

    @rpc
    def restart_machine(self):
        if self.get('care_busy') or not self.get('address'):
            return False
        if not compat.messagebox.askyesno('Restart the machine', 'Restart the whole machine, as switching it off and '
                                          'on does? A game being played ends. It is back in about a minute.',
                                          icon='warning'):
            return False

        def work(m):
            from ...core import machine_care
            machine_care.restart_machine(m)
            return 'The machine is restarting; it is back on your network in about a minute.'
        return self._care('Restarting the machine', work)

    @rpc
    def follow_log(self, on):
        """Follow PAD's mode log on the machine: its last lines, read every two seconds until told to stop."""
        if not on:
            self._follow = None
            self.set(care_following=False)
            return True
        if self.get('care_following') or not self.get('address'):
            return False
        token = object()
        self._follow = token
        address = self.get('address')
        self.set(care_following=True, care_log='Connecting...')

        def run():
            from ...core import machine_care, remote_send
            text = ''
            try:
                m = remote_send.connect(address)
                try:
                    while self._follow is token:
                        tail = machine_care.mode_log_tail(m, 120) or "(the machine's card has no mode log yet)"
                        self.ctx.loop.post(lambda tail=tail: self._follow is token and self.set(care_log=tail))
                        for _ in range(20):
                            if self._follow is not token:
                                break
                            time.sleep(0.1)
                finally:
                    m.close()
            except Exception as e:                      # noqa: BLE001
                text = 'The mode log could not be followed: %s' % e
            if text:
                self.ctx.loop.post(lambda: self.set(care_following=False, care_note=text, care_kind='err'))
        threading.Thread(target=run, daemon=True, name='pad-follow-log').start()
        return True

    # ---- recording the live view (PAD-1467)
    @rpc
    def record_live(self, on):
        """Keep the live view's frames from now (up to five minutes), or stop and save them as a video."""
        live = getattr(self, '_live', None)
        if on:
            if not live or live.get('done'):
                return False
            live['rec'] = []
            live['rec_t'] = time.monotonic()
            self.set(screen_recording=True)
            return True
        frames = (live or {}).pop('rec', None) if live else None
        if frames is None:
            frames = getattr(self, '_last_rec', None)
        self._last_rec = None
        self.set(screen_recording=False)
        if not frames:
            return False
        seconds = max(frames[-1][0] - frames[0][0], 0.2)
        fps = max(1.0, min(15.0, (len(frames) - 1) / seconds)) if len(frames) > 1 else 5.0
        path = self.window.ask_save('machine_screen', "Save the recording of the machine's screen",
                                    initialfile=self._care_name('screen') + '.mp4', defaultextension='.mp4',
                                    filetypes=[('Video', '*.mp4'), ('Animated GIF', '*.gif')])
        if not path:
            return False
        try:
            from ...core import machine_screen
            kind = machine_screen.save_recording([f for _t, f in frames], fps, path)
        except Exception as e:                          # noqa: BLE001
            self.set(screen_note='The recording could not be saved: %s' % e, screen_kind='err')
            return False
        self.set(screen_note='Saved %d frames (%.0f s, %s) to %s.' % (len(frames), seconds, kind, path), screen_kind='ok')
        return True

    # ------------------------------------------------------------------ PAD-1467: straight onto a card or the machine
    # David: 'Add "Put on the attached card" and "Put on my machine now" to the Wi-Fi and Remote buttons panels'
    def _direct_options(self, kind):
        """``(wifi, buttons)`` for the panel *kind*: what its boxes say now (ticked goes on, unticked comes off)."""
        if kind == 'wifi':
            return {'enabled': bool(self.get('wifi_enabled')), 'band5': bool(self.get('wifi_band5'))}, None
        if kind == 'buttons':
            return None, {'enabled': bool(self.get('buttons_enabled'))}
        return None, None

    def _direct_start(self, kind, what, work):
        if self.get('direct_busy') or self.get('running'):
            return False
        loop = self.ctx.loop
        self.set(direct_busy=what, direct_for=kind, direct_note='Starting...', direct_kind='', direct_pct=None)

        def log(text, level='info'):
            loop.post(self.log, text, level)
            loop.post(lambda: self.get('direct_busy') and self.set(direct_note=text))

        last = [-1]

        def progress(done, total, msg=''):
            pct = int(done * 100 / total) if total else 0
            if pct != last[0]:
                last[0] = pct
                loop.post(lambda: self.get('direct_busy') and self.set(direct_pct=pct))

        def run():
            try:
                text, kind_ = work(log, progress), 'ok'
            except Exception as e:                      # noqa: BLE001 - said, never raised into the UI
                text, kind_ = str(e) or e.__class__.__name__, 'err'
            loop.post(lambda: self.set(direct_busy='', direct_note=text, direct_kind=kind_, direct_pct=None))
        threading.Thread(target=run, daemon=True, name='pad-network-direct').start()
        return True

    @rpc
    def put_on_card(self, kind):
        """Put this panel's options straight on the plugged-in card picked under Remote access (asked first)."""
        from ...core import network_apply
        wifi, buttons = self._direct_options(kind)
        device = self.get('card')
        if (wifi is None and buttons is None) or not device:
            return False
        shown = next((c['display'] for c in self.get('cards') or [] if c['device'] == device), device)
        if not compat.messagebox.askyesno(
                'Put on the attached card',
                "Put %s on the card in %s?\n\nOnly the card's system files change: the game, its settings and "
                "high scores stay as they are. Your computer may ask for administrator access."
                % (network_apply._said(wifi, buttons), shown), icon='warning'):
            return False
        source = self._source() or None

        def work(log, progress):
            res = network_apply.to_card_with_privileges(device, wifi=wifi, buttons=buttons, stern_from=source,
                                                        log=log, progress=progress)
            said = network_apply._said(wifi, buttons)
            return ('The card already had %s.' % said if res == 'already'
                    else 'The card has %s now. Put it back in the machine and switch it on.' % said)
        return self._direct_start(kind, 'Changing the card', work)

    @rpc
    def put_on_machine(self, kind):
        """Put this panel's options straight on the machine over remote access; it restarts (asked first)."""
        from ...core import network_apply
        wifi, buttons = self._direct_options(kind)
        address = self.get('address')
        if (wifi is None and buttons is None) or not address:
            return False
        if not compat.messagebox.askyesno(
                'Put on my machine now',
                "Put %s on the machine at %s now?\n\nThe machine restarts when it is done (about a minute), so a "
                "game being played ends. Its settings and high scores stay as they are."
                % (network_apply._said(wifi, buttons), address), icon='warning'):
            return False
        source = self._source() or None

        def work(log, progress):
            from ...core import remote_send
            stern = None
            if wifi is not None and not wifi.get('band5') and source:
                try:
                    stern = wifi_card._stern_module(source)
                except Exception:                       # noqa: BLE001 - asked for only if the machine needs it
                    stern = None
            m = remote_send.connect(address)
            try:
                res = network_apply.to_machine(m, wifi=wifi, buttons=buttons, stern_module=stern, log=log)
            finally:
                m.close()
            said = network_apply._said(wifi, buttons)
            return ('The machine already had %s; nothing was changed.' % said if res == 'already'
                    else 'The machine has %s now and is restarting; it is back in about a minute.' % said)
        return self._direct_start(kind, 'Changing the machine', work)

    def on_show(self):
        self._visible = True
        self.publish()
        self._show_machine()
        if not self.get('cards_state'):
            self.refresh_cards()

    def on_hide(self):
        self._visible = False
        self.stop_live()            # PAD-1467: a live view nobody is looking at stops loading the machine
        self._follow = None
        self.set(care_following=False)

    def on_project(self, folder):
        self.publish()

    def on_manufacturer(self, mfr):
        self.publish()

    def refresh_after_revert(self):
        self.publish()

    def on_running(self, running, mode):
        self.set(running=bool(running))

    @rpc
    def configure(self, enabled, public_keys, project):
        if project != self._project() or self.get('running') or not self._inspect()['supported']:
            return False
        try:
            card_extras.save(project, enabled, public_keys)
        except card_extras.ExtrasError as e:
            error = str(e)
            try:
                card_extras.stage_draft(project, enabled, public_keys)
            except card_extras.ExtrasError:
                # Never persist private keys, even as a disabled draft.
                pass
            self.publish()
            self.set(error=error)
            return False
        self.publish()
        write = self.window.service('write')
        if write is not None:
            write.reload_assets_tabs()
        return True

    @rpc
    def configure_buttons(self, enabled, project):
        """PAD-1467: save the project's remote-buttons choice; the next card written from it carries it."""
        info = self._inspect_buttons()
        if project != self._project() or self.get('running') or not info['supported']:
            return False
        if not os.path.isdir(project or ''):
            self._unsaved = dict(self._unsaved, buttons={'enabled': bool(enabled)})
            self.publish()
            return True
        try:
            card_extras.save_buttons(project, bool(enabled))
        except card_extras.ExtrasError as e:
            self.publish()
            self.set(buttons_error=str(e))
            return False
        self.publish()
        write = self.window.service('write')
        if write is not None:
            write.reload_assets_tabs()
        return True

    @rpc
    def press_button(self, name):
        """Press one of the machine's coin-door service buttons from here, on a worker: over the live view's
        connection when one is running (a press is then immediate), else over one of its own."""
        if name not in remote_buttons.BITS or not self.get('address') or self.get('running'):
            return False
        if self.get('buttons_busy'):
            return False
        address, live = self.get('address'), getattr(self, '_live', None)
        self.set(buttons_busy=True)

        def work():
            from ...core import remote_send
            text, kind = '', ''
            try:
                shared = live.get('machine') if live and not live.get('done') else None
                m = shared or remote_send.connect(address)
                try:
                    res = remote_buttons.press(m, name)
                finally:
                    if shared is None:
                        m.close()
                if not res['ok']:
                    text, kind = res['reason'], 'err'
            except remote_send.SendError as e:
                text, kind = str(e), 'err'
            except Exception as e:                      # noqa: BLE001 - said, never raised into the UI
                text, kind = 'The button could not be pressed: %s' % e, 'err'
            self.ctx.loop.post(lambda: self.set(buttons_busy=False, buttons_note=text, buttons_kind=kind))
        threading.Thread(target=work, daemon=True, name='pad-button-press').start()
        return True

    @rpc
    def configure_wifi(self, enabled, project, band5=None):
        """PAD-1467: save the project's Wi-Fi choices; the next card written from it carries them.  *band5* None
        keeps the 5 GHz choice as it is (it goes off with the start-up choice, which it needs)."""
        info = self._inspect_wifi()
        if project != self._project() or self.get('running') or not info['supported']:
            return False
        try:
            if band5 is None:
                rec = (card_extras.load_wifi(project) if os.path.isdir(project or '')
                       else self._unsaved.get('wifi'))
                band5 = bool(rec and rec['band5'])
            if band5 and not info.get('band5_supported'):
                return False
            if not os.path.isdir(project or ''):
                self._unsaved = dict(self._unsaved, wifi={'enabled': bool(enabled),
                                                          'band5': bool(enabled and band5)})
                self.publish()
                return True
            card_extras.save_wifi(project, enabled, bool(enabled and band5))
        except card_extras.ExtrasError as e:
            self.publish()
            self.set(wifi_error=str(e))
            return False
        self.publish()
        write = self.window.service('write')
        if write is not None:
            write.reload_assets_tabs()
        return True


TAB = NetworkTab
