# PAD-1467: how a Spike 2 machine could join a 5 GHz network

David's Godzilla LE (192.168.4.145) has an AC1200 USB stick, RTL8822BU (0bda:b812), and joins VanderGiga
(eero mesh, one name on both bands) at 2.4 GHz, channel 1. The service menu says "2.4GHz" everywhere. This
note sets out what limits it to 2.4 GHz and what it would take to get 5 GHz. Everything below comes from
the card image (his v36 HEISEI card: SPIKE system v2.7.0, kernel 3.14.28 built 2022-09-05), plus one
read-only look at the live machine that started no scan.

## What limits it, layer by layer

| Layer | What the card has | Limits to 2.4 GHz? |
|---|---|---|
| Game program (`/games/godzilla_le/game`) | Menu pages `MenuPageNetworkWirelessScan/Find/Name/Password`. It reads scan results with nl80211 `GET_SCAN` (cmd 32) and link stats with `GET_STATION` (17); it never triggers a scan and never sets a regulatory domain (no `TRIGGER_SCAN`, no `REQ_SET_REG`). The scan callback (0x4e8f8c) keeps every BSS: SSID, signal, flags and the frequency, which it turns into a channel number only for 2412-2494 MHz (table at 0x6a5e38, channels 1-14), so a 5 GHz BSS gets channel 0. The list builder (0x27b150) merges results by network name (strongest signal wins) and looks at the name and signal only. It joins over wpa_supplicant's control socket (`ADD_NETWORK`, `SET_NETWORK ssid/psk/key_mgmt/pairwise/group/proto`, `ENABLE_NETWORK`). It sets no `freq_list` and never runs `SAVE_CONFIG`. | **No.** "2.4GHz" is only the menu's wording. A 5 GHz network would show in the list and the game would hand it to wpa_supplicant by name. |
| `/etc/network/interfaces`, `/etc/wpa_supplicant.conf` | `wpa-driver wext`. The conf holds only `ctrl_interface`, `ctrl_interface_group=0` and `update_config=1`: no `freq_list`, no `country=`. | No |
| wpa_supplicant | v2.3, built with nl80211, wext and wired drivers, and supports `freq_list`. | No, but it picks the band (see below) |
| Driver | Not in the kernel (that has only rtl8187 and rtl8192cu). `/etc/init.d/game` lines 303-311 `insmod` Stern's `/usr/local/spike/8188eu.ko`, `8192eu.ko` and `8812bu.ko` with **no parameters**. `8812bu.ko` is Realtek `v5.3.1_27678.20180430` (registers as `rtl88x2bu`; aliases 0bda:b812, 0bda:b82c, 13b1:0043). Compiled-in defaults: `rtw_wireless_mode=0x5f` (b/g/a/n/ac, all on), `rtw_vht_enable=1`, `rtw_bw_mode=0x21` (40 MHz on 2.4, 80 MHz on 5), `rtw_channel_plan=0xFF`, `rtw_country_code` unset. | No. 5 GHz and 11ac are compiled in. With no country code, the channel plan is whatever is burned into the stick's EFUSE (unknown until the stick reports it). |
| Kernel regulatory domain | The live boot log shows `cfg80211: Calling CRDA for country: US` (the eero's beacons) and then back to world. The card has no CRDA. The Realtek driver uses its own channel plan anyway. | Not the deciding layer |

## Why it lands on 2.4 GHz

On the live machine, `wpa_cli status` gives `bssid=c4:a8:16:a4:ab:06`, `wpa_state=COMPLETED`, `freq=0`
(wext reports no frequency). `wpa_cli scan_results` prints wpa_supplicant's cached list without scanning:
it holds that one access point, at 2412 MHz and -39 dBm.

The eero uses one name on both bands. wpa_supplicant 2.3 ranks matching access points by signal, and it
prefers 5 GHz only when the two signals are within about 5 dB. A 2.4 GHz signal at -39 dBm beats the same
node's 5 GHz signal by more than that almost everywhere, so 2.4 GHz wins every time, even with a 5 GHz
channel plan. The cached list cannot show whether the stick hears the 5 GHz access points at all: entries
expire about three minutes after the scan made at connect time.

## What it would take

Both of these are parameters on the one `insmod .../8812bu.ko` line in `/etc/init.d/game`. Nothing in
the game, wpa_supplicant or the kernel needs to change:

1. **`rtw_country_code=XX`** (the owner's country) makes the driver ignore the stick's EFUSE and use that
   country's channel plan. From the module's `country_chplan_map` and `RTW_ChannelPlanMap`, US maps to plan
   0x76 (2.4 GHz FCC plus 5 GHz domain 35, 11ac on), CA to 0x2B (5 GHz domain 49), GB and DE to 0x26
   (ETSI, 5 GHz domain 1), JP to 0x27 (5 GHz domain 13). All of them include 5 GHz. On its own this does
   not cost 2.4 GHz anything.
2. **`rtw_excl_chs=1,2,3,4,5,6,7,8,9,10,11,12,13,14`** takes the 2.4 GHz channels out of the driver's
   channel set, so its scans see 5 GHz only and wpa_supplicant can only join on 5 GHz. This is "5 GHz only",
   with no fallback: a machine that cannot hear a 5 GHz access point loses Wi-Fi until the line is put
   back, by cable, SSH over Ethernet, or the SD card.

A "prefer 5 GHz, fall back to 2.4" mode would need a helper on the card that drives `wpa_cli` (set a
5 GHz `freq_list` on the game's network, then clear it after a timeout). That means disconnecting under the
game's own connection handling, which has not been read yet. Not recommended unless 5-GHz-only turns out
to be too fragile.

## The radio gate

The emulator has no Wi-Fi, and this stick wedged three times on 2026-11-19 (once during an SSH session that
ran `iw reg get`, `iwlist channel` and `iwlist scan`). So whether this particular stick holds a 5 GHz link
can only be seen on the machine, and only with David's go-ahead. The trial is two reversible steps, each one
reboot:

1. Back up `/etc/init.d/game`, add `rtw_country_code=US` to the 8812bu line, and reboot. Within a minute of
   the connection, read `wpa_cli -i wlan0 scan_results`: it still holds the boot-time scan, with no new scan
   needed. If VanderGiga access points at 5xxx MHz are listed, the stick hears 5 GHz, and the signals show
   how much weaker they are. Restore the backup if anything looks wrong.
2. If they are listed: add `rtw_excl_chs=1,...,14` as well and reboot. `wpa_cli status` then shows a 5 GHz
   BSSID (`scan_results` gives its frequency), and a Send to machine shows the speed. To undo, restore the
   backup over SSH, or by cable or SD card if the Wi-Fi does not come up.

Once the trial shows the stick holds 5 GHz, the PAD feature is a **Wi-Fi band** choice on the Network tab
(2.4 GHz as Stern ships it / 5 GHz only, plus the country). It is built onto the card the way remote
access is (card_extras + ssh_card build hook): an edit of the 8812bu `insmod` line, applied only when that
exact line is there, generic for every Spike 2 system that ships 8812bu.ko, and read back after the build.

## Trial on the machine, 2026-11-20

David approved the two steps above. What happened:

1. **Country only (`rtw_country_code=US`): works, and the stick hears 5 GHz.** After the reboot the cached
   scan listed VanderGiga at 5200 MHz (channel 40) at -46 dBm as well as on 2.4 GHz at -53 dBm. The machine
   still joined on 2.4 GHz. So the stick's radio and the US channel plan are fine, and the country code alone
   does not move it to 5 GHz. It also puts the "strongest signal wins" explanation above in doubt: here the
   5 GHz access point was the stronger one and 2.4 GHz was still chosen. Either wpa_supplicant 2.3 over wext
   does not rank the way the source reads, or it tried 5 GHz, failed and fell back. Not yet known which.
2. **Country plus `rtw_excl_chs=1..14`: the machine lost Wi-Fi.** It never came back on the network and the
   service menu's Wi-Fi page did not connect. With no network there was no SSH, so the line was put back from
   the SD card on the PC (the system partition read out raw, `/etc/init.d/game` restored from the on-card
   backup in WSL, written back and read back identical). The machine is on Wi-Fi again, at 192.168.4.77.

The kernel log of the failed boot is gone: `dmesg` lives in memory and `/dump/log` holds only the
connectivity agent's logs. So **why** 5 GHz-only fails is not known. `rtw_excl_chs` is ruled out as the
feature's mechanism until that is known, and "5 GHz only with no fallback" is ruled out for good: it cost
a trip to the SD card.

## Next trial: one boot, undoes itself, keeps its own log

`/dump` is writable at boot. The 8812bu block in `/etc/init.d/game` becomes:

    if [ -e /dump/pad1467_trial ]; then
        rm -f /dump/pad1467_trial; sync          # gone before the driver loads: the next boot is stock
        insmod /usr/local/spike/8812bu.ko <trial parameters>
        (sleep 150; { dmesg; wpa_cli -i wlan0 status; wpa_cli -i wlan0 scan_results; \
          cat /proc/net/wireless; } > /dump/pad1467_trial.log 2>&1; sync) &
    else
        insmod /usr/local/spike/8812bu.ko
    fi

A trial is then: create the marker, reboot, wait three minutes, power cycle. The second boot is always the
stock line whatever the first did, and the log of the trial boot is on `/dump` to read over Wi-Fi. No SD
card trip is possible from a failed trial. It needs David's go-ahead like any radio change.

What it should answer, in order: does the stick associate on 5 GHz at all when 2.4 GHz is excluded (the
log shows the driver's join attempts), and if not, at which step it stops. The feature's mechanism follows
from that: "prefer 5 GHz with 2.4 GHz fallback", never a hard exclusion.

## Logged trials, 2026-11-20: the fault is the Wi-Fi client's driver mode

Four one-boot trials followed, each with its own log on `/dump` (copies: `/dump/pad1467_run1..3`,
`/dump/pad1467_trial.*`). What they showed:

- **Held to 5 GHz (`rtw_excl_chs`), wext mode.** The stick hears VanderGiga on channel 40 at -47 dBm. Nine
  join attempts in 150 s, every one the same: `Trying to associate ... freq=5200 MHz`, `Association request
  to the driver failed`, `Associated with ...`, then `CTRL-EVENT-DISCONNECTED reason=0` with no handshake
  (once `Authentication ... timed out`). Never connected.
- **Country code only, wext mode, both bands.** wpa_supplicant goes for the stronger 5 GHz access point,
  fails the same way, tries 2.4 GHz once and that fails too (`Association request to the driver failed`,
  `4-Way Handshake failed`, network temp-disabled as WRONG_KEY), then keeps retrying 5 GHz with growing
  back-off. So a country code on its own makes the machine worse, not better.
- **Stock driver line, wext mode (the shipped set-up).** The scan cache already lists the 5 GHz access
  points (5200 MHz, -48 dBm): the stick's own channel plan includes 5 GHz and **no country code is needed**.
  Joins show the same failed-request pattern and a kernel `WARNING` in `cfg80211_connect` from the wext
  path; on 2.4 GHz one of the retries usually gets through, which is the slow, flaky start-up connection.
- **Stock driver line, nl80211 mode.** One attempt: `Trying to associate`, `Associated`, `Key negotiation
  completed`, `CTRL-EVENT-CONNECTED`, 14 s after wpa_supplicant started, address 88 s after a soft reboot.
  No `Association request to the driver failed`, no kernel warning, link steady for the 135 s logged. It
  joined 2.4 GHz (2412 MHz, -43 dBm, the strongest access point), and `status` now reports the frequency.

Why wext is used: the game sends Stern's connectivity agent (`conagent`) a `CONFIG_NETWORK` message that
names `wpa-driver wext`. The agent writes `/tmp/network_interface.wlan0` and runs `ifup -i` on it; busybox
`ifup` runs `/etc/network/if-pre-up.d/wpa-supplicant`, which starts `wpa_supplicant ... -D $IF_WPA_DRIVER`.
`/etc/network/interfaces` is not involved (changing it has no effect). wpa_supplicant 2.3 on the card lists
nl80211, and the Realtek driver registers a cfg80211 phy, so nl80211 is the right interface; wext is a
compatibility layer in which wpa_supplicant's separate set-BSSID and set-SSID calls each start a connect.

**The hook for a card change:** the pre-up script reads `/etc/wpa_supplicant/driver.$IFACE` before anything
else and uses its contents as the driver name. The directory does not exist on the shipped card. So the
card change is one new file, `/etc/wpa_supplicant/driver.wlan0`, containing `nl80211`. No script edits.
The trials overrode the pre-up script in memory for one boot instead (bind mount), which is equivalent.

Still open: whether the machine holds a 5 GHz link in nl80211 mode. It has not been tried: with both bands
available it picks the stronger 2.4 GHz access point. Two mistakes cost a trial each: the first nl80211
trial changed `/etc/network/interfaces` (not used), and a stray `%%` in a shell arithmetic line killed its
logging loop, so its self-restart never ran.

## 5 GHz in nl80211 mode, and transfer speed (2026-11-20)

A sixth trial boot started the client with `-D nl80211,wext` (nl80211 first, wext only if nl80211 cannot
start) and then asked for a roam to the strongest 5 GHz access point.

- **`nl80211,wext` joins first time too**: connected 14 s after wpa_supplicant started (two boots of two in
  nl80211 mode). This is the value the card option writes: a stick whose driver has no cfg80211 support
  still gets wext.
- **wpa_supplicant already tries 5 GHz first in nl80211 mode.** The boot's own event log:
  `Trying to associate with c4:a8:16:b8:64:07 (freq=5200 MHz)`, `Associated`, then
  `CTRL-EVENT-DISCONNECTED reason=34`, then 2.4 GHz and `CTRL-EVENT-CONNECTED`. The requested roam went the
  same way on two 5 GHz access points, and the machine was back on 2.4 GHz about 7 s later.
- **Reason 34** is "disassociated: too many frames not acknowledged". The eero drops the stick right after
  association, at -49 dBm. So with the stock driver parameters this stick (RTL8822BU, driver v5.3.1 of 2018)
  and the eero's 5 GHz radio do not hold a link. Not tried yet: plainer 5 GHz modes through insmod parameters
  (`rtw_vht_enable=0`, `rtw_bw_mode`, `rtw_beamform_cap=0`, `rtw_ldpc_cap=0`, `rtw_stbc_cap=0`).
- **Speed on 2.4 GHz** (24 MB over SSH, channel 1, 20 MHz, -44 dBm): PC to machine 1.8 MB/s, machine to PC
  2.5 MB/s. There is no 5 GHz figure because no 5 GHz link has held.

A radio scan was not requested at any point: the roam used the boot-time scan cache.

## The option as built, and the 5 GHz driver-parameter trials (2026-11-20)

**Built form on the machine.** With Stern's original `/etc/init.d/game` and only
`/etc/wpa_supplicant/driver.wlan0` (`nl80211,wext`) added, wpa_supplicant started with `-D nl80211,wext` and the
link was up 15 s later: the third start of three in nl80211 mode. This is what `core/wifi_card.py` writes
(Network tab, Wi-Fi start-up). Send to machine carries the file (its plans cover the system partition).

**5 GHz with driver parameters: none holds.** Each trial was one boot with the parameters on the 8812bu
`insmod` line, nl80211 mode, then a roam to the strongest 5 GHz access point from the boot-time scan cache
(-48 dBm). Every 5 GHz attempt ended `CTRL-EVENT-DISCONNECTED reason=34`, on three eero nodes, and the
machine went back to 2.4 GHz each time:

| Parameters | 5 GHz attempts | Result |
|---|---|---|
| `rtw_bw_mode=0x00` (20 MHz) | 1 | reason 34 |
| `rtw_vht_enable=0 rtw_bw_mode=0x00 rtw_beamform_cap=0 rtw_rx_stbc=0 rtw_ampdu_enable=0 rtw_power_mgnt=0 rtw_ips_mode=0` | 2 | reason 34 |
| `rtw_vht_enable=0` | 1 | reason 34 |
| `rtw_power_mgnt=0 rtw_ips_mode=0` | 4 | reason 34 |
| `rtw_country_code=US` | 4 | reason 34 |

(A first batch without the roam step was mostly void: five of its six boots joined 2.4 GHz without trying
5 GHz, because wpa_supplicant only tries 5 GHz first when that signal is the stronger one at that start.)

So no insmod parameter of driver v5.3.1 gets a 5 GHz link with this eero. What is left:

- **A newer driver.** `8812bu.ko` is Realtek v5.3.1_27678.20180430, vermagic
  `3.14.28_1.0.0_ga-wandboard+g08f5291 SMP preempt mod_unload modversions ARMv7 p2v8`. The kernel commit
  `08f5291c` is in the public `wandboard-org/linux` (branch `wandboard_imx_3.14.28_1.0.0_ga`), the machine
  has `/proc/config.gz` (saved as `C:\tmp\PAD-1467\machine.config`), and `/proc/version` names gcc 4.9.2.
  `CONFIG_MODVERSIONS=y`, so a module needs the kernel's symbol CRCs: build the tree with that config, then
  check its `Module.symvers` against the 193 CRCs in Stern's own `.ko` (`modprobe --dump-modversions`).
  Realtek v5.8.7.1 (2019, `cilynx/rtl88x2bu`) is the first candidate. Build script:
  `C:\tmp\PAD-1467\kbuild.sh` (blocked in the ticket session: it downloads a gcc 4.9 toolchain and runs as
  root in WSL; David can run it).
- **Whether the eero is the odd one.** Not known. A 5 GHz phone hotspot separates the two: the adapter
  holding a link there means the fault is specific to the eero.

Speed on 2.4 GHz stays the only figure: 1.8 MB/s PC to machine, 2.5 MB/s back.

## A newer driver holds 5 GHz; the transfer limit is the encrypted channel on the machine's CPU (2026-11-20)

**Kernel tree.** `wandboard-org/linux` at `08f5291c` with the machine's `/proc/config.gz`, built with kernel.org's
`x86_64-gcc-4.9.4-nolibc-arm-linux-gnueabi` (its `cc1` wants `libmpfr.so.4`: a private symlink to the host's
`libmpfr.so.6`). `olddefconfig` changed nothing, `kernel.release` is `3.14.28_1.0.0_ga-wandboard+g08f5291`, and
all 194 symbol CRCs in Stern's `8812bu.ko` (including `module_layout`) equal the tree's `Module.symvers`. The
tree is Stern's kernel. Script: `C:\tmp\PAD-1467\kbuild.sh`; tree: WSL `/var/tmp/pad1467/build/linux`.

**Driver.** Realtek `rtl88x2bu` v5.8.7.1_35809.20191129 (`cilynx/rtl88x2bu`, head `04ed700`) built against it
unchanged: `make ARCH=arm CROSS_COMPILE=... KSRC=<tree> KVER=3.14.28_1.0.0_ga-wandboard+g08f5291`. Result
`88x2bu.ko`, 2.96 MB, same vermagic, no undefined symbols, every CRC in the tree, alias `usb:v0BDApB812`.
Six symbols Stern's build does not use (`strcasecmp`, `kern_path`, `single_open_size`, `strstr`, `strrchr`,
`usb_autopm_put_interface`), all exported by the kernel.

**One-boot trial** (the driver loaded from `/dump` by a one-shot hook, nl80211 mode, then a roam to the strongest
5 GHz access point): `Associated`, `Key negotiation completed`, `CTRL-EVENT-CONNECTED` on c4:a8:16:b8:64:07 at
5200 MHz, channel 40, 80 MHz, VHT on, signal -45 to -52 dBm; held for the minutes measured, 20 pings of 20
answered. Before the roam it had joined 2.4 GHz at the first attempt (16 s) as Stern's driver does in nl80211
mode. One boot; not yet tried cold on 5 GHz first, nor over hours.

**Speed, same boot, 5 GHz:**

| Path | PC to machine | Machine to PC |
|---|---|---|
| Raw TCP (no encryption) | 28 MB/s | 13 MB/s |
| Remote access channel, dropbear as it runs on this card (no `-W`) | 2.1 MB/s | 2.7 MB/s |
| Remote access channel, a second dropbear with `-W 4194304` | 3.3 MB/s | 2.9 MB/s |

(2.4 GHz with Stern's driver, remote access channel, no `-W`: 1.8 / 2.5 MB/s. No raw 2.4 GHz figure yet.)

So the radio is not what limits Send to machine. Two things do:

- **This card's dropbear runs without the 4 MB window** (`-W 4194304`, PAD-1434): its `/etc/init.d/sshd`
  predates that fix. Dropbear's 24 KB default holds it near 2 MB/s.
- **With the window, the channel is close to the machine's CPU limit.** dropbear (v2025.88, aes128-ctr +
  hmac-sha2-256) sat at 60 to 70 % of a core at 3.3 MB/s, on a two-core i.MX6 whose other core the game holds
  at 100 %.

5 GHz is worth about ten times that only to a transfer that does not encrypt the bulk data on the machine.

## What PAD does now (2026-11-20, end of the ticket's build)

Three things came out of the trials, all on the branch:

1. **Network tab, Wi-Fi card, two switches** (`core/wifi_card.py`, the project's `extras.wifi`
   `{enabled, band5}`):
   - *Use the reliable Wi-Fi start-up*: `/etc/wpa_supplicant/driver.wlan0` = `nl80211,wext`.
   - *Also use the newer adapter driver, so the machine can join on 5 GHz* (needs the first): Realtek
     rtl88x2bu v5.8.7.1 at `/usr/local/spike/8812bu.ko`, the band helper `/usr/local/bin/pad-wifi-band` with
     `/etc/init.d/padwifi` and `/etc/rc5.d/S31padwifi`, and the game's six network-menu lines without "2.4GHz"
     (`wifi_card.MENU_TEXT`, applied as program text by `engine._radium_text_writes`). Offered only when the
     card's own driver has the vermagic the bundled one was built for; off puts Stern's driver back from the
     original card image.
   Each lists exactly what it changes (`DETAILS`, `BAND_DETAILS`), is a row on the Write tab, is undone by
   Revert all, and is carried by Send to machine. Source, licence and build steps of the driver:
   `pinball_decryptor/resources/wifi/README.md`.
2. **Send to machine, plain connection for big files** (`remote_send.SshMachine._put_fast`): a file of 4 MB or
   more has its bytes sent over plain TCP to the machine's own `nc`, with the Send's existing sha1 check on the
   machine as the judge; any failure falls back to the encrypted path. `PAD_SEND_PLAIN=0` turns it off.
3. **This card's dropbear** now starts with the 4 MB window (its `/etc/init.d/sshd` was from before PAD-1434).

**On the machine, installed form** (put on over remote access, the same files a build writes): after a plain
restart it came up on the new driver, joined, and the helper had it on 5200 MHz within a minute.

**Speed through Send to machine's own upload call, 5 GHz, a 64 MB file written to `/dump` and sha1-checked:**

| Path | MB/s |
|---|---|
| Plain connection | 12.9, 10.3 |
| Encrypted, one connection, 4 MB window | 2.7 |
| Encrypted, two connections (what a Send did before) | 3.4 |

The plain path is about 3 to 4 times the old one, not the 28 MB/s of the bare link: the file is also written
to the SD card, and each file costs about two seconds of listener start and stop.

**Not proven yet:** a whole PAD build with both switches written to a card or sent to the machine (the parts
are proven separately: the build step on a copy of the real system partition, the files on the machine by
hand, the upload path by its own call); the menu wording on the machine's screen (applied to a copy of the
real game program only); 5 GHz over hours or days; any adapter other than the AC1200; any game or system
version other than Godzilla LE on Spike system v2.7.0.

## End to end on the machine (2026-11-20)

**What ran:** the card image David's Godzilla runs, a Heisei V2.3 card another user built with PAD
(`Godzilla Premium 1.16 Heisei Custom V2.3 Kaiju Edition.raw`: its own modes, co-op, handicap), as the original;
a new project holding only remote access and the two Wi-Fi boxes; `SternWritePipeline` from this branch; then
`remote_send.SendPipeline` to the machine at 192.168.4.77, as the app's Send to machine runs it.

**Two faults the build showed on that card, both fixed here:**

- The menu wording is a game-program edit, so the build took the full path, and that path's
  `_retire_menu_rows` (PAD-1394) took MUSIC MODE, CO-OP PLAY and HANDICAP off the operator menu, rows the
  card's own modes use. A Write whose only game-program change is the Wi-Fi wording now skips it
  (`wifi_menu_only`).
- The build record came out incomplete, so Send refused the build: that card's game program has a hole
  (PAD-491's two blocks of zeros at 0x795000), `_file_extents` returns `None` for such a file, and the six
  wording writes and the bypass's two could not be traced to it. `_map_writes` now maps such a file through
  `Ext4Reader.mapped_ranges`.

Before those, a project with nothing else staged never got the wording at all (the remote-access shortcut ran).

**The Send:** the machine's files were not the image's (143 game files differed; it had been sent an older
build of the same card), so it was the full kind. 155 changes, 3.3 GB, of which the machine already held 2.5 GB
(in place or elsewhere on its card); 862 MB crossed the network. 17 min 27 s in all: 10 min comparing every
file on the machine, 7 min rebuilding and sending, then the boot partition and a restart. Whole new files went
over the plain connection (a 77 MB bank in 8 s, a 47 MB one in 5 s, each checked by hash).

**After the restart, read from the machine:** reachable 60 s after the Send ended; `freq=5200`,
`wpa_state=COMPLETED` on VanderGiga with no help; `/etc/wpa_supplicant/driver.wlan0` = `nl80211,wext`;
`pad-wifi-band` running; the game running; the adapter driver, the helper, its init script, the override, the
card's `mode.so`, the game program and a sound bank all byte-identical to the build; no "2.4GHz" left in the
game program ("Find WiFi Network", "Available WiFi networks", ...). The machine's screen can be read over
remote access (`/dev/fb0`: 1360 wide, 16 bits a pixel, two 768-line pages, the shown one named by
`/sys/class/graphics/fb0/pan`); `C:\tmp\PAD-1467\verify.py` saves it as a PNG.

**Not proven yet:** the wording seen on the service menu's own page (the program holds it; nobody has opened the
menu since); 5 GHz over days; another adapter, game or system version. Also seen on this PC: PAD-Runtime times
out when starting (`HCS_E_CONNECTION_TIMEOUT`), so these builds ran with `PAD_RUNTIME=0` (Ubuntu).

## Machine screen and remote buttons (2026-11-20, asked for after the end-to-end)

**Machine screen** (`core/machine_screen.py`, the Network tab's card, the page server's `/screen`). The game draws
into `/dev/fb0`: 1360 wide, 16 bits a pixel (RGB565), two 768-line pages, the shown one at
`/sys/class/graphics/fb0/pan`. One page is 2 MB. Capture: about 2 s. Live, with a game running, on 5 GHz: 1.4 to
1.6 frames a second over the encrypted connection, 5 to 6.6 over a plain one (the machine listens with `nc`, the
PC connects, as Send's big files). Nothing is left running on the machine after Stop.

**Remote buttons** (`core/remote_buttons.py`, `resources/remote/pad-buttons.c`).

- The machine has no input device (`/dev/input` holds only `mice`) and its kernel no uinput. The game has
  `/dev/spidev1.0` (the cabinet switches) and `/dev/ttymxc1` (the playfield boards) open; its cabinet thread loops
  on an 8-byte `SPI_IOC_MESSAGE`, bits active low (`tools/spike2_emu/hwshim.c` documents the same on the emulator).
- Bits, read off the machine with a watching build of the shim while David pressed each button: Back 11, Minus 10,
  Plus 9, Enter 8; the coin door 23 (1 open, 0 closed). A finger's press lasted 15 to 19 hundredths of a second.
- The shim is preloaded by `/etc/init.d/game_monitor` (PAD's mode runtime already is: `LD_PRELOAD=... $1`). It
  wraps `ioctl`, makes the real call itself by system call, and clears the asked bits in the word only while the
  real word's bit 23 reads 1. A press is `<mask hex> <deadline cs> 23 1` in `/run/pad-buttons`; a deadline more
  than 3 s ahead is refused. `/run/pad-buttons.state` says it is alive and what the real word is.
- Proven on the machine: Enter, Plus, Back from a script and then from the app's page with the live view running
  (a press over the live view's connection takes 0.13 s; a connection of its own about 2 s).
- **Found on the way:** an incremental Send restarted only the game, but `game_monitor`'s running copy is the old
  script, so the game came back without the shim. The same holds for the Wi-Fi start-up file and the adapter
  driver. `remote_send.BOOT_ONLY`: a Send that changed one of those restarts the machine.
- Not done: Start, the flippers and the action button (the playfield boards' serial line, another protocol).
  The bits are the CPU board's own wiring and so should be every Spike 2 title's, but only a Godzilla was tried.

## Merged with main (2026-11-20)

PAD-1465 landed on main while this ticket ran, with its own faster Send: a Send's big writes go over plain TCP into
the machine's helper (`padpieces recv`), every frame signed with a key that went over SSH and checked before it is
written, and only on this computer's own network (`remote_send._home_network`, `PAD_SEND_RAW=0` to turn it off).
This ticket's `SshMachine._put_fast` (a whole file through the machine's `nc`, checked by sha1 afterwards) did the
same job less carefully and was dropped in the merge; its measurements above stand as measurements of that path.
`remote_send.plain_allowed()` stays, for the live view and the whole-card backup, which follow the same switch and
the same home-network rule. The Wi-Fi card's comparison now says 7 to 13 MB a second: PAD-1465 measured 7 to 8 with
a game running, this ticket 10 to 13 with the game held. PAD-1465's path was not re-timed here.

## Machine care (2026-11-20)

`core/machine_care.py`, the Network tab's card. On the Godzilla: status 0.2 s; logs (9 files, one zip, no password
in it) 1.8 s; settings, audits and high scores (`/data/nv`, 40 files) backed up in 0.4 s and restored in 7.6 s with
every file's sha1 read back and the game started again; the folder a restore replaces is kept once as
`/data/nv.pad-old`.

**A copy of the whole card was built and taken out again.** `dd if=/dev/mmcblk0` over a plain connection ran at 3.5
to 6 MB a second with the Wi-Fi link at 867 Mbit/s and half the processor idle (the card's own reading is the
limit), so 16 GB held the game for over an hour. David: "a whole backup from the sd card this way is somewhat dumb
... takes far too long". The run was cancelled at 4.1 GB; the settings backup is what stays.

Not tried on the machine: recording the live view in the real page (its saving step has a test); the live view's
cost to a game being played.

## Network options without a build of the project (2026-11-20)

Asked for after the layout: a flash that keeps the network options, and the Wi-Fi and remote-buttons options put
straight where they go.

- **Keep my network settings on this card** (`core/network_keep.py`, the flash dialog, `SternFlashImagePipeline`
  `network_from=`): a copy of the image is built from a project that holds only the real project's `extras`
  records that are on (ssh, wifi, buttons), written, and removed. On a copy of the real Heisei V2.3 image: 36 s,
  all three on the copy, the image itself unchanged, the copy removed. Not seen in the dialog on screen, and no
  physical card was written this way.
- **Straight onto an attached card or card image** (`network_apply.to_card`, after `remote_setup.set_up`): the
  system partition copied off, `wifi_card.prepare_rootfs` / `remote_buttons.prepare_rootfs` on the copy, the
  differing blocks written back, all read back. On the V2.3 image file: on in 5 s (10 MB changed), the same again
  says "already" and writes nothing, off puts Stern's driver and the start-up script back. Not run on a physical
  card (that goes through the administrator helper, `elevated_flash`'s `network_options` job).
- **Straight onto the machine** (`network_apply.to_machine`): each file written beside its place, its sha1 read
  back before any is moved in, then a restart. On the Godzilla its plan was right both ways (everything ticked is
  byte-identical already, so nothing written; taking all off would write the script and Stern's driver and remove
  five files). A write-and-restart over this route was not run on the machine.
- Neither direct route carries the menu wording (a game-program edit) or the score feed (PAD's mode runtime):
  `network_apply.WAYS` is what each Network tab panel shows.
