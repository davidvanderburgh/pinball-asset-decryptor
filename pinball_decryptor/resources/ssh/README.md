# Card SSH payload

Copied from the user's MIT-licensed stern-event-agent/ssh-image payload.
Dropbear/dropbearkey 2025.88: static musl ARM EABI5, public-key authentication
only, password authentication compiled out, DROPBEAR_REEXEC=0 for the Spike 2
3.14 kernel. sftp-server: static Go ARMv7, pkg/sftp v1.13.2, kr/fs v0.1.0,
golang.org/x/{crypto,sys} v0.7.0. License notices are alongside this file.

The rebuilding script is included as build-binaries.sh. Run it in
this directory with a Docker-compatible CLI available; it writes armv7/.
Update the pinned hashes in core/ssh_card.py, and repeat emulator qualification
before distributing a changed payload. The script downloads the pinned
upstream tag and the musl.cc cross toolchain rather than building on the end
user's computer. A rebuild can differ with newer compiler/Go packages; the
shipped binary hashes identify the exact payload that passed qualification.

The service script is PAD's own; no event logger or host private keys are
bundled. Keys are generated on the target's persistent data partition.

Spike 3 uses the same versions and key-only options, built natively for
AArch64 with static musl/Go binaries. Rebuild with
`CONTAINER_ENGINE=podman bash build-aarch64.sh` on an AArch64 container host.
The hash pins are in `core/ssh_spike3.py`. This payload uses
`/usr/local/libexec/pad-sftp-server`, preserving the card's stock
`/usr/libexec/sftp-server`. Its Buildroot startup hook is
`/etc/init.d/S60padsshd -> sshd`; authorized keys go in
`/root/.ssh/authorized_keys`. Both platforms retain host keys in
`/data/dropbear`. Repeat each platform's qualification after a payload change.
