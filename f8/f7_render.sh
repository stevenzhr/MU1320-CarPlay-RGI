#!/bin/sh
# MU1320 F7 renderer keeper.  The F7 Java RendererKeeper runs it with
# Runtime.exec ("/bin/sh /mnt/app/root/mu1320-rgi-f7-v2/render/f7_render.sh up") on the first
# CarPlay session of a boot, while a route has no ready renderer, and when a
# ready renderer lost its Java link.  It can also be run by hand over SSH.
#
# It replaces the F5/F6 manual "arm": start maneuver_render through f7_spawn
# (detached, default signals, no inherited descriptors) unless ours is alive,
# wait until it has registered displayable 98, and declare cluster context 80
# {98,102,101,33} natively (dmdt dc, the F4/F5 car path).  It never switches
# the cluster; the Java ClusterPresenter does that only while a route is shown.
#
# Exit: 0 READY, 10 HELD (stop/rollback hold, off-render, not installed),
# 11 renderer failed to start, 12 no Java link, 13 displayable 98 missing,
# 14 context 80 declared differently or dc failed, 15 displaymanager unclear,
# 16 foreign displayable 98, 17 runtime file checksum, 252 usage.
# Never "dmdt ts": on this unit it hung displaymanager (F4 run2).
exec < /dev/null >> /tmp/mu1320-f7-keeper.log 2>&1
# Started from the HMI JVM: its PATH is unknown; dm()'s watchdog needs sleep/kill.
PATH=/proc/boot:/bin:/usr/bin:/sbin:/usr/sbin:$PATH; export PATH
ROOT=/mnt/app/root/mu1320-rgi-f7-v2
RENDER=$ROOT/render
JAR=/mnt/app/eso/hmi/lsd/jars/CarPlayRGI-MU1320-F7DailyV2.jar
HOLD=/tmp/mu1320-f7-render-hold
LOG=/tmp/mu1320-f7-keeper.log
UNBUF=$RENDER/f4_unbuf.so
DMP=/tmp/mu1320-f7-dm-keep
out() { echo "KEEP $*"; }
fail() { out "FAIL code=$1 $2"; exit "$1"; }
exists() { [ -e "$1" ] || [ -L "$1" ]; }
check() { [ -f "$3" ] && [ ! -L "$3" ] || return 1; c=$1; n=$2; output=$(cksum "$3") || return 1; set -- $output; [ "${1:-}" = "$c" ] && [ "${2:-}" = "$n" ]; }
size() { output=$(ls -ln "$1" 2>/dev/null) || { echo 0; return 0; }; set -- $output; echo "${5:-0}"; }
[ "$#" = 1 ] && [ "$1" = up ] || fail 252 "usage: $*"
n=$(size "$LOG"); case "$n" in ''|*[!0-9]*) ;; *) if [ "$n" -gt 262144 ]; then : > "$LOG"; out "LOG_TRUNCATED bytes=$n"; fi ;; esac
out "BEGIN pid=$$"
# F7 v2.1 (F8): start the long-term monitor once per boot, before the HOLD exits so a
# stopped boot keeps its record.  It never fails the keeper.
MON=$ROOT/mon
MON_RUN=/tmp/mu1320-f8-mon.run
mon_start() {
    [ -f "$JAR" ] || return 0
    if exists /tmp/mu1320-f8-mon-off || exists "$ROOT/off-monitor"; then out 'MON off'; return 0; fi
    m_pid=''
    if [ -f "$MON_RUN" ]; then read -r m_pid < "$MON_RUN" || :; fi
    case "$m_pid" in ''|*[!0-9]*) ;; *) if kill -0 "$m_pid" 2>/dev/null; then return 0; fi ;; esac
    check 2255473972 11899 "$MON/f8_mon.sh" || { out 'MON_FAIL monitor checksum'; return 0; }
    check 2952412687 7302 "$MON/mount_state" || { out 'MON_FAIL mount helper checksum'; return 0; }
    check 292735868 8680 "$RENDER/f7_spawn" || { out 'MON_FAIL launcher checksum'; return 0; }
    m_rc=0
    "$RENDER/f7_spawn" /tmp/mu1320-f8-mon.pid /tmp/mu1320-f8-mon.log "$MON" /bin/sh "$MON/f8_mon.sh" run || m_rc=$?
    if [ "$m_rc" = 0 ]; then out "MON SPAWNED pid=$(cat /tmp/mu1320-f8-mon.pid)"; else out "MON_FAIL f7_spawn exit $m_rc"; fi
    return 0
}
mon_start
if exists "$HOLD"; then out 'HELD hold'; exit 10; fi
if exists "$ROOT/off-render"; then out 'HELD off-render'; exit 10; fi
if [ ! -f "$JAR" ]; then out 'HELD not-installed'; exit 10; fi
check 1766868864 120056 "$RENDER/maneuver_render" || fail 17 'renderer checksum'
check 2017122787 917504 "$RENDER/flag_atlas.rgba" || fail 17 'flag atlas checksum'
check 3641631177 10620 "$RENDER/f5_dm.sh" || fail 17 'displaymanager helper checksum'
check 1988489462 5403 "$UNBUF" || fail 17 'dmdt stdout shim checksum'
check 292735868 8680 "$RENDER/f7_spawn" || fail 17 'launcher checksum'
. "$RENDER/f5_dm.sh"
started=0
if renderer_alive; then
    out "ALIVE pid=$r_pid"
