#!/bin/bash
cd $HOME
L=${1:-gz57.log}
grep -E '\[segv\]' "$L" | head -14
