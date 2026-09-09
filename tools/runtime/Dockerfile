# The PAD runtime: the Linux the emulator rigs run on, built and pinned by US.
#
# WHY THIS EXISTS.  Phase 1 (pinball_decryptor/core/payloads.py) stopped the app
# COMPILING things on a user's machine.  This stops it DEPENDING on that
# machine's Linux at all.  Until now every rig ran inside whichever distro
# happened to be the user's WSL default - some Ubuntu, some Debian, one tester
# on an Arch spin - and each of those brings its own glibc, its own python, its
# own package names and its own idea of which tools are installed.  Every field
# break so far has come out of that gap, and none of them was reproducible on
# the machine that could fix it.
#
# So the app brings its own: this image is exported as a rootfs tarball, pinned
# by SHA-256, and imported as a private WSL distro (PAD-Runtime).  The user's
# own distro is not touched, not read and not required - and a Windows machine
# with WSL enabled but NO distro installed at all can now run the emulator,
# which was previously a Microsoft Store errand before the app was any use.
#
# EVERYTHING HERE IS PINNED TWICE OVER:
#
#   * the base image by DIGEST, not by tag - `ubuntu:24.04` is a moving target
#     that is rebuilt every few weeks, and "the same Dockerfile" would
#     otherwise mean a different Linux each time;
#   * the packages by SNAPSHOT - snapshot.ubuntu.com serves the archive exactly
#     as it stood at one instant, so `apt-get install python3` resolves to the
#     same version next month as it did today.  The ordinary archive cannot do
#     that: it carries only the newest version of anything, so a rebuild
#     silently picks up whatever security update landed since;
#   * and the binaries we build ourselves come from the payloads release,
#     verified by the same SHA-256 the app carries (the workflow does that
#     check before this file ever sees them).
#
# TWO VARIANTS, and `full` is what the app ships:
#
#   base   what the SPIKE 1 rig needs: python3 and a few shell tools, plus the
#          emulator and device model we build.  45 MB.
#   full   base plus everything the SPIKE 2 rig needs AND everything the
#          extract/write pipelines need - the ARM cross compiler
#          and qemu-user-static it runs a guest with, ffmpeg for the picture
#          and the sound, e2fsprogs and fuse3 for the card, a static busybox
#          for the checkpointable boot, and criu, which no Ubuntu has ever
#          packaged and which this image therefore BUILDS.  That last one is
#          the point of the whole exercise: `getcriu.sh` compiles criu from
#          source on the user's machine today, and a compile on a machine we
#          have never seen is exactly what this is here to end.  It also
#          carries the pipeline tools - partclone, xorriso, gnupg, GDRE Tools
#          and the rest - because every extract and write path shells into
#          Linux as well, and the app now sends those here too.  A rig is not
#          the only thing that used to depend on a stranger's distro.

FROM ubuntu:24.04@sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517 AS apt

# The instant of the archive this image installs from.  Bump it deliberately,
# never automatically: a new stamp is a new image and a new pin.
ARG SNAPSHOT=20260801T000000Z

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# THE SNAPSHOT SERVICE IS THE PRICE OF PINNING, and it is a BUILD-time price
# only - no user ever fetches from it, because what they get is the finished
# rootfs.  It answers a 503 often enough to lose a build (this image's third
# attempt died on one .deb out of forty), so every apt call here gets a large
# retry budget.  A build that still fails this way is retried, not worked
# around: the alternative is the ordinary archive, which cannot be pinned.
# (Hence the `Acquire::Retries=10` on every apt call below.)

