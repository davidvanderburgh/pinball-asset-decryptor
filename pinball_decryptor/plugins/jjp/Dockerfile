# Lightweight container for JJP Asset Decryptor
# Provides the Linux tools needed for ISO partition extraction, ext4
# editing, and ISO rebuild on macOS (where there's no WSL).
#
# Usage (standalone):
#   docker build -t jjp-decryptor .
#   docker run --privileged --rm -v /path/to/data:/data jjp-decryptor bash
#
# The GUI app builds and manages this container automatically on macOS:
# it runs the image with `sleep infinity` and `docker exec`s individual
# tool commands into it.  partclone_to_raw.py is staged into the
# bind-mounted /tmp at runtime, so the image only needs to carry tools.

FROM alpine:latest

RUN apk add --no-cache \
    bash \
    python3 \
    partclone \
    xorriso \
    e2fsprogs \
    e2fsprogs-extra \
    pigz \
    coreutils \
    tar \
    rsync \
    util-linux \
    findmnt

WORKDIR /tmp

CMD ["bash"]
