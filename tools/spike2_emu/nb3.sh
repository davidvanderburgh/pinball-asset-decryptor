#!/bin/bash
# nb3.sh - the function that WRITES the node board registry.
#
#   5a2f0c  add r6, lr, r6, lsl #2      ; lr = 0x70a474, r6 = node id
#   5a2f14  str ip, [r6, #40]           ; registry[id] = ip     <- registration
#
# ip is picked by a linear scan of a 28-entry table of 28-byte descriptors at
# 0x69cc24, keyed on a value in lr; not-found falls to 0x69cc24-28 = 0x69cc08,
# which is the default object every slot holds today ([+20] == 0, so the
# exchange wrapper at 0x59ec1c refuses to talk to it).
bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/disval.sh 0x5a2d70 0x5a2f40
