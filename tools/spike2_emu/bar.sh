#!/bin/bash
# bar.sh <log> - print the validation-bar counters for a run log in one place.
cd $HOME
L=${1:-gz208.log}
printf 'log                : %s\n' "$L"
printf 'Radium Warning     : %s\n' "$(grep -ac 'Radium Warning' "$L")"
printf 'ExchangeData       : %s\n' "$(grep -ac 'ExchangeData' "$L")"
printf 'throw              : %s\n' "$(grep -ac '\[throw\]' "$L")"
printf 'scenebytes lines   : %s\n' "$(grep -ac '\[scenebytes\]' "$L")"
printf 'scenebytes nonzero : %s\n' "$(grep -a '\[scenebytes\]' "$L" | awk '$2 > 0' | wc -l)"
printf 'scenebytes distinct: %s\n' "$(grep -a '\[scenebytes\]' "$L" | awk '$2 > 0 {print $2}' | sort -u | wc -l)"
printf 'segv line          : %s\n' "$(grep -a '\[segv\] pc=' "$L" | head -1)"
printf 'live game procs    : %s\n' "$(ps -eo args | grep -c '[g]odzilla_pro/game')"
