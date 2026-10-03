#!/bin/sh
set -eu
for var in LD_PRELOAD LD_DEBUG DL_DEBUG LD_DEBUG_OUTPUT; do unset "$var" || :; done
PATH=/proc/boot:/bin:/usr/bin:/sbin:/usr/sbin:/mnt/app/armle/bin:/mnt/app/armle/usr/bin
export PATH
[ "$#" -ge 1 ] || exit 2
action=$1; phase=${2:-snapshot}
component=''
case "$action:$#" in status:1|install:1|stop:1|rollback:1|purge:1|collect:2) ;; off:2|on:2) component=$2; phase=snapshot ;; *) exit 2 ;; esac
case "$phase" in live|restored|snapshot) ;; *) exit 2 ;; esac
case "$component" in ''|native|render|bap|touchpad|monitor) ;; *) exit 2 ;; esac
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
ROOT=/mnt/app/root/mu1320-rgi-f7-v2
SYSTEM=/mnt/system/etc/eso/production/smartphone_integrator.json
ACTIVE=/etc/eso/production/smartphone_integrator.json
JARS=/mnt/app/eso/hmi/lsd/jars
OLD=$JARS/NavActiveIgnore.jar
QUARANTINE=$ROOT/quarantine/NavActiveIgnore.jar
BACKUP=$ROOT/backup/NavActiveIgnore.jar
NEW=$JARS/CarPlayRGI-MU1320-F7DailyV2.jar
# F7: no arm token.  Runtime holds (until reboot) written by stop/rollback:
HOLD=/tmp/mu1320-f7-render-hold
NATIVE_OFF=/tmp/mu1320-f7-native-off
JAVA_LOG=/tmp/carplay_java.log
MARKER=mu1320_f7_v2_773045ab
fail() { echo "STOP: $*" >&2; exit 1; }
exists() { [ -e "$1" ] || [ -L "$1" ]; }
for utility in id uname cksum ls cat; do command -v "$utility" >/dev/null 2>&1 || fail "missing $utility"; done
uid=$(id -u); set -f; set -- $uid
[ "$#" = 1 ] && [ "$1" = 0 ] || fail 'effective UID must be 0'
case "$(uname -a)" in QNX\ *\ 6.5.0\ *\ armle) ;; *) fail 'wrong platform' ;; esac
check() { [ -f "$3" ] && [ ! -L "$3" ] || return 1; c=$1; n=$2; output=$(cksum "$3") || return 1; set -- $output; [ "${1:-}" = "$c" ] && [ "${2:-}" = "$n" ]; }
attrs() { output=$(LC_ALL=C ls -ln "$1") || return 1; set -- $output; [ "$#" -ge 5 ] || return 1; printf '%s %s %s\n' "$1" "$3" "$4"; }
dir_attrs() { output=$(LC_ALL=C ls -ldn "$1") || return 1; set -- $output; [ "$#" -ge 5 ] || return 1; printf '%s %s %s\n' "$1" "$3" "$4"; }
old_si_ok() { check 535418540 7359 "$1" && [ "$(attrs "$1")" = '-rw-r--r-- 0 0' ]; }
new_si_ok() { check 3705995034 7482 "$1" && [ "$(attrs "$1")" = '-rw-r--r-- 0 0' ]; }
navignore_ok() { check 2960431692 2645 "$1" && [ "$(attrs "$1")" = '-rwxrwxrwx 0 0' ]; }
java_ok() { check 3555241766 147646 "$1" && [ "$(attrs "$1")" = '-rw-r--r-- 0 0' ]; }
run_clean() { (for var in LD_PRELOAD LD_DEBUG DL_DEBUG LD_DEBUG_OUTPUT; do unset "$var" || :; done; LD_LIBRARY_PATH=/proc/boot:/lib exec "$@"); }
check 2952412687 7302 "$stage_dir/mount_state" || fail 'mount helper checksum'
check 3136660668 10880 "$stage_dir/collect_f7.sh" || fail 'collector checksum'
check 3641631177 10620 "$stage_dir/f5_dm.sh" || fail 'displaymanager helper checksum'
check 1988489462 5403 "$stage_dir/f4_unbuf.so" || fail 'dmdt stdout shim checksum'
check 2992755173 34464 /mnt/app/eso/bin/apps/dmdt || fail 'dmdt baseline'
UNBUF=$stage_dir/f4_unbuf.so
# Query output goes to /tmp (flat files): the SD may be read-only when control.sh runs directly.
DMP="/tmp/mu1320-f5-dm-$action-$$"
. "$stage_dir/f5_dm.sh"
check 3727885851 560715 /proc/boot/libc.so.3 || fail 'libc baseline'
state() { run_clean "$stage_dir/mount_state" "$1"; }
app_state=$(state /mnt/app) || fail 'app mount query'; system_state=$(state /mnt/system) || fail 'system mount query'
case "$app_state:$system_state" in ro:ro|ro:rw|rw:ro|rw:rw) ;; *) fail 'unknown mount states' ;; esac
config_state() { if old_si_ok "$1"; then echo BASELINE; elif new_si_ok "$1"; then echo F7_TRIAL; else echo UNKNOWN; fi; }
java_state() { if java_ok "$NEW"; then echo F7_INSTALLED; elif exists "$NEW"; then echo UNKNOWN_PRESENT; else echo ABSENT; fi; }
echo "SYSTEM_CONFIG: $(config_state "$SYSTEM")"; echo "ACTIVE_CONFIG: $(config_state "$ACTIVE")"
navignore_state() {
    if navignore_ok "$OLD"; then echo ACTIVE_BASELINE
    elif exists "$OLD"; then echo UNKNOWN_PRESENT
    elif navignore_ok "$QUARANTINE"; then echo QUARANTINED
    else echo MISSING; fi
}
echo "JAVA_ARCHIVE: $(java_state)"; echo "NAV_ACTIVE_IGNORE: $(navignore_state)"
echo "BAP_KILL_SWITCH: $(exists /tmp/mu1320-f5-bap-off && echo PRESENT || echo ABSENT)"
echo "RENDER_OFF_SWITCH: $(exists /tmp/mu1320-f5-render-off && echo PRESENT || echo ABSENT)"
echo "CALIBRATION_SWITCH: $(exists /tmp/mu1320-f5-calib && echo PRESENT || echo ABSENT)"
echo "GEOMETRY_OVERRIDE: $(exists /tmp/mu1320-f5-geom.cfg && echo PRESENT || echo ABSENT)"
echo "TOUCHPAD_OFF_SWITCH: $(exists /tmp/mu1320-f6-touchpad-off && echo PRESENT || echo ABSENT)"
echo "TOUCHPAD_LOG: $(exists /tmp/mu1320-f6-touchpad.log && echo PRESENT || echo ABSENT)"
ctx_mode=kdk; ctx_word=''
if [ -f /tmp/mu1320-f5-ctx-mode ]; then read -r ctx_word < /tmp/mu1320-f5-ctx-mode || :; fi
case "$ctx_word" in native*) ctx_mode=native ;; esac
echo "CTX_MODE: $ctx_mode"
echo "MOUNTS: app=$app_state system=$system_state"
echo "RUN_ENV: cwd=$(pwd) umask=$(umask) ld=${LD_LIBRARY_PATH:-unset}"
# Persistent component switches (files in the workspace; control.sh off|on <component>).
for component_name in native render bap touchpad monitor; do
    if exists "$ROOT/off-$component_name"; then echo "SWITCH_$component_name: OFF_PERSISTENT"; else echo "SWITCH_$component_name: on"; fi
