# MU1320 Toolbox v1: F7 green-menu dispatcher, sourced by the five button scripts
# (f7_status.sh, f7_install.sh, f7_uninstall.sh, f7_collect.sh, f7_stop.sh).
#
# Thin by design: all logic stays in the F7 folder on the SD card, so a new F7 version
# needs no Toolbox update.  The dispatcher
#   - cleans the environment a GEM script starts with (Toolbox v0 on the car: PATH and
#     LD_LIBRARY_PATH begin with ".", umask 000, cwd /mnt/app/eso);
#   - allows one button at a time (lock in /tmp; a stale lock of a dead pid is replaced);
#   - finds exactly one F7 folder on the SD root that carries TOOLBOX-ENTRY;
#   - runs its f7.sh (which remounts the SD, writes the full log to out/ and restores
#     the SD) with the output kept in /tmp, and shows a summary of at most 10 lines of
#     at most 60 characters (the console shows about 12 lines of about 60 characters).
# It writes nothing to the SD or /mnt itself.  Never "dmdt ts".
F7M_SDS='/fs/sda0 /fs/sdb0'
F7M_LOCK=/tmp/mu1320-f7-menu.lock
F7M_OUT=/tmp/mu1320-f7-menu-$$.txt
F7M_ENTRY='MU1320_F7_TOOLBOX_ENTRY 1'

f7m_say() { printf '%.60s\n' "$*"; }

f7m_env() {
    PATH=/proc/boot:/bin:/usr/bin:/sbin:/usr/sbin:/mnt/app/armle/bin:/mnt/app/armle/usr/bin
    export PATH
    for f7m_v in LD_PRELOAD LD_DEBUG DL_DEBUG LD_DEBUG_OUTPUT; do unset "$f7m_v" || :; done
    f7m_keep=''; f7m_ifs=$IFS; IFS=:; set -f
    for f7m_d in ${LD_LIBRARY_PATH:-}; do case "$f7m_d" in /*) f7m_keep=${f7m_keep:+$f7m_keep:}$f7m_d ;; esac; done
    set +f; IFS=$f7m_ifs
    if [ -n "$f7m_keep" ]; then LD_LIBRARY_PATH=$f7m_keep; export LD_LIBRARY_PATH; else unset LD_LIBRARY_PATH || :; fi
    cd / || return 1
    umask 022
}

# f7m_lock: 0 when this process holds the lock, 1 when another live button holds it.
f7m_lock() {
    if (set -C; echo "$$" > "$F7M_LOCK") 2>/dev/null; then return 0; fi
    f7m_holder=''
    if [ -f "$F7M_LOCK" ]; then read -r f7m_holder < "$F7M_LOCK" || :; fi
    case "$f7m_holder" in
        ''|*[!0-9]*) ;;
        *) if kill -0 "$f7m_holder" 2>/dev/null; then return 1; fi ;;
    esac
    rm -f "$F7M_LOCK" || return 1
    (set -C; echo "$$" > "$F7M_LOCK") 2>/dev/null
}

f7m_unlock() {
    f7m_holder=''
    if [ -f "$F7M_LOCK" ]; then read -r f7m_holder < "$F7M_LOCK" || :; fi
    if [ "$f7m_holder" = "$$" ]; then rm -f "$F7M_LOCK" || :; fi
}

# f7m_find: sets F7M_DIR to the single SD folder with a valid TOOLBOX-ENTRY; F7M_COUNT.
f7m_find() {
    F7M_DIR=''; F7M_COUNT=0
    for f7m_sd in $F7M_SDS; do
        [ -d "$f7m_sd" ] || continue
        for f7m_c in "$f7m_sd"/mu1320-f7-*; do
            if [ -d "$f7m_c" ] && [ ! -L "$f7m_c" ] && [ -f "$f7m_c/TOOLBOX-ENTRY" ]; then :; else continue; fi
            f7m_first=''
            read -r f7m_first < "$f7m_c/TOOLBOX-ENTRY" || :
            [ "$f7m_first" = "$F7M_ENTRY" ] || continue
            F7M_COUNT=$((F7M_COUNT + 1)); F7M_DIR=$f7m_c
        done
    done
}

# f7m_get KEY: value of the first "KEY: value" line of the output (empty if absent).
f7m_get() {
    f7m_val=''
    while IFS= read -r f7m_l || [ -n "$f7m_l" ]; do
        case "$f7m_l" in "$1: "*) f7m_val=${f7m_l#"$1: "}; break ;; esac
    done < "$F7M_OUT"
    echo "$f7m_val"
}

f7m_word() { set -f; set -- $1; set +f; echo "${1:-?}"; }

f7m_status_summary() {
    f7m_say "SI: $(f7m_get SYSTEM_CONFIG)/$(f7m_get ACTIVE_CONFIG)"
    f7m_say "JAVA: $(f7m_get JAVA_ARCHIVE)  NAVIGNORE: $(f7m_get NAV_ACTIVE_IGNORE)"
    f7m_say "LISTENER: $(f7m_get JAVA_LISTENER)  RENDER: $(f7m_word "$(f7m_get F7_RENDERER)")"
    f7m_say "CLUSTER: $(f7m_word "$(f7m_get DM_CLUSTER_CONTEXT)")  HOLD: $(f7m_get RENDER_HOLD)  BAPOFF: $(f7m_get BAP_KILL_SWITCH)"
    f7m_say "GATE: strikes=$(f7m_get GATE_STRIKES) last=$(f7m_word "$(f7m_get GATE_LAST)")"
    f7m_off=''
    for f7m_c in native render bap touchpad; do
        case "$(f7m_get "SWITCH_$f7m_c")" in on) ;; *) f7m_off="$f7m_off $f7m_c" ;; esac
    done
    f7m_say "OFF (persistent):${f7m_off:- none}"
}

# f7m_lines [status]: the interesting lines of an action (at most 4, only STOP lines for
# status, whose summary is built by f7m_status_summary); LOG/SAVED/PASSED remembered.
f7m_lines() {
    f7m_n=0; f7m_more=0; F7M_LOG=''; F7M_SAVED=''; F7M_PASSED=0
    while IFS= read -r f7m_l || [ -n "$f7m_l" ]; do
        case "$f7m_l" in
            'ACTION_LOG_ON_SD: '*) F7M_LOG=${f7m_l#*/out/}; continue ;;
            'SAVED_ON_SD: '*) F7M_SAVED=${f7m_l#*/out/}; continue ;;
            F7_ACTION_PASSED) F7M_PASSED=1; continue ;;
            F7_COLLECT_BEGIN*|F7_COLLECT_END*) continue ;;
            STOP:*) ;;
            *) if [ "${1:-}" = status ]; then continue; fi ;;
        esac
        case "$f7m_l" in
            STOP:*|WARNING:*|F7_STOPPED:*|F7_*_FILES_PASSED:*|JAVA_RELEASE:*|JAVA_CLUSTER_CONTEXT:*|DISARM_CLUSTER_CONTEXT:*|RESUME_WORKSPACE:*|\
            ROLLBACK_ALREADY_BASELINE:*|INSTALL_INCOMPLETE:*|COLLECT_EXIT=*|DIO_PROCESSES_OBSERVED=*|usage:*) ;;
            *) continue ;;
        esac
        if [ "$f7m_n" -lt 4 ]; then f7m_say "$f7m_l"; f7m_n=$((f7m_n + 1)); else f7m_more=$((f7m_more + 1)); fi
    done < "$F7M_OUT"
    if [ "$f7m_more" -gt 0 ]; then f7m_say "(+$f7m_more more lines in the log)"; fi
}

