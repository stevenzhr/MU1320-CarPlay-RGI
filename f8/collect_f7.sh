#!/bin/sh
set -eu
for var in LD_PRELOAD LD_DEBUG DL_DEBUG LD_DEBUG_OUTPUT; do unset "$var" || :; done
PATH=/proc/boot:/bin:/usr/bin:/sbin:/usr/sbin:/mnt/app/armle/bin:/mnt/app/armle/usr/bin
export PATH
phase=${1:-snapshot}; case "$phase" in live|restored|snapshot) ;; *) exit 2 ;; esac
MARKER='MU1320_F7_TRIAL=mu1320_f7_v2_773045ab'
PRELOAD='LD_PRELOAD=/mnt/app/root/mu1320-rgi-f7-v2/libcarplay_hook.so'
SYSTEM=/mnt/system/etc/eso/production/smartphone_integrator.json; ACTIVE=/etc/eso/production/smartphone_integrator.json
for utility in pidin mkdir cat cksum tr sync cp grep uname date; do command -v "$utility" >/dev/null 2>&1 || { echo "STOP: missing $utility"; exit 2; }; done
case "$0" in */*) sd_dir=${0%/*} ;; *) exit 2 ;; esac
sd_dir=$(CDPATH= cd "$sd_dir" && pwd -P); case "$sd_dir" in /fs/sda0/*|/fs/sdb0/*) ;; *) echo 'STOP: collector must run from SD'; exit 2 ;; esac
umask 077; out="$sd_dir/out"; [ -d "$out" ] || mkdir "$out"; [ ! -L "$out" ] || exit 2
fail() { echo "STOP: $*"; exit 2; }
exists() { [ -e "$1" ] || [ -L "$1" ]; }
output=$(cksum "$sd_dir/f5_dm.sh"); set -- $output; [ "${1:-}" = '3641631177' ] && [ "${2:-}" = '10620' ] || fail 'displaymanager helper checksum'
output=$(cksum "$sd_dir/f4_unbuf.so"); set -- $output; [ "${1:-}" = '1988489462' ] && [ "${2:-}" = '5403' ] || fail 'dmdt stdout shim checksum'
UNBUF=$sd_dir/f4_unbuf.so; DMP=/tmp/mu1320-f5-dm-collect-$$
. "$sd_dir/f5_dm.sh"
logdir="$out/$phase-$$"; mkdir "$logdir"
snapshot() { pidin -F '%a %e %256n'; }; identity() { pidin -p "$1" -F '%a %e %256n %t'; }
observe() {
    p=$1; role=$2; echo "PROCESS_BEGIN: role=$role pid=$p"
    before=$(identity "$p" 2>&1); brc=$?; printf '%s\n' "$before"
    envfile="$logdir/$role-$p-environment.txt"; pidin -p "$p" environment > "$envfile" 2>&1; erc=$?
    echo "ENVIRONMENT_BEGIN: exit=$erc file=$envfile"; cat "$envfile"; echo ENVIRONMENT_END
    if [ "$role" = DIO ]; then
        receipt="/tmp/mu1320-f7-gate-$p"; echo GATE_RECEIPT_BEGIN
        if [ -f "$receipt" ] && [ ! -L "$receipt" ]; then cp "$receipt" "$logdir/$role-$p-gate-receipt.txt"; cat "$receipt"; else echo NO_RECEIPT; fi
        echo GATE_RECEIPT_END
    fi
    memfile="$logdir/$role-$p-mem.txt"; pidin -p "$p" mem > "$memfile" 2>&1; mrc=$?
    echo "MEMORY_MAP_BEGIN exit=$mrc"; cat "$memfile"; echo MEMORY_MAP_END
    after=$(identity "$p" 2>&1); arc=$?; echo IDENTITY_AFTER; printf '%s\n' "$after"
    if [ "$arc" != 0 ] || [ "$brc" != 0 ] || [ "$before" != "$after" ] || [ "$erc" != 0 ]; then echo OBSERVATION_INVALID_OR_CHANGED
    elif [ "$role" = DIO ]; then
        has_marker=0; has_preload=0; grep "$MARKER" "$envfile" >/dev/null 2>&1 && has_marker=1 || :; grep "$PRELOAD" "$envfile" >/dev/null 2>&1 && has_preload=1 || :
        echo "DIO_ENV_MARKER=$has_marker DIO_ENV_PRELOAD=$has_preload"
    fi
    echo PROCESS_END
}
collect() {
    echo "F7_COLLECT_BEGIN phase=$phase"; uname -a; date
    echo CONFIG_CHECKSUMS; cksum "$SYSTEM" "$ACTIVE"
    echo ACTIVE_ARCHIVES; cksum /mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar 2>&1 || :; cksum /mnt/app/eso/hmi/lsd/jars/CarPlayRGI-MU1320-F7DailyV2.jar 2>&1 || :
    cksum /mnt/app/root/mu1320-rgi-f7-v2/quarantine/NavActiveIgnore.jar 2>&1 || :
    echo RAM_MARKERS; for f in /tmp/carplay_verbose /tmp/mu1320-f7-render-hold /tmp/mu1320-f7-native-off; do if [ -e "$f" ] || [ -L "$f" ]; then echo "PRESENT: $f"; else echo "ABSENT: $f"; fi; done
    echo ALL_GATE_RECEIPTS_BEGIN
    # Globbing is intentionally enabled here. The earlier collector's global
    # `set -f` made this enumerate the literal pattern instead of receipts.
    receipt_count=0
    for f in /tmp/mu1320-f7-gate-*; do
        if [ -f "$f" ] && [ ! -L "$f" ]; then receipt_count=$((receipt_count+1)); echo "FILE: $f"; cat "$f"; fi
    done
    echo "GLOBAL_GATE_RECEIPT_COUNT=$receipt_count"; echo ALL_GATE_RECEIPTS_END
    for f in /tmp/mu1320-f7-gate.last /tmp/mu1320-f7-gate.strikes; do
        if [ -f "$f" ] && [ ! -L "$f" ]; then echo "GATE_RECORD: $f $(cat "$f")"; else echo "GATE_RECORD: $f ABSENT"; fi
    done
    for component_name in native render bap touchpad monitor; do
        if [ -e "/mnt/app/root/mu1320-rgi-f7-v2/off-$component_name" ]; then echo "F7_SWITCH[$component_name]=OFF_PERSISTENT"; else echo "F7_SWITCH[$component_name]=on"; fi
    done
    echo JAVA_LOGS_BEGIN
    for f in /tmp/carplay_java.log /tmp/carplay_java.log.1; do echo "FILE: $f"; if [ -f "$f" ] && [ ! -L "$f" ]; then name=${f##*/}; cp "$f" "$logdir/$name"; cat "$f"; else echo NO_LOG; fi; done
    echo JAVA_LOGS_END
    echo F7_FILES_BEGIN
    # The capture holds sanitized frame diffs (free text replaced by tokens); it is
    # copied for host replay, not printed.  State, BAP and render logs hold no road text.
    for f in /tmp/mu1320-f5-state.log /tmp/mu1320-f5-frames.cap /tmp/mu1320-f5-bap.log /tmp/mu1320-f5-render.log /tmp/mu1320-f5-renderer.log /tmp/mu1320-f5-geom.cfg /tmp/mu1320-f5-sc.log /tmp/mu1320-f5-ctx-mode /tmp/mu1320-f6-touchpad.log /tmp/mu1320-f7-keeper.log /tmp/mu1320-f8-mon.log /tmp/mu1320-f8-mon.state /tmp/mu1320-f8-mon.buf; do
        if [ -f "$f" ] && [ ! -L "$f" ]; then name=${f##*/}; cp "$f" "$logdir/$name"; echo "COPIED: $f $(cksum "$f")"; else echo "MISSING: $f"; fi
    done
    echo F7_FILES_END
    state_log=/tmp/mu1320-f5-state.log; bap_log=/tmp/mu1320-f5-bap.log
    for label in 'F2 i=' 'ev=REJECT' 'ACTIVATE' 'ROUTE_END' 'ARRIVED' 'LINK_LOST' 'sym=MANEUVER'; do
        n=0; if [ -f "$state_log" ]; then n=$(grep -c -- "$label" "$state_log" 2>/dev/null || :); fi
        echo "F7_STATE_COUNT[$label]=${n:-0}"
    done
    for label in ' START ' ' RESUME ' ' TEARDOWN ' ' RELEASE_SILENT ' ' HOLD_OFF ' ' FAULT ' ' BIND ok' ' BIND fail' ' GATE ' ' DEBOUNCE ' ' DEBOUNCE_FIRE' ' CALL ' ' CALL DESCRIPTOR ' ' CALL LANES n=' ' CALL ETA src=eta' ' CALL ETA src=rem' ' RCMD MAN ' ' RCMD CLEAR'; do
        n=0; if [ -f "$bap_log" ]; then n=$(grep -c -- "$label" "$bap_log" 2>/dev/null || :); fi
        echo "F7_BAP_COUNT[$label]=${n:-0}"
    done
    echo F7_BAP_EVENT_LINES_BEGIN
    if [ -f "$bap_log" ]; then grep -v -e ' CALL ' -e ' RCMD ' "$bap_log" | head -300 || :; fi
    echo F7_BAP_EVENT_LINES_END
    render_log=/tmp/mu1320-f5-render.log
    for label in ' TAKE ' ' RELEASE ' ' STOCK_RECLAIMED ' ' FIGHT_STOP' ' YIELD_VIEW ' ' WAIT_MAP ' ' GEOM ' ' GEOM_CONFIG' ' RENDERER ' ' RESEND ' ' GRID ' ' DISPLAY fail' ' TAKE_FAILED' ' VERIFY ' ' JAVA_CONFIRMED' ' KDK_REWRITE ' ' UNSTICK_73' ' BACKING_REASSERT' ' RELEASE_STRAY' ' MODE ' ' TAKE_RACED' ' RACE_RETRY' ' WAIT_RETRY' ' FIGHT_RESUME' ' KEEPER_UP' ' KEEPER_READY' ' KEEPER_HELD' ' KEEPER_FAIL' ' KEEPER_LOST' ' KEEPER_GIVE_UP' ' LOG_TRUNCATED'; do
        n=0; if [ -f "$render_log" ]; then n=$(grep -c -- "$label" "$render_log" 2>/dev/null || :); fi
        echo "F7_RENDER_COUNT[$label]=${n:-0}"
    done
    echo F7_RENDER_LINES_BEGIN
    if [ -f "$render_log" ]; then head -300 "$render_log" || :; fi
    echo F7_RENDER_LINES_END
    keeper_log=/tmp/mu1320-f7-keeper.log
    for label in 'KEEP BEGIN' 'KEEP READY' 'KEEP ALIVE' 'KEEP SPAWNED' 'KEEP HELD' 'KEEP FAIL' 'KEEP LOG_TRUNCATED'; do
        n=0; if [ -f "$keeper_log" ]; then n=$(grep -c -- "$label" "$keeper_log" 2>/dev/null || :); fi
        echo "F7_KEEPER_COUNT[$label]=${n:-0}"
    done
    echo F7_KEEPER_LINES_BEGIN
    if [ -f "$keeper_log" ]; then grep 'KEEP ' "$keeper_log" | head -100 || :; fi
    echo F7_KEEPER_LINES_END
    echo "F7_KILL_SWITCH: $( [ -e /tmp/mu1320-f5-bap-off ] && echo PRESENT || echo ABSENT )"
    echo "F7_RENDER_OFF: $( [ -e /tmp/mu1320-f5-render-off ] && echo PRESENT || echo ABSENT )"
    echo "F7_CALIBRATION: $( [ -e /tmp/mu1320-f5-calib ] && echo PRESENT || echo ABSENT )"
    # Touchpad bridge log: numbers only (key codes, sample/tick counts); no trajectories.
    touch_log=/tmp/mu1320-f6-touchpad.log
    for label in ' READY ' ' SESSION ' ' MODE dpad=1' ' MODE dpad=0' ' DPAD key=5' ' DPAD key=6' ' DPAD key=7' ' DPAD key=8' ' GESTURE ' ' MULTI ' ' FAULT ' ' DROP ' ' STOP' ' LOG_LIMIT'; do
        n=0; if [ -f "$touch_log" ]; then n=$(grep -c -- "$label" "$touch_log" 2>/dev/null || :); fi
        echo "F7_TOUCH_COUNT[$label]=${n:-0}"
    done
    echo F7_TOUCH_LINES_BEGIN
    if [ -f "$touch_log" ]; then grep -v ' DPAD key=' "$touch_log" | head -200 || :; fi
    echo F7_TOUCH_LINES_END
    echo "F7_TOUCHPAD_OFF: $( [ -e /tmp/mu1320-f6-touchpad-off ] && echo PRESENT || echo ABSENT )"
    echo F7_DISPLAY_BEGIN
    renderer_status
    DMP="$logdir/dm"; dm_query
    echo F7_DISPLAY_END
    if command -v sloginfo >/dev/null 2>&1; then sloginfo > "$logdir/sloginfo.txt" 2>&1; lrc=$?; else echo 'sloginfo unavailable' > "$logdir/sloginfo.txt"; lrc=127; fi
    echo "SLOGINFO_SAVED exit=$lrc lines=$(grep -c '' "$logdir/sloginfo.txt" 2>/dev/null || :)"
    echo SLOG_EXCERPT_BEGIN
    grep -i -E 'Modes changed|exception|verifyerror|linkageerror|noclassdef|incompatibleclass' "$logdir/sloginfo.txt" 2>/dev/null | tail -80 || :
    echo SLOG_EXCERPT_END
    echo HOOK_LOGS_BEGIN
    for f in /tmp/carplay_hook.log /tmp/carplay_hook.log.1 /tmp/carplay_hook.log.2 /tmp/carplay_hook.log.3; do echo "FILE: $f"; if [ -f "$f" ] && [ ! -L "$f" ]; then name=${f##*/}; cp "$f" "$logdir/$name"; cat "$f"; else echo NO_LOG; fi; done
    echo HOOK_LOGS_END
    snapshot > "$logdir/processes.txt" 2>&1; src=$?; echo "PROCESS_TABLE_BEGIN exit=$src"; cat "$logdir/processes.txt"; echo PROCESS_TABLE_END; [ "$src" = 0 ] || return 1
    si=' '; while read -r p parent name rest; do case "$p" in ''|*[!0-9]*) continue;; esac; case "$name" in */smartphone_integrator|smartphone_integrator) si="$si$p " ;; esac; done < "$logdir/processes.txt"
    count=0; seen=' '
    while read -r p parent name rest; do
        case "$p" in ''|*[!0-9]*) continue;; esac; case "$seen" in *" $p "*) continue;; esac
        case "$name" in */smartphone_integrator|smartphone_integrator) role=SI ;; */dio_manager|dio_manager) role=DIO; count=$((count+1)); case "$si" in *" $parent "*) echo "DIRECT_SI_PARENT: dio=$p si=$parent";; *) echo "DIO_PARENT_NOT_SI: dio=$p parent=$parent";; esac ;; *) continue;; esac
        seen="$seen$p "; observe "$p" "$role"
    done < "$logdir/processes.txt"
    echo "DIO_PROCESSES_OBSERVED=$count"; [ "$count" != 0 ] || echo INCONCLUSIVE_NO_DIO
    echo 'INTERPRETATION: F7 evidence = every DIO gate ACTIVE (reason ON/PREV_ALIVE) without arm + KEEP READY once per boot + BIND ok + START/TEARDOWN per route with zero FAULT + TAKE/RELEASE of context 80 per shown route; VC/HUD display is judged from photos and OBSERVATIONS'
    echo 'PRIVACY: logs can contain route names and destinations; keep the raw directory private'
    echo "F7_COLLECT_END phase=$phase"
}
set +e; collect > "$logdir/collect.txt" 2>&1; rc=$?; set -e
cat "$logdir/collect.txt"; echo "COLLECT_EXIT=$rc"; sync || echo 'WARNING: sync failed'; echo "SAVED_ON_SD: $logdir"; exit "$rc"