done
echo "NATIVE_RUNTIME_OFF: $(exists "$NATIVE_OFF" && echo PRESENT || echo ABSENT)"
echo "RENDER_HOLD: $(exists "$HOLD" && echo PRESENT || echo ABSENT)"
gate_word() { word=ABSENT; if [ -f "$1" ]; then word=; read -r word < "$1" || :; fi; echo "${word:-EMPTY}"; }
echo "GATE_LAST: $(gate_word /tmp/mu1320-f7-gate.last)"; echo "GATE_STRIKES: $(gate_word /tmp/mu1320-f7-gate.strikes)"
if [ -f "$JAVA_LOG" ] && grep 'MU1320-F7-DAILY-V2 LISTENER_READY' "$JAVA_LOG" >/dev/null 2>&1; then echo 'JAVA_LISTENER: F7_READY'; else echo 'JAVA_LISTENER: ABSENT'; fi
keeper_last=NONE; if [ -f /tmp/mu1320-f7-keeper.log ]; then while read -r keeper_line; do case "$keeper_line" in 'KEEP '*) keeper_last=$keeper_line ;; esac; done < /tmp/mu1320-f7-keeper.log; fi
echo "KEEPER_LAST: $keeper_last"
# F7 v2.1 (F8): the long-term monitor and any other workspace left in /mnt/app/root.
MON_RUN=/tmp/mu1320-f8-mon.run
mon_alive() {
    mon_pid=''
    if [ -f "$MON_RUN" ]; then read -r mon_pid < "$MON_RUN" || :; fi
    case "$mon_pid" in ''|*[!0-9]*) return 1 ;; esac
    kill -0 "$mon_pid" 2>/dev/null
}
mon_state=NONE; if [ -f /tmp/mu1320-f8-mon.state ]; then read -r mon_state < /tmp/mu1320-f8-mon.state || :; fi
if mon_alive; then echo "F8_MONITOR: RUNNING pid=$mon_pid"; elif [ "$mon_state" != NONE ]; then echo 'F8_MONITOR: ENDED'; else echo 'F8_MONITOR: ABSENT'; fi
echo "F8_MONITOR_STATE: $mon_state"
other_ws=''; set +f
for ws in /mnt/app/root/mu1320-rgi-*; do
    if [ -d "$ws" ] && [ "$ws" != "$ROOT" ]; then other_ws="$other_ws ${ws##*/}"; fi
