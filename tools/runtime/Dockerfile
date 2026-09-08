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
#     that: it carries only the newest version of anything, so a rebuild silently
#     picks up whatever security update landed since;
#   * and the two binaries we build ourselves come from the payloads release,
#     verified by the same SHA-256 the app carries (the workflow does that
#     check before this file ever sees them).
#
# WHAT IS DELIBERATELY NOT HERE.  The Spike 2 rig's toolchain - qemu-user-static,
# the ARM cross compiler, ffmpeg, criu - is another ~400 MB and its own
# verification pass, and Spike 2 is the rig that is in daily use, so moving it
# to a new distro is not something to do in the same breath as introducing one.
# The package list below is the variant `base`; the workflow is written to build
# more than one.

FROM ubuntu:24.04@sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517

# The instant of the archive this image installs from.  Bump it deliberately,
# never automatically: a new stamp is a new image and a new pin.
ARG SNAPSHOT=20260801T000000Z
ARG RUNTIME_VERSION=1
ARG VARIANT=base

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# One source list, one instant.  `check-valid-until=no` because a snapshot's
# Release file ages by definition and apt would otherwise refuse it as stale.
RUN printf '%s\n' \
      "deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/${SNAPSHOT} noble main universe" \
      "deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/${SNAPSHOT} noble-updates main universe" \
      "deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/${SNAPSHOT} noble-security main universe" \
    > /etc/apt/sources.list.d/ubuntu.sources.list \
 && rm -f /etc/apt/sources.list.d/ubuntu.sources

#: WHAT THE RIG ACTUALLY USES, read out of the rig rather than remembered:
#: every command its scripts call and every module its python imports.
#:   python3        every rig script that is not shell (build_rootfs.py reads
#:                  ext4 in pure python, so no e2fsprogs is needed for it)
#:   procps         pgrep/pkill - how the rig finds and stops its own processes
#:   util-linux     unshare/setsid/mount - the namespace the guest boots in
#:   socat          the one socket relay in the boot path
#:   ca-certificates  so anything fetched from in here can verify a certificate
#: fuse3 is NOT here on purpose: the device model links libfuse statically and
#: talks to /dev/fuse directly, so there is nothing left to install for it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 \
      procps \
      util-linux \
      socat \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# THE RIG LOOKS UP uid 1000 BY NUMBER (`getent passwd 1000`) to find the
# desktop user and its home, so the image must have one - an image whose only
# account is root would have the rig writing its work dir into /root and the
# viewer windows running as the wrong user.
RUN useradd -m -u 1000 -s /bin/bash pad

# WSL reads this on every start of the distro.
#   default=pad          the rig's ordinary-user half runs as uid 1000
#   automount            /mnt/c, which is how the rig reaches the app's own
#                        files and the card images the user picks
#   interop + appendWindowsPath   the emulator's sound is played by a WINDOWS
#                        process the rig launches through interop; without this
#                        the run is silent and nothing says why
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
