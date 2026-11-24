#!/bin/sh
# PAD-1559: inside the guest (the card's own userland), run mattlqx's run-live.sh from main ("before") and the
# patched one ("after") through the same cases, with a stand-in game that records how it was started.
# cases.sh <pad dir> <case list>
D=$1; shift
B=/usr/local/spikebt
EX=/usr/local/bin/pad-buttons.so
mkdir -p /run
cat > $D/fakegame <<'EOF'
#!/bin/sh
D=${PADD:?}
{
  echo "LD_PRELOAD=$LD_PRELOAD"
  echo "SPIKEBT_BACKEND=${SPIKEBT_BACKEND:-}"
  echo "loaded:"; grep -o '/[^ ]*\.so[^ ]*' /proc/$$/maps | sort -u | grep -v '^/lib/\|^/usr/lib/' | sed 's/^/  /'
} > "$D/run.$PADCASE.txt" 2>&1
exit "${PADCODE:-0}"
EOF
chmod 755 $D/fakegame
real_helper() { [ -f $B/spikebt.real ] && mv -f $B/spikebt.real $B/spikebt; cp -f $D/radio-start.orig $B/radio-start.sh; }
shim_helper() {   # the rig has no radio: the helper runs its demo backend, radio-start succeeds
    [ -f $B/spikebt.real ] || mv $B/spikebt $B/spikebt.real
    printf '#!/bin/sh\nexec %s --backend=demo "$2" "${3%%/*}/demo-state.json"\n' "$B/spikebt.real" > $B/spikebt
    printf '#!/bin/sh\nexit 0\n' > $B/radio-start.sh
    chmod 755 $B/spikebt $B/radio-start.sh
}
[ -f $D/radio-start.orig ] || cp $B/radio-start.sh $D/radio-start.orig
one() {   # one <launcher before|after> <case name> <helper real|shim> <backend or -> <game exit code>
    L=$1 C=$2 H=$3 BE=$4 CODE=$5
    rm -rf /dump/spikebt; mkdir -p /dump/spikebt; rm -f /run/spikebt-helper.pid "$D/run.$L.$C.txt"
    if [ "$H" = shim ]; then shim_helper; else real_helper; fi
    : > $B/enabled
    t0=$(date +%s)
    if [ "$BE" = - ]; then
        env -u LD_PRELOAD -u SPIKEBT_BACKEND SPIKEBT_PRELOAD=$EX PADD=$D PADCASE=$L.$C PADCODE=$CODE \
            /bin/sh $D/run-live.$L.sh $D/fakegame > $D/out.$L.$C.txt 2>&1
    else
        env -u LD_PRELOAD SPIKEBT_BACKEND=$BE SPIKEBT_PRELOAD=$EX PADD=$D PADCASE=$L.$C PADCODE=$CODE \
            /bin/sh $D/run-live.$L.sh $D/fakegame > $D/out.$L.$C.txt 2>&1
    fi
    rc=$?
    cp /dump/spikebt/live/helper.log "$D/helper.$L.$C.txt" 2>/dev/null
    started=no; [ -f "$D/run.$L.$C.txt" ] && started=yes
    dis=no; [ -e /dump/spikebt/disabled ] && dis=yes
    pre=$(sed -n 's/^LD_PRELOAD=//p' "$D/run.$L.$C.txt" 2>/dev/null)
    menu=no; grep -q 'spikebt/menu.so' "$D/run.$L.$C.txt" 2>/dev/null && menu=yes
    btn=no; grep -q 'pad-buttons.so' "$D/run.$L.$C.txt" 2>/dev/null && btn=yes
    echo "$L $C: backend=$BE helper=$H game_exit=$CODE -> launcher_rc=$rc game_started=$started preload=[$pre] menu_loaded=$menu buttons_loaded=$btn disabled_mark=$dis secs=$(( $(date +%s) - t0 ))" >> $D/results.txt
}
for L in before after; do
    for c in "$@"; do
        case $c in
            fallback)   one $L fallback   real -      0 ;;  # Spike 2 default backend, no radio on the rig
            fallback5)  one $L fallback5  real bluez5 0 ;;  # Spike 3: the helper finds no BlueZ on the rig
            unknown)    one $L unknown    real demo   0 ;;
            live)       one $L live       shim -      0 ;;
            s2exit1)    one $L s2exit1    shim -      1 ;;
            s3exit1)    one $L s3exit1    shim bluez5 1 ;;
            s3exit3)    one $L s3exit3    shim bluez5 3 ;;
            s3exit6)    one $L s3exit6    shim bluez5 6 ;;
            s3exit2)    one $L s3exit2    shim bluez5 2 ;;
        esac
    done
done
real_helper
rm -rf /dump/spikebt
