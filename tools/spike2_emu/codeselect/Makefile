# Makefile - codeselect, an ARM executable for the Spike 2 card rootfs
# (glibc 2.21, kernel 3.14.28), built with Ubuntu's arm-linux-gnueabihf-gcc.
#
# The card rootfs copy ($(ROOT)) is used as the sysroot BY HAND: the cross
# gcc searches its own tooldir /usr/arm-linux-gnueabihf/{include,lib}
# (glibc 2.39) AHEAD of --sysroot, so --sysroot alone silently produces a
# GLIBC_2.34 binary that the card's loader refuses. -nostdinc/-nostdlib plus
# explicit paths (recipe D of read_build.md) is the only order that cannot
# drift; the -U/-fno-* flags are load-bearing, keep them.
#
#   make [BUILD=dir]           build $(BUILD)/codeselect
#   make check                 readelf ceiling + headless render + padsw test
#                              + select.sh syntax/lookup (runs under qemu-arm-static)
#   make check-hw              fakebus.py node-bus test (pty, no hardware)
#   make install DESTDIR=dir   install into $(DESTDIR)/usr/local/codeselect
.RECIPEPREFIX := >
ROOT     ?= /home/david/spike2root
CROSS    ?= arm-linux-gnueabihf-
CC        = $(CROSS)gcc
# QEMU reaches the test scripts through the ENVIRONMENT, never their argv:
# the rig's teardown (killgame.sh, watch.sh) does pkill -9 -f 'arm-binfmt|qemu-arm',
# and `bash test/headless.sh qemu-arm-static ...` matched it - a run torn down
# beside `make check` killed the tests. Only the short-lived qemu child's own
# command line matches now.
QEMU     ?= qemu-arm-static
export QEMU
BUILD    ?= build
DESTDIR  ?=
PREFIX   ?= /usr/local/codeselect
DEJAVU   ?= /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
TABLES   ?= $(ROOT)/dump/tables/turtles_pro/switch_list.txt
GCCINC   := $(shell $(CC) -print-file-name=include)
CRTBEGIN := $(shell $(CC) -print-file-name=crtbegin.o)
CRTEND   := $(shell $(CC) -print-file-name=crtend.o)
CFLAGS    = -O2 -Wall -Werror=implicit-function-declaration \
            -U_TIME_BITS -U_FILE_OFFSET_BITS -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0 \
            -fno-stack-protector -fno-pie -no-pie \
            -nostdinc -isystem $(GCCINC) -isystem $(ROOT)/usr/include
LDPRE     = -nostdlib -nostartfiles $(ROOT)/usr/lib/crt1.o $(ROOT)/usr/lib/crti.o $(CRTBEGIN)
LDPOST    = $(CRTEND) $(ROOT)/usr/lib/crtn.o -L$(ROOT)/lib -L$(ROOT)/usr/lib \
            -Wl,-rpath-link,$(ROOT)/lib -Wl,-rpath-link,$(ROOT)/usr/lib \
            -Wl,--dynamic-linker=/lib/ld-linux-armhf.so.3
# libc_nonshared.a: __libc_csu_init/fini for the rootfs crt1.o + the stat wrappers
# -l:libgcc_s.so.1: the rig's bridge shims leave __aeabi_uldivmod undefined
LIBC      = -l:libc.so.6 $(ROOT)/usr/lib/libc_nonshared.a -l:libm.so.6 -l:libgcc_s.so.1 -lgcc
GLLIBS    = -l:libEGL.so.1 -l:libGLESv2.so.2

SRCS = codeselect.c conf.c gfx.c egl_stern.c input.c input_hw.c input_padsw.c log.c
HDRS = conf.h gfx.h egl_stern.h input.h log.h
OBJS = $(SRCS:%.c=$(BUILD)/%.o)
BIN  = $(BUILD)/codeselect

all: $(BIN)

$(BUILD):
> mkdir -p $(BUILD)

$(BUILD)/%.o: %.c $(HDRS) | $(BUILD)
> $(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/gfx.o: third_party/stb_truetype.h

# a failed link deletes its output: never leave a stale binary behind
$(BIN): $(OBJS)
> $(CC) $(CFLAGS) $(LDPRE) $(OBJS) $(LDPOST) $(GLLIBS) $(LIBC) -o $@ || { rm -f $@; exit 1; }
> @echo "built $@"

check: $(BIN)
> bash test/check_elf.sh "$(CROSS)" "$(BIN)"
> bash test/headless.sh "$(ROOT)" "$(BIN)" "$(BUILD)/t" "$(DEJAVU)"
> python3 test/padsw_test.py "$(ROOT)" "$(BIN)" "$(BUILD)/t" "$(TABLES)" "$(DEJAVU)"
> bash -n select.sh && bash test/select_sh_test.sh
> @echo "check: OK"

check-hw: $(BIN)
> python3 test/fakebus_test.py "$(ROOT)" "$(BIN)" "$(BUILD)/t" "$(DEJAVU)"
> @echo "check-hw: OK"

install: $(BIN)
> install -d "$(DESTDIR)$(PREFIX)"
> install -m 755 "$(BIN)" "$(DESTDIR)$(PREFIX)/codeselect"
> install -m 755 select.sh "$(DESTDIR)$(PREFIX)/select.sh"
> install -m 644 images.conf.example "$(DESTDIR)$(PREFIX)/images.conf.example"
> if [ -f "$(DEJAVU)" ]; then install -m 644 "$(DEJAVU)" "$(DESTDIR)$(PREFIX)/font.ttf"; else echo "no $(DEJAVU): the card's VeraMono.ttf will be used"; fi

clean:
> rm -rf "$(BUILD)"

.PHONY: all check check-hw install clean