# CERTIFICATES BEFORE THE SNAPSHOT, and the order is the whole of it.  The
# snapshot service is HTTPS only (plain http 301s onto it) and this base image
# ships NO CA certificates at all - so apt cannot verify the connection, each
# index fetch fails as a WARNING rather than an error, `apt-get update` exits 0
# having downloaded nothing, and the install two steps down reports "Unable to
# locate package python3".  That is a confusing way to say "no trust store",
# and it is exactly what the first build of this image died of.  So the
# certificates come first, from the base image's own archive over http, and
# the snapshot is switched to afterwards.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# One source list, one instant.  `check-valid-until=no` because a snapshot's
# Release file ages by definition and apt would otherwise refuse it as stale.
#
# And the index is CHECKED, not assumed: apt answers a broken source with a
# warning and a zero exit, so without this the failure surfaces later as a
# missing package rather than here as a missing archive.
#
# The check is `apt-cache show`, deliberately NOT `apt-cache policy | grep -q`.
# This file runs its RUN lines under `bash -o pipefail`, and `grep -q` exits
# the moment it matches, which closes the pipe under apt-cache, which dies of
# SIGPIPE - so the pipeline FAILS on the success case.  That cost this image
# its second build, reporting a missing archive over a log that had just
# downloaded 1.5 MB of package index.
RUN printf '%s\n' \
      "deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/${SNAPSHOT} noble main universe" \
      "deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/${SNAPSHOT} noble-updates main universe" \
      "deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/${SNAPSHOT} noble-security main universe" \
    > /etc/apt/sources.list.d/ubuntu.sources.list \
 && rm -f /etc/apt/sources.list.d/ubuntu.sources \
 && apt-get -o Acquire::Retries=10 update \
 && if ! apt-cache show python3 >/dev/null 2>&1; then \
      echo "the snapshot archive gave apt no usable index"; exit 1; fi


# ---------------------------------------------------------------- criu ------
# BUILT HERE SO IT IS NEVER BUILT THERE.  criu is the one dependency no Ubuntu
# has ever packaged (the only criu-named package in the archive is a Go
# binding), so the rig's getcriu.sh compiles it from source on the user's
# machine - installing a dozen -dev packages to do it, and failing on whatever
# the distro's compiler has decided to be strict about this year.  Version and
# dialect are taken from that script, so the binary is the one the rig expects.
#
# Its own stage, so the -dev packages and the source tree stay OUT of the
# finished rootfs; only the binary is copied across.  The `base` variant builds
# nothing here and copies an empty tree, because a COPY cannot be conditional.
FROM apt AS criu
ARG VARIANT=full
ARG CRIU_VERSION=v4.1
RUN mkdir -p /out \
 && if [ "$VARIANT" = full ]; then \
      apt-get -o Acquire::Retries=10 install -y --no-install-recommends \
        build-essential git pkg-config libprotobuf-dev libprotobuf-c-dev \
        protobuf-c-compiler protobuf-compiler python3-protobuf libnl-3-dev \
        libnet1-dev libcap-dev libbsd-dev uuid-dev \
      && git clone --depth 1 --branch "$CRIU_VERSION" \
           https://github.com/checkpoint-restore/criu.git /src \
      && echo "criu $CRIU_VERSION is commit $(git -C /src rev-parse HEAD)" \
      && make -C /src -j"$(nproc)" USERCFLAGS=-std=gnu17 criu \
      && install -D -m 0755 /src/criu/criu /out/usr/local/bin/criu; \
    fi


# ------------------------------------------------------------- the runtime --
FROM apt AS runtime
ARG SNAPSHOT=20260801T000000Z
#: WHAT VERSION THIS IMAGE CLAIMS TO BE, and it is NOT decided here.  The app
#: declares what it expects (RUNTIME_VERSION in core/runtime.py) and the
#: workflow passes that number in - because the one time this file carried its
#: own copy, a bump landed in the app and not here, the image stamped itself
#: version 2 against an app expecting 3, and the install failed at the last
#: step with "the runtime imported but does not answer as ours".  The default
#: is 0 so an unstamped build is obviously wrong rather than plausibly right.
ARG RUNTIME_VERSION=0
ARG VARIANT=full

