#!/bin/sh
# build-binaries.sh — rebuild bin/{dropbear,dropbearkey,sftp-server} in a
# Docker container, reproducing the original pinball-assets/.ssh-build builds:
#
#   dropbear/dropbearkey : dropbear 2025.88, static musl armhf
#                          (password auth compiled out, DROPBEAR_REEXEC=0 —
#                           the Spike 2 kernel 3.14 predates execveat)
#   sftp-server          : static Go (pkg/sftp), GOARCH=arm GOARM=7,
#                          built in GOPATH mode from codeload tarballs
#                          (proxy.golang.org is unreachable on the dev network)
#
# Overwrites bin/ in place and prints file(1) + sha256 for each result.
# Requires docker. The container downloads:
#   https://musl.cc/arm-linux-musleabihf-cross.tgz
#   https://github.com/mkj/dropbear (tag DROPBEAR_2025.88)
#   https://codeload.github.com/pkg/sftp (v1.13.2) + deps
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DOCKER_IMAGE="debian:12"

command -v docker >/dev/null 2>&1 || { echo "error: docker not found" >&2; exit 1; }

# scratch dir under $HOME (Docker Desktop on macOS mishandles /tmp bind mounts)
WORK=$HOME/.ssh-image-build.$$
mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT

cat > "$WORK/build.sh" <<'BUILD'
#!/bin/sh
set -e
apt-get update -qq
apt-get install -y -qq make wget xz-utils file golang-go >/dev/null
cd /src

# --- dropbear 2025.88, static musl armhf ------------------------------------
if [ ! -d musl-toolchain ]; then
  wget -q https://musl.cc/arm-linux-musleabihf-cross.tgz -O musl.tgz
  mkdir musl-toolchain && tar xzf musl.tgz -C musl-toolchain --strip-components=1
fi
export PATH=/src/musl-toolchain/bin:$PATH
if [ ! -d dropbear ]; then
  wget -q https://github.com/mkj/dropbear/archive/refs/tags/DROPBEAR_2025.88.tar.gz -O dropbear.tar.gz
  tar xzf dropbear.tar.gz && mv dropbear-DROPBEAR_2025.88 dropbear
fi
cd dropbear
cat > localoptions.h <<'OPTS'
#define DROPBEAR_SVR_PASSWORD_AUTH 0
#define DROPBEAR_CLI_PASSWORD_AUTH 0
#define DROPBEAR_SVR_PUBKEY_AUTH 1
#define DROPBEAR_REEXEC 0
OPTS
CC=arm-linux-musleabihf-gcc \
  ./configure --host=arm-linux-musleabihf --disable-zlib --enable-static >/dev/null 2>&1
make clean >/dev/null 2>&1 || true
make -j"$(nproc)" PROGRAMS="dropbear dropbearkey" >/dev/null 2>&1
file dropbear dropbearkey
cp dropbear dropbearkey /out/

# --- sftp-server: static Go, armv7, GOPATH mode from codeload tarballs -------
export GOARCH=arm GOARM=7 GOOS=linux CGO_ENABLED=0 GO111MODULE=off
export GOPATH=/src/gopath
mkdir -p $GOPATH/src/github.com/pkg $GOPATH/src/github.com/kr $GOPATH/src/golang.org/x
cd $GOPATH/src/github.com/pkg
[ -d sftp ] || (wget -q https://codeload.github.com/pkg/sftp/tar.gz/refs/tags/v1.13.2 -O sftp.tgz && mkdir sftp && tar xzf sftp.tgz -C sftp --strip-components=1)
cd $GOPATH/src/github.com/kr
[ -d fs ] || (wget -q https://codeload.github.com/kr/fs/tar.gz/refs/tags/v0.1.0 -O fs.tgz && mkdir fs && tar xzf fs.tgz -C fs --strip-components=1)
cd $GOPATH/src/golang.org/x
[ -d crypto ] || (wget -q https://codeload.github.com/golang/crypto/tar.gz/refs/tags/v0.7.0 -O crypto.tgz && mkdir crypto && tar xzf crypto.tgz -C crypto --strip-components=1)
[ -d sys ] || (wget -q https://codeload.github.com/golang/sys/tar.gz/refs/tags/v0.7.0 -O sys.tgz && mkdir sys && tar xzf sys.tgz -C sys --strip-components=1)
mkdir -p /src/sftp-go && cd /src/sftp-go
cat > main.go <<'GO'
package main

import (
	"io"
	"log"
	"os"

	"github.com/pkg/sftp"
)

type rw struct{}

func (rw) Read(p []byte) (int, error)  { return os.Stdin.Read(p) }
func (rw) Write(p []byte) (int, error) { return os.Stdout.Write(p) }
func (rw) Close() error                { return nil }

func main() {
	srv, err := sftp.NewServer(rw{})
	if err != nil {
		log.Fatal(err)
	}
	if err := srv.Serve(); err != nil && err != io.EOF {
		log.Fatal(err)
	}
}
GO
go build -trimpath -ldflags="-s -w" -o /out/sftp-server .
file /out/sftp-server
BUILD
chmod +x "$WORK/build.sh"
mkdir -p "$WORK/out"

echo "[build] running container ($DOCKER_IMAGE) — downloads ~200 MB, takes a few minutes"
if ! docker run --rm -v "$WORK:/src:rw" -v "$WORK/out:/out:rw" "$DOCKER_IMAGE" /bin/sh /src/build.sh; then
  echo "error: build failed" >&2
  exit 1
fi

mkdir -p "$SCRIPT_DIR/armv7"
for B in dropbear dropbearkey sftp-server; do
  [ -f "$WORK/out/$B" ] || { echo "error: build did not produce $B" >&2; exit 1; }
  cp "$WORK/out/$B" "$SCRIPT_DIR/armv7/$B"
  chmod 755 "$SCRIPT_DIR/armv7/$B"
done
echo "[build] done. armv7/ now contains:"
for B in dropbear dropbearkey sftp-server; do
  echo "  $B: $(file -b "$SCRIPT_DIR/armv7/$B" | cut -c1-60)..."
  shasum -a 256 "$SCRIPT_DIR/armv7/$B" | sed 's/^/           sha256 /'
done
echo "[build] NOTE: rebuilt binaries may differ from the originally deployed ones"
echo "[build] (toolchain versions); if in doubt, keep the shipped bin/ files."
