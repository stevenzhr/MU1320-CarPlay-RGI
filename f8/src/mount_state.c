/* Exact whitelisted mount points; never infer state from mount text. */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <sys/statvfs.h>
#if !defined(__QNXNTO__) || !defined(__arm__)
#error QNX ARM build required
#endif
int main(int argc, char **argv) {
    struct statvfs state; int sd;
    if (argc != 2) return 2;
    sd = !strcmp(argv[1], "/fs/sda0") || !strcmp(argv[1], "/fs/sdb0");
    if (!sd && strcmp(argv[1], "/mnt/app") && strcmp(argv[1], "/mnt/system")) return 2;
    memset(&state, 0, sizeof(state));
    if (statvfs(argv[1], &state)) { fprintf(stderr, "FAIL statvfs: %s\n", strerror(errno)); return 3; }
    /* QNX 6.5 reports FAT SD cards as "dos (fat32)" (vehicle mount output). */
    if (strcmp(state.f_basetype, sd ? "dos (fat32)" : "qnx6")) {
        fprintf(stderr, "FAIL unexpected filesystem: %s\n", state.f_basetype); return 4;
    }
    puts((state.f_flag & ST_RDONLY) ? "ro" : "rw");
    return 0;
}
