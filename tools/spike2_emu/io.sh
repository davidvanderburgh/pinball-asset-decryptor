#!/bin/bash
cd $HOME
L=${1:-gz67.log}
echo "=== scene handles ==="
grep '\[sceneopen\]' "$L"
echo
echo "=== fread calls ==="
grep '\[fread\]' "$L" | head -25
echo
echo "=== read calls flagged as SCENE ==="
grep '\[read\]' "$L" | grep SCENE | head -10
echo
echo "=== first 20 read calls ==="
grep '\[read\]' "$L" | head -20
