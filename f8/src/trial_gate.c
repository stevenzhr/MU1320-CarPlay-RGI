/* MU1320 F7 daily gate for the navigation hook.
 *
 * F1-F6 used a one-shot arm token: only the first dio_manager after "arm"
 * was active and every replacement DIO (USB replug) forwarded passively.
 * F7 activates every real dio_manager unless it is switched off:
 *
 *   OFF_PERSIST  (on /mnt/app, survives reboot; control.sh off native)
 *   OFF_RUNTIME  (/tmp, until reboot or removal)
 *   crash guard  three consecutive active generations that each started less
 *                than SHORT_MS after the previous one -> passive for the rest
 *                of the boot (a hook fault in a restart loop heals itself;
 *                rm STRIKES re-enables).
 *
 * LAST and STRIKES are written in place (open O_TRUNC + write): /tmp is
 * /dev/shmem on this unit and has no rename(), so the v1/v1.1 temp+rename
 * never produced either file and the crash and live-DIO guards stayed inert
 * (F7 v1.1 car session P4, BACKLOG B11).  Both records are a few bytes and
 * are read only by later DIO generations; a torn read fails safe (no LAST:
 * is_current() answers 1; unreadable STRIKES counts as 0).
 *
 * Live-DIO guard: every activation records "pid start_ms" in LAST.  Only
 * the process named there may (re)connect the bus to Java; an older DIO that
 * is still alive stops reconnecting (trial_gate_is_current), so two
 * generations never take the single-accept Java bus from each other.
 *
 * The decision is made once per process, lazily, at the first interposed
 * Cinemo/NME boundary; no work runs from an ELF constructor.  Non-DIO
 * processes (helpers that inherit LD_PRELOAD) are passive and write nothing.
 */
#include "trial_gate.h"

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#ifndef F7_OFF_PERSIST
#define F7_OFF_PERSIST "/mnt/app/root/mu1320-rgi-f7-v2/off-native"
#endif
#ifndef F7_OFF_RUNTIME
#define F7_OFF_RUNTIME "/tmp/mu1320-f7-native-off"
#endif
#ifndef F7_LAST
#define F7_LAST "/tmp/mu1320-f7-gate.last"
#endif
#ifndef F7_STRIKES
#define F7_STRIKES "/tmp/mu1320-f7-gate.strikes"
#endif
#ifndef F7_RECEIPT_PREFIX
#define F7_RECEIPT_PREFIX "/tmp/mu1320-f7-gate-"
#endif
#ifndef F7_SHORT_MS
#define F7_SHORT_MS 15000L
#endif
#ifndef F7_MAX_STRIKES
#define F7_MAX_STRIKES 3
#endif

enum { GATE_UNDECIDED = 0, GATE_PASSIVE = 1, GATE_ACTIVE = 2 };
static pthread_once_t g_gate_once = PTHREAD_ONCE_INIT;
static volatile int g_gate_state = GATE_UNDECIDED;
static volatile int g_gate_owner_pid;

static int current_process_is_dio(void) {
#ifdef TRIAL_ASSUME_DIO
    return TRIAL_ASSUME_DIO;
#else
    char buf[256];
    int fd = open("/proc/self/cmdline", O_RDONLY), n;
    if (fd < 0) return 0;
    n = (int)read(fd, buf, sizeof(buf) - 1);
    (void)close(fd);
    if (n <= 0) return 0;
    buf[n] = 0;
    return strstr(buf, "dio_manager") != NULL;
#endif
}

static int present(const char *path) {
    struct stat st;
    return lstat(path, &st) == 0;
}

static long now_ms(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) return -1L;
    return (long)ts.tv_sec * 1000L + (long)(ts.tv_nsec / 1000000L);
}

/* Read up to two decimal integers from a small file; returns how many. */
static int read_numbers(const char *path, long *a, long *b) {
    char buf[64];
    char *end;
    int fd = open(path, O_RDONLY), n, got = 0;
    if (fd < 0) return 0;
    n = (int)read(fd, buf, sizeof(buf) - 1);
    (void)close(fd);
    if (n <= 0) return 0;
    buf[n] = 0;
    *a = strtol(buf, &end, 10);
    if (end == buf) return 0;
    got = 1;
    if (b) {
        char *p = end;
        *b = strtol(p, &end, 10);
        if (end != p) got = 2;
    }
    return got;
}

