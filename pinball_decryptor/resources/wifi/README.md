# Wi-Fi files PAD puts on a Stern Spike 2 card (PAD-1467)

Used by `pinball_decryptor/core/wifi_card.py` for the Network tab's Wi-Fi options.

| File | Goes on the card as | What it is |
|---|---|---|
| `88x2bu.ko` | `/usr/local/spike/8812bu.ko` | Realtek's Linux driver for the RTL8822BU USB Wi-Fi adapter, v5.8.7.1_35809.20191129, built for kernel `3.14.28_1.0.0_ga-wandboard+g08f5291` |
| `pad-wifi-band` | `/usr/local/bin/pad-wifi-band` | PAD's own shell script: asks wpa_supplicant to move to the network's 5 GHz access point |
| `padwifi` | `/etc/init.d/padwifi` (linked from `/etc/rc5.d/S31padwifi`) | PAD's own start-up script for the above |

## The driver: licence and source

`88x2bu.ko` is a Linux kernel module under the **GNU General Public License, version 2** (the module's own
`license=GPL`; the text is in `LICENSE.GPL-2.0` here and in the kernel source's `COPYING`). It is built from
Realtek's source **without modification**:

- Source: <https://github.com/cilynx/rtl88x2bu>, branch `5.8.7.1_35809.20191129_COEX20191120-7777`,
  commit `04ed700`.
- Kernel it is built against: <https://github.com/wandboard-org/linux>, branch
  `wandboard_imx_3.14.28_1.0.0_ga`, commit `08f5291c`, with the configuration a Spike 2 card reports in
  `/proc/config.gz` (Spike system v2.7.0).

Anyone who received this file may have the corresponding source from those two places; if either is ever gone,
ask the PAD project and it will be supplied.

## How it was built

1. Compiler: kernel.org's `x86_64-gcc-4.9.4-nolibc-arm-linux-gnueabi`
   (<https://mirrors.edge.kernel.org/pub/tools/crosstool/files/bin/x86_64/4.9.4/>; the card's kernel says it was
   built with gcc 4.9.2). On a current Linux its `cc1` needs `libmpfr.so.4`: point that name at the host's
   `libmpfr.so.6` in a folder on `LD_LIBRARY_PATH`.
2. Kernel tree: check out `08f5291c`, copy the card's `/proc/config.gz` (unpacked) to `.config`, put `+g08f5291`
   in `.scmversion`, then `make ARCH=arm CROSS_COMPILE=<...>arm-linux-gnueabi- olddefconfig zImage modules`
   (add `HOSTCFLAGS=-fcommon` for a current host compiler). `olddefconfig` changes nothing, and
   `include/config/kernel.release` reads `3.14.28_1.0.0_ga-wandboard+g08f5291`.
3. Check the tree is the card's kernel: every symbol version in the card's own `/usr/local/spike/8812bu.ko`
   (`modprobe --dump-modversions`, 194 of them including `module_layout`) equals the tree's `Module.symvers`.
   The kernel has `CONFIG_MODVERSIONS=y`, so a module from any other tree is refused when it loads.
4. Driver: in the driver source,
   `make ARCH=arm CROSS_COMPILE=<...> KSRC=<kernel tree> KVER=3.14.28_1.0.0_ga-wandboard+g08f5291`.
   The result has the same `vermagic` as the card's own driver and no undefined symbols.

sha256 of the built file: `7a2194e4cda4bbd3d4f01c3627fbf75e95080f731df12930493aedaa6239ea3d`
(`wifi_card.NEW_MODULE_SHA256`; the app refuses to use a file that does not match).

A kernel module fits one kernel build. PAD offers this driver only on a card whose own driver carries that same
`vermagic`; a card with another kernel needs its own build by the steps above.
