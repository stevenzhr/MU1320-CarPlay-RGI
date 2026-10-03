/*
 * f4_unbuf - LD_PRELOAD shim for the stock dmdt only.
 *
 * dmdt prints its reply with stdio and leaves via _Exit(0), which does not
 * flush stdio.  On a terminal stdout is line-buffered, so it looks fine; when
 * redirected to a file only whole buffer blocks reach the file (gs/gd came
 * back empty and gc cut at exactly 10240 bytes on the car).  Making stdout
 * and stderr unbuffered before main() writes every printf immediately.
 * Constructors in LD_PRELOADed libraries run on this unit (preload-probe v1.1).
 */
#include <stdio.h>

__attribute__((constructor))
static void f4_unbuf_init(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);
}

__attribute__((visibility("default")))
const char *mu1320_f4_unbuf_identity(void) {
    return "MU1320_F4_UNBUF_V1";
}