else
    dm "$DMP-gd.txt" gd || :; parse_gd "$DMP-gd.txt"
    [ "$GD_COMPLETE" = yes ] || fail 15 "dmdt gd incomplete ($GD_COUNT)"
    [ -z "$GD98" ] || fail 16 'displayable 98 exists without our renderer'
    : > "$RLOG" || fail 11 'renderer log'
    rc=0; "$RENDER/f7_spawn" "$RPID" "$RLOG" "$RENDER" "$RENDER/maneuver_render" || rc=$?
    [ "$rc" = 0 ] || fail 11 "f7_spawn exit $rc"
    started=1
    out "SPAWNED pid=$(cat "$RPID")"
    n=0
    while ! grep 'maneuver_render: ready' "$RLOG" >/dev/null 2>&1; do
        renderer_alive || { rm -f "$RPID"; fail 11 'renderer exited during init'; }
        [ "$n" -lt 25 ] || { render_stop; fail 11 'renderer not ready after 25 s'; }
        sleep 1; n=$((n + 1))
    done
    n=0
    while ! grep 'server: connected to 127.0.0.1:19800' "$RLOG" >/dev/null 2>&1; do
        [ "$n" -lt 10 ] || { render_stop; fail 12 'renderer did not reach the Java listener on 19800 within 10 s'; }
        sleep 1; n=$((n + 1))
    done
fi
drop() { if [ "$started" = 1 ]; then render_stop; fi; }
n=0
while :; do
    dm "$DMP-gd-r.txt" gd || :; parse_gd "$DMP-gd-r.txt"
    if [ -n "$GD98" ]; then break; fi
    [ "$n" -lt 5 ] || { drop; fail 13 'displayable 98 not registered by the renderer'; }
    sleep 1; n=$((n + 1))
done
dm "$DMP-gc.txt" gc || :; parse_gc "$DMP-gc.txt"
[ "$GC_FORMAT" = parsed ] || { drop; fail 15 "dmdt gc output $GC_FORMAT ($GC_COUNT)"; }
if ctx_declared "$DMP-gc.txt"; then
    [ "$GC_LIST" = "$TEST_LIST" ] || { drop; fail 14 "context $CTX declared as [$GC_LIST]"; }
    declared=existing
else
    dm "$DMP-dc.txt" dc "$CTX" $TEST_LIST || { drop; fail 14 "dmdt dc $CTX"; }
    dm "$DMP-gc-dc.txt" gc || :
    if ctx_declared "$DMP-gc-dc.txt" && [ "$GC_FORMAT" = parsed ] && [ "$GC_LIST" = "$TEST_LIST" ]; then :
    else drop; fail 14 "context $CTX not declared as [$TEST_LIST] after dc"; fi
    declared=now
fi
out "READY pid=$(cat "$RPID") d98=$GD98 started=$started ctx$CTX=$declared"
exit 0
