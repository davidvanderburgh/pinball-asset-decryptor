#!/bin/bash
. "$(dirname "$0")/padpath.sh"
A=$ROOT/games/godzilla_pro/assets
echo "=== assets/lcd ==="
ls "$A/lcd" | head
echo
echo "=== auto_loaded: entry count and a sample ==="
ls "$A/lcd/auto_loaded" | wc -l
ls "$A/lcd/auto_loaded" | head -3
echo
echo "=== inside first auto_loaded entry ==="
FIRST=$(ls "$A/lcd/auto_loaded" | head -1)
ls -la "$A/lcd/auto_loaded/$FIRST" | head -20
echo
echo "=== how many scene.radium anywhere under assets ==="
find "$A" -name 'scene.radium' 2>/dev/null | wc -l
echo "=== any *.radium ==="
find "$A" -name '*.radium' 2>/dev/null | wc -l
find "$A" -name '*.radium' 2>/dev/null | head -3
echo
echo "=== demand_loaded ==="
ls "$A/lcd/demand_loaded" | wc -l
ls "$A/lcd/demand_loaded" | head -3
