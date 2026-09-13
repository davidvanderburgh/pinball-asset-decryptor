#!/bin/sh
# native.sh - the QEMU stand-in for a native build (make PLATFORM=jjp).
# The test drivers run the selector as "$QEMU -L $ROOT $BIN args..." because
# the Stern binary is ARM and needs qemu-arm-static with the card rootfs as
# its -L.  An x86 jjpselect runs on the host as it is: drop the "-L ROOT"
# pair and exec the rest.
if [ "$1" = "-L" ]; then shift 2; fi
exec "$@"
