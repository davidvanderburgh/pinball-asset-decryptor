#!/bin/bash
# segvtest.sh - prove the crash reporter reports, on a LABELLED EXAMPLE.
#
# Item 41: two turtles_pro crashes died with qemu's bare "uncaught target
# signal 11" and NO signature, so there was nothing to say where they faulted.
# The reporter that should have named them could not run (it was installed only
# by interposing the game's own sigaction, and that game never calls it).
#
# THE POINT OF THIS SCRIPT. That fault cannot be provoked on demand, so the fix
# cannot be judged by "the next crash will tell us" - by then the run is gone
# and it is another week before it happens again. So: fault DELIBERATELY, under
# the same qemu-user + LD_PRELOAD arrangement the game runs in, and require the
# reporter to name it. Run this after ANY change to the segv path.
#
# IT NEEDS NO RUN and takes about two seconds. Do not start the emulator for it.
#
# THE CONTROL IS THE IMPORTANT CASE. B2 runs the same guest with the reporter
# switched off. B1 must produce the same guest-visible outcome as B2 - if the
# guest's own handler stops running once we are watching, the reporter is not
# an observer any more, it is a change in behaviour. The first version of this
# fix failed exactly that check, and only the control showed it.
#
# WHY THE ODD BUILD FLAGS: the Spike rootfs ships an older glibc than this
# host's cross-compiler targets, so a normally-linked test binary dies at
# "GLIBC_2.34 not found" before main. That requirement comes from
# __libc_start_main in the startup files, so -nostartfiles with our own _start
# removes it. The binaries stay DYNAMIC, which is the part that matters:
# LD_PRELOAD and the sigaction interposer only exist for a dynamic guest.
set -u
R=${PAD_ROOT:-$HOME/spike2root}
T=${TMPDIR:-/var/tmp}/segvtest
mkdir -p "$T"

[ -f "$R/lib/hwshim.so" ] || { echo "no shim at $R/lib/hwshim.so - run build.sh"; exit 1; }
command -v qemu-arm-static >/dev/null || { echo "needs qemu-arm-static"; exit 1; }

# A: nothing anywhere registers a SIGSEGV handler. This is the turtles shape -
# what qemu means by "uncaught". It must now print a signature AND still die.
cat > "$T/nohandler.c" <<'EOF'
extern long write(int, const void *, unsigned long);
extern void _exit(int);
int main(void){ volatile int *p = (int *)0;
    write(1, "about to fault\n", 15); *p = 1;
    write(1, "NOT REACHED\n", 12); return 0; }
void _start(void){ main(); _exit(0); }
EOF

# B: the guest installs its own handler and survives the fault. The reporter
# must not take that away from it.
cat > "$T/ownhandler.c" <<'EOF'
extern long write(int, const void *, unsigned long);
extern void _exit(int);
extern int sigaction(int, const void *, void *);
static void mine(int s){ (void)s; write(1, "MY HANDLER RAN\n", 15); _exit(0); }
int main(void){ volatile int *p = (int *)0;
    unsigned char sa[160]; int i; for (i=0;i<160;i++) sa[i]=0;
    *(void **)sa = (void *)mine;          /* sa_handler is slot 0 on ARM */
    sigaction(11, sa, 0);
    write(1, "about to fault\n", 15); *p = 1;
    write(1, "NOT REACHED\n", 12); return 0; }
void _start(void){ main(); _exit(0); }
EOF

CC="arm-linux-gnueabihf-gcc -O0 -nostartfiles"
$CC -o "$T/nohandler"  "$T/nohandler.c"  || { echo "BUILD A FAILED"; exit 1; }
$CC -o "$T/ownhandler" "$T/ownhandler.c" || { echo "BUILD B FAILED"; exit 1; }

run() {   # run <label> <binary> <env...>
    echo "=== $1"
    env $3 LD_PRELOAD="$R/lib/hwshim.so" PAD_AUDIO_OUT=/dev/null \
        qemu-arm-static -L "$R" "$2" 2>&1 \
      | grep -aE 'about to fault|NOT REACHED|MY HANDLER RAN|\[segv\]|qemu:' | head -8
    echo
}

run "A. no handler at all, as run_game.sh runs it. WANT: [segv] pc=, then it dies." \
    "$T/nohandler"  "PAD_SEGV_REPORT=1"
run "B1. guest has its OWN handler.  WANT: [segv] pc=, delegating, MY HANDLER RAN." \
    "$T/ownhandler" "PAD_SEGV_HEADER=1"
run "B2. THE CONTROL - same guest, reporter off. WANT: MY HANDLER RAN, no [segv]." \
    "$T/ownhandler" "PAD_SEGV_HEADER=0"
run "C. reporter off on A.           WANT: no [segv] at all - exactly as before." \
    "$T/nohandler"  "PAD_SEGV_HEADER=0"

cat <<'EOF'
Read it like this:
  A  must show "[segv] pc=" AND "qemu: uncaught target signal 11". Both. The
     signature is the new part; the death is what must NOT have changed.
  B1 must end with MY HANDLER RAN. If it does not, the reporter is eating a
     handler the guest installed, and B2 is the proof of what should happen.
  B2 and C are the controls. They must look exactly like the old behaviour.
EOF
