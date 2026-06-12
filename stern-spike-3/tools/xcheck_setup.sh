#!/bin/bash
set -e
mkdir -p /root/xc
cd /root/xc
test -f tt.img && shred -u tt.img 2>/dev/null || true
for f in tt.img ktmp plain.in mkdump.txt; do [ -e "$f" ] && command rm -f "$f" || true; done

# 32-byte known keyfile = bytes 0x00..0x1f
python3 -c "import sys; sys.stdout.buffer.write(bytes(range(32)))" > ktmp
echo "keyfile bytes:"; xxd ktmp

# 40MB container
dd if=/dev/zero of=tt.img bs=1M count=40 status=none

# Stern-matching LUKS2 format
cryptsetup luksFormat --type luks2 --cipher aes-xts-plain64 --key-size 256 \
  --pbkdf pbkdf2 --pbkdf-force-iterations 250000 --hash sha256 \
  --sector-size 512 --batch-mode tt.img --key-file ktmp

echo "=== luksDump ==="
cryptsetup luksDump tt.img | sed -n '1,60p'

# Open, write known plaintext at sector 0..7
cryptsetup luksOpen tt.img tt_test --key-file ktmp
python3 -c "import sys; sys.stdout.buffer.write((b'STERN-XTS-CROSSCHECK!'*256)[:4096])" > plain.in
dd if=plain.in of=/dev/mapper/tt_test bs=512 count=8 conv=notrunc status=none

echo "=== dump-master-key ==="
cryptsetup luksDump --dump-master-key --batch-mode --key-file ktmp tt.img > mkdump.txt 2>&1 || true
cat mkdump.txt

cryptsetup luksClose tt_test

# Export to C drive
mkdir -p /mnt/c/tmp/stern_decrypt/xcheck
dd if=tt.img of=/mnt/c/tmp/stern_decrypt/xcheck/tt_header.bin bs=1M count=4 status=none
command cp tt.img /mnt/c/tmp/stern_decrypt/xcheck/tt.img
command cp ktmp /mnt/c/tmp/stern_decrypt/xcheck/ktmp
command cp plain.in /mnt/c/tmp/stern_decrypt/xcheck/plain.in
echo "DONE"
