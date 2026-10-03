#!/bin/sh
# MU1320 /mnt/app/root leftover inventory. Run only through root_inventory.sh (SD wrapper).
# Read-only on the unit: lists and checksums /mnt/app/root, the HMI jars directory and the
# production config directory, and copies only trial leftovers (mu1320-*) plus the live
# originals to $stage_dir/out.  No remount of /mnt, no delete/move/chmod, no kill, no reboot.
set -u
for var in LD_PRELOAD LD_DEBUG DL_DEBUG LD_DEBUG_OUTPUT; do unset "$var" || :; done
PATH=/proc/boot:/bin:/usr/bin:/sbin:/usr/sbin:/mnt/app/armle/bin:/mnt/app/armle/usr/bin
export PATH
case "$*: $#" in 'run: 1') ;; *) echo 'usage: control.sh run'; exit 2 ;; esac
case "$0" in */*) stage_dir=${0%/*} ;; *) exit 2 ;; esac
stage_dir=$(CDPATH= cd "$stage_dir" && pwd -P)
fail() { echo "STOP: $*"; exit 1; }

ROOT=/mnt/app/root
JARS=/mnt/app/eso/hmi/lsd/jars
PROD=/mnt/system/etc/eso/production
ETCPROD=/etc/eso/production
MAX_DEPTH=12
COPY_LIMIT=268435456
FILE_LIMIT=33554432

for utility in id uname ls cksum cat mkdir grep; do
    command -v "$utility" >/dev/null 2>&1 || fail "missing $utility"
done
out="$stage_dir/out"
if [ ! -d "$out" ] || [ -L "$out" ]; then fail 'out directory'; fi
run="$out/inv-$$"
if [ -e "$run" ] || [ -L "$run" ]; then fail 'run directory collision'; fi
mkdir "$run" "$run/copy" || fail 'cannot create run directory on SD'
man="$run/manifest.txt"; cands="$run/copy-candidates.txt"
: > "$man" || fail 'manifest'
: > "$cands" || fail 'candidate list'

echo "ROOT_INVENTORY_V1 run=$run"
uname -a
echo "UID=$(id -u)"

# walk PATH DEPTH COPY: one DIR/FILE/LINK/OTHER record plus ls -ld per entry; symlinks are
# recorded, never followed.  Subshell body keeps the recursion's variables local.
walk() (
    p=$1; depth=$2; want=$3
    if [ -L "$p" ]; then echo "LINK $p"; ls -ld "$p"; return 0; fi
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

echo '== /mnt/app/root top level =='
top=0; ours=0
for e in "$ROOT"/* "$ROOT"/.[!.]* "$ROOT"/..?*; do
    if [ -e "$e" ] || [ -L "$e" ]; then :; else continue; fi
    top=$((top + 1)); name=${e##*/}
    case "$name" in
        mu1320*) kind=TRIAL; ours=$((ours + 1)) ;;
        *) kind=OTHER ;;
    esac
    if [ -L "$e" ]; then type=link; elif [ -d "$e" ]; then type=dir; else type=file; fi
    echo "TOP $kind $type $name"
done
echo "TOP_COUNT=$top TRIAL_COUNT=$ours"

{
    echo "== WALK $ROOT =="
    for e in "$ROOT"/* "$ROOT"/.[!.]* "$ROOT"/..?*; do
        if [ -e "$e" ] || [ -L "$e" ]; then :; else continue; fi
        case "${e##*/}" in mu1320*) walk "$e" 1 1 ;; *) walk "$e" 1 0 ;; esac
    done
    echo "== WALK $JARS =="
    walk "$JARS" 0 0
    echo "== WALK $PROD =="
    walk "$PROD" 0 0
    echo "== CKSUM $ETCPROD =="
    ls -ld "$ETCPROD"
    cksum "$ETCPROD/smartphone_integrator.json" "$ETCPROD/dio_manager.json"
} > "$man" 2>&1
echo "MANIFEST_LINES=$(grep -c '' "$man")"

# Live originals and anything in the HMI jars / production dirs that a trial may have left.
want_copy "$JARS/NavActiveIgnore.jar"
want_copy "$PROD/smartphone_integrator.json"
want_copy "$PROD/dio_manager.json"
for f in "$JARS"/* "$JARS"/.[!.]*; do
    case "${f##*/}" in
        NavActiveIgnore.jar) ;;
        *[Cc][Aa][Rr][Pp][Ll][Aa][Yy]*|*[Mm][Uu]1320*|*.DISABLED|*.bak|*.orig|*.old|.*) want_copy "$f" ;;
    esac
done
for f in "$PROD"/* "$PROD"/.[!.]*; do
    case "${f##*/}" in
        smartphone_integrator.json|dio_manager.json) ;;
        *[Mm][Uu]1320*|*.DISABLED|*.bak|*.orig|*.old|.*) want_copy "$f" ;;
    esac
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

echo '== Live config references to trial files =='
for f in "$PROD/smartphone_integrator.json" "$PROD/dio_manager.json"; do
    echo "-- $f"
    grep -n -i mu1320 "$f" || echo 'no mu1320'
    grep -n LD_PRELOAD "$f" || echo 'no LD_PRELOAD'
done

echo '== Processes referencing mu1320 (this inventory itself runs from SD) =='
pidin ar > "$run/pidin_ar.txt" 2>&1 || echo 'pidin failed'
grep -i mu1320 "$run/pidin_ar.txt" || echo 'none'
mount > "$run/mount.txt" 2>&1 || echo 'mount listing failed'
df -k "$ROOT" "$stage_dir" > "$run/df.txt" 2>&1 || echo 'df failed (informational)'

sync || :
if [ "$bad" != 0 ]; then fail "$bad copy errors; inventory incomplete"; fi
echo 'ROOT_INVENTORY_COMPLETE'
