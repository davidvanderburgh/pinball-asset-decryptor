#!/bin/sh
# spike3_otp_probe.sh - read-only Spike 3 (Raspberry Pi CM4) OTP + secure-boot probe.
#
# Run this ON a Spike 3 board over SSH or the service UART, as root. It does two
# READ-ONLY things and prints one copy-paste-able report:
#
#   1. Secure boot: reports whether the board ENFORCES Raspberry Pi secure boot.
#      That is the single fact that decides whether the extractor-card route
#      (tools/build_extractor_card.py) can ever boot. (The CM4/BCM2711 customer
#      key-hash lives in OTP rows 47-54; "row 90" is the Pi 5 / BCM2712 spot.)
#      question - here we read it from the authoritative source (the bootloader
#      config + the customer-key-hash OTP rows 47-54) rather than one row.
#
#   2. The key: reads the 256-bit customer OTP that unlocks the LUKS2 volumes,
#      exactly the way Stern's own initramfs /init does (vcmailbox 0x00030021,
#      GET_CUSTOMER_OTP, 8 rows), and prints it as the 64-hex keyfile plus the
#      8 raw OTP words. Feed that 64-hex string to:
#          python tools/luks_otp.py verify <header.bin> --key-hex <64hex>
#
# SAFETY: this script is strictly read-only. It NEVER writes to the board, never
# touches or modifies the SD partitions, never shreds anything, and needs no
# card modification. Run it only on a machine you own. If you have a shell, you
# do not need the extractor card at all - this prints the key directly, and it
# works whether or not secure boot is enforced.
#
# Offline testing: set SPIKE3_FAKE_VCMAILBOX / SPIKE3_FAKE_OTP_DUMP /
# SPIKE3_FAKE_BOOTLOADER_CONFIG to canned command output to exercise the
# parsing without hardware (see tests/test_probe.py). These are test hooks only;
# on a real board leave them unset and the real vcgencmd/vcmailbox are used.

# --- helpers ---------------------------------------------------------------

# Run vcmailbox (or the injected fake). Prints its stdout, empty on failure.
run_vcmailbox() {
    if [ -n "${SPIKE3_FAKE_VCMAILBOX:-}" ]; then
        printf '%s\n' "$SPIKE3_FAKE_VCMAILBOX"
        return 0
    fi
    command -v vcmailbox >/dev/null 2>&1 || return 1
    vcmailbox 0x00030021 40 40 0 8 0 0 0 0 0 0 0 0 2>/dev/null
}

run_otp_dump() {
    if [ -n "${SPIKE3_FAKE_OTP_DUMP:-}" ]; then
        printf '%s\n' "$SPIKE3_FAKE_OTP_DUMP"
        return 0
    fi
    command -v vcgencmd >/dev/null 2>&1 || return 1
    vcgencmd otp_dump 2>/dev/null
}

run_bootloader_config() {
    if [ -n "${SPIKE3_FAKE_BOOTLOADER_CONFIG:-}" ]; then
        printf '%s\n' "$SPIKE3_FAKE_BOOTLOADER_CONFIG"
        return 0
    fi
    command -v vcgencmd >/dev/null 2>&1 || return 1
    vcgencmd bootloader_config 2>/dev/null
}

# Extract the 8 customer-OTP words from a vcmailbox response line and print them
# concatenated as 64 lowercase hex chars (== the /init keyfile, big-endian).
#
# The GET_CUSTOMER_OTP response is:
#   <bufsz> <respcode> <tag> <valbufsz> <respsz> <startrow> <numrows> W0..W7 <end>
# so the 8 rows are fields 8..15. Stern's /init slices the same bytes with
# `awk '{print substr($0,77,88)}'` (fields 1..7 are 7 * 11 = 77 chars wide).
# We compute BOTH ways and only trust the result when they agree and it is
# exactly 64 hex chars - otherwise the framing differs on this firmware and we
# fall back to dumping the raw line for manual column math.
keyhex_by_fields() {
    awk '{printf "%s%s%s%s%s%s%s%s", $8,$9,$10,$11,$12,$13,$14,$15}' \
        | sed 's/0[xX]//g' | tr 'A-F' 'a-f' | tr -cd '0-9a-f'
}
keyhex_by_substr() {
    awk '{print substr($0, 77, 88)}' \
        | sed 's/0[xX]//g' | tr 'A-F' 'a-f' | tr -cd '0-9a-f'
}

