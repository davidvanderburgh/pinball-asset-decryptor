#!/bin/bash
cd $HOME
for L in gz66.log gz67.log; do
  echo "=== $L: full [branch] list ==="
  grep '\[branch\]' "$L" | sed 's/.*against //' | sort | uniq -c
  echo "total: $(grep -c '\[branch\]' "$L")"
  echo
done
