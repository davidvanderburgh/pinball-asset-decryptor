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

from .base import TabService, rpc
from ...core import card_extras, ssh_card

#: the page's lead: what the tab is for, said to someone who has never heard of either
INTRO = ("For a machine connected to your home network, by the same cable or Wi-Fi Insider Connected uses. "
         "Tick what you want, then Write the card.")


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
                 enabled=False, public_keys='', error='', running=False)

    def rail_needs(self):
        return 'project'

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
                 enabled=enabled, public_keys=keys, error=error)

    def on_show(self):
        self._visible = True
        self.publish()

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
