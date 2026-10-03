#!/bin/sh
# MU1320 Toolbox inventory. Run only through toolbox_inventory.sh (SD wrapper).
# Read-only on the unit: lists and checksums the green-menu tree (engdefs), the Toolbox SSH
# install (inetd/pf entries, /mnt/app/root), the SWDL FileCopyInfo records and the SD roots,
# and copies the Toolbox pages/scripts plus the small config files it edits to $stage_dir/out
# as a rollback reference.  The sshd tree and ~/.ssh are listed only, never copied (host keys).
# No remount of /mnt, no delete/move/chmod, no kill, no reboot.
set -u
for var in LD_PRELOAD LD_DEBUG DL_DEBUG LD_DEBUG_OUTPUT; do unset "$var" || :; done
PATH=/proc/boot:/bin:/usr/bin:/sbin:/usr/sbin:/mnt/app/armle/bin:/mnt/app/armle/usr/bin
export PATH
case "$*: $#" in 'run: 1') ;; *) echo 'usage: control.sh run'; exit 2 ;; esac
case "$0" in */*) stage_dir=${0%/*} ;; *) exit 2 ;; esac
stage_dir=$(CDPATH= cd "$stage_dir" && pwd -P)
fail() { echo "STOP: $*"; exit 1; }

ENGDEFS=/mnt/app/eso/hmi/engdefs
SSHDIR=/mnt/app/eso/hmi/engdefs/scripts/ssh
ROOT=/mnt/app/root
SYSETC=/mnt/system/etc
FCI=/net/rcc/mnt/efs-persist/SWDL/FileCopyInfo
TRAIN=/net/rcc/dev/shmem/version.txt
MAX_DEPTH=12
COPY_LIMIT=67108864
FILE_LIMIT=16777216

for utility in id uname ls cksum cat mkdir grep; do
    command -v "$utility" >/dev/null 2>&1 || fail "missing $utility"
done
out="$stage_dir/out"
if [ ! -d "$out" ] || [ -L "$out" ]; then fail 'out directory'; fi
run="$out/tbinv-$$"
if [ -e "$run" ] || [ -L "$run" ]; then fail 'run directory collision'; fi
mkdir "$run" "$run/copy" || fail 'cannot create run directory on SD'
man="$run/manifest.txt"; cands="$run/copy-candidates.txt"
: > "$man" || fail 'manifest'
: > "$cands" || fail 'candidate list'

echo "TOOLBOX_INVENTORY_V1 run=$run"
uname -a
echo "UID=$(id -u)"

# walk PATH DEPTH COPY: one DIR/FILE/LINK/OTHER/MISSING record plus ls -ld per entry;
# symlinks are recorded, never followed; nothing under the sshd tree or ~/.ssh is copied.
walk() (
    p=$1; depth=$2; want=$3
    case "$p" in "$SSHDIR"|"$SSHDIR"/*|"$ROOT"/.ssh|"$ROOT"/.ssh/*) want=0 ;; esac
    if [ -L "$p" ]; then echo "LINK $p"; ls -ld "$p"; return 0; fi
    if [ ! -e "$p" ]; then echo "MISSING $p"; return 0; fi
    if [ -d "$p" ]; then
        echo "DIR $p"; ls -ld "$p"
        if [ "$depth" -ge "$MAX_DEPTH" ]; then echo "DEPTH_LIMIT $p"; return 0; fi
        for c in "$p"/* "$p"/.[!.]* "$p"/..?*; do
            if [ -e "$c" ] || [ -L "$c" ]; then walk "$c" $((depth + 1)) "$want"; fi
        done
        return 0
    fi
    if [ -f "$p" ]; then
        ls -ld "$p"
        if line=$(cksum "$p" 2>&1); then :; else echo "CKSUM_FAIL $p $line"; return 0; fi
        set -f; set -- $line; set +f
        echo "FILE $1 $2 $p"
        if [ "$want" = 1 ]; then echo "$2 $p" >> "$cands"; fi
        return 0
    fi
    echo "OTHER $p"; ls -ld "$p"
)

want_copy() {
    if [ -f "$1" ] && [ ! -L "$1" ]; then
        if line=$(cksum "$1" 2>/dev/null); then
            set -f; set -- $line; set +f
            echo "$2 $3" >> "$cands"
        fi
    fi
}

{
    echo "== WALK $ENGDEFS =="
    walk "$ENGDEFS" 0 1
    echo "== WALK $FCI =="
    walk "$FCI" 0 1
    echo "== WALK $ROOT/.ssh =="
    walk "$ROOT/.ssh" 0 0
    echo "== LS $ROOT =="
    ls -la "$ROOT"
    echo "== LS $SYSETC =="
    ls -la "$SYSETC"
} > "$man" 2>&1
lines=0
while read -r line; do lines=$((lines + 1)); done < "$man"
echo "MANIFEST_LINES=$lines"

want_copy "$TRAIN"
want_copy "$ROOT/.profile"
want_copy "$ROOT/scp"
for f in "$SYSETC"/inetd.conf "$SYSETC"/inetd.conf.bu "$SYSETC"/pf*.conf "$SYSETC"/pf*.conf.bu; do
    want_copy "$f"
done

echo '== Toolbox pages =='
esd=0; mqb=0
for f in "$ENGDEFS"/*.esd; do
    if [ -f "$f" ]; then :; else continue; fi
    esd=$((esd + 1))
    case "${f##*/}" in mqb-*) mqb=$((mqb + 1)); echo "PAGE ${f##*/}" ;; esac
done
echo "ESD_TOTAL=$esd ESD_MQB=$mqb"
echo '-- mqb-main.esd header'
grep -n -i version "$ENGDEFS/mqb-main.esd" || echo 'no version line'
for d in "$ENGDEFS/scripts" "$ENGDEFS/scripts/mqb" "$SSHDIR"; do
    if [ -d "$d" ]; then n=0; for c in "$d"/*; do if [ -e "$c" ]; then n=$((n + 1)); fi; done; echo "DIR_PRESENT $d entries=$n"
    else echo "DIR_ABSENT $d"; fi
done

echo '== Toolbox SSH =='
grep -n -i ssh "$SYSETC/inetd.conf" || echo 'no ssh line in inetd.conf'
for f in "$SYSETC"/pf*.conf; do
    if [ -f "$f" ]; then :; else continue; fi
    echo "-- $f"
    grep -n 'port 22' "$f" || echo 'no port 22 rule'
done
for f in inetd.conf.bu .profile scp .ssh .ssh/authorized_keys; do
    case "$f" in inetd.conf.bu) p="$SYSETC/$f" ;; *) p="$ROOT/$f" ;; esac
    if [ -e "$p" ]; then echo "PRESENT $p"; else echo "ABSENT $p"; fi
done
pidin ar > "$run/pidin_ar.txt" 2>&1 || echo 'pidin failed'
grep -i sshd "$run/pidin_ar.txt" || echo 'no sshd process'
grep -i inetd "$run/pidin_ar.txt" || echo 'no inetd process'

echo '== SWDL FileCopyInfo =='
if [ -d "$FCI" ]; then
    for f in "$FCI"/*; do
        if [ -f "$f" ]; then echo "INFO ${f##*/}"; fi
    done
