#!/bin/bash
# Rebuild the Spike 3 key-only payload natively in an AArch64 Linux container.
# CONTAINER_ENGINE=podman bash build-aarch64.sh
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ENGINE=${CONTAINER_ENGINE:-docker}
WORK=$(mktemp -d /tmp/pad-ssh-a64.XXXXXX)
WORK=$(cd "$WORK" && pwd -P)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/out"
cat > "$WORK/build.sh" <<'BUILD'
#!/bin/bash
set -euo pipefail
[ "$(uname -m)" = aarch64 ] || { echo 'This payload build needs an AArch64 container' >&2; exit 1; }
apt-get update -qq
apt-get install -y -qq build-essential musl-tools curl ca-certificates golang-go file >/dev/null
cd /work
curl -fsSL --retry 3 https://github.com/mkj/dropbear/archive/refs/tags/DROPBEAR_2025.88.tar.gz -o dropbear.tar.gz
tar xzf dropbear.tar.gz
cd dropbear-DROPBEAR_2025.88
cat > localoptions.h <<'OPTS'
#define DROPBEAR_SVR_PASSWORD_AUTH 0
#define DROPBEAR_CLI_PASSWORD_AUTH 0
#define DROPBEAR_SVR_PUBKEY_AUTH 1
#define DROPBEAR_REEXEC 0
#define SFTPSERVER_PATH "/usr/local/libexec/pad-sftp-server"
OPTS
CC=musl-gcc ./configure --disable-zlib --enable-static > /work/configure.log 2>&1
make -j2 PROGRAMS='dropbear dropbearkey' > /work/make.log 2>&1
cp dropbear dropbearkey /work/out/
export GOOS=linux GOARCH=arm64 CGO_ENABLED=0 GO111MODULE=off GOPATH=/work/gopath
for spec in github.com/pkg/sftp:v1.13.2 github.com/kr/fs:v0.1.0 golang.org/x/crypto:v0.7.0 golang.org/x/sys:v0.7.0; do
  module=${spec%:*}; version=${spec#*:}
  case "$module" in golang.org/x/*) upstream=golang/${module##*/} ;; *) upstream=${module#github.com/} ;; esac
  mkdir -p "$GOPATH/src/$module"
  curl -fsSL --retry 3 "https://codeload.github.com/$upstream/tar.gz/refs/tags/$version" | tar xz -C "$GOPATH/src/$module" --strip-components=1
done
mkdir -p /work/sftp
cat > /work/sftp/main.go <<'GO'
package main
import("io";"log";"os";"github.com/pkg/sftp")
type rw struct{}
func(rw) Read(p []byte)(int,error){return os.Stdin.Read(p)}
func(rw) Write(p []byte)(int,error){return os.Stdout.Write(p)}
func(rw) Close()error{return nil}
func main(){srv,err:=sftp.NewServer(rw{});if err!=nil{log.Fatal(err)};if err=srv.Serve();err!=nil&&err!=io.EOF{log.Fatal(err)}}
GO
cd /work/sftp
go build -trimpath -ldflags='-s -w' -o /work/out/sftp-server .
file /work/out/*
sha256sum /work/out/*
BUILD
"$ENGINE" run --rm --platform linux/arm64 -v "$WORK:/work:rw" docker.io/library/debian:12 /bin/bash /work/build.sh
mkdir -p "$HERE/aarch64"
for binary in dropbear dropbearkey sftp-server; do
  cp "$WORK/out/$binary" "$HERE/aarch64/$binary"
  chmod 755 "$HERE/aarch64/$binary"
done
