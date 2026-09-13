# JJP multi-boot in the emulator (item 117)

The JJP twin of `tools/spike2_emu/codeselect/DESIGN.md`: how a multi-boot
install ISO (`mkjjpmulti.py`, item 116) boots in this rig, which script does
what, and what has been proven. The plan is `plans/jjp_multiboot_plan.md`
(gitignored, on David's machine); the menu is `jjpselect` (item 114) and the
hook `padselect.sh` (item 115), both in `tools/spike2_emu/codeselect/`.

## What a multi-boot install is, in one paragraph

Image 0's root goes into JJP's root A with the menu staged into it; image 1's
root goes into root B byte for byte; the stick's own installer, copied to
`/jjp/pad_install.sh` and patched on two lines, restores root B from the
second image's pieces. grub never changes and the machine always boots A, so
perm A (settings, audits, scores) is one set for both. On every boot root A's
`rungame.sh` runs `padselect.sh` after `runonce.sh`: fewer than two images,
nothing; otherwise JJP's updater is masked (it would write root B and boot
it), `jjpselect` draws the menu on the X server the machine already started
and reads the cabinet buttons off `/dev/jjpio100`, and for image 1 the hook
mounts root B at `/jjpe/multi/b` (by the UUID in the card's own
`fs_uuids.sh`), bind-mounts `/jjpe/multi/b/jjpe/gen1/<Game>` over
`/jjpe/gen1/<Game>`, re-does what `runonce.sh` did on the tree the game now
sees (the `vf` link into perm, chown, +x) and returns. Any failure unwinds to
image 0. The game then starts exactly as it always did.

## How the rig boots it

Every path is `padpath.sh`'s; `JJP_ISO=<multi.iso>` picks the base
`/var/tmp/jjp_<slug>/` like any other title.

