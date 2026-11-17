# Extras: SSH server on written cards

Status: approved 2026-11-17. Work branch: `mattlqx/extras-ssh`.

## Intent and scope

Add **Extras** under the existing **Replace** sidebar group. Its first option lets a user configure key-only SSH access to a card when PAD builds and writes it, using the working Dropbear setup from `stern-event-agent/ssh-image`.

The user's release requirement is a hard constraint: **a platform may expose an enabled SSH control only after this PAD integration has passed functional emulator testing on that platform**. Manufacturer names alone are not platform identifiers. Stern Spike 1, Spike 2, Spike 3, and CGC Pulp Fiction have different systems and must be qualified separately. No live cabinet changes are part of this work.

Start with Stern Spike 2. Investigate other locally available systems, especially Pulp Fiction, and enable additional adapters only when they pass the same checks. An unavailable image or failed test means unsupported, with the reason recorded; it does not weaken the release requirement or block shipping a proven Spike 2 implementation.

## Approaches

Recommended engineering choice: a project-staged Extras option and a PAD-owned image preparation module called inside the build pipeline, before success is reported or flashing starts. Reuse the existing Dropbear payload and filesystem layout, with provenance and rebuilding instructions. This fits PAD's project state and manufacturer pipelines, and makes a failure stop the build.

Two alternatives were considered: calling the other repository's shell script, which would make a released PAD depend on a developer checkout and host-specific tools; and patching a physical card after flashing, which would add a second write operation after PAD has already reported a completed image. Neither is the proposed implementation.

## User experience

The screen uses PAD's existing tab, form, help, and staging conventions:

```text
Replace
  ...
  Color profile
  Extras

Extras
  SSH server
  [ ] Enable SSH server

  SSH public keys (one key per line)
  +--------------------------------------------------+
  | ssh-ed25519 AAAA... workstation                   |
  | ssh-ed25519 AAAA... another computer              |
  +--------------------------------------------------+

  Saved with this project. Applied when you build the card.
  Connect as root on port 22 using one of these keys.
```

Keep the page visible for card-writing manufacturers, with the SSH controls disabled and an explanation when the detected card platform is unsupported. A manufacturer switch cannot carry an enabled value into another platform. There is no additional visual redesign.

Settings belong to the current project and are restored on project changes and restart. Public keys are retained while the checkbox is off, so toggling does not erase the user's input. Changes participate in the Write tab's staged-change summary and build/no-change decision: SSH alone must be sufficient to build a card.

Proposed checkbox semantics: a project with no SSH configuration leaves its source image's behavior unchanged. On opening a supported source card, inspect whether it already carries the recognized SSH setup and show that state. An explicit checked or unchecked setting becomes the desired state of the next output: checked installs/enables it; unchecked disables the recognized setup, including one originally installed by the existing `stern-event-agent` script. Do not remove unrelated files or silently re-enable a stock competing daemon. Inspecting a factory card does not itself stage changes.

When enabled, at least one supported, valid public key is required. Accept pasted multiline keys and ordinary comments/blank lines, normalize CRLF, and reject private keys, malformed SSH key blobs, unsupported key types/options, and invalid lines with a line-numbered error. The implementation will explicitly define and test the accepted key types against the bundled server. Do not print key blobs in logs or errors. Validate again in the build backend, including calls that bypass the screen.

## State and build integration

Use an `extras` section in the project's existing `.staged_changes.json`, preserving unrelated sections. Store desired enablement and normalized public-key text, distinguishing no configuration from an explicit disabled setting. Use the existing tab RPC/state pattern and project change notifications.

Engineering choice identified by the design review: SSH settings remain local to the project owner. Exclude the SSH enablement and public keys from mod-pack/replacement exports, portable presets, and their corresponding imports; downloading somebody's mod must never authorize their key on the recipient's card. A local project-folder backup can retain the setting. Add regression coverage for these sharing boundaries. This restriction does not affect the reusable feature code or bundled server payload.

Image preparation is a required worker phase before the manufacturer pipeline reports success. Do not use `App._apply_staged_settings_to_build` as a template for error handling: that method is post-success and tolerates errors, which is unsuitable for SSH. Validate platform, source/output separation, keys, payload availability, and filesystem support before expensive work. Propagate failures and cancellation so no chained flash starts on an incomplete output. A partially prepared output must not be presented as a successful, flashable build.

