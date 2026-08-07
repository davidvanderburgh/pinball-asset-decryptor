#!/bin/bash
. "$(dirname "$0")/padpath.sh"
L=$ROOT/usr/lib/libstdc++.so.6.0.20
echo "=== filebuf / streambuf symbols exported by the guest libstdc++ ==="
arm-linux-gnueabihf-nm -D --defined-only $L 2>/dev/null \
  | grep -E 'basic_filebuf.*(xsgetn|underflow|open|_M_)|basic_streambuf.*xsgetn' \
  | c++filt | head -20
echo
echo "=== raw mangled names we would need ==="
arm-linux-gnueabihf-nm -D --defined-only $L 2>/dev/null \
  | grep -E '6xsgetnEPci|9underflowEv' | head -10
echo
echo "=== does libstdc++ import read/fread/fopen64? ==="
arm-linux-gnueabihf-nm -D --undefined-only $L 2>/dev/null \
  | grep -wE 'read|fread|fopen|fopen64|open|open64|lseek|lseek64|fseek|fstat|__fxstat64|memcpy' | head -20
