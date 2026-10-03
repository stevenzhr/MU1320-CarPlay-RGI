/* Independent loader test: never call an interposed Cinemo entry point. */
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <dlfcn.h>
#if !defined(__QNXNTO__) || !defined(__arm__)
#error QNX ARM build required
#endif
int main(int argc, char **argv) {
    static const char *names[] = {
        "CinemoCreateIAP", "_ZN14NmeIAP2Message6DecodeEPKhi",
        "_ZNK14NmeIAP2Message6EncodeER8NmeArrayIhE",
        "_ZN12NmeTransport4SendEPKhjPj", "_ZN12NmeTransport4RecvER8NmeArrayIhE"
    };
    sigset_t signals;
    void *handle;
    size_t i;
    if (argc != 2 || argv[1][0] != '/') { puts("FAIL: absolute library path required"); return 2; }
    if (sigemptyset(&signals) || sigaddset(&signals, SIGALRM) ||
        signal(SIGALRM, SIG_DFL) == SIG_ERR || sigprocmask(SIG_UNBLOCK, &signals, NULL)) return 3;
    alarm(15);
    puts("STAGE1_LOADER_BEGIN: standalone process; no Cinemo calls");
    fflush(stdout);
    handle = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!handle) { printf("FAIL: dlopen: %s\n", dlerror()); return 4; }
    puts("PASS: dlopen RTLD_NOW/LOCAL");
    for (i = 0; i < sizeof(names)/sizeof(names[0]); ++i) {
        const char *error;
        void *symbol;
        dlerror();
        symbol = dlsym(handle, names[i]);
        error = dlerror();
        if (error || !symbol) {
            printf("FAIL: dlsym %s: %s\n", names[i], error ? error : "NULL symbol");
            dlclose(handle);
            return 5;
        }
        printf("PASS: symbol %s (not called)\n", names[i]);
    }
    if (dlclose(handle)) { printf("FAIL: dlclose: %s\n", dlerror()); return 6; }
    alarm(0);
    puts("STAGE1_LOADER_PASSED: loading/unloading only; interposition and RGI untested");
    return 0;
}