| step | script | what changed for multi-boot |
|---|---|---|
| restore | `mount.sh` | restores EVERY `sdaN.ext4-ptcl-img` set the ISO carries, not a fixed list: `sda3.raw` (root A with the menu) and `sda5.raw` (root B) both land in the base; root B is loop-mounted read-only at `$JJP_ROOTB` (`<base>/rootb`). Prints `multiboot=` and `rootb=`. |
| jail | `jail.sh` | when `$JJP_ROOTB` is mounted, lays an overlay of it (tmpfs upper `$JJP_OVLB`, because root B is rw on the machine and the hook chowns and links inside it) at `$JJP_JAIL/jjpe/multi/b`, the path the hook looks at FIRST. So the hook takes its "already there" branch and never touches `/dev/disk/by-uuid`: one script serves the machine and the rig. |
| run | `run_game.sh` | the RUN executes in a mount namespace of its own (`unshare -m --propagation private`), and runs `$JJPEDIR/scripts/padselect.sh` at the point the machine's `rungame.sh` does (display up, before `./game`) when root A carries it. The hook's binds and the updater mask die with the run. `JJP_SELECT` is the three-way switch: unset = ask the image, `1` = insist (exit 9 when the image has no hook), `0` = skip the menu. The hook runs BEFORE the `cd $GAMEDIR`: a shell already inside the directory would keep the old one under the bind. Right before `./game` the run logs `[rig] game tree: <findmnt SOURCE,OPTIONS of $GAMEDIR>`. The launch watch counts a live `jjpselect` as up, because a run sits in the menu for up to the conf's timeout before a game process exists. |
| facts | `status.sh` | `multiboot=` (root A carries hook + conf), `rootb_mounted=`, `selector_procs=`, `choice=` (the integer the menu wrote), `bound=` / `bound_lower=` (asked INSIDE the run's namespace with `nsenter -t <leader> -m findmnt`; `bound_lower` ending in `/rootb` is image 1, empty is image 0 or no run). |
| alive | `alive.sh` | counts `jjpselect` with the game: a rig in the menu is live. `killgame.sh` kills it with the game (a client of the nested Xephyr, so no ghost). |
| teardown | `unjail.sh` | takes root B's overlay and its tmpfs down before the jail. The hook's own binds need nothing: the namespace died with the run. |

Two overlays read alike. Both roots are overlays in the rig, so a bind of
either shows `overlay[/jjpe/gen1/GunsNRoses]` as its SOURCE; the mount
OPTIONS (`lowerdir=…/rootb` vs `…/root`) are what tell them apart, which is
why the log line and `status.sh` carry them. On the machine the source reads
`/dev/sda5[/jjpe/gen1/GunsNRoses]` and there is no ambiguity.

## Running it

```
wsl -u root -- env JJP_ISO=/var/tmp/jjp116/GunsNRoses-v03.03.multi.iso bash tools/jjp_emu/watch.sh
```

is the whole thing (mount, jail, dongle, audio, boards, display, game, the
matrix): the menu appears on the Xephyr window, LEFT / RIGHT move, START
confirms, the timeout boots the highlighted image. `JJP_SELECT=0` in the
environment skips the menu (image 0), `JJP_SELECT=1` insists on it. To drive
the menu from a script, poke the cabinet bytes in the shared block the CUSE
boards serve (RIGHT = byte 1 bit 2, LEFT = byte 1 bit 0, START = byte 3 bit 0,
active low; `jjpshm.h`).

Scripted runs wait for the MENU, not for a process: `JJP_SELECT_LOG=1` makes
the hook hand the selector `--log /jjpe/temp/jjpselect.log` (the same
`PADSELECT_SELECT_LOG` knob the hook's tests use), and a driver polls that
file for its `menu:` line before it pokes a button. A poke that lands while
the selector is still starting is simply lost: the first run of 2026-09-13
recorded no choice for exactly that reason, and the rerun with the wait
recorded every key.

## Proof (2026-09-13, the GNR multi-boot ISO of item 116, no Sentinel key attached)

| step | oracle | result |
|---|---|---|
| restore | `mount.sh` on the 12.97 GB ISO | sda3, sda2, sda4 and sda5 restored in 2 min 28 s; `multiboot=1`, `rootb=<base>/rootb` |
| root A | its tree | `padselect/{jjpselect,font.ttf,images.conf,build.json,media.json,media/}`, `scripts/padselect.sh`, the hook line at `rungame.sh` 32-33 |
| root B | its tree | Chaka's `GunsNRoses` with `edata` 5,157,432,132 B (root A's stock one: 4,450,623,016 B) |
| jail | `jail.sh` | `root B  : /var/tmp/jjp_run/jjpe/multi/b (overlay of <base>/rootb)`, the game dir visible there |
| choose 1 | RIGHT, START | selector log `chose 1 CHAKA'S LOTLJ`; hook log `image 1: rootB - /jjpe/multi/b/jjpe/gen1/GunsNRoses bound over /jjpe/gen1/GunsNRoses (root B was already at /jjpe/multi/b)`; game log `[rig] game tree: overlay[/jjpe/gen1/GunsNRoses] rw,relatime,lowerdir=<base>/rootb,upperdir=/var/tmp/jjp_ovlb/up,…`; `status.sh` `choice=1` |
| choose 0 | RIGHT, RIGHT (wraps), START | `chose 0 GUNS N' ROSES 3.03`; hook `image 0 chosen: the primary, already in place`; game log `[rig] game tree: /jjpe/gen1/GunsNRoses (no bind: image 0)`; `choice=0` |
| `JJP_SELECT=0` | no menu | `selector_procs=0`, no hook log, `no bind: image 0` |
| `JJP_SELECT=1` | the menu must run | it ran; START alone chose the default 0 |
| updater | every menu run | hook log `updater masked (2 images, jjp_update=refuse)` |
| the game | `./game` after the hook | `Sentinel key not found (H0007)` in every run: no key was attached (`usbipd list` showed none connected), so the game exited at its first envelope call, right after the bind was made |
| teardown | `unjail.sh`, `stop.sh --all`, `alive.sh --total` | 0 jail mounts, `game=0 matrix=0 xephyr=0 cuse=0`, alive 0 |

**Owed (plan row R3, needs David's GNR key over usbipd):** with the key
attached, choose 1 and confirm from three places while the game runs: the game
log's `Loaded N files (bytes)` line (the two images differ: 8.206 vs 8.864 GiB
used), `status.sh`'s `bound_lower` ending in `/rootb`, and `grab.sh` of attract
showing the Chaka art; then choose 0 and see stock attract. The command is
`watch.sh` with `JJP_ISO` pointing at the multi ISO; nothing else changes.