#: WHAT THE SPIKE 1 RIG USES, read out of the rig rather than remembered:
#: every command its scripts call and every module its python imports.
#:   python3        every rig script that is not shell (build_rootfs.py reads
#:                  ext4 in pure python, so no e2fsprogs is needed for it)
#:   procps         pgrep/pkill - how the rig finds and stops its own processes
#:   util-linux     unshare/setsid/mount - the namespace the guest boots in
#:   socat          the one socket relay in the boot path
#:   ca-certificates  so anything fetched from in here can verify a certificate
#: fuse3 is NOT here on purpose for Spike 1: its device model links libfuse
#: statically and talks to /dev/fuse directly.  Spike 2 needs the real thing,
#: and gets it below.
RUN apt-get -o Acquire::Retries=10 install -y --no-install-recommends \
      python3 \
      procps \
      util-linux \
      socat \
 && apt-get -o Acquire::Retries=10 install -y --reinstall \
      --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

#: WHAT THE SPIKE 2 RIG USES.  The first eight are its own setupcheck.sh's
#: table, verbatim and in its order - that script is the rig's one list of what
#: it needs, and copying it here rather than re-deciding is what stops the
#: image and the rig disagreeing about a machine:
#:   qemu-user-static           the ARM interpreter the guest runs under
#:   gcc-arm-linux-gnueabihf    builds the hardware shim and the GL bridge's
#:                              guest halves - which LINK against the CARD's
#:                              own libc, so they can never be prebuilt for it
#:   libc6-dev-armhf-cross      ...but they still COMPILE against ordinary libc
#:                              HEADERS - hwshim.c includes setjmp.h.
#:                              `-nostdlib` governs the LINK, not the includes,
#:                              and an image without these headers compiles a
#:                              toy freestanding file perfectly and then dies
#:                              on the rig's real source with "bits/wordsize.h:
#:                              No such file or directory".  Found by compiling
#:                              the ACTUAL shim instead of a stand-in, which is
#:                              now what CI does
#:   gcc + libc6-dev            the native half of the bridge
#:   e2fsprogs                  debugfs
#:   fuse2fs                    running a card WITHOUT unpacking it, and its
#:                              OWN package since 24.04 - it used to ship
#:                              inside e2fsprogs, so the rig's list (which
#:                              names capabilities, spelled for the distro of
#:                              the day) did not carry it, and the first full
#:                              image was built without it.  Caught by the CI
#:                              step that asks each tool to do its job, which
#:                              is the entire reason that step exists
#:   fuse3                      fusermount3, for those mounts
#:   ffmpeg                     the game decodes NEITHER its video nor its
#:                              sound itself, so both go through this; without
#:                              it a run comes up black and silent, which is
#:                              the one missing package that does not look like
#:                              a missing package
#:   busybox-static             the checkpointable (save-state) boot pivots
#:                              away from the host tree and needs a NATIVE
#:                              STATIC binary inside the guest root
#: and the rest are what the rig's own scripts call: make and patch for its
#: builds, zstd and xxd for card work, file(1) - which emu_root.sh uses to
#: decide whether busybox is static, and therefore whether SAVE STATES are
#: possible at all (without it the boot quietly falls back and blames the
#: machine for a missing static busybox that is right there), and the two runtime libraries the GL
#: renderer links by SONAME (it declares every entry point itself, so no -dev
#: packages are needed for them).  criu's shared libraries are here too,
#: because the binary copied in from the stage above is dynamically linked.
RUN if [ "$VARIANT" = full ]; then \
      apt-get -o Acquire::Retries=10 update \
      && apt-get -o Acquire::Retries=10 install -y --no-install-recommends \
        qemu-user-static \
        gcc-arm-linux-gnueabihf libc6-dev-armhf-cross \
        gcc libc6-dev \
        e2fsprogs \
        fuse2fs \
        fuse3 \
        ffmpeg \
        busybox-static \
        make patch zstd xxd file \
        libegl1 libx11-6 \
        libprotobuf-c1 libnl-3-200 libnet1 libcap2 libbsd0 libuuid1 \
      && rm -rf /var/lib/apt/lists/*; \
    fi

#: WHAT THE PIPELINES USE - the OTHER half of this app, and the reason this
#: image is not merely an emulator detail.  Every manufacturer's extract and
#: write path shells into Linux too: partclone opens a Clonezilla restore
#: image, xorriso rebuilds a JJP .iso, gnupg decrypts a .fun, cwebp re-imports
#: a texture.  All of that has until now run in whichever distro the machine
#: happened to have, installed by asking apt on the user's machine - which is
#: the arrangement this runtime exists to end, and the only reason the app
#: could not simply route everything here: an image missing these would trade
#: a working default distro for one with tools missing from it.
#:
#: THE LIST IS THE UNION of installer/install_prerequisites.ps1's WslPackages
#: tables, minus what the two blocks above already installed, and a test holds
#: the two together (tests/test_runtime_packages.py) so a package added to a
#: manufacturer and forgotten here cannot ship quietly.
#:   gnupg              Barrels of Fun: .fun decryption and re-encryption
#:   partclone          Spooky and JJP: Clonezilla restore images
#:   python3-zstandard  zstd-compressed images, read by this image's python3
#:   xorriso            JJP: rebuilding the .iso on Write
#:   pigz               JJP: parallel gzip, over images measured in gigabytes
#:   curl, unzip        what install_gdre.sh below needs for its download
#:   xvfb               GDRE Tools is a Godot BINARY and opens a display even
#:                      for a headless job, so the pipeline runs it under
#:                      xvfb-run
#:   xauth              which xvfb-run itself shells out to for the display's
#:                      cookie, and which nothing pulls in under
#:                      --no-install-recommends - an image with xvfb and no
#:                      xauth has an xvfb-run that exits before it starts
#:   webp               cwebp, the texture re-import in the BOF write pipeline
#:   psmisc             fuser(1), which the multi-boot card builder asks who
#:                      is holding a mountpoint before it detaches a stale
#:                      loop device.  Not in any prerequisite table because
#:                      every desktop distro has it - and its absence is not a
#:                      missing feature but a FileNotFoundError mid-build
#: tar, e2fsprogs, ffmpeg, xxd, zstd, gcc, libc6-dev, util-linux and mount are
#: already here - from the base image, or from the two blocks above.
RUN if [ "$VARIANT" = full ]; then \
      apt-get -o Acquire::Retries=10 update \
      && apt-get -o Acquire::Retries=10 install -y --no-install-recommends \
        gnupg \
        partclone \
        python3-zstandard \
        xorriso \
        pigz \
        curl \
        unzip \
        xvfb \
        xauth \
        webp \
        psmisc \
      && rm -rf /var/lib/apt/lists/*; \
    fi

# GDRE TOOLS, INSTALLED BY THE APP'S OWN INSTALLER SCRIPT rather than by a copy
# of it.  installer/install_gdre.sh is the single place its version, URL and
# SHA-256 live - it is what both prerequisite installers already run - so the
# workflow stages that same file here and this line runs it.  The tool baked
# into this image is therefore the tool, at the version, a user on his own
# distro gets, verified against the same hash before anything is unpacked.
#
# It is not in apt and never has been, which is why it needed a downloader at
# all.  Baked in, the Barrels of Fun write path needs no download on a user's
# machine, and no third-party release still being there years from now.
COPY payload/install_gdre.sh /tmp/install_gdre.sh
RUN if [ "$VARIANT" = full ]; then bash /tmp/install_gdre.sh; fi \
 && rm -f /tmp/install_gdre.sh

COPY --from=criu /out/ /

# THE RIG LOOKS UP uid 1000 BY NUMBER (`getent passwd 1000`) to find the
# desktop user and its home, so the image must have one - an image whose only
# account is root would have the rig writing its work dir into /root and the
# viewer windows running as the wrong user.
#
# The stock account goes first.  Ubuntu's 24.04 image ships a user called
# `ubuntu` AT UID 1000 (22.04 did not), so creating ours is "UID 1000 is not
# unique" until that one is gone - which cost this image its fourth build.
# Removing it rather than reusing it keeps the name predictable: every path
# baked in below, and every log line the rig writes, says /home/pad.
RUN userdel -r ubuntu 2>/dev/null || true \
 && useradd -m -u 1000 -s /bin/bash pad \
 && [ "$(id -u pad)" = 1000 ]

# WSL reads this on every start of the distro.
#   default=pad          the rig's ordinary-user half runs as uid 1000
#   automount            /mnt/c, which is how the rig reaches the app's own
#                        files and the card images the user picks
#   interop + appendWindowsPath   the emulator's sound is played by a WINDOWS
#                        process the rig launches through interop; without this
#                        the run is silent and nothing says why
#
# AND NO `[boot] systemd=true`, which this file did claim for exactly one
# build.  Two reasons, and the second is the one that matters:
#
#   * it was a lie.  This base image has no systemd package, so WSL falls back
#     to its own init and the setting does nothing - the rig's own check
#     reported `wslconf=0` on an image whose wsl.conf said systemd=true.
#   * and installing systemd to make it true would be worse.  binfmt_misc is
#     VM-GLOBAL in WSL: every distro shares one kernel and one handler table.
#     qemu-user-static's /usr/lib/binfmt.d entry, applied by our systemd at
#     every start of this distro, would re-register the ARM interpreter for the
#     user's OTHER distros too - and the Spike 1 rig deliberately swaps that
#     handler and restores the stock one when it stops.  A distro of ours
#     quietly reaching into that is the kind of surprise this runtime exists to
#     remove, not to introduce.
#
# So the RIG owns the ARM handler, as it always has: setupcheck.sh reports it,
# setupfix.sh registers it, and the rig puts back what it found.
RUN printf '%s\n' \
      '[user]' 'default=pad' '' \
      '[automount]' 'enabled=true' 'options="metadata"' '' \
      '[interop]' 'enabled=true' 'appendWindowsPath=true' \
    > /etc/wsl.conf

# The binaries we build ourselves, already verified against the app's pins by
# the workflow that put them here.  Baked in so a fresh import needs no second
# download and no compiler: the rig finds them exactly where it looks.
COPY --chmod=0755 payload/qemu-arm /home/pad/qemubuild/qemu-arm
COPY --chmod=0755 payload/s1hwshim /home/pad/s1emu/s1hwshim
COPY payload/qemu-arm.pad-payload /home/pad/qemubuild/qemu-arm.pad-payload
COPY payload/s1hwshim.pad-payload /home/pad/s1emu/s1hwshim.pad-payload
RUN chown -R pad:pad /home/pad

# WHAT THIS IMAGE IS, answerable from inside it.  The app reads this to decide
# whether the installed runtime is the one this app version expects, and it is
# how a support question ("which runtime are you on?") has one answer instead
# of a guess.  dpkg -l goes in beside it: the exact version of every package
# that was installed, so a build can be described even if it can never be
# byte-reproduced.
ARG BUILD_STAMP=unknown
RUN printf '{\n  "runtime_version": %s,\n  "variant": "%s",\n  "snapshot": "%s",\n  "base_digest": "%s",\n  "built": "%s"\n}\n' \
      "${RUNTIME_VERSION}" "${VARIANT}" "${SNAPSHOT}" \
      "sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517" \
      "${BUILD_STAMP}" > /etc/pad-runtime.json \
 && dpkg-query -W -f='${binary:Package}=${Version}\n' | sort > /etc/pad-runtime.packages \
 && chmod 0644 /etc/pad-runtime.json /etc/pad-runtime.packages