done
set -f
echo "OTHER_WORKSPACES:${other_ws:- none}"
echo "EXPECTED_MARKER: MU1320_F7_TRIAL=$MARKER"
runtime_ok() {
    [ -d "$ROOT" ] && [ ! -L "$ROOT" ] && [ -d "$ROOT/config" ] && [ -d "$ROOT/backup" ] && [ -d "$ROOT/quarantine" ] || fail 'unsafe runtime workspace'
    [ "$(dir_attrs "$ROOT/quarantine")" = 'drwx------ 0 0' ] || fail 'runtime quarantine attributes'
    [ "$(dir_attrs "$ROOT")" = 'drwx------ 0 0' ] || fail 'runtime root attributes'
    [ "$(dir_attrs "$ROOT/config")" = 'drwx------ 0 0' ] || fail 'runtime config attributes'
    [ "$(dir_attrs "$ROOT/backup")" = 'drwx------ 0 0' ] || fail 'runtime backup attributes'
    check 1788014713 19 "$ROOT/IDENTITY" || fail 'identity mismatch'
    check 1291246513 242082 "$ROOT/libcarplay_hook.so" || fail 'runtime hook checksum'
    check 1713239687 15784 "$ROOT/config/dio_manager.json" || fail 'runtime dio config checksum'
    java_ok "$ROOT/carplay_mu1320_f7_daily_v2.jar" || fail 'runtime Java payload checksum/attributes'
    navignore_ok "$ROOT/backup/NavActiveIgnore.jar" || fail 'NavActiveIgnore backup checksum/attributes'
    old_si_ok "$ROOT/backup/smartphone_integrator.json" || fail 'SI backup checksum/attributes'
    [ -d "$ROOT/render" ] && [ ! -L "$ROOT/render" ] || fail 'runtime render directory'
    check 1766868864 120056 "$ROOT/render/maneuver_render" || fail 'runtime renderer checksum'
    check 2017122787 917504 "$ROOT/render/flag_atlas.rgba" || fail 'runtime flag atlas checksum'
    check 1010800451 2167 "$ROOT/render/f5_sc.sh" || fail 'runtime context helper checksum'
    check 3641631177 10620 "$ROOT/render/f5_dm.sh" || fail 'runtime displaymanager helper checksum'
    check 1988489462 5403 "$ROOT/render/f4_unbuf.so" || fail 'runtime dmdt stdout shim checksum'
    check 292735868 8680 "$ROOT/render/f7_spawn" || fail 'runtime renderer launcher checksum'
    check 3779396577 5790 "$ROOT/render/f7_render.sh" || fail 'runtime renderer keeper checksum'
    [ -d "$ROOT/mon" ] && [ ! -L "$ROOT/mon" ] || fail 'runtime monitor directory'
    check 2255473972 11899 "$ROOT/mon/f8_mon.sh" || fail 'runtime monitor checksum'
    check 2952412687 7302 "$ROOT/mon/mount_state" || fail 'runtime monitor mount helper checksum'
    check 3518254750 798799 /mnt/app/eso/bin/apps/smartphone_integrator || fail "smartphone_integrator baseline"
    check 399102352 682672 /mnt/app/eso/bin/apps/dio_manager || fail "dio_manager baseline"
    check 863911487 179441 /lib/libsocket.so.3 || fail "libsocket.so.3 baseline"
    check 897556495 168169 /mnt/app/armle/usr/lib/libNme.so || fail "libNme.so baseline"
    check 3950733012 2544054 /mnt/app/armle/usr/lib/libNmeBaseClasses.so || fail "libNmeBaseClasses.so baseline"
    check 2897516468 765523 /mnt/app/armle/usr/lib/libNmeSDK.so || fail "libNmeSDK.so baseline"
    check 2083831845 92575 /mnt/app/armle/usr/lib/cinemo/libNmeTransport.so || fail "libNmeTransport.so baseline"
    check 1120623070 1069275 /mnt/app/armle/usr/lib/cinemo/libNmeNav.so || fail "libNmeNav.so baseline"
}
if [ "$action" = status ]; then
    renderer_status
    if command -v pidin >/dev/null 2>&1; then dm_query; fi
    echo 'FILE_STATE_ONLY: Java/native execution requires live logs and process evidence'; exit 0
fi
if [ "$action" = collect ]; then exec /bin/sh "$stage_dir/collect_f7.sh" "$phase"; fi
# stop and rollback: hold the renderer (the Java keeper answers HELD, no restart)
# and keep the next DIO passive, both until the next reboot.  F7 v2 (BACKLOG B12,
# v1.1 car session P7: VC/HUD kept the arrow after stop until USB was unplugged,
# because BAP output went on): first switch BAP off through the running Java with
# the runtime kill switch (BAP teardown puts VC/HUD back to stock and the
# presenter releases context 80 and gives the KDK back), wait until Java logged
# it and displaymanager left 80, and only then stop the renderer.  A cluster
# still on 80 is put back on 74 natively, as before.
BAP_KILL=/tmp/mu1320-f5-bap-off
BAP_LOG=/tmp/mu1320-f5-bap.log
count_matches() {
    cm_n=0
    if [ -f "$2" ]; then
        grep "$1" "$2" > "$DMP-count.txt" 2>/dev/null || :
        while read -r cm_line || [ -n "$cm_line" ]; do cm_n=$((cm_n + 1)); done < "$DMP-count.txt"
        rm -f "$DMP-count.txt" || :
    fi
    echo "$cm_n"
}
java_release() {
    JAVA_RELEASE=NO_JAVA
    kills_before=$(count_matches 'GATE kill=1' "$BAP_LOG")
    kill_was=0; if exists "$BAP_KILL"; then kill_was=1; fi
    : > "$BAP_KILL" || fail 'BAP runtime kill switch create'
    if [ "$kill_was" = 1 ]; then JAVA_RELEASE=ALREADY_OFF
    elif [ -f "$JAVA_LOG" ] && grep 'MU1320-F7-DAILY-V2 LISTENER_READY' "$JAVA_LOG" >/dev/null 2>&1; then
        JAVA_RELEASE=NO_ACK; n=0
        while [ "$n" -lt 10 ]; do
            sleep 1; n=$((n + 1))
            if [ "$(count_matches 'GATE kill=1' "$BAP_LOG")" -gt "$kills_before" ]; then JAVA_RELEASE=BAP_OFF; break; fi
        done
    fi
    echo "JAVA_RELEASE: $JAVA_RELEASE"
    case "$JAVA_RELEASE" in BAP_OFF|ALREADY_OFF) ;; *) return 0 ;; esac
    n=0
    while :; do
        dm "$DMP-gs-release.txt" gs || :; parse_gs "$DMP-gs-release.txt"
        if [ "$CL_CTX" != "$CTX" ] || [ "$n" -ge 8 ]; then break; fi
        sleep 1; n=$((n + 1))
    done
    echo "JAVA_CLUSTER_CONTEXT: ${CL_CTX:-UNKNOWN} waited=${n}s"
    sleep 1
}
stop_runtime() {
    : > "$HOLD" || fail 'render hold create'
    : > "$NATIVE_OFF" || fail 'native runtime off create'
    java_release
    render_disarm
}
if [ "$action" = stop ]; then
    stop_runtime
    [ "$DISARM_CLUSTER_OK" = 1 ] || fail 'cluster not confirmed off context 80 (see WARNING); do a normal reboot, which clears context 80'
    echo 'F7_STOPPED: BAP off (VC/HUD stock), renderer stopped and held, next DIO passive, until the next reboot; touchpad unchanged'; exit 0