# f7m_main status|install|uninstall|collect|stop
f7m_main() {
    f7m_action=$1
    case "$f7m_action" in
        status) set -- status ;;
        install) set -- install ;;
        uninstall) set -- rollback ;;
        collect) set -- collect snapshot ;;
        stop) set -- stop ;;
        *) f7m_say "MU1320 F7: unknown button $f7m_action"; f7m_say 'RESULT: FAILED'; exit 2 ;;
    esac
    f7m_say "MU1320 F7: $f7m_action"
    if f7m_env; then :; else f7m_say 'FAIL: cannot clean the environment'; f7m_say 'RESULT: FAILED'; exit 2; fi
    if f7m_lock; then :; else f7m_say 'BUSY: another MU1320 button is still running'; f7m_say 'RESULT: FAILED'; exit 3; fi
    trap 'f7m_unlock; rm -f "$F7M_OUT"' 0
    trap 'exit 129' 1; trap 'exit 130' 2; trap 'exit 143' 15
    f7m_find
    if [ "$F7M_COUNT" != 1 ]; then
        if [ "$F7M_COUNT" = 0 ]; then f7m_say 'NO F7 FOLDER: need one mu1320-f7-*/ with'
        else f7m_say "$F7M_COUNT F7 FOLDERS: keep only one mu1320-f7-*/ with"; fi
        f7m_say '  TOOLBOX-ENTRY in the SD root (/fs/sda0 or /fs/sdb0)'
        f7m_say 'RESULT: FAILED'
        exit 2
    fi
    if [ -f "$F7M_DIR/f7.sh" ] && [ ! -L "$F7M_DIR/f7.sh" ]; then :; else
        f7m_say "FAIL: ${F7M_DIR##*/}/f7.sh missing"; f7m_say 'RESULT: FAILED'; exit 2
    fi
    f7m_say "Folder: ${F7M_DIR##*/}"
    f7m_rc=0
    /bin/sh "$F7M_DIR/f7.sh" "$@" < /dev/null > "$F7M_OUT" 2>&1 || f7m_rc=$?
    if [ "$f7m_action" = status ] && [ -n "$(f7m_get SYSTEM_CONFIG)" ]; then f7m_status_summary; fi
    f7m_lines "$f7m_action"
    if [ -n "$F7M_SAVED" ]; then f7m_say "Saved: out/$F7M_SAVED"; fi
    if [ -n "$F7M_LOG" ]; then f7m_say "Log: out/$F7M_LOG"; else f7m_say 'Log: none (see the lines above)'; fi
    if [ "$f7m_rc" = 0 ] && [ "$F7M_PASSED" = 1 ]; then
        case "$f7m_action" in install|uninstall) f7m_say 'NEXT: full restart of the MMI' ;; esac
        f7m_say 'RESULT: OK'
        exit 0
    fi
    [ "$f7m_rc" != 0 ] || f7m_rc=1
    f7m_say "RESULT: FAILED ($f7m_rc)"
    exit "$f7m_rc"
}
