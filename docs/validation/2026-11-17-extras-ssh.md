# Extras SSH qualification — 2026-11-17

## Support matrix

| Platform | SSH option | Evidence / reason |
|---|---|---|
| Stern Spike 2, recognized SysV/ext rootfs | Available | Real King Kong LE 0.97.0 image; full pipeline, guest SSH lifecycle and game startup checks passed below. |
| Stern Spike 1 | Unavailable | Distinct ABI/rootfs/boot integration; no passing test of this adapter. |
| Stern Spike 3 | Unavailable | Encrypted platform and different boot integration; no passing test of this adapter. |
| CGC Pulp Fiction | Unavailable | Investigated related Dropbear work. Its game OS is inside `emmc.img` inside the installer, with a competing stock OpenSSH Upstart job. This Spike 2 adapter cannot safely apply there; no PAD adapter qualified. |
| Other CGC, JJP, Spooky, Barrels of Fun, Dutch Pinball, American Pinball, Pinball Brothers | Unavailable | No platform-specific PAD injector and passing emulator qualification. |

Availability depends on the card contents, not its filename or manufacturer label. Unrecognized/competing SSH services and unsafe layouts are refused. This does not claim every historical Spike 2 release or altered Linux distribution was tested.

## Reproduce the SSH qualification

From the checkout's Python environment (with its requirements installed), using a source factory card image and a **new** work directory shared with the container engine:

```sh
python scripts/validate_card_ssh.py \
  --source /path/to/king_kong_le-0_97_0.Release.16G.sdcard.raw \
  --work-dir /path/to/new/ssh-qualification \
  --engine podman
```

The script generates disposable client keys before injection, builds through `SternWritePipeline`, and starts a dedicated container with the built card's own rootfs. It executes `/etc/rc5.d/S30sshd` in the guest under QEMU. `/data` is backed by a persistent test folder; the source image is never mounted writable. Existing emulator containers and cabinets are untouched. The script removes its own container, leaving logs, scratch image, disposable keys and `results.json` for inspection; delete that work directory when finished.

The recorded run used `docker.io/library/pad-spike2-emu:c2977305564` with its installed ARM QEMU interpreter. This is **guest userspace and service/boot-hook emulation**, not a full guest-kernel boot or a cabinet test.

All checks passed on the current integration:

- SSH-only builds through the real PAD pipeline, without an audio/image/video replacement.
- Public-key login as root using two Ed25519 keys, RSA, and ECDSA nistp256/384/521.
- An unauthorized key and password-only login are refused; only `publickey` is advertised.
- A 4096-byte SFTP upload/download is byte-identical.
- Service restart retains all three host private keys in `/data/dropbear` and the pinned SSH host identity.
- A rebuilt image replacing the authorized-key list admits the retained key and rejects the removed key; host identity survives another rootfs boot.
- A disabled rebuild has no startup hook, no Dropbear process and no working SSH connection; persisted host keys remain intact.
- Every output byte outside the system partition matches the source, including boot, game, data and dump regions. Filesystem checks, root ownership, executable/key permissions and injected-file content are checked by PAD before write-back.

Exact source/output/rootfs and payload hashes are in [the recorded results](2026-11-17-extras-ssh-results.json). Test client private keys and guest host private keys are not committed.

## Game emulator check

Dedicated `pad-extras-game-20261117` and `pad-extras-game-final-20261117` containers booted the written SSH-enabled King Kong images (the final run used the exact full-pipeline artifact identified in the results JSON) with fresh home/rootfs volumes and the checkout's `tools/spike2_emu` rig. The existing rig's first-run GL bridge ordering did not build its guest EGL shim before starting, so the documented `buildbridge.sh` prebuild was run before restarting the disposable game container. No emulator source changes were needed.

The game reached its rendered **Guided Setup** screen and decoded/played LCD video. This is the factory-empty card's startup milestone; attract mode and physical cabinet behavior are not claimed. The game emulator's direct launcher does not start SysV services, so this check is separate from the actual guest SSH boot-hook tests above.

The run shape was:

```sh
# Use dedicated, empty volumes and a disposable container name.
podman run --rm --user 0 --privileged --security-opt seccomp=unconfined \
  -v extras-test-home:/pad/home -v extras-test-rootfs:/pad/rootfs \
  -v /path/to/new/ssh-qualification:/work:ro \
  -v /path/to/checkout/tools/spike2_emu:/pad/rig:ro \
  -e PAD_CARD=/work/ssh-card.raw -e PAD_HIDDEN=1 -e PAD_PLAYFIELD=0 \
  --entrypoint /bin/bash docker.io/library/pad-spike2-emu:c2977305564 -c \
  'bash /pad/rig/rootfs.sh "$PAD_CARD" && bash /pad/rig/buildbridge.sh && exec bash /pad/rig/docker/entrypoint.sh watch.sh 3'
```

## UI and regression verification

The Browser plugin was not available, so Playwright with headless local Chrome exercised the real rendered page at 1360×1000. Extras appeared in Replace, multiline key edits saved, and enabling/disabling updated the project. No browser console or page errors were observed. The UI test process had isolated settings and an isolated project.

Regression coverage includes key syntax/cryptographic points, strict persistence failures, malicious raw project-state mod imports, source aliases, incomplete outputs, foreign services, payload tampering, cancellation, enable/replace/disable, SSH-only builds, pipeline failure handling and project-switch isolation. Existing build-update, write-computation, staging, mod-pack, and emulator-override tests were also run. Final combined verification: **271 passed, 4 skipped**.
