#!/bin/sh
# SD wrapper. control.sh rollback remains the recovery entry when SD logging fails.
set -eu
for var in LD_PRELOAD LD_DEBUG DL_DEBUG LD_DEBUG_OUTPUT; do unset "$var" || :; done
PATH=/proc/boot:/bin:/usr/bin:/sbin:/usr/sbin:/mnt/app/armle/bin:/mnt/app/armle/usr/bin
export PATH
case "$*: $#" in
  'status: 1'|'install: 1'|'stop: 1'|'rollback: 1'|'purge: 1'|'collect live: 2'|'collect restored: 2'|'collect snapshot: 2') ;;
  'off native: 2'|'off render: 2'|'off bap: 2'|'off touchpad: 2'|'on native: 2'|'on render: 2'|'on bap: 2'|'on touchpad: 2') ;;
  'off monitor: 2'|'on monitor: 2') ;;
  *) echo 'usage: f7.sh status|install|stop|rollback|purge|collect live|restored|snapshot|off|on native|render|bap|touchpad|monitor'; exit 2 ;;
esac
requested_action=$1; requested_phase=${2:-}
case "$0" in */*) stage_dir=${0%/*} ;; *) exit 2 ;; esac
stage_dir=$(CDPATH= cd "$stage_dir" && pwd -P)
# F7 v2: green-menu scripts start with "." first in PATH and LD_LIBRARY_PATH, umask 000 and
# cwd /mnt/app/eso (Toolbox v0 on the car).  PATH is fixed above; relative library
# directories are dropped; the stage directory is resolved before leaving the cwd.
cd / || exit 2
umask 022
ld_keep=''; ld_ifs=$IFS; IFS=:; set -f
for ld_dir in ${LD_LIBRARY_PATH:-}; do case "$ld_dir" in /*) ld_keep=${ld_keep:+$ld_keep:}$ld_dir ;; esac; done
set +f; IFS=$ld_ifs
if [ -n "$ld_keep" ]; then LD_LIBRARY_PATH=$ld_keep; export LD_LIBRARY_PATH; else unset LD_LIBRARY_PATH || :; fi
case "$stage_dir" in /fs/sda0/*) sd=/fs/sda0 ;; /fs/sdb0/*) sd=/fs/sdb0 ;; *) echo 'STOP: use SD /fs/sda0 or /fs/sdb0'; exit 2 ;; esac
fail() { echo "STOP: $*" >&2; exit 1; }
uid=$(id -u); set -f; (set -- $uid; [ "$#" = 1 ] && [ "$1" = 0 ]) || fail 'effective UID must be 0'
case "$(uname -a)" in QNX\ *\ 6.5.0\ *\ armle) ;; *) fail 'wrong platform' ;; esac
output=$(cksum "$stage_dir/mount_state"); set -- $output; [ "${1:-}" = '2952412687' ] && [ "${2:-}" = '7302' ] || fail 'mount helper checksum'
output=$(cksum "$stage_dir/control.sh"); set -- $output; [ "${1:-}" = '2701278872' ] && [ "${2:-}" = '33746' ] || fail 'control checksum'
state() { (LD_LIBRARY_PATH=/proc/boot:/lib exec "$stage_dir/mount_state" "$sd"); }
# F7 v2.1 (F8): the monitor remounts this SD for its flushes; both sides take the same
# lock before they look at or change the mount state.  A dead holder is replaced.
SD_LOCK=/tmp/mu1320-f8-sd.lock; sd_locked=0
lock_holder() { lh=''; if [ -f "$SD_LOCK" ]; then read -r lh < "$SD_LOCK" || :; fi; echo "$lh"; }
lock_take() {
    if (set -C; echo "$$" > "$SD_LOCK") 2>/dev/null; then return 0; fi
    lt=$(lock_holder)
    case "$lt" in ''|*[!0-9]*) ;; *) if kill -0 "$lt" 2>/dev/null; then return 1; fi ;; esac
    rm -f "$SD_LOCK" || return 1
    (set -C; echo "$$" > "$SD_LOCK") 2>/dev/null
}
sd_unlock() { if [ "$sd_locked" = 1 ] && [ "$(lock_holder)" = "$$" ]; then rm -f "$SD_LOCK" || :; fi; sd_locked=0; }
lock_wait=0
while ! lock_take; do
    [ "$lock_wait" -lt 30 ] || fail "SD busy for 30 s (F8 monitor flush, pid $(lock_holder)); press again"
    sleep 1; lock_wait=$((lock_wait + 1))
done
sd_locked=1; [ "$lock_wait" = 0 ] || echo "SD_LOCK_WAITED: ${lock_wait}s"
initial=$(state) || { sd_unlock; fail 'SD mount query'; }
case "$initial" in ro|rw) ;; *) sd_unlock; fail 'unknown SD mount state' ;; esac
restore=0; log=''; completed=0; control_rc=255
cleanup() {
    outer_rc=$?; trap - 0 1 2 15; set +e
    if [ -n "$log" ] && [ -f "$log" ]; then printf 'CONTROL_EXIT=%s\nOUTER_EXIT_BEFORE_SD_CLEANUP=%s\nSD_INITIAL=%s\n' "$control_rc" "$outer_rc" "$initial" >> "$log"; sync || outer_rc=1; fi
    if [ "$restore" = 1 ]; then mount -ur "$sd" || outer_rc=1; fi
    final=$(state); query=$?
    if [ "$query" != 0 ] || [ "$final" != "$initial" ]; then echo "STOP: SD state not restored to $initial; do not remove card" >&2; outer_rc=1
    else echo "SD_MOUNT_RESTORED: $sd=$final"; fi
    sd_unlock
    [ -z "$log" ] || echo "ACTION_LOG_ON_SD: $log"
    echo "CONTROL_EXIT: $control_rc"; echo "OUTER_EXIT: $outer_rc"
    echo 'EVIDENCE_NOTE: save this terminal tail with the SD action log; final SD state occurs after the log is closed.'
    if [ "$outer_rc" = 0 ] && [ "$completed" = 1 ]; then echo 'F7_ACTION_PASSED'; fi
    exit "$outer_rc"
}
trap cleanup 0; trap 'exit 129' 1; trap 'exit 130' 2; trap 'exit 143' 15
if [ "$initial" = ro ]; then restore=1; mount -uw "$sd" || fail 'SD remount rw'; fi
[ "$(state)" = rw ] || fail 'SD not writable'
umask 077; out="$stage_dir/out"; [ ! -L "$out" ] || fail 'unsafe out directory'; [ -d "$out" ] || mkdir "$out"
log="$out/action-$requested_action-$$.txt"; [ ! -e "$log" ] && [ ! -L "$log" ] || fail 'action log collision'
set +e
if [ -n "$requested_phase" ]; then (set -C; /bin/sh "$stage_dir/control.sh" "$requested_action" "$requested_phase" > "$log" 2>&1)
else (set -C; /bin/sh "$stage_dir/control.sh" "$requested_action" > "$log" 2>&1); fi
control_rc=$?; set -e; cat "$log"; [ "$control_rc" = 0 ] || exit "$control_rc"; completed=1
