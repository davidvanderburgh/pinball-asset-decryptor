# PAD-1434: Send over Wi-Fi, dropbear's receive window

The Godzilla is Wi-Fi only (USB RTL8188EU, 802.11n 1x1 2.4 GHz, 72.2 Mb/s link, ~5 MB/s ceiling). A Send ran
at ~1.4 MB/s: dropbear's default receive window (24 KB) caps one connection at about window / RTT.

## Measured on the machine (2026-11-18, 192.168.4.130, game running)

| what | MB/s |
|---|---|
| raw channel, card's listener (24 KB window) | 1.4 |
| raw channel, `-W 4194304` listener | 3.5-3.9 |
| `-W`, 2 / 3 connections at once | 4.2 / 4.4-4.6 |
| Send upload 32 MB, before / after (`SshMachine.widen`) | 1.55 / 3.6 |
| Send block writes 16 MB (4 MB batches), before / after | 1.2-1.6 / 3.2-3.65 |

Ciphers: the card's dropbear 2025.88 offers, of what paramiko speaks, only aes128-ctr + hmac-sha2-256 (no GCM,
no sha1/md5/etm MACs; chacha20 is not in paramiko), which paramiko already picks first. There is no cheaper pair.

## What changed

1. `resources/ssh/sshd` starts dropbear with `-W 4194304`: every card set up or built from now on.
2. `SshMachine.widen()` (called by `SendPipeline` only, not the Network tab's check):
   - reads the running listener's arguments from `/proc/<pid>/cmdline` (`/var/run/pad-sshd.pid`, the same
     script on Spike 2 and Spike 3);
   - narrow window: starts a temporary listener with those arguments, its `-p/-P/-W/-F/-E` replaced by
     `-p 2222|22222|42222 -P /var/run/pad-sshd-send.pid -W 4194304`, after stopping a stale one (only if the
     pid in that file is still that listener);
   - connects to it twice, each checked against the identity just seen on :22 (never remembered for the port);
     the wide connection stands in for the Send's own, the :22 one is parked;
   - already wide: a second connection on the machine's own port;
   - files and block-write batches of 2 MB or more are dealt in 1 MB pieces to both connections at once
     (pipelined SFTP writes), size checked after; smaller ones stay on one connection;
   - `close()` stops the temporary listener (over the wide connection, else the parked one) and closes all.
   Anything failing logs one line and the Send carries on over :22.