fi
switch_note() { case "$1" in native) echo 'from the next DIO start (USB connect)' ;; monitor) echo 'off: within 60 s; on: from the next CarPlay session' ;; *) echo 'within 2 s, no restart' ;; esac; }
for utility in cp cmp mv chmod mkdir sync mount find rm; do command -v "$utility" >/dev/null 2>&1 || fail "missing $utility"; done
for directory in /mnt/app/root /mnt/app/eso/hmi/lsd "$JARS" /mnt/system/etc/eso/production; do [ -d "$directory" ] && [ ! -L "$directory" ] || fail "unsafe directory $directory"; done
if [ "$action" = install ]; then
    old_si_ok "$SYSTEM" && old_si_ok "$ACTIVE" || fail 'baseline SI required at both paths'
    navignore_ok "$OLD" || fail 'NavActiveIgnore must be the active baseline file before install'
    if exists "$QUARANTINE"; then fail 'quarantine slot occupied while NavActiveIgnore is active; preserve both'; fi
    if exists "$NEW"; then fail 'F7 Java archive already exists; use rollback'; fi
    if exists "$JARS/CarPlayRGI-MU1320-Stage2.jar"; then fail 'Stage2 archive still installed'; fi
    check 3919119664 15734 /etc/eso/production/dio_manager.json || fail 'active dio config differs'
    check 3919119664 15734 /mnt/system/etc/eso/production/dio_manager.json || fail 'system dio config differs'
    check 3705995034 7482 "$stage_dir/smartphone_integrator.json" || fail "smartphone_integrator.json payload checksum"
    check 1713239687 15784 "$stage_dir/dio_manager.json" || fail "dio_manager.json payload checksum"
    check 1788014713 19 "$stage_dir/IDENTITY" || fail "IDENTITY payload checksum"
    check 1291246513 242082 "$stage_dir/libcarplay_hook.so" || fail "libcarplay_hook.so payload checksum"
    check 2755445070 8203 "$stage_dir/loader_check" || fail "loader_check payload checksum"
    check 3555241766 147646 "$stage_dir/carplay_mu1320_f7_daily_v2.jar.DISABLED" || fail "carplay_mu1320_f7_daily_v2.jar.DISABLED payload checksum"
    check 1766868864 120056 "$stage_dir/maneuver_render" || fail "maneuver_render payload checksum"
    check 2017122787 917504 "$stage_dir/flag_atlas.rgba" || fail "flag_atlas.rgba payload checksum"
    check 1010800451 2167 "$stage_dir/f5_sc.sh" || fail "f5_sc.sh payload checksum"
    check 292735868 8680 "$stage_dir/f7_spawn" || fail "f7_spawn payload checksum"
    check 3779396577 5790 "$stage_dir/f7_render.sh" || fail "f7_render.sh payload checksum"
    check 2255473972 11899 "$stage_dir/f8_mon.sh" || fail "f8_mon.sh payload checksum"
    check 483111144 250996 /mnt/app/eso/hmi/lsd/jars/AppDevelopment.jar || fail "baseline archive differs: AppDevelopment.jar"
    check 1252008303 23585 /mnt/app/eso/hmi/lsd/jars/DevelopmentStubEvo.jar || fail "baseline archive differs: DevelopmentStubEvo.jar"
    check 2960431692 2645 /mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar || fail "baseline archive differs: NavActiveIgnore.jar"
    check 2061441066 164348 /mnt/app/eso/hmi/lsd/jars/RemoteHMI-Libs-Ext.jar || fail "baseline archive differs: RemoteHMI-Libs-Ext.jar"
    check 960769547 493315 /mnt/app/eso/hmi/lsd/jars/diag.jar || fail "baseline archive differs: diag.jar"
    check 1380918901 110239 /mnt/app/eso/hmi/lsd/jars/fw_util_commons.jar || fail "baseline archive differs: fw_util_commons.jar"
    check 4212266484 68237 /mnt/app/eso/hmi/lsd/jars/fw_util_config.jar || fail "baseline archive differs: fw_util_config.jar"
    check 1324906276 1268 /mnt/app/eso/hmi/lsd/jars/fw_util_os.jar || fail "baseline archive differs: fw_util_os.jar"
    check 3578407106 45815 /mnt/app/eso/hmi/lsd/jars/fw_util_serializer.jar || fail "baseline archive differs: fw_util_serializer.jar"
    check 1185153822 14589 /mnt/app/eso/hmi/lsd/jars/fw_util_services.jar || fail "baseline archive differs: fw_util_services.jar"
    check 3183950927 280197 /mnt/app/eso/hmi/lsd/jars/fw_util_tracing.jar || fail "baseline archive differs: fw_util_tracing.jar"
    check 433073376 89205 /mnt/app/eso/hmi/lsd/jars/fw_util_transport.jar || fail "baseline archive differs: fw_util_transport.jar"
    check 534936305 494162 /mnt/app/eso/hmi/lsd/jars/lang_data.zip || fail "baseline archive differs: lang_data.zip"
    check 2777033241 2205704 /mnt/app/eso/hmi/lsd/jars/locale.zip || fail "baseline archive differs: locale.zip"
    check 1550376410 30422 /mnt/app/eso/hmi/lsd/jars/xEventRecorder.jar || fail "baseline archive differs: xEventRecorder.jar"
    check 2556391359 4005 /mnt/app/eso/hmi/lsd/jars/xEventRecorderEvo.jar || fail "baseline archive differs: xEventRecorderEvo.jar"
    check 260923114 16749 /mnt/app/eso/hmi/lsd/jars/xTcpKeyPanel.jar || fail "baseline archive differs: xTcpKeyPanel.jar"
    check 3475392554 44082 /mnt/app/eso/hmi/lsd/jars/xTcpLog.jar || fail "baseline archive differs: xTcpLog.jar"
    archive_listing=$(find "$JARS" \( -name '*.jar' -o -name '*.zip' \)) || fail 'cannot enumerate HMI archives'
    while IFS= read -r archive; do
        case "$archive" in
            "/mnt/app/eso/hmi/lsd/jars/AppDevelopment.jar") check 483111144 250996 "$archive" || fail "archive changed: AppDevelopment.jar" ;;
            "/mnt/app/eso/hmi/lsd/jars/DevelopmentStubEvo.jar") check 1252008303 23585 "$archive" || fail "archive changed: DevelopmentStubEvo.jar" ;;
            "/mnt/app/eso/hmi/lsd/jars/NavActiveIgnore.jar") check 2960431692 2645 "$archive" || fail "archive changed: NavActiveIgnore.jar" ;;
            "/mnt/app/eso/hmi/lsd/jars/RemoteHMI-Libs-Ext.jar") check 2061441066 164348 "$archive" || fail "archive changed: RemoteHMI-Libs-Ext.jar" ;;
            "/mnt/app/eso/hmi/lsd/jars/diag.jar") check 960769547 493315 "$archive" || fail "archive changed: diag.jar" ;;
            "/mnt/app/eso/hmi/lsd/jars/fw_util_commons.jar") check 1380918901 110239 "$archive" || fail "archive changed: fw_util_commons.jar" ;;
            "/mnt/app/eso/hmi/lsd/jars/fw_util_config.jar") check 4212266484 68237 "$archive" || fail "archive changed: fw_util_config.jar" ;;
            "/mnt/app/eso/hmi/lsd/jars/fw_util_os.jar") check 1324906276 1268 "$archive" || fail "archive changed: fw_util_os.jar" ;;
            "/mnt/app/eso/hmi/lsd/jars/fw_util_serializer.jar") check 3578407106 45815 "$archive" || fail "archive changed: fw_util_serializer.jar" ;;
            "/mnt/app/eso/hmi/lsd/jars/fw_util_services.jar") check 1185153822 14589 "$archive" || fail "archive changed: fw_util_services.jar" ;;
            "/mnt/app/eso/hmi/lsd/jars/fw_util_tracing.jar") check 3183950927 280197 "$archive" || fail "archive changed: fw_util_tracing.jar" ;;
            "/mnt/app/eso/hmi/lsd/jars/fw_util_transport.jar") check 433073376 89205 "$archive" || fail "archive changed: fw_util_transport.jar" ;;
            "/mnt/app/eso/hmi/lsd/jars/lang_data.zip") check 534936305 494162 "$archive" || fail "archive changed: lang_data.zip" ;;
            "/mnt/app/eso/hmi/lsd/jars/locale.zip") check 2777033241 2205704 "$archive" || fail "archive changed: locale.zip" ;;
            "/mnt/app/eso/hmi/lsd/jars/xEventRecorder.jar") check 1550376410 30422 "$archive" || fail "archive changed: xEventRecorder.jar" ;;
            "/mnt/app/eso/hmi/lsd/jars/xEventRecorderEvo.jar") check 2556391359 4005 "$archive" || fail "archive changed: xEventRecorderEvo.jar" ;;
            "/mnt/app/eso/hmi/lsd/jars/xTcpKeyPanel.jar") check 260923114 16749 "$archive" || fail "archive changed: xTcpKeyPanel.jar" ;;
            "/mnt/app/eso/hmi/lsd/jars/xTcpLog.jar") check 3475392554 44082 "$archive" || fail "archive changed: xTcpLog.jar" ;;
            *) fail "unknown HMI archive: $archive" ;;
        esac
    done <<ARCHIVE_LIST
