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
