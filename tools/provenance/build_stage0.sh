#!/bin/sh
# Workstation only. Build just the standalone check in an isolated, pinned container.
set -eu
BASE=$(CDPATH= cd "$(dirname "$0")/.." && pwd -P)
IMAGE=${QNX_IMAGE:-sha256:e52565b1f62dab0f93f12532d52611b94e90b89e4da04f972b11f54eaeb6a05d}
if [ -e "$BASE/stage0/native_smoke" ]; then
    echo 'Refusing to overwrite existing stage0/native_smoke; preserve the prior build first.' >&2
    exit 2
fi
IMAGE=$(docker image inspect "$IMAGE" --format '{{.Id}}')
VERSION=$(docker run --rm --network=none --platform=linux/amd64 "$IMAGE" \
    arm-unknown-nto-qnx6.5.0eabi-gcc -dumpversion)
[ "$VERSION" = 4.9.4 ] || { echo 'Expected GCC 4.9.4' >&2; exit 2; }
docker run --rm --network=none --platform=linux/amd64 \
    -v "$BASE/stage0:/src" "$IMAGE" \
    arm-unknown-nto-qnx6.5.0eabi-gcc -O2 -std=gnu99 -Wall -Wextra -Werror \
    /src/native_smoke.c -o /src/native_smoke -lsocket
