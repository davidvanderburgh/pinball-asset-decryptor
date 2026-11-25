#!/bin/bash
# Rebuild the JJP (x86-64 PC) key-only payload: bash build-x86_64.sh
#
# Same pinned versions and options as the Spike 2 / Spike 3 payloads:
#   dropbear/dropbearkey : dropbear 2025.88, static musl x86-64, password auth
#                          compiled out, SFTP at /usr/local/libexec/pad-sftp-server
#                          (the machine's stock /usr/lib/openssh/sftp-server is kept)
#   sftp-server          : static Go, pkg/sftp v1.13.2, kr/fs v0.1.0,
#                          golang.org/x/{crypto,sys} v0.7.0
#
# Runs natively on any x86-64 Linux host (WSL is fine); no container needed.
# Toolchains are fetched into a scratch folder, nothing is installed:
#   https://musl.cc/x86_64-linux-musl-cross.tgz
#   https://go.dev/dl/go1.22.12.linux-amd64.tar.gz
# Writes x86_64/ beside this file and prints sha256 of each result; update
# X86_64_HASHES in core/ssh_jjp.py and repeat the emulator qualification.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
[ "$(uname -m)" = x86_64 ] || { echo 'This payload build needs an x86-64 Linux host' >&2; exit 1; }
WORK=${PAD_SSH_BUILD_WORK:-$(mktemp -d /tmp/pad-ssh-x64.XXXXXX)}
mkdir -p "$WORK/out"
cd "$WORK"
[ -d musl ] || { curl -fsSL --retry 3 https://musl.cc/x86_64-linux-musl-cross.tgz -o musl.tgz
                 mkdir musl && tar xzf musl.tgz -C musl --strip-components=1; }
[ -d go ] || curl -fsSL --retry 3 https://go.dev/dl/go1.22.12.linux-amd64.tar.gz | tar xz
export PATH=$WORK/musl/bin:$WORK/go/bin:$PATH

[ -d dropbear-DROPBEAR_2025.88 ] || curl -fsSL --retry 3 \
  https://github.com/mkj/dropbear/archive/refs/tags/DROPBEAR_2025.88.tar.gz | tar xz
cd dropbear-DROPBEAR_2025.88
cat > localoptions.h <<'OPTS'
#define DROPBEAR_SVR_PASSWORD_AUTH 0
#define DROPBEAR_CLI_PASSWORD_AUTH 0
#define DROPBEAR_SVR_PUBKEY_AUTH 1
#define DROPBEAR_REEXEC 0
#define SFTPSERVER_PATH "/usr/local/libexec/pad-sftp-server"
OPTS
CC=x86_64-linux-musl-gcc ./configure --host=x86_64-linux-musl --disable-zlib --enable-static \
  > "$WORK/configure.log" 2>&1
make clean > /dev/null 2>&1 || true
make -j"$(nproc)" PROGRAMS='dropbear dropbearkey' > "$WORK/make.log" 2>&1
x86_64-linux-musl-strip dropbear dropbearkey
cp dropbear dropbearkey "$WORK/out/"

export GOOS=linux GOARCH=amd64 CGO_ENABLED=0 GO111MODULE=off GOPATH=$WORK/gopath GOFLAGS=
for spec in github.com/pkg/sftp:v1.13.2 github.com/kr/fs:v0.1.0 golang.org/x/crypto:v0.7.0 golang.org/x/sys:v0.7.0; do
  module=${spec%:*}; version=${spec#*:}
  case "$module" in golang.org/x/*) upstream=golang/${module##*/} ;; *) upstream=${module#github.com/} ;; esac
  [ -d "$GOPATH/src/$module" ] && continue
  mkdir -p "$GOPATH/src/$module"
  curl -fsSL --retry 3 "https://codeload.github.com/$upstream/tar.gz/refs/tags/$version" | tar xz -C "$GOPATH/src/$module" --strip-components=1
done
mkdir -p "$WORK/sftp"
cat > "$WORK/sftp/main.go" <<'GO'
package main
import("io";"log";"os";"github.com/pkg/sftp")
type rw struct{}
func(rw) Read(p []byte)(int,error){return os.Stdin.Read(p)}
func(rw) Write(p []byte)(int,error){return os.Stdout.Write(p)}
func(rw) Close()error{return nil}
func main(){srv,err:=sftp.NewServer(rw{});if err!=nil{log.Fatal(err)};if err=srv.Serve();err!=nil&&err!=io.EOF{log.Fatal(err)}}
GO
cd "$WORK/sftp"
go build -trimpath -ldflags='-s -w' -o "$WORK/out/sftp-server" .
mkdir -p "$HERE/x86_64"
for binary in dropbear dropbearkey sftp-server; do
  cp "$WORK/out/$binary" "$HERE/x86_64/$binary"
  chmod 755 "$HERE/x86_64/$binary"
done
file "$HERE"/x86_64/* 2>/dev/null || true
sha256sum "$HERE"/x86_64/*