$archive_listing
ARCHIVE_LIST
    # An earlier interrupted install may have left a partial workspace. Accept
    # only a real root-owned 0700 directory; exact files are kept and anything
    # missing or different is replaced atomically below.
    if exists "$ROOT"; then
        [ -d "$ROOT" ] && [ ! -L "$ROOT" ] || fail 'runtime workspace is not a directory; preserve it'
        [ "$(dir_attrs "$ROOT")" = 'drwx------ 0 0' ] || fail 'runtime root attributes; preserve it'
        echo 'RESUME_WORKSPACE: existing runtime files are re-verified; mismatches are replaced'
    fi
elif [ "$action" = off ] || [ "$action" = on ]; then
    runtime_ok
    java_ok "$NEW" || fail 'F7 is not installed; switches belong to an installation'
elif [ "$action" = purge ]; then
    [ -d "$ROOT" ] && [ ! -L "$ROOT" ] || fail 'no runtime workspace to purge'
    [ "$(dir_attrs "$ROOT")" = 'drwx------ 0 0' ] || fail 'runtime root attributes; preserve it'
    install_phase=''; if [ -f "$ROOT/phase.txt" ]; then read -r install_phase < "$ROOT/phase.txt" || :; fi
    [ "$install_phase" = INSTALLATION_BASELINE_RESTORED ] || fail "purge needs a completed rollback (phase=${install_phase:-none})"
    old_si_ok "$SYSTEM" && old_si_ok "$ACTIVE" || fail 'baseline SI required at both paths: reboot after rollback, then purge'
    navignore_ok "$OLD" || fail 'NavActiveIgnore must be back in the scan tree'
    ! exists "$NEW" || fail 'F7 Java archive still installed'
    ! renderer_alive || fail 'renderer still running; reboot first'
    # F7 v2.1: purge only after the reboot that follows rollback (F7 v2 car run purged in
    # the rollback boot): no F7 Java, monitor or hooked DIO may still be running.
    for java_log in "$JAVA_LOG" "$JAVA_LOG.1"; do
        if [ -f "$java_log" ] && grep 'MU1320-F7-DAILY-V2 LISTENER_READY' "$java_log" >/dev/null 2>&1; then
            fail 'F7 Java ran in this boot: reboot after rollback, then purge'
        fi
    done
    if mon_alive; then fail 'F8 monitor still running: reboot after rollback, then purge'; fi
    command -v pidin >/dev/null 2>&1 || fail 'missing pidin'
    table=$(pidin -F '%a %256n') || fail 'cannot inspect live processes'
    while read -r p_pid p_name; do
        case "$p_pid" in ''|*[!0-9]*) continue ;; esac
        case "$p_name" in
            *dio_manager*)
                if pidin -p "$p_pid" environment 2>/dev/null | grep "$MARKER" >/dev/null 2>&1; then
                    fail "DIO $p_pid carries the F7 hook: reboot after rollback, then purge"
                fi ;;
        esac
    done <<PURGE_TABLE
