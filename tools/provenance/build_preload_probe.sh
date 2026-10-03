#!/bin/sh
# Workstation only. Uses the already available immutable toolchain offline.
set -eu
base=$(CDPATH= cd "$(dirname "$0")/.." && pwd -P)
docker run --rm --network=none --platform=linux/amd64 \
  -v "$base/preload-probe:/src" \
  sha256:e52565b1f62dab0f93f12532d52611b94e90b89e4da04f972b11f54eaeb6a05d \
  /bin/sh -ec '
CC=arm-unknown-nto-qnx6.5.0eabi-gcc
"$CC" -O2 -std=gnu99 -Wall -Wextra -Werror -fPIC -fvisibility=hidden -shared /src/preload_probe.c -Wl,-soname,libmu1320_preload_probe.so -Wl,--version-script=/src/exports.map -Wl,-z,defs -lc -o /src/libmu1320_preload_probe.so
"$CC" -O2 -std=gnu99 -Wall -Wextra -Werror /src/loader_check.c -o /src/loader_check
"$CC" -O2 -std=gnu99 -Wall -Wextra -Werror /src/mount_state.c -o /src/mount_state
'
