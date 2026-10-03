/* MU1320 F7 renderer launcher.
 *
 *   f7_spawn PIDFILE LOGFILE DIR PROGRAM [ARG...]
 *
 * Starts PROGRAM detached from its caller and returns at once.  F7 starts the
 * renderer from the HMI JVM (Runtime.exec -> f7_render.sh -> f7_spawn), so the
 * child must not inherit what the JVM hands its children:
 *   - signal dispositions: JVM children inherit SIGTERM ignored (F5 v3 car
 *     run); every signal is reset to default, SIGHUP ignored, mask cleared;
 *   - descriptors: everything above stderr is closed (the JVM's sockets,
 *     including the 19800/19810 listeners, must not leak into the renderer);
 *   - session: setsid(), so a signal to the HMI process group does not reach it;
 *   - environment: LD_PRELOAD and loader debug variables removed, the F4
 *     library path and GRAPHICS_ROOT set.
 * stdin is /dev/null; stdout and stderr append to LOGFILE.  The child pid is
 * written to PIDFILE (mode 0600) before the launcher exits 0.
 * Exit codes: 2 usage, 3 fork, 4 pid file.  A child that cannot exec exits 127.
 */
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

#ifndef F7_LIBRARY_PATH
#define F7_LIBRARY_PATH "/proc/boot:/lib"
#endif
#ifndef F7_GRAPHICS_ROOT
#define F7_GRAPHICS_ROOT "/proc/boot"
#endif
#ifndef F7_MAX_SIGNAL
#define F7_MAX_SIGNAL 64
#endif

static void child(const char *log, const char *dir, char **argv) {
    struct sigaction sa;
    sigset_t none;
    long max, fd;
    int in, out, sig;

    (void)setsid();
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = SIG_DFL;
    (void)sigemptyset(&sa.sa_mask);
    for (sig = 1; sig < F7_MAX_SIGNAL; sig++) {
        if (sig == SIGKILL || sig == SIGSTOP) continue;
        (void)sigaction(sig, &sa, NULL);
    }
    sa.sa_handler = SIG_IGN;
    (void)sigaction(SIGHUP, &sa, NULL);
    (void)sigemptyset(&none);
    (void)sigprocmask(SIG_SETMASK, &none, NULL);

    in = open("/dev/null", O_RDONLY);
    out = open(log, O_WRONLY | O_CREAT | O_APPEND, 0600);
    if (in < 0 || out < 0) _exit(126);
    if (dup2(in, 0) < 0 || dup2(out, 1) < 0 || dup2(out, 2) < 0) _exit(126);
    max = sysconf(_SC_OPEN_MAX);
    if (max < 64 || max > 4096) max = 4096;
    for (fd = 3; fd < max; fd++) (void)close((int)fd);
    if (chdir(dir) != 0) _exit(126);

    (void)unsetenv("LD_PRELOAD");
    (void)unsetenv("LD_DEBUG");
    (void)unsetenv("DL_DEBUG");
    (void)unsetenv("LD_DEBUG_OUTPUT");
    (void)setenv("LD_LIBRARY_PATH", F7_LIBRARY_PATH, 1);
    (void)setenv("GRAPHICS_ROOT", F7_GRAPHICS_ROOT, 1);
    execv(argv[0], argv);
    _exit(127);
}

int main(int argc, char **argv) {
    char text[32];
    pid_t pid;
    int fd, len;

    if (argc < 5) {
        fprintf(stderr, "usage: f7_spawn PIDFILE LOGFILE DIR PROGRAM [ARG...]\n");
        return 2;
    }
    pid = fork();
    if (pid < 0) return 3;
    if (pid == 0) child(argv[2], argv[3], argv + 4);
    len = snprintf(text, sizeof(text), "%d\n", (int)pid);
    (void)unlink(argv[1]);
    fd = open(argv[1], O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd < 0 || len <= 0 || write(fd, text, (size_t)len) != (ssize_t)len) {
        if (fd >= 0) (void)close(fd);
        (void)kill(pid, SIGKILL);
        return 4;
    }
    (void)close(fd);
    return 0;
}
