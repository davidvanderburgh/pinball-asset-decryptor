#!/bin/bash
# startcheck.sh <key> <card> - does this build boot AND start a game? rigbatch's second stock job and the example
# of a job written on rigjob.sh: boot to attract (bootcheck.sh's question), then credits, Start and the launch -
# a ball in play - and a picture of it. The last line is
#
#   VERDICT <key> pass|fail <seconds> attract=<s> game=<s> [why]
#
# Everything after attract is in the game's time, so `rigbatch.sh --speed 4` (its default) makes it a quarter as
# long; the boot is the CPU's and stays as it is. PAD_BOOT_DEADLINE (420) caps the wait for attract.
. "$(dirname "$0")/rigjob.sh"
job_begin "${1:?usage: startcheck.sh <key> <card>}" "${2:?usage: startcheck.sh <key> <card>}"
job_boot
job_wait_attract "${PAD_BOOT_DEADLINE:-420}" || job_fail "$JOB_WHY"
job_sleep 5                       # the show settles: a Start in attract's first seconds was ignored (Godzilla Pro)
job_start_game || job_fail "attract=${JOB_ATTRACT_S}s $JOB_WHY"
job_sleep 4
job_shot "$JOB_OUT/game.png"
job_pass "attract=${JOB_ATTRACT_S}s game=${JOB_GAME_S}s"
