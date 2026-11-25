# PAD-1585: PAD's own game update (a new Stern build onto a modified card)

David, 2026-11-25: *"when a new code update gets pushed from Stern, like a new version 1.0.1 and we are on
version 1.0.0, it would be great if the update would get installed appropriately onto the modified image without
wiping out our custom assets. Additionally, if we could have it work for multi-boot too ... I think we need some
built-in system update function that replaces the Stern one."*

## Decisions

- **Where the work runs: on the PC** (the ticket's pick). The machine only receives the finished result (Send to
  machine's delta, a card write, or a stick). A machine-side updater re-applying our files from a kept copy would
  only work for cards with no modes and no audio whose index moved, and needs room for a second copy of every
  replaced file.
- **The way back to Stern's updater: a file on the stick**, not a service-menu row. A stick holding a file whose
  name starts `stern-update-ok` (any case, any extension) hands that power-up's update to Stern's code. A menu row
  would need the game program grown and an NVM reader in the boot script (the row's value lives in the game's
  store; only the mode runtime and codeselect read it) on every card, including cards with no modes; the stick file
  works on every card, needs nothing in the game, and is as hard to hit by accident.

## 1. Stern's updater made safe on a PAD card (DONE, Spike 2)

How Stern updates (read off the King Kong LE 1.00 and Godzilla 1.16 cards): the last section of `/etc/init.d/game`
starts `game_monitor` and then `/etc/init.d/update /games &`. That script looks for a `*.spk` downloaded over
Insider Connected (`/connectivity/update` + `UPDATE_REQUESTED`), then five times three seconds apart on a USB stick
(`/dev/sda1 /dev/sda /dev/sdb1 /dev/sdb` mounted read-only on `/media`); one found, it kills the game, remounts
/games read-write and runs Stern's installer (`/usr/local/spike/spike_menu/game` via `update_monitor`).

PAD's guard (`pinball_decryptor/core/update_guard.py`, twin `tools/spike2_emu/updateguard.py`, a test holds them
equal) is a marked block at the top of Stern's own script, which otherwise stays. It does the same looking and:

- `.spk` on a stick: the game held the way Send to machine holds it (game_monitor SIGSTOP, game killed), the card's
  own message screen (`boot_display` + `dprint`): **STERN UPDATE / NOT INSTALLED / UPDATE WITH PAD / REMOVE USB
  DRIVE** until the stick is out (half an hour at most), then the game back (SIGCONT). Nothing written; a line in
  `/dump/pad-update-guard.log`.
- Insider Connected download: the flag removed (as Stern's script does for a flag with no `.spk`; the download
  stays), **STERN UPDATE / NOT INSTALLED / THIS CARD IS / UPDATED WITH PAD** for 30 s, the game back.
- nothing waiting: the script ends (and so never reaches Stern's loop, which could still catch a stick put in late).
- `stern-update-ok*` on the stick: Stern's code below the block runs as it always did.

Where it goes on:

- every Spike 2 image build: `pipeline._guard_updater_on`, after the add-ons, the same checked system-partition
  rewrite (scratch copy, debugfs, e2fsck, read-back, pending marker, quarantine on failure); the build record
  restamped so the next build can still update in place; an already guarded card is not rewritten. Stern's times
  kept on the script. Direct-SD writes never change the system partition (as before), so they don't get it.
- every multi-boot card the menu builder injects: `mkmulticard.ensure_update_guard` from `inject_into_p2`.
  `p2_digest` reads a guarded updater as Stern's own (`_unguarded_rec`), so a guarded card and its stock source
  have the same p2 fingerprint and existing multi-boot records stay valid.

Proof (2026-11-25, `C:\tmp\PAD-1585`: `standin.sh`, `runall.sh`, `run2.log` + `run4.log`): a stand-in machine, the
stock King Kong LE 1.00 card's own system partition as `/` under qemu-arm in its own PID + mount namespace (Stern's
updater pkills by name), the card's own `game_monitor` running a stand-in game, a zram disk as the USB stick
(busybox's umount frees a loop device, and device-mapper passes that on), `dprint`/`boot_display`/`spike_menu`
stood in by loggers:

| card | waiting | result |
|---|---|---|
| stock | `.spk` on the stick | Stern's installer ran, /games remounted rw and replaced (the bug) |
| guarded | `.spk` on the stick | game held (monitor T), screen USB message, held 14 s+ until the stick was pulled, then a new game process; installer never ran; /games never remounted |
| guarded | `.spk` + `STERN-UPDATE-OK.txt` | Stern's installer ran, as on a stock card |
| guarded | Insider download | flag removed, `.spk` left, screen NET message, game held, back after 30 s; installer never ran |
| guarded | nothing | updater ended after 16 s, the same game process running |

The guarded partition was made by the app's own `prepare_rootfs`; the build step `_guard_updater_on` on a card made
of a partition table + that stock partition: guarded in 3.6 s, record vouches, second run writes nothing;
`mkmulticard.ensure_update_guard` on the same partition in WSL: guarded, idempotent, e2fsck clean;
`p2_digest(stock) == p2_digest(guarded)`.

## 1b. Spike 3 (DONE)

Spike 3's `/etc/init.d/update` (read off Fallout LE 0.82) is the same shape: its paths in `/etc/init.d/shared`
(`DOWNLOADED_SPK_AVAILABLE` = `/connectivity/update/UPDATE_REQUESTED`), sticks `/dev/sda1 /dev/sda`, Stern's menu
copied from `/games/spike3/spike_menu` by `update_monitor`, screen tools in `/games/spike3/bin`. The same block goes
on (`stern_shaped` checks the strings both share). Two things only Spike 3 needed: the screen tools are looked for in
`/games/spike3/bin` first, and its `game_monitor` counts every restart in `/tmp/game_restarts` (five clear the
connectivity cache, ten reboot), so `pad_back` waits for the new game and removes the marks the hold left, as Send
does. `Spike3WritePipeline._guard_updater` runs it on every Spike 3 build, the system partition opened with the
card's keys and rewritten through `ssh_spike3.rewrite_rootfs` (remote access's checked way).