$table
PURGE_TABLE
    cmp "$OLD" "$ROOT/backup/NavActiveIgnore.jar" >/dev/null || fail 'NavActiveIgnore differs from its backup; preserve the workspace'
    cmp "$SYSTEM" "$ROOT/backup/smartphone_integrator.json" >/dev/null || fail 'SI differs from its backup; preserve the workspace'
else
    stop_runtime
    [ "$DISARM_CLUSTER_OK" = 1 ] || echo 'WARNING: cluster not confirmed off context 80; the full restart after rollback clears it'
    case "$(navignore_state)" in ACTIVE_BASELINE|QUARANTINED|MISSING) ;; *) fail 'unknown NavActiveIgnore state; preserve it' ;; esac
    if old_si_ok "$SYSTEM" && ! exists "$NEW" && [ "$(navignore_state)" = ACTIVE_BASELINE ]; then echo 'ROLLBACK_ALREADY_BASELINE: full restart is still required if trial classes were loaded'; exit 0; fi
    runtime_ok
    if ! old_si_ok "$SYSTEM" && ! new_si_ok "$SYSTEM"; then fail 'system SI is neither baseline nor this trial'; fi
    if exists "$NEW"; then java_ok "$NEW" || fail 'unknown F7 archive; preserve it'; fi
