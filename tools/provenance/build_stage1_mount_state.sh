#!/bin/sh
set -eu
BASE=$(CDPATH= cd "$(dirname "$0")/.." && pwd -P)
[ ! -e "$BASE/stage1/mount_state" ] || { echo 'Refusing to overwrite mount_state'; exit 2; }
IMAGE=sha256:e52565b1f62dab0f93f12532d52611b94e90b89e4da04f972b11f54eaeb6a05d
docker run --rm --network=none --platform=linux/amd64 -v "$BASE/stage1:/src" "$IMAGE" \
 arm-unknown-nto-qnx6.5.0eabi-gcc -O2 -std=gnu99 -Wall -Wextra -Werror /src/mount_state.c -o /src/mount_state
# Extend provenance for the subsequent package-stage1 build/hash check.
python3 - "$BASE" <<'PY'
import hashlib,json,sys
from pathlib import Path
b=Path(sys.argv[1]);p=b/'reports/stage1-build.json'
def sha(f):return hashlib.sha256(f.read_bytes()).hexdigest()
d=json.loads(p.read_text())
d['artifacts']['mount_state']={'sha256':sha(b/'stage1/mount_state'),'size':(b/'stage1/mount_state').stat().st_size}
d['mount_state_build']={'script':'scripts/build_stage1_mount_state.sh','script_sha256':sha(b/'scripts/build_stage1_mount_state.sh'),'source_sha256':sha(b/'stage1/mount_state.c'),'image_id':d['image_id'],'exit_code':0}
p.write_text(json.dumps(d,indent=2)+'\n')
PY
