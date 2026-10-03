#!/bin/sh
# F7 step marker (the F6 step marker with F7 labels, F7 switches and the
# keeper log). Read-only on the vehicle: it only appends one block to
# <SD folder>/out/f7-marks.txt, so each step can be placed between the F5 log
# lines (i=/t= of the last line of each log at that moment).
# The F5 logs, the touchpad log and the F7 keeper log it reads hold numbers and
# states only; the hook log (road names) is not read.
set -eu
for var in LD_PRELOAD LD_DEBUG DL_DEBUG LD_DEBUG_OUTPUT; do unset "$var" || :; done
PATH=/proc/boot:/bin:/usr/bin:/sbin:/usr/sbin:/mnt/app/armle/bin:/mnt/app/armle/usr/bin
export PATH
fail() { echo "STOP: $*" >&2; exit 1; }
[ "$#" -ge 1 ] || { echo 'usage: f7_mark.sh <step> [note words]'; exit 2; }
step=$1; shift
case "$step" in ''|*[!A-Za-z0-9._-]*) echo 'STOP: step must be letters, digits, . _ -'; exit 2 ;; esac
[ "${#step}" -le 16 ] || { echo 'STOP: step longer than 16'; exit 2; }
# Characters spelled out: the vehicle tr takes 'A-Z' literally (no ranges).
note=$(printf '%s' "$*" | tr -c 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ._:+/=-' '_') || fail 'note filter'
case "$0" in */*) stage_dir=${0%/*} ;; *) exit 2 ;; esac
stage_dir=$(CDPATH= cd "$stage_dir" && pwd -P)
case "$stage_dir" in /fs/sda0/*) sd=/fs/sda0 ;; /fs/sdb0/*) sd=/fs/sdb0 ;; *) echo 'STOP: use SD /fs/sda0 or /fs/sdb0'; exit 2 ;; esac
uid=$(id -u); set -f; (set -- $uid; [ "$#" = 1 ] && [ "$1" = 0 ]) || fail 'effective UID must be 0'
case "$(uname -a)" in QNX\ *\ 6.5.0\ *\ armle) ;; *) fail 'wrong platform' ;; esac
output=$(cksum "$stage_dir/mount_state"); set -- $output; [ "${1:-}" = '2952412687' ] && [ "${2:-}" = '7302' ] || fail 'mount helper checksum'
state() { (LD_LIBRARY_PATH=/proc/boot:/lib exec "$stage_dir/mount_state" "$sd"); }
last_line() {
    # tail when present; otherwise keep the last line with a read loop.
    if command -v tail >/dev/null 2>&1; then tail -1 "$1" 2>/dev/null || :; return 0; fi
    line=''; while IFS= read -r l || [ -n "$l" ]; do line=$l; done < "$1"; printf '%s\n' "$line"
}
block() {
    echo "F7MARK step=$step note=$note"
    echo "DATE: $(date 2>&1 || :)"
    epoch=$(date +%s 2>/dev/null) || epoch=NA
    case "$epoch" in ''|*[!0-9]*) epoch=NA ;; esac
    echo "EPOCH: $epoch"
    for f in /tmp/mu1320-f5-state.log /tmp/mu1320-f5-bap.log /tmp/mu1320-f5-render.log /tmp/mu1320-f6-touchpad.log /tmp/mu1320-f7-keeper.log; do
        if [ -f "$f" ] && [ ! -L "$f" ]; then echo "LAST ${f##*/}: $(last_line "$f")"; else echo "LAST ${f##*/}: ABSENT"; fi
    done
    mode=ABSENT; if [ -f /tmp/mu1320-f5-ctx-mode ]; then read -r mode < /tmp/mu1320-f5-ctx-mode || mode=EMPTY; fi
    echo "CTX_MODE_FILE: $mode"
    for f in /tmp/mu1320-f5-bap-off /tmp/mu1320-f5-render-off /tmp/mu1320-f5-calib /tmp/mu1320-f6-touchpad-off /tmp/mu1320-f7-native-off /tmp/mu1320-f7-render-hold; do
        if [ -e "$f" ] || [ -L "$f" ]; then echo "SWITCH ${f##*/}: PRESENT"; else echo "SWITCH ${f##*/}: ABSENT"; fi
    done
    strikes=ABSENT; if [ -f /tmp/mu1320-f7-gate.strikes ]; then read -r strikes < /tmp/mu1320-f7-gate.strikes || strikes=EMPTY; fi
    echo "GATE_STRIKES: $strikes"
    echo F7MARK_END
}
initial=$(state) || fail 'SD mount query'; case "$initial" in ro|rw) ;; *) fail 'unknown SD mount state' ;; esac
restore=0; written=0
cleanup() {
    rc=$?; trap - 0 1 2 15; set +e
    if [ "$restore" = 1 ]; then mount -ur "$sd" || rc=1; fi
    final=$(state); query=$?
    if [ "$query" != 0 ] || [ "$final" != "$initial" ]; then echo "STOP: SD state not restored to $initial; do not remove card" >&2; rc=1; fi
    if [ "$rc" = 0 ] && [ "$written" = 1 ]; then echo "F7_MARK_SAVED step=$step"; fi
    exit "$rc"
}
trap cleanup 0; trap 'exit 129' 1; trap 'exit 130' 2; trap 'exit 143' 15
text=$(block)
if [ "$initial" = ro ]; then restore=1; mount -uw "$sd" || fail 'SD remount rw'; fi
[ "$(state)" = rw ] || fail 'SD not writable'
umask 077; out="$stage_dir/out"; [ ! -L "$out" ] || fail 'unsafe out directory'; [ -d "$out" ] || mkdir "$out"
marks="$out/f7-marks.txt"; [ ! -L "$marks" ] || fail 'unsafe marks file'
printf '%s\n' "$text" >> "$marks" || fail 'marks append'
sync || fail 'sync'
written=1
printf '%s\n' "$text"