fi
restore_app=0; restore_system=0; completed=0
cleanup() {
    rc=$?; trap - 0 1 2 15; set +e; sync || rc=1
    if [ "$restore_system" = 1 ]; then mount -ur /mnt/system || rc=1; fi
    if [ "$restore_app" = 1 ]; then mount -ur /mnt/app || rc=1; fi
    final_app=$(state /mnt/app); aq=$?; final_system=$(state /mnt/system); sq=$?
    if [ "$aq" != 0 ] || [ "$sq" != 0 ] || [ "$final_app:$final_system" != "$app_state:$system_state" ]; then echo 'STOP: original mounts not restored' >&2; rc=1; else echo "MOUNTS_RESTORED: app=$final_app system=$final_system"; fi
    if [ "$rc" = 0 ] && [ "$completed" = 1 ]; then echo "F7_${action}_FILES_PASSED: no restart performed"; elif [ "$action" = install ]; then echo 'INSTALL_INCOMPLETE: run rollback before restart' >&2; fi
    exit "$rc"
}
trap cleanup 0; trap 'exit 129' 1; trap 'exit 130' 2; trap 'exit 143' 15
if [ "$app_state" = ro ]; then restore_app=1; mount -uw /mnt/app || fail 'app remount rw'; fi
[ "$(state /mnt/app)" = rw ] || fail 'app not writable'
phase_write() {
    tmp="$ROOT/phase.pending.$$"; if exists "$tmp"; then fail 'phase collision'; fi
    printf '%s\n' "$1" > "$tmp" || fail "phase write $1"; mv "$tmp" "$ROOT/phase.txt" || fail "phase commit $1"; sync || fail "phase sync $1"
}
# put_file SRC DST MODE CKSUM SIZE LABEL keep|plain
# An exact existing DST is kept (never rewritten in place: a cached SI may still
# start a DIO that maps the old hook). Otherwise copy to a pending name, verify,
# then rename over DST.
put_file() {
    if check "$4" "$5" "$2"; then chmod "$3" "$2" || fail "$6 chmod"; echo "install_STEP: $6 already exact"; return 0; fi
    part="$2.pending.$$"; if exists "$part"; then fail "$6 pending collision"; fi
    echo "install_STEP: write $6"
    if [ "$7" = keep ]; then cp -p "$1" "$part" || fail "$6 copy"; else cp "$1" "$part" || fail "$6 copy"; fi
    chmod "$3" "$part" || fail "$6 chmod"; check "$4" "$5" "$part" || fail "$6 validation"
    mv "$part" "$2" || fail "$6 commit rename"
}
if [ "$action" = off ] || [ "$action" = on ]; then
    target="$ROOT/off-$component"
    if [ "$action" = off ]; then
        if ! exists "$target"; then (umask 077; : > "$target") || fail "switch write $component"; fi
        [ -f "$target" ] && [ ! -L "$target" ] || fail "switch state $component"
    elif exists "$target"; then
        [ -f "$target" ] && [ ! -L "$target" ] || fail "unexpected $target; preserve it"
        rm "$target" || fail "switch remove $component"
    fi
    sync || fail 'switch sync'; completed=1
    if [ "$action" = off ]; then word=OFF; else word=ON; fi
    echo "F7_SWITCH: $component=$word persistent, effective $(switch_note "$component")"
    exit 0
fi
if [ "$action" = purge ]; then
    echo 'purge_STEP: remove the rolled-back runtime workspace (stock files were compared with its backups)'
    rm -rf "$ROOT" || fail 'purge remove'
    ! exists "$ROOT" || fail 'workspace still present'
    sync || fail 'purge sync'; completed=1
    echo 'F7_PURGED: runtime workspace removed'
    exit 0
fi
if [ "$action" = install ]; then
    echo 'install_STEP: prepare private runtime workspace'
    umask 077
    for directory in "$ROOT" "$ROOT/backup" "$ROOT/config" "$ROOT/quarantine" "$ROOT/render" "$ROOT/mon"; do
        if exists "$directory"; then [ -d "$directory" ] && [ ! -L "$directory" ] || fail "unsafe runtime directory $directory"
        else mkdir "$directory" || fail "runtime mkdir $directory"; fi
    done
    put_file "$stage_dir/IDENTITY" "$ROOT/IDENTITY" 600 1788014713 19 'identity' plain
    put_file "$SYSTEM" "$ROOT/backup/smartphone_integrator.json" 644 535418540 7359 'SI backup' keep
    put_file "$OLD" "$ROOT/backup/NavActiveIgnore.jar" 777 2960431692 2645 'NavActiveIgnore backup' keep
    put_file "$stage_dir/libcarplay_hook.so" "$ROOT/libcarplay_hook.so" 644 1291246513 242082 'runtime hook' plain
    put_file "$stage_dir/dio_manager.json" "$ROOT/config/dio_manager.json" 644 1713239687 15784 'runtime dio config' plain
    put_file "$stage_dir/carplay_mu1320_f7_daily_v2.jar.DISABLED" "$ROOT/carplay_mu1320_f7_daily_v2.jar" 644 3555241766 147646 'runtime Java payload' plain
    put_file "$stage_dir/maneuver_render" "$ROOT/render/maneuver_render" 755 1766868864 120056 'runtime renderer' plain
    put_file "$stage_dir/flag_atlas.rgba" "$ROOT/render/flag_atlas.rgba" 644 2017122787 917504 'runtime flag atlas' plain
    put_file "$stage_dir/f5_sc.sh" "$ROOT/render/f5_sc.sh" 755 1010800451 2167 'runtime context helper' plain
    put_file "$stage_dir/f5_dm.sh" "$ROOT/render/f5_dm.sh" 644 3641631177 10620 'runtime displaymanager helper' plain
    put_file "$stage_dir/f4_unbuf.so" "$ROOT/render/f4_unbuf.so" 644 1988489462 5403 'runtime dmdt stdout shim' plain
    put_file "$stage_dir/f7_spawn" "$ROOT/render/f7_spawn" 755 292735868 8680 'runtime renderer launcher' plain
    put_file "$stage_dir/f7_render.sh" "$ROOT/render/f7_render.sh" 755 3779396577 5790 'runtime renderer keeper' plain
    put_file "$stage_dir/f8_mon.sh" "$ROOT/mon/f8_mon.sh" 755 2255473972 11899 'runtime monitor' plain
    put_file "$stage_dir/mount_state" "$ROOT/mon/mount_state" 755 2952412687 7302 'runtime monitor mount helper' plain
    sync || fail 'sync private runtime workspace'
    runtime_ok; cmp "$OLD" "$ROOT/backup/NavActiveIgnore.jar" >/dev/null || fail 'NavActiveIgnore changed during backup'
    phase_write BACKUPS_AND_RUNTIME_VERIFIED
    echo 'install_STEP: standalone hook loader check'
    run_clean "$stage_dir/loader_check" "$ROOT/libcarplay_hook.so" || fail 'standalone hook loader; SI not patched'
    pending="$JARS/.mu1320-f7.pending.$$"
    if exists "$pending"; then fail 'Java pending collision'; fi
    echo 'install_STEP: write pending Java archive'
    cp "$ROOT/carplay_mu1320_f7_daily_v2.jar" "$pending" || fail 'Java pending copy'
    chmod 644 "$pending" || fail 'Java pending chmod'; java_ok "$pending" || fail 'Java pending validation'
    sync || fail 'sync before Java commit'
    echo 'install_STEP: commit Java archive rename'
    mv "$pending" "$NEW" || fail 'Java commit rename'
    java_ok "$NEW" || fail 'Java install validation'; navignore_ok "$OLD" || fail 'NavActiveIgnore changed'
    phase_write JAVA_INSTALLED
    # Same qnx6 filesystem: rename moves NavActiveIgnore out of the recursive scan tree atomically.
    echo 'install_STEP: move NavActiveIgnore out of the scan tree'
    mv "$OLD" "$QUARANTINE" || fail 'NavActiveIgnore quarantine rename'
    navignore_ok "$QUARANTINE" || fail 'quarantined NavActiveIgnore validation'
    cmp "$QUARANTINE" "$BACKUP" >/dev/null || fail 'quarantine differs from backup'
    ! exists "$OLD" || fail 'NavActiveIgnore still in scan tree'
    phase_write NAVIGNORE_QUARANTINED
