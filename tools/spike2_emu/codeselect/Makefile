# Makefile - codeselect, the boot-time code selector, for two machines:
#
#   make [PLATFORM=stern]   the Spike 2 card: an ARM executable for the card
#                           rootfs (glibc 2.21, kernel 3.14.28), built with
#                           Ubuntu's arm-linux-gnueabihf-gcc against $(ROOT)
#   make PLATFORM=jjp       a JJP machine (item 114): x86-64 for the card's
#                           Ubuntu 21.10 rootfs (glibc 2.34), built NATIVELY on
#                           the WSL host, as $(BUILD)/jjpselect.  egl_x11.c,
#                           input_jjpio.c and stubs_jjp.c stand in for the Stern
#                           hardware files; the menu sources are the same copy.
#                           JJPROOT=<mounted card image root> links against the
#                           card's own libraries and proves every symbol.
#
# THE STERN BUILD.  The card rootfs copy ($(ROOT)) is used as the sysroot BY
# HAND: the cross gcc searches its own tooldir /usr/arm-linux-gnueabihf/
# {include,lib} (glibc 2.39) AHEAD of --sysroot, so --sysroot alone silently
# produces a GLIBC_2.34 binary that the card's loader refuses. -nostdinc/
# -nostdlib plus explicit paths (recipe D of read_build.md) is the only order
# that cannot drift; the -U/-fno-* flags are load-bearing, keep them.
#
# THE JJP BUILD has the same trap the other way round: the host's glibc 2.39
# headers redirect strtol/sscanf to __isoc23_* symbols the card's 2.34 lacks
# (tools/jjp_emu/build.sh met it first).  jjp_glibc.h, force-included, turns
# the redirect off; test/check_elf_jjp.sh proves it.
#
#   make [BUILD=dir]           build $(BUILD)/codeselect  (jjp: $(BUILD)/jjpselect)
#   make check                 readelf ceiling + headless render + padsw test
#                              + select.sh syntax/lookup (stern: under qemu-arm-static;
#                              jjp: natively, plus the jjpio pty test)
#   make check-hw              fakebus.py node-bus test (pty, no hardware; stern)
#   make install DESTDIR=dir   install into $(DESTDIR)$(PREFIX)
.RECIPEPREFIX := >
PLATFORM ?= stern
ifeq ($(PLATFORM),jjp)
BUILD    ?= build-jjp
else
BUILD    ?= build
endif
ROOT     ?= /home/david/spike2root
JJPROOT  ?=
CROSS    ?= arm-linux-gnueabihf-
PYTHON   ?= python3
DESTDIR  ?=
DEJAVU   ?= /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
TABLES   ?= $(ROOT)/dump/tables/turtles_pro/switch_list.txt

ifeq ($(PLATFORM),jjp)
# ---- JJP: native x86-64, the host gcc, the card's paths baked in ----
CC        = gcc
CROSS     =
BINNAME   = jjpselect
PREFIX   ?= /jjpe/gen1/padselect
# no emulator: the test drivers' "$(QEMU) -L $(ROOT) BIN" becomes "BIN"
QEMU      = $(CURDIR)/test/native.sh
export QEMU
CRTBEGIN := $(shell $(CC) -print-file-name=crtbegin.o)
CRTEND   := $(shell $(CC) -print-file-name=crtend.o)
CFLAGS    = -std=gnu17 -O2 -Wall -Werror=implicit-function-declaration \
            -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0 -fno-stack-protector -fno-pie -no-pie \
            -include jjp_glibc.h \
            -DDEF_CONF='"/jjpe/gen1/padselect/images.conf"' \
            -DDEF_OUT='"/jjpe/temp/padselect.choice"' \
            -DDEF_LAST='"/jjpe/perm/padselect.last"' \
            -DDEF_FONT='"/jjpe/gen1/padselect/font.ttf"' \
            -DDEF_MEDIA='"/jjpe/gen1/padselect/media"' \
            -DCARD_FONT='"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"' \
            -I$(BUILD) $(EXTRA_CFLAGS)
# libEGL/libGLESv2 are NOT linked: egl_x11.c dlopens them, so a box without
# Mesa (and the WSL host, which has no libGLESv2) still runs the menu.
ifneq ($(JJPROOT),)
# the card's own libraries: every symbol version pinned to what it ships
JJPLIB    = $(JJPROOT)/usr/lib/x86_64-linux-gnu
LDPRE     = -nostdlib -nostartfiles $(shell $(CC) -print-file-name=crt1.o) $(shell $(CC) -print-file-name=crti.o) $(CRTBEGIN)
LDPOST    = $(CRTEND) $(shell $(CC) -print-file-name=crtn.o) -L$(JJPLIB) -Wl,-rpath-link,$(JJPLIB) \
            -l:libX11.so.6 -l:libasound.so.2 -l:libpthread.so.0 -l:libdl.so.2 -l:libm.so.6 \
            -l:libc.so.6 $(shell $(CC) -print-file-name=libc_nonshared.a) -l:libgcc_s.so.1 -lgcc