is_64hex() {
    case "$1" in *[!0-9a-f]* | "" ) return 1 ;; esac
    [ "${#1}" = "64" ]
}

echo "================ Spike 3 OTP / secure-boot probe (read-only) ================"
if [ -z "${SPIKE3_FAKE_VCMAILBOX:-}" ] && [ "$(id -u 2>/dev/null || echo 0)" != "0" ]; then
    echo "NOTE: not running as root - vcmailbox/vcgencmd usually need root; rerun with sudo if the reads below come back empty."
fi

# --- 1. secure boot --------------------------------------------------------
echo
echo "---- 1. Secure boot enforcement ----"
BLCFG="$(run_bootloader_config || true)"
OTP="$(run_otp_dump || true)"

SIGNED=""
if [ -n "$BLCFG" ]; then
    echo "bootloader_config:"
    printf '%s\n' "$BLCFG" | sed 's/^/    /'
    SIGNED="$(printf '%s\n' "$BLCFG" | sed -n 's/.*SIGNED_BOOT=\([0-9]\).*/\1/p' | head -n 1)"
else
    echo "bootloader_config: (unavailable - vcgencmd missing or not root)"
fi

# The customer key hash (burned only when a signing key is provisioned) lives in
# OTP rows 47-54 on the CM4 (BCM2711). Any non-zero value there means a key is
# fused, i.e. secure boot is permanently enforced.
CKH_NONZERO=""
if [ -n "$OTP" ]; then
    CKH_NONZERO="$(printf '%s\n' "$OTP" \
        | awk -F: '/^(0*(4[7-9]|5[0-4])):/ {
              v=$2; gsub(/[^0-9a-fA-F]/,"",v);
              if (v ~ /[1-9a-fA-F]/) print }' )"
fi

if [ "$SIGNED" = "1" ]; then
    echo "VERDICT: secure boot is ENFORCED (SIGNED_BOOT=1)."
    echo "  -> the extractor card would be REJECTED; but you have a shell, so the"
    echo "     key below is read directly and none of that matters."
elif [ -n "$SIGNED" ]; then
    echo "VERDICT: secure boot NOT enforced (SIGNED_BOOT=$SIGNED)."
    echo "  -> the extractor-card route (build_extractor_card.py) would also work."
elif [ -n "$CKH_NONZERO" ]; then
    echo "VERDICT: a customer key hash IS fused (secure boot likely enforced)."
    echo "  customer-key-hash OTP rows (non-zero):"
    printf '%s\n' "$CKH_NONZERO" | sed 's/^/      /'
else
    echo "VERDICT: could not determine enforcement from available data."
    echo "  -> send back the full otp_dump below and we will read it off."
fi

if [ -n "$OTP" ]; then
    echo "full otp_dump (send this back - it settles the enforcement question):"
    printf '%s\n' "$OTP" | sed 's/^/    /'
fi

# --- 2. the OTP key --------------------------------------------------------
echo
echo "---- 2. Customer OTP key (the LUKS keyfile) ----"
RAW="$(run_vcmailbox || true)"
if [ -z "$RAW" ]; then
    echo "vcmailbox returned nothing (missing tool, or not root). Cannot read the key here."
    echo "============================================================================"
    exit 1
fi
echo "raw vcmailbox response:"
printf '%s\n' "$RAW" | sed 's/^/    /'

KF="$(printf '%s\n' "$RAW" | keyhex_by_fields)"
KS="$(printf '%s\n' "$RAW" | keyhex_by_substr)"

echo
if is_64hex "$KF" && [ "$KF" = "$KS" ]; then
    W="$(printf '%s\n' "$RAW" | awk '{print $8,$9,$10,$11,$12,$13,$14,$15}')"
    echo "8 OTP words : $W"
    echo "KEYFILE (64 hex, feed to luks_otp.py --key-hex):"
    echo "    $KF"
    echo
    echo "COPY-PASTE THIS BACK TO DAVID:"
    echo "    SPIKE3_KEY=$KF"
else
    echo "WARNING: the two extractions disagree or are not 64 hex chars - the"
    echo "vcmailbox framing on this firmware differs from the reference. DO NOT"
    echo "trust either candidate; send the raw response above back to David so the"
    echo "column math can be redone for this board."
    echo "    fields 8..15 -> $KF"
    echo "    substr(77,88) -> $KS"
fi
echo "============================================================================"