/* Write "text" to path in place (no rename on /dev/shmem, see above). */
static void write_small(const char *path, const char *text) {
    size_t len = strlen(text);
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) return;
    (void)write(fd, text, len);
    (void)close(fd);
}

static int process_alive(long pid) {
    if (pid <= 0) return 0;
    if (kill((pid_t)pid, 0) == 0) return 1;
    return errno == EPERM;
}

static void write_receipt(const char *mode, const char *reason, int pid, int ppid,
                          long strikes, long prev, int prev_alive) {
    char path[192], record[192];
    int fd, len;
    len = snprintf(path, sizeof(path), "%s%d", F7_RECEIPT_PREFIX, pid);
    if (len <= 0 || (size_t)len >= sizeof(path)) return;
    len = snprintf(record, sizeof(record),
                   "MU1320_F7_GATE mode=%s reason=%s pid=%d ppid=%d strikes=%ld prev=%ld prev_alive=%d\n",
                   mode, reason, pid, ppid, strikes, prev, prev_alive);
    if (len <= 0 || (size_t)len >= sizeof(record)) return;
    fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd >= 0) { (void)write(fd, record, (size_t)len); (void)close(fd); }
}

static void decide_once(void) {
    int saved = errno;
    int pid = (int)getpid(), ppid = (int)getppid();
    long prev = 0, prev_start = 0, strikes = 0, now;
    int prev_alive = 0;
    char text[64];

    g_gate_owner_pid = pid;
    g_gate_state = GATE_PASSIVE;
    if (!current_process_is_dio()) { errno = saved; return; }
    if (present(F7_OFF_PERSIST)) {
        write_receipt("PASSIVE", "OFF_PERSIST", pid, ppid, 0, 0, 0);
        errno = saved; return;
    }
    if (present(F7_OFF_RUNTIME)) {
        write_receipt("PASSIVE", "OFF_RUNTIME", pid, ppid, 0, 0, 0);
        errno = saved; return;
    }
    now = now_ms();
    if (read_numbers(F7_STRIKES, &strikes, NULL) != 1 || strikes < 0) strikes = 0;
    if (strikes >= F7_MAX_STRIKES) {
        write_receipt("PASSIVE", "CRASH_GUARD", pid, ppid, strikes, 0, 0);
        errno = saved; return;
    }
    if (read_numbers(F7_LAST, &prev, &prev_start) == 2 && prev != pid) {
        prev_alive = process_alive(prev);
        if (!prev_alive && now >= 0 && prev_start >= 0 && now - prev_start < F7_SHORT_MS) strikes++;
        else strikes = 0;
    }
    (void)snprintf(text, sizeof(text), "%ld\n", strikes);
    write_small(F7_STRIKES, text);
    if (strikes >= F7_MAX_STRIKES) {
        write_receipt("PASSIVE", "CRASH_GUARD", pid, ppid, strikes, prev, prev_alive);
        errno = saved; return;
    }
    (void)snprintf(text, sizeof(text), "%d %ld\n", pid, now);
    write_small(F7_LAST, text);
    g_gate_state = GATE_ACTIVE;
    write_receipt("ACTIVE", prev_alive ? "PREV_ALIVE" : "ON", pid, ppid, strikes, prev, prev_alive);
    errno = saved;
}

int trial_gate_active(void) {
    (void)pthread_once(&g_gate_once, decide_once);
    return g_gate_state == GATE_ACTIVE && g_gate_owner_pid == (int)getpid();
}

int trial_gate_was_active(void) {
    return g_gate_state == GATE_ACTIVE && g_gate_owner_pid == (int)getpid();
}

int trial_gate_is_current(void) {
    long pid = 0;
    int saved = errno, current;
    if (read_numbers(F7_LAST, &pid, NULL) < 1) { errno = saved; return 1; }
    current = pid == (long)getpid();
    errno = saved;
    return current;
}
