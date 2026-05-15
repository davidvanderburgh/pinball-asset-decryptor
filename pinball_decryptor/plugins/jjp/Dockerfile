# All-in-one Docker image for JJP Asset Decryptor
# Usage:
#   docker build -t jjp-decryptor .
#   docker run --privileged --rm \
#     -v /path/to/isos:/data \
#     -v /path/to/output:/output \
#     jjp-decryptor decrypt -i /data/game.iso -o /output

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

COPY jjp_decryptor/ /app/jjp_decryptor/
COPY partclone_to_raw.py /app/

WORKDIR /app

ENTRYPOINT ["python3", "-m", "jjp_decryptor.cli"]
