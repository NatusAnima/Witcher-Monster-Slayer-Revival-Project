/*
 * seccomp_shim — LD_PRELOAD'd into the musl server/Python on Android.
 *
 * Android's untrusted_app seccomp filter raises SIGSYS (killing the process) for syscalls outside
 * its allow-list. The .NET GC probes NUMA at startup with get_mempolicy(236), which Android blocks.
 * On a phone there is one memory node, so the right answer is "not supported": this handler returns
 * -ENOSYS for the NUMA syscall family and lets the process continue, which is how the runtime behaves
 * on any non-NUMA kernel. A SIGSYS for any other syscall is a real problem, so it is logged and fatal.
 *
 * arm64 only (the only ABI the phone runtime targets). Built by build_runtime.py in Alpine aarch64.
 */
#define _GNU_SOURCE
#include <signal.h>
#include <ucontext.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>

/* asm-generic syscall numbers (arm64): the NUMA memory-policy family. */
static int numa_syscall(unsigned long nr) {
    switch (nr) {
        case 235: /* mbind */
        case 236: /* get_mempolicy */
        case 237: /* set_mempolicy */
        case 238: /* migrate_pages */
        case 239: /* move_pages */
        case 450: /* set_mempolicy_home_node */
            return 1;
        default:
            return 0;
    }
}

static void on_sigsys(int sig, siginfo_t *si, void *ctx) {
    (void)sig;
    ucontext_t *uc = (ucontext_t *)ctx;
    unsigned long nr = uc->uc_mcontext.regs[8]; /* x8 holds the arm64 syscall number */
    if (numa_syscall(nr)) {
        uc->uc_mcontext.regs[0] = (unsigned long)(-ENOSYS); /* skip it, report "unsupported" */
        return; /* resume after the trapped svc; the syscall never runs */
    }
    char buf[96];
    int n = snprintf(buf, sizeof buf, "\nseccomp_shim: fatal SIGSYS on unexpected syscall %lu\n", nr);
    write(2, buf, n > 0 ? n : 0);
    _exit(159);
}

__attribute__((constructor))
static void arm(void) {
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = on_sigsys;
    sa.sa_flags = SA_SIGINFO | SA_RESTART;
    sigaction(SIGSYS, &sa, NULL);
}
