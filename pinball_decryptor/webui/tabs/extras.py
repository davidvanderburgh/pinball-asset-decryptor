"""Project-local system options for emulator-qualified card platforms."""

import os

from .base import TabService, rpc
from ...core import card_extras, ssh_card


class ExtrasTab(TabService):
    ns = 'extras'
    key = 'Extras'
    label = 'Extras'
    group = 'Replace'
    icon = 'gear'

    def __init__(self, window):
        super().__init__(window)
        self.set(project='', source='', supported=False, reason='Select a card image and project first.',
                 enabled=False, public_keys='', error='', running=False)

    def rail_needs(self):
        return 'project'

    def _project(self):
        return self.window.write_assets_var.get().strip()

    def _source(self):
        return self.window.write_upd_var.get().strip()

    def _inspect(self):
        mfr = self.mfr
        if (getattr(mfr, 'key', '') != 'stern'
                or getattr(mfr, '_era', 'spike2') not in ('spike2', 'spike3')):
            return dict(supported=False, reason='SSH has not passed emulator qualification for this platform.',
                        enabled=False, public_keys='')
        return ssh_card.inspect_image(self._source())

    def publish(self):
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
        self.publish()

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


TAB = ExtrasTab
