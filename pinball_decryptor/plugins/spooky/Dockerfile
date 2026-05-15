# Lightweight container for Spooky Pinball Asset Decryptor
# Provides Linux tools needed for Clonezilla extraction and GPG operations.
#
# Usage (standalone):
#   docker build -t spooky-decryptor .
#   docker run --privileged --rm -v /path/to/data:/data spooky-decryptor bash
#
# The GUI app builds and manages this container automatically on macOS.

FROM alpine:latest

RUN apk add --no-cache \
    bash \
    python3 \
    py3-pip \
    partclone \
    e2fsprogs \
    e2fsprogs-extra \
    gnupg \
    pigz \
    coreutils \
    tar \
    zstd \
    util-linux \
    && pip3 install --break-system-packages zstandard

WORKDIR /tmp

CMD ["bash"]
