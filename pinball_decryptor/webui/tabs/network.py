"""Network: what a card does with the owner's home network (PR #38 review, David's call).

Two things only matter once the machine is plugged into the owner's network (the connection Insider Connected
uses), and are set once and built onto the card: the **score feed** (PAD-1204: each game's final scores posted to a
server of the owner's own; moved here from Play options, whose other options change how the game plays) and
**remote access** (SSH, PR #38 by mattlqx: a computer on that network logs in to the machine and copies files to and
from it, no SD card pulled; emulator-qualified Stern Spike 2 and Spike 3 cards only).

The score feed's state and actions stay the Modes service's (``modes.set_score_feed``; this tab asks it to publish
for the project, as Play options does for its options). Remote access is this tab's own: the project's
``.staged_changes.json`` ``extras.ssh`` record (core/card_extras.py; the key stays as the PR wrote it)."""

import os
import threading

from .base import TabService, rpc
from .. import compat
from ...core import card_extras, pad_ssh_key, ssh_card

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
    """One machine a scan found, said plainly."""
    if rec.get('lets_in'):
        return '%s at %s' % (_game_name(rec.get('game')) or 'A machine', rec['address'])
    return '%s: %s' % (rec['address'], rec.get('note') or "doesn't let this computer in")


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

        def work():
            from ...core import machine_scan
            try:
                found, err = machine_scan.scan(progress=progress, cancel=lambda: self._scan_cancel), ''
            except Exception as e:                              # noqa: BLE001
                found, err = [], str(e) or e.__class__.__name__
            loop.post(self._scanned, found, err)
        threading.Thread(target=work, daemon=True, name='pad-network-scan').start()
        return True

    @rpc
    def scan_state(self):
        return bool(self.get('scanning'))

    def _scanned(self, found, err):
        from ...core import machine_scan
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
            self.set(scan_note=("Found no machine that lets this computer in, only other devices. Is the machine "
                                "switched on, and was its card set up for remote access from this computer?"),
                     scan_kind='err')
        else:
            self.set(scan_note=("Found no machine. Is it switched on and plugged into your network, and was its "
                                "card set up for remote access?"), scan_kind='err')

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

    def on_show(self):
        self._visible = True
        self.publish()
        self._show_machine()
        if not self.get('cards_state'):
            self.refresh_cards()

    def on_hide(self):
        self._visible = False

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


TAB = NetworkTab