else
    source="$ROOT/backup/smartphone_integrator.json"
fi
echo "${action}_STEP: remount /mnt/system rw"
if [ "$system_state" = ro ]; then restore_system=1; mount -uw /mnt/system || fail 'system remount rw'; fi
[ "$(state /mnt/system)" = rw ] || fail 'system not writable'
if [ "$action" = install ]; then source="$stage_dir/smartphone_integrator.json"; fi
if [ "$action" = install ] || ! old_si_ok "$SYSTEM"; then
    pending="/mnt/system/etc/eso/production/.mu1320-f7-$action.$$"
    if exists "$pending"; then fail 'SI pending collision'; fi
    echo "${action}_STEP: write pending SI"
    if [ "$action" = rollback ]; then cp -p "$source" "$pending" || fail 'pending SI restore copy'; else cp "$source" "$pending" || fail 'pending SI install copy'; fi
    chmod 644 "$pending" || fail 'pending SI chmod'
    if [ "$action" = install ]; then new_si_ok "$pending" || fail 'candidate SI validation'; else old_si_ok "$pending" || fail 'restore SI validation'; fi
    sync || fail 'sync before SI commit'
    echo "${action}_STEP: commit SI rename"
    mv "$pending" "$SYSTEM" || fail 'SI commit rename'
fi
if [ "$action" = install ]; then new_si_ok "$SYSTEM" || fail 'installed SI validation'; phase_write SI_COMMITTED
else
    old_si_ok "$SYSTEM" || fail 'restored SI validation'; phase_write SI_RESTORED
    if ! navignore_ok "$OLD"; then
        if navignore_ok "$QUARANTINE"; then
            echo 'rollback_STEP: move quarantined NavActiveIgnore back'
            mv "$QUARANTINE" "$OLD" || fail 'NavActiveIgnore restore rename'
        else
            pending="$JARS/.mu1320-f7-restore.pending.$$"
            if exists "$pending"; then fail 'restore pending collision'; fi
            echo 'rollback_STEP: restore NavActiveIgnore from verified backup'
            cp -p "$BACKUP" "$pending" || fail 'NavActiveIgnore restore copy'
            chmod 777 "$pending" || fail 'NavActiveIgnore restore chmod'
            navignore_ok "$pending" || fail 'NavActiveIgnore restore validation'
            mv "$pending" "$OLD" || fail 'NavActiveIgnore restore commit'
        fi
    fi
    navignore_ok "$OLD" || fail 'restored NavActiveIgnore validation'; phase_write NAVIGNORE_RESTORED
    if exists "$NEW"; then
        removed="$ROOT/removed-java.$$"; if exists "$removed"; then fail 'Java removal collision'; fi
        echo 'rollback_STEP: move F7 Java archive out of the scan tree'
        mv "$NEW" "$removed" || fail 'Java removal rename'; java_ok "$removed" || fail 'removed Java validation'
    fi
    ! exists "$NEW" || fail 'F7 Java still active'; navignore_ok "$OLD" || fail 'NavActiveIgnore baseline not restored'
    cmp "$OLD" "$ROOT/backup/NavActiveIgnore.jar" >/dev/null || fail 'NavActiveIgnore differs from trial backup'
    phase_write INSTALLATION_BASELINE_RESTORED
fi
sync || fail 'final sync'; completed=1