else
# the host's runtime libraries by soname (no -dev packages needed)
LDPRE     =
LDPOST    = -L/usr/lib/x86_64-linux-gnu -l:libX11.so.6 -l:libasound.so.2 -lpthread -ldl -lm
endif
GLLIBS    =
AUDLIBS   =
LIBC      =
SRCS = codeselect.c conf.c theme.c gfx.c egl_x11.c input.c input_jjpio.c input_padsw.c stubs_jjp.c log.c art.c audio.c audio_fifo.c audio_alsa.c nvm.c
HDRS = conf.h theme.h gfx.h egl_stern.h input.h log.h art.h audio.h codec.h nvm.h jjp_glibc.h $(BUILD)/theme_table.h
else
# ---- Stern: the ARM cross build against the card rootfs ----
CC        = $(CROSS)gcc
BINNAME   = codeselect
PREFIX   ?= /usr/local/codeselect
# QEMU reaches the test scripts through the ENVIRONMENT, never their argv:
# the rig's teardown (killgame.sh, watch.sh) does pkill -9 -f 'arm-binfmt|qemu-arm',
# and `bash test/headless.sh qemu-arm-static ...` matched it - a run torn down
# beside `make check` killed the tests. Only the short-lived qemu child's own
# command line matches now.
QEMU     ?= qemu-arm-static
export QEMU
GCCINC   := $(shell $(CC) -print-file-name=include)
CRTBEGIN := $(shell $(CC) -print-file-name=crtbegin.o)
CRTEND   := $(shell $(CC) -print-file-name=crtend.o)
# -std=gnu17: the dialect is a decision, not whatever the distro's gcc defaults
# to this year.  gcc 11 (22.04) and 13 (24.04) already default to it; gcc 15
# defaults to gnu23, where bool/true/false are keywords - the change that broke
# criu here already, and which would otherwise arrive in these sources with the
# next LTS and no warning.
CFLAGS    = -std=gnu17 -O2 -Wall -Werror=implicit-function-declaration \
            -U_TIME_BITS -U_FILE_OFFSET_BITS -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0 \
            -fno-stack-protector -fno-pie -no-pie \
            -nostdinc -isystem $(GCCINC) -isystem $(ROOT)/usr/include -I$(BUILD) $(EXTRA_CFLAGS)
LDPRE     = -nostdlib -nostartfiles $(ROOT)/usr/lib/crt1.o $(ROOT)/usr/lib/crti.o $(CRTBEGIN)
LDPOST    = $(CRTEND) $(ROOT)/usr/lib/crtn.o -L$(ROOT)/lib -L$(ROOT)/usr/lib \
            -Wl,-rpath-link,$(ROOT)/lib -Wl,-rpath-link,$(ROOT)/usr/lib \
            -Wl,--dynamic-linker=/lib/ld-linux-armhf.so.3
# libc_nonshared.a: __libc_csu_init/fini for the rootfs crt1.o + the stat wrappers
# -l:libgcc_s.so.1: the rig's bridge shims leave __aeabi_uldivmod undefined
# -l:libpthread.so.0: the input scan and the animation cache are threads (2.8)
LIBC      = -l:libpthread.so.0 -l:libc.so.6 $(ROOT)/usr/lib/libc_nonshared.a -l:libm.so.6 -l:libgcc_s.so.1 -lgcc
GLLIBS    = -l:libEGL.so.1 -l:libGLESv2.so.2
# the rootfs alsa-lib 1.0.28 (GLIBC_2.4 only; its libdl/libpthread/librt are
# in the rootfs). Hand prototypes in audio_alsa.c: no headers on the box.
AUDLIBS   = -l:libasound.so.2
# input_jjpio.c is plain POSIX and rides along: codeselect.c dispatches every
# backend by name, and on a Stern card `--input jjpio` finds no /dev/jjpio
SRCS = codeselect.c conf.c theme.c gfx.c egl_stern.c input.c input_hw.c input_padsw.c input_jjpio.c log.c art.c audio.c audio_fifo.c audio_alsa.c codec.c nvm.c
HDRS = conf.h theme.h gfx.h egl_stern.h input.h log.h art.h audio.h codec.h nvm.h $(BUILD)/theme_table.h
endif

