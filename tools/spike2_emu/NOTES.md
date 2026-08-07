# Spike 2 on a PC — rig directory

The authoritative document for this work is:

    c:\Users\david\Documents\development\pinball-asset-decryptor\plans\spike2_pc_emulation_handoff.md

Read that first. It carries the current status, the node bus protocol, the address map,
the do-not-retry list and the next steps. Everything that used to be in this file has
been folded into it; nothing here supersedes it.

## What is in this directory

    hwshim.c                  LD_PRELOAD shim: fake spidev/i2c/vpu, virtual i2c EEPROM
                              with persistence, node bus instrument and responder,
                              tty/serial ioctl round-trip, SCHED_RR stripping,
                              SIGSEGV reporter with stack-scanned backtrace,
                              open/fopen/fopen64 call-site tracing
    alsastub.c                fake ALSA card, 36 entry points, optional PCM capture
    glstub.c                  headless replacement for libEGL.so.1 / libGLESv2.so.2
    nodebus.py                holds the pty master; can log and answer bus traffic
    run_gz.sh                 namespace, fake /dev and /sys, pty, launch
    fdstat.py                 parses a QEMU_STRACE=1 log: fd -> path -> bytes read.
                              Use this before theorising about what does or does not load.

    nodebus_capture.txt       raw node bus frames from a live run
    nodebus_replylen_map.txt  request -> expected reply length, as the game reported it
    nvram_formatted.bin       the 64 KB NVRAM image the game formatted for itself

Guest rootfs lives at `$PAD_ROOT` in WSL; shim build sources are kept at
`~/emusrc`; run logs are `~/gz*.log`.
