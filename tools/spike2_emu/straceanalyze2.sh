#!/bin/bash
cd $HOME
L=gz52.strace
echo "=== scene.radium opens WITHOUT O_DIRECTORY (i.e. real file opens) ==="
grep 'scene.radium' $L | grep -v O_DIRECTORY | head -10
echo
echo "count: $(grep 'scene.radium' $L | grep -vc O_DIRECTORY)"
echo
echo "=== all distinct open flag-sets used on scene.radium ==="
grep -o 'scene.radium",[A-Z_|]*' $L | sort | uniq -c
echo
echo "=== what happens right after the FIRST non-directory scene open ==="
N=$(grep -n 'scene.radium' $L | grep -v O_DIRECTORY | head -1 | cut -d: -f1)
echo "line $N"
sed -n "${N},$((N+14))p" $L
echo
echo "=== /tmp/login.bmp and CAPS_update context ==="
grep -n 'login.bmp\|CAPS_update' $L | head -10
