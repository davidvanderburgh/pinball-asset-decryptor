# PAD-1465: Send's big writes over a direct connection

David put an AC1200 Wi-Fi adapter (RTL8822BU, out-of-tree `rtl88x2bu`) in his Godzilla and Send barely moved. Raw TCP
to the machine did 10.8 MB/s; SSH, even with PAD-1434's wide window and two lanes, stayed at 3.1-5.5 MB/s.

## Why SSH can't go faster here

The card's dropbear 2025.88 offers ciphers `chacha20-poly1305@openssh.com, aes256-ctr, aes128-ctr` and the MAC
`hmac-sha2-256` only. Paramiko has no chacha20, so every byte is AES-CTR plus HMAC-SHA2-256 in software on a
two-core ARMv7 (i.MX6, 996 MHz, no crypto extensions), sharing it with the game. A third SSH lane added nothing.

## What changed

`padpieces` (the helper a Send already uploads to `/run`) gained `recv` (version 2). Send starts it over SSH and
hands it a fresh 32-byte key on stdin. It listens on a free port, takes the one connection that opens with
HMAC-SHA1(key, hello), and writes frames of up to 1 MiB, each signed with HMAC-SHA1(key, sequence + frame) and
**checked before a byte is written**: a tampered, replayed or reordered frame is refused, and a stranger connecting
first is dropped. `_put` (whole files and partition images) and `write_ranges` (deltas) of 2 MiB or more use two raw
lanes. Anything that fails (old card, firewall, no helper for the processor) puts the rest of the Send on SSH, as
before; a dropped SSH connection still reconnects and redoes the step (PAD-1436). The raw lanes are used only for a
machine at a private or link-local address, never over the internet. `PAD_SEND_RAW=0` turns them off.

## Measured on the Godzilla (192.168.4.145, 2.4 GHz, 174 Mb/s link)

| | SSH (wide + 2 lanes) | raw, 2 lanes |
|---|---|---|
| 128 MB, game running | 3.12 MB/s | 7.44 MB/s (1 lane 5.37, 3 lanes 7.58) |
| 256 MB, game running | 3.89 MB/s | 7.86 MB/s; ranges 7.42 |
| 128 MB, game held (as a Send runs) | 5.54 MB/s | 7.87 MB/s |

Every run's sha1 matched on the machine. The helper hashes ~20 MB/s per core, so the radio is now the limit; the
machine is on 2.4 GHz, and 5 GHz would leave more room.

## The adapter wedge

During the first round, on the original USB port, the adapter stopped passing traffic (associated, no ARP) and then
could not get an address until it was moved to the other USB port. On the new port, 1.5 GB of raw runs (3 x 128 MB,
2 x 512 MB) and all the measurements above went through without a drop.
