#!/bin/bash
# co70.sh <log> - name every `70 XX` index seen on the wire.
#
# The handoff read `70 XX 00 00` as "per-drive writes... coil/lamp drives indexed
# by XX". It is not. Its ONLY caller is 0x1e7818, which walks the pending-NodeRec
# list at [0x7aa9b4] and, for each SWITCH entry, calls
#
#   0x5a3cb4(node = entry[+20], index = entry[+18], a = entry[+27], b = entry[+28])
#
# i.e. XX is the switch's BIT NUMBER on its node board, and the two payload bytes
# are that switch's two per-switch parameters scaled by the board's rate.
#
# This script is the empirical half of that proof: it joins the (node, index)
# pairs seen in `70` frames against the game's own switch coordinate table
# (PAD_SW_MAP), so run the log with PAD_SW_MAP set as well as PAD_NB_TRACE.
set -u
L=${1:?log}
awk '
/\[swmap\] id=/ {
    id = $2; sub(/id=/, "", id)
    n  = $3; sub(/node=/, "", n)
    b  = $4; sub(/bit=/,  "", b)
    name = ""
    for (i = 11; i <= NF; i++) name = name (i > 11 ? " " : "") $i
    key = n ":" b
    sw[key] = id "  " name
    next
}
/\[nbts\] .* cmd=70 / {
    n = $3; sub(/node=/, "", n)
    idx = strtonum("0x" substr($6, 7, 2))
    key = n ":" idx
    cnt[key]++
    if (!(key in first)) { t = $2; sub(/t=/, "", t); first[key] = t }
}
END {
    printf "%-6s %-5s %-6s %-5s %s\n", "node", "idx", "writes", "sw", "switch name (from the game s own table)"
    n = 0
    for (k in cnt) { keys[n++] = k }
    for (i = 0; i < n; i++)
        for (j = i + 1; j < n; j++) {
            split(keys[i], a, ":"); split(keys[j], b2, ":")
            if (a[1] + 0 > b2[1] + 0 || (a[1] + 0 == b2[1] + 0 && a[2] + 0 > b2[2] + 0)) {
                t = keys[i]; keys[i] = keys[j]; keys[j] = t
            }
        }
    unmapped = 0
    for (i = 0; i < n; i++) {
        k = keys[i]; split(k, a, ":")
        s = (k in sw) ? sw[k] : "*** NOT A SWITCH COORDINATE ***"
        if (!(k in sw)) unmapped++
        printf "%-6s 0x%02x  %-6s %s\n", a[1], a[2], cnt[k], s
    }
    printf "\n%d distinct (node,index) pairs, %d of them NOT switch coordinates\n", n, unmapped
}' "$L"
