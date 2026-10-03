#!/bin/bash
# pad_install.sh - the Barrels of Fun multi-boot install step (PAD-342).
#
# BOF's own updater (~/updatecode.sh) installs a .fun like this: empty
# /home/pinball/extracted, decrypt the .fun there, untar it into
# extracted/decrypt, require exactly ONE *.x86_64, rename it GDCraze.x86_64,
# copy it to craze/GDCraze.x86_64, record its size in craze/GAMEFILESIZE - and
# then run the .fun's own update/update.sh, which copies update/.bash_profile
# to ~/.bash_profile.  A multi-boot .fun is a stock one with three changes:
# its .bash_profile carries the menu's hook line, its update.sh runs THIS
# first, and it carries padselect/ (the menu, its pictures, this script) and
# one DELTA per extra image (paddelta.c says why: two programs do not fit in
# one file on a FAT32 stick).  So when this runs, image 0 is installed and
# everything else is in extracted/decrypt.  It:
#
#   1. removes the decrypted archive the updater leaves in extracted/ (the
#      size of the .fun, never read again) - the space the rebuild needs;
#   2. turns craze/GDCraze.x86_64 from a COPY of image 0 into a hard link to
#      extracted/decrypt/GDCraze.x86_64 (the same bytes; another 4 GB back);
#   3. rebuilds every extra image from image 0 and its delta (paddelta), checks
#      it against the md5 the builder recorded, and deletes the delta;
#   4. checks image 0 against its md5 too.
#
# AN IMAGE THAT DOES NOT CHECK OUT IS TAKEN OUT OF THE MENU (its image= line
# goes, its files go) and the rest carries on; with one image left there is
# no menu at all and the machine is a stock machine.  Nothing here can stop
# the update the updater is already running: every failure is a log line in
# padselect/install.log and the step still exits 0.
#
# programs: "<index> <file> <size> <md5> [<delta>]", one line per image.
# PADSELECT_HOME moves /home/pinball (the tests).
H=${PADSELECT_HOME:-/home/pinball}
D=$H/extracted/decrypt
P=$D/padselect
CONF=$P/images.conf
PROGS=$P/programs
GAME=$H/craze/GDCraze.x86_64
LOG=$P/install.log

exec 3>>"$LOG" 2>&3 || exec 3>/dev/null
say() { echo "$(date '+%F %T') $*" >&3; }
say "PAD multi-boot install step"
df -h "$H" >&3 2>&1

[ -f "$PROGS" ] && [ -f "$CONF" ] || { say "no programs / images.conf: nothing to do"; exit 0; }

# 1. the decrypted archive
for f in "$H"/extracted/*.tar.gz.gpg; do
    [ -f "$f" ] && rm -f "$f" && say "removed $(basename "$f") (the decrypted update, not needed again)"
done

# 2. craze's copy of image 0 -> a hard link
if [ -f "$D/GDCraze.x86_64" ] && [ -f "$GAME" ] \
   && [ "$(stat -c %i "$GAME")" != "$(stat -c %i "$D/GDCraze.x86_64")" ] \
   && [ "$(stat -c %s "$GAME")" = "$(stat -c %s "$D/GDCraze.x86_64")" ]; then
    rm -f "$GAME" && ln "$D/GDCraze.x86_64" "$GAME" 2>/dev/null \
        && say "craze/GDCraze.x86_64 is a link to image 0 now (was a copy)" \
        || { cp -f "$D/GDCraze.x86_64" "$GAME"; say "could not link craze to image 0: copied it back"; }
fi

drop_image() {   # drop_image <index> <file> <why>
    say "image $1 ($2) taken out of the menu: $3"
    rm -f "$D/$2" "$D/$2.part"
    # its image= line: the (N+1)th image= line of the conf
    awk -v n="$1" '/^image=/ { if (i++ == n) next } { print }' "$CONF" > "$CONF.tmp" && mv -f "$CONF.tmp" "$CONF"
}

# 3 + 4, the extras first, highest index first (dropping a line shifts the later ones)
sort -rn "$PROGS" | while read -r idx file size md5 delta; do
    case "$file" in ""|*/*|.*) say "programs: a bad line for image $idx"; continue ;; esac
    if [ -n "$delta" ]; then
        if [ ! -f "$D/$delta" ]; then
            drop_image "$idx" "$file" "its delta $delta is not in the update"
            continue
        fi
        say "image $idx: rebuilding $file from image 0 and $delta"
        if ! "$P/paddelta" "$D/GDCraze.x86_64" "$D/$delta" "$D/$file" 2>&3; then
            rm -f "$D/$delta"
            drop_image "$idx" "$file" "paddelta failed (see above)"
            continue
        fi
        rm -f "$D/$delta"
    fi
    if [ ! -f "$D/$file" ]; then
        if [ "$idx" = 0 ]; then say "image 0 ($file) is missing - the updater's own install did not leave it"; continue; fi
        drop_image "$idx" "$file" "the file is not there"
        continue
    fi
    have=$(md5sum "$D/$file" | cut -d' ' -f1)
    if [ "$have" != "$md5" ]; then
        if [ "$idx" = 0 ]; then say "image 0 ($file): md5 $have, the builder recorded $md5 - left as the updater installed it"; continue; fi
        drop_image "$idx" "$file" "md5 $have is not the $md5 the builder recorded"
        continue
    fi
    chmod 755 "$D/$file" 2>/dev/null
    say "image $idx ($file): $size bytes, md5 $md5 ok"
done

# the hook runs as the pinball user: it writes its log and the menu's memory here
chown -R pinball:pinball "$P" 2>/dev/null || sudo -n chown -R pinball:pinball "$P" 2>/dev/null
sync
say "install step done: $(grep -c '^image=' "$CONF") image(s) in the menu"
df -h "$H" >&3 2>&1
exit 0