Proof (`C:\tmp\PAD-1585\standin3.sh`, `run_s3.log` + `run_s3b.log`): the stock Fallout LE 0.82 card's decrypted
system partition (exported with its keys; `state` reads it `open`) guarded by `prepare_rootfs`, run as `/` under
qemu-aarch64 with its own `game_monitor`: stock + stick = Stern's installer replaced the files; guarded + stick =
held with the message until the stick was out, a new game, no restart marks; `stern-update-ok` = Stern's installer;
download = refused, back after 30 s; nothing = the same game running, no marks.

## 2. Update to <new build> on My machines (DONE, proof owed)

A machine row with newer code out (`code_watch`) and a project gets **Update to 1.17** (shell.js `MachineRow`,
`MACH.update`; RPC `shellx.machines_update`). `app._start_machine_update`: the owner picks the new stock image (the
app downloads none); `core/game_update.check_new_card` refuses another game or a build that is not newer; then the
one-click port chain for that one image (`_run_port_chain(gate=, after=)`), built beside the machine's card. The
gate runs after `plan_transfer`, before `apply_transfer`: `game_update.carry_report` + `question` name what can't
be carried (the plan's error/warning detail lines, dropped text, `mode_news` when the modes can't run on the new
build) and ask: yes builds without those, no = `PortSkip`, nothing written. After the build: the machine is
rebound to the update and the Write tab is set to it (original = the new stock image, assets = the carried
workspace, output = the build), so Send to machine (keeps /data, /dump, /connectivity) or Build / flash (tick
"Keep the card's own settings") puts it on the machine.

Shots: `scripts/shot_pad1585.py` (from shot_pad783: scratch settings, a stub of Stern's code page with 1.17, the
watch ticked), `artifacts/PAD-1585/{before,after}_machine_row.png`.

## Decisions taken in run 2

- **No PAD update stick.** A machine with no network gets the update by a card write (with Keep the card's own
  settings), which already exists; a stick our guard would install from means PAD's own installer writing /games
  on the machine, a second, riskier delivery path for the same result.
- **The machine is shown on the update as soon as it is built** (rebound to the built image), since the button's
  purpose is that machine; the done message says how to put it on.

## Still to do (next runs of this ticket)

- **End-to-end proof, N -> N+1** (the ticket's DONE): stock King Kong LE 1.00 is in the WSL card cache
  (`/mnt/wsl/cards/cardcache/king_kong_le-1_00_0_spike2.raw`, NOT the archival "older versions" folder, which is
  off limits) and 1.01 is the library's newest (`D:\Pinball\images\Stern\spike2\king_kong_le-1_01_0_spike2...`).
  Extract 1.00 into a scratch project; give it an audio, a video or image replacement, a text edit and a mode; add a
  machine on a build of it; drive `shellx.machines_update` through the web server (`scripts/webui_shot.py`
  `start_server`; `agent.use_files([1.01 raw])` answers the picker; click the modal); check every change is in the
  1.01 build (decode the replaced files, read the text, the mode in the build record) and boot it on a rig
  (`riglock.sh take --any PAD-1585`, hidden, muted).
- **Modes carried by shot name**: the explorer found no mode copying in `plan_transfer`; check how a project's modes
  reach the new workspace in the port chain (docs/plans/project_transfer.md `copy_modes`) and wire it in if the
  chain misses it, refusing nothing: a mode whose shot the new build lacks is named in the report.

2. (done above) **"Update to 1.0.1" button**: on My machines' "1.0.1 is out" row (`webui/shellx_machines._machine_row`,
   `row["newer"]`, from `core/code_watch.newest`) and on the project. The owner points at the new stock image (the
   app downloads none). Extract it, `mod_transfer.plan_transfer` + `apply_transfer` (modes by shot name, port
   checked), and say BEFORE anything is written what can't be carried: `plan_transfer`'s `dropped`/`flagged`,
   unmatched text (`unmatched_text_lines`), modes whose shot the new build lacks, a build with no port yet ("update
   without them" / "wait"). `mod_port.plan_ports`/`run_ports` already chain extract/transfer/stage/write.
3. **The result to the machine**: Send to machine (`remote_send.open_plan` + `send`; check whether a Send carries
   the system partition's guard to a machine whose card predates it: it does, Send compares `/` too and the
   updater is read only at power-up, so it is not `BOOT_ONLY`), a PAD update stick for a machine with no
   network (new: the guard's hand-over point is where a PAD stick would be recognised), or a card write. Settings,
   audits and scores stay (Send keeps /data; a card write needs the settings carry the multi-boot guide describes).
4. **Multi-boot**: the same button updates every image of that title (`multiboot_core.replace_image` per image;
   compact cards' shared files once), other titles left alone.
6. **No port yet** for the new build: assets and text carry; modes, co-op and runtime features wait (step 2's report).
- **Other makers** (BoF, Spooky, AP, TBL) where the multi-boot guide says a normal update takes our menu away:
  the same guard on their updaters.
