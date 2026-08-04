#!/bin/bash
cd /home/david
L=${1:-gz57.log}
grep -E '\[segv\]' "$L" | head -14