# THE PAST-32 BINARY (item 105).  The animation tick used to mark the cards
# that moved in an `unsigned` bitmask (`1u << i`), which is undefined from
# card 32 up and fails silently.  It is a flag array now, and this second
# build of the SAME sources at a raised cap is what proves it: a menu is
# CONF_MAX_CARDS wide (16) and no conf can talk the shipped binary past that,
# so without this build the fix would stay untested.  Item 106 raised the
# IMAGE cap to 64 and left CARDS at 16 - a group of forty variants is one
# card - so the override moved to the cap that actually sizes the tick.
# Built by `make check`, never installed, never written to a card.
CAP_N    ?= 40
CAPBUILD  = $(BUILD)-cap$(CAP_N)
CAPBIN    = $(CAPBUILD)/$(BINNAME)

OBJS = $(SRCS:%.c=$(BUILD)/%.o)
BIN  = $(BUILD)/$(BINNAME)

all: $(BIN)

$(BUILD):
> mkdir -p $(BUILD)

# The colour themes: themes.json is the one definition (mkmulticard.py and the
# app read the same file), turned into a header in the build dir - generated,
# never committed, and checked by the generator (a bad JSON fails the build).
$(BUILD)/theme_table.h: themes.json gen_themes.py | $(BUILD)
> $(PYTHON) gen_themes.py themes.json $@

$(BUILD)/%.o: %.c $(HDRS) | $(BUILD)
> $(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/gfx.o: third_party/stb_truetype.h
$(BUILD)/art.o: third_party/stb_image.h

# a failed link deletes its output: never leave a stale binary behind
$(BIN): $(OBJS)
> $(CC) $(CFLAGS) $(LDPRE) $(OBJS) $(LDPOST) $(GLLIBS) $(AUDLIBS) $(LIBC) -o $@ || { rm -f $@; exit 1; }
> @echo "built $@"

# a recursive build of the same sources: only BUILD and the cap differ
capbin:
> $(MAKE) PLATFORM=$(PLATFORM) JJPROOT="$(JJPROOT)" BUILD="$(CAPBUILD)" EXTRA_CFLAGS=-DCONF_MAX_CARDS=$(CAP_N) "$(CAPBIN)"

ifeq ($(PLATFORM),jjp)
check: $(BIN) capbin
> bash test/check_elf_jjp.sh "$(BIN)" "$(JJPROOT)"
> bash test/check_elf_jjp_selftest.sh "$(BUILD)/t"
> CAPBIN="$(CAPBIN)" CAP_N=$(CAP_N) bash test/headless.sh "$(ROOT)" "$(BIN)" "$(BUILD)/t" "$(DEJAVU)"
> $(PYTHON) test/padsw_test.py "$(ROOT)" "$(BIN)" "$(BUILD)/t" "$(TABLES)" "$(DEJAVU)"
> $(PYTHON) test/jjpio_test.py "$(BIN)" "$(BUILD)/t" "$(DEJAVU)"
> @echo "check: OK (jjp)"

check-hw:
> @echo "check-hw: the node-bus test is Stern's; the JJP board test is part of make check"

install: $(BIN)
> install -d "$(DESTDIR)$(PREFIX)"
> install -m 755 "$(BIN)" "$(DESTDIR)$(PREFIX)/jjpselect"
> install -m 644 images.conf.example "$(DESTDIR)$(PREFIX)/images.conf.example"
> if [ -f "$(DEJAVU)" ]; then install -m 644 "$(DEJAVU)" "$(DESTDIR)$(PREFIX)/font.ttf"; else echo "no $(DEJAVU): the card's DejaVuSans-Bold.ttf will be used"; fi
> if [ -d media ]; then install -d "$(DESTDIR)$(PREFIX)/media"; for f in media/*; do if [ -f "$$f" ]; then install -m 644 "$$f" "$(DESTDIR)$(PREFIX)/media/"; fi; done; fi
else
check: $(BIN) capbin
> bash test/check_elf.sh "$(CROSS)" "$(BIN)"
> CAPBIN="$(CAPBIN)" CAP_N=$(CAP_N) bash test/headless.sh "$(ROOT)" "$(BIN)" "$(BUILD)/t" "$(DEJAVU)"
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
> install -m 755 materialize.py "$(DESTDIR)$(PREFIX)/materialize.py"
> install -m 644 images.conf.example "$(DESTDIR)$(PREFIX)/images.conf.example"
> if [ -f "$(DEJAVU)" ]; then install -m 644 "$(DEJAVU)" "$(DESTDIR)$(PREFIX)/font.ttf"; else echo "no $(DEJAVU): the card's VeraMono.ttf will be used"; fi
> if [ -d media ]; then install -d "$(DESTDIR)$(PREFIX)/media"; for f in media/*; do if [ -f "$$f" ]; then install -m 644 "$$f" "$(DESTDIR)$(PREFIX)/media/"; fi; done; fi
endif

clean:
> rm -rf "$(BUILD)" "$(CAPBUILD)"

.PHONY: all capbin check check-hw install clean