else
    echo "FCI_ABSENT $FCI"
fi

echo '== Train =='
cat "$TRAIN" 2>&1 || echo 'train file unreadable'

echo '== SD roots =='
for sd in /fs/sda0 /fs/sdb0; do
    if [ -d "$sd" ]; then echo "-- $sd"; ls -la "$sd"; else echo "SD_ABSENT $sd"; fi
done

total=0; count=0
while read -r size path; do total=$((total + size)); count=$((count + 1)); done < "$cands"
echo "COPY_CANDIDATES=$count BYTES=$total"
copied=0; bad=0; skipped=0
if [ "$total" -gt "$COPY_LIMIT" ]; then
    echo "COPY_SKIPPED_TOTAL_OVER_LIMIT limit=$COPY_LIMIT"
    skipped=$count
else
    while read -r size path; do
        if [ "$size" -gt "$FILE_LIMIT" ]; then echo "COPY_SKIP_LARGE $size $path"; skipped=$((skipped + 1)); continue; fi
        dst="$run/copy$path"
        case "$dst" in "$run/copy/"*) ;; *) echo "COPY_SKIP_PATH $path"; skipped=$((skipped + 1)); continue ;; esac
        if mkdir -p "${dst%/*}" && cat "$path" > "$dst"; then
            a=$(cksum < "$path"); b=$(cksum < "$dst")
            if [ "$a" = "$b" ]; then copied=$((copied + 1)); else echo "COPY_MISMATCH $path"; bad=$((bad + 1)); fi
        else
            echo "COPY_FAIL $path"; bad=$((bad + 1))
        fi
    done < "$cands"
fi
echo "COPIED=$copied COPY_ERRORS=$bad COPY_SKIPPED=$skipped"

mount > "$run/mount.txt" 2>&1 || echo 'mount listing failed'
df -k "$ENGDEFS" "$stage_dir" > "$run/df.txt" 2>&1 || echo 'df failed (informational)'

sync || :
if [ "$bad" != 0 ]; then fail "$bad copy errors; inventory incomplete"; fi
echo 'TOOLBOX_INVENTORY_COMPLETE'