Rebuilds, incremental builds, changes to keys, and disabling a previously enabled output must converge on the current desired state rather than retain stale SSH settings. Keep enough build state to detect a changed Extras configuration. Never treat an earlier output as the pristine source for restoring unrelated data.

Build-and-flash must flash the prepared image. For flash-only, Direct-SD/SSD, menu-only updates, or emulator asset overrides that cannot apply the requested system change safely, refuse the incompatible operation with a direct instruction to build the complete image first. A previously built image may still be flashed as-is when no pending Extras change needs application. Do not silently claim project SSH settings were applied to a flash-only image. Use the existing whole-device confirmation and elevation flow; do not add new physical-card mutation paths.

## Spike 2 adapter

Read and validate the actual partition table and root filesystem signature; do not assume King Kong offsets for other cards. Work on a scratch copy of the output's system partition, and verify it before committing it back to the image. The original is read-only. Reject device paths, overlapping or out-of-bounds partitions, unsupported layouts, unhealthy filesystems, insufficient space, and failed checks.

Match the established layout:

- `/usr/local/bin/dropbear` and `/usr/local/bin/dropbearkey`, executable and root-owned.
- `/usr/libexec/sftp-server`, executable and root-owned.
- `/etc/init.d/sshd` plus `/etc/rc5.d/S30sshd` for startup.
- `/home/root/.ssh` mode 0700 and `authorized_keys` mode 0600, root-owned.
- Key-only authentication, root login on port 22, persistent host keys generated on first boot in `/data/dropbear`.

The public-key list replaces the configured authorized-key list. Preserve existing host keys, game content, audits, scores, and settings. Never bake one machine's host private keys into a distributed image. Do not deploy the event logger or change game modes as part of enabling SSH. Disabling removes the recognized service's startup, without deleting persisted host keys.

Use PAD's filesystem/executor facilities where practical so released Windows, Linux, and macOS builds work. Carry the binary payload, exact hashes, upstream license notices, source/version information, and reproducible build instructions inside this feature's owned resources. Include them in all three packaging paths; do not depend on a local `stern-event-agent` checkout or compile at card-write time.

## Additional platform adapters

Each adapter owns its filesystem identification, guest ABI, root home, boot integration, persistence path, and any stock SSH conflict. Pulp Fiction is a candidate because the related project already identified a competing OpenSSH Upstart job; simply adding Dropbear there is insufficient. The installed game rootfs inside an installer payload is the target, not just the installer's temporary OS. Stock-server suppression and the Dropbear service must be validated together.

Spike 1 and Spike 3 are not covered by a Spike 2 test. An ARM binary running on the host architecture also does not qualify an emulated foreign ABI. Other manufacturers remain unavailable unless real image-derived tests support their exact platform adapter. Adapter implementations and the public support registry are added only with passing evidence.

## Validation and acceptance

Add meaningful backend, pipeline, project-state, and UI regression tests for validation, enable/disable/key replacement, rebuilding, cancellation/failure, unsupported-card refusal, and the SSH-only build path. Use tiny filesystem fixtures for preservation and corruption cases. Verify the rendered sidebar and form through browser testing, using the existing frontend testing workflow.

For every enabled adapter, build from a real card/installer through PAD's integration with throwaway public keys generated **before injection**. Then test the resulting image in an isolated emulator environment using the guest's own rootfs and installed boot/service entry point. Do not substitute another authorized-key file after injection. Verify:

1. Startup invokes the installed service; first-run host keys are generated at the persistent path.
2. An authorized SSH key authenticates as root and executes a command; a second authorized key also works.
3. An unauthorized key and password-only authentication are rejected.
4. SFTP upload/download is byte-identical.
5. Restart retains host identity, changed keys take effect, and disabling prevents the service from starting again.
6. Filesystem checks pass, source hashes are unchanged, and image bytes outside the intended filesystem changes are preserved.
7. The game still reaches its established emulator startup/attract milestone on the prepared card, without requiring a physical machine. The existing game-only launcher is not itself evidence of SSH boot integration.

Use dedicated disposable containers and scratch images. Do not alter the user's currently running emulator containers, physical cards, or cabinet services. Clearly describe the distinction between guest-rootfs/service emulation and full system/kernel boot in the evidence; do not claim cabinet validation.

Commit a support matrix and reproducible commands/results under the repository's docs. Complete means only adapters with passing emulator evidence are enableable, the UI/build tests pass, and the feature is reviewable on its feature branch. Publishing, merging, and deployment to cabinets are outside this request. Routine implementation choices remain with the builder.
