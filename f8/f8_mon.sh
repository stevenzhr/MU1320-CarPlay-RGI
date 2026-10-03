#!/bin/sh
# MU1320 F8 monitor (F7 v2.1; BACKLOG B10).  Long-term evidence without a Collect
# press: every SAMPLE_S seconds it records free memory and, for the processes F7
# touches, CPU times, thread count, data size and descriptor count into a buffer
# in /tmp; every FLUSH_EVERY samples it appends the buffer and copies the changed
# F7 logs to the SD card, out/f8/boot-<seq>-<pid>/ inside the F7 v2.1 folder.
#
#   f8_mon.sh run      started by f7_render.sh through f7_spawn (detached, default
#                      signals, no inherited descriptors) on the first CarPlay
#                      session of a boot; one instance per boot.
#
# It runs until the unit powers off.  It ends by itself when F7 is uninstalled
# (the Java archive left the scan tree), when /tmp/mu1320-f8-mon-off or the
# persistent switch <workspace>/off-monitor exists, or after an exit request.
# The SD is optional: without the card (or without the folder) samples stay in
# the /tmp buffer (capped) and nothing is written.  An SD that was read-only is
# remounted read-write only for the flush and put back; f7.sh takes the same
# lock (/tmp/mu1320-f8-sd.lock), so a menu action never sees the card change
# under it.  Nothing is written to /mnt/app or /mnt/system.  Read-only queries
# only (pidin, sloginfo, ls); never dmdt.
# /tmp is /dev/shmem on this unit: flat files only, no rename.
PATH=/proc/boot:/bin:/usr/bin:/sbin:/usr/sbin:/mnt/app/armle/bin:/mnt/app/armle/usr/bin
export PATH
LD_LIBRARY_PATH=/proc/boot:/lib:/usr/lib:/mnt/app/armle/lib:/mnt/app/armle/usr/lib
export LD_LIBRARY_PATH
for var in LD_PRELOAD LD_DEBUG DL_DEBUG LD_DEBUG_OUTPUT; do unset "$var" || :; done
umask 077
ROOT=/mnt/app/root/mu1320-rgi-f7-v2
MON=$ROOT/mon
JAR=/mnt/app/eso/hmi/lsd/jars/CarPlayRGI-MU1320-F7DailyV2.jar
FOLDER=mu1320-f7-daily-v2.1
SDS='/fs/sda0 /fs/sdb0'
RUN=/tmp/mu1320-f8-mon.run
BUF=/tmp/mu1320-f8-mon.buf
STATE=/tmp/mu1320-f8-mon.state
OUTLOG=/tmp/mu1320-f8-mon.log
LOCK=/tmp/mu1320-f8-sd.lock
OFF=/tmp/mu1320-f8-mon-off
SCRATCH=/tmp/mu1320-f8-mon-scratch
SAMPLE_S=60
FLUSH_EVERY=2
SLOG_EVERY=5
BUF_CAP=1048576
OUTLOG_CAP=262144
SD_CAP=268435456
BIG=1048576
BIG_EVERY=5
TARGETS='dio_manager smartphone_integrator displaymanager j9 maneuver_render screen io-usb'
LOGS='carplay_hook.log carplay_java.log carplay_java.log.1 mu1320-f5-state.log mu1320-f5-frames.cap mu1320-f5-bap.log mu1320-f5-render.log mu1320-f5-renderer.log mu1320-f5-sc.log mu1320-f6-touchpad.log mu1320-f7-keeper.log mu1320-f7-gate.last mu1320-f7-gate.strikes mu1320-f8-mon.log'
[ "$#" = 1 ] && [ "$1" = run ] || { echo 'usage: f8_mon.sh run'; exit 2; }
# Messages go to the monitor log on fd 3: a signal trap may run while a sample's
# output is redirected into the buffer.
exec 3>&1
say() { echo "MON $*" >&3; }
exists() { [ -e "$1" ] || [ -L "$1" ]; }
size() { sz_out=$(ls -ln "$1" 2>/dev/null) || { echo 0; return 0; }; set -f; set -- $sz_out; set +f; echo "${5:-0}"; }
stamp() { st_out=$(ls -ln "$1" 2>/dev/null) || { echo -; return 0; }; set -f; set -- $st_out; set +f; echo "${5:-0}:${6:-}${7:-}${8:-}"; }
holder() { h=''; if [ -f "$1" ]; then read -r h < "$1" || :; fi; case "$h" in ''|*[!0-9]*) echo '' ;; *) echo "$h" ;; esac; }

# ---- one instance per boot (O_EXCL file; a dead holder is replaced) ----------------
take() {
    if (set -C; echo "$$" > "$1") 2>/dev/null; then return 0; fi
    tk=$(holder "$1")
    if [ -n "$tk" ] && [ "$tk" != "$$" ] && kill -0 "$tk" 2>/dev/null; then return 1; fi
    rm -f "$1" || return 1
    (set -C; echo "$$" > "$1") 2>/dev/null
}
give() { if [ "$(holder "$1")" = "$$" ]; then rm -f "$1" || :; fi; }
if ! take "$RUN"; then say "DUPLICATE pid=$$ holder=$(holder "$RUN")"; exit 0; fi

seq=0; flushes=0; sd_bytes=0; dir=''; sd=''; end_reason=''; mirror=1
declare_state() {
    printf 'MON pid=%s samples=%s flushes=%s sd_bytes=%s dir=%s mirror=%s end=%s\n' \
        "$$" "$seq" "$flushes" "$sd_bytes" "${dir:-none}" "$mirror" "${end_reason:-running}" > "$STATE" 2>/dev/null || :
}
finish() {
    trap - 0 1 2 15
    [ -n "$end_reason" ] || end_reason=signal
    echo "=== END reason=$end_reason samples=$seq" >> "$BUF" 2>/dev/null
    flush final || :
    declare_state
    say "END pid=$$ reason=$end_reason samples=$seq flushes=$flushes sd_bytes=$sd_bytes"
    give "$RUN"
    rm -f "$SCRATCH" || :
    exit 0
}
trap finish 0
trap 'end_reason=int; exit 0' 2
trap 'end_reason=term; exit 0' 15

# ---- SD -------------------------------------------------------------------------------
mstate() { (LD_LIBRARY_PATH=/proc/boot:/lib exec "$MON/mount_state" "$1") 2>/dev/null; }
find_sd() {
    sd=''
    for fs_sd in $SDS; do
        if [ -d "$fs_sd/$FOLDER" ] && [ ! -L "$fs_sd/$FOLDER" ] && [ -f "$fs_sd/$FOLDER/TOOLBOX-ENTRY" ]; then sd=$fs_sd; return 0; fi
    done
    return 1
}
# The lock is shared with f7.sh: whoever holds it owns the SD mount state.
sd_lock() {
    n=0
    while ! take "$LOCK"; do
        [ "$n" -lt "$1" ] || return 1
        sleep 1; n=$((n + 1))
    done
    return 0
}
# copy SRC NAME: SRC to <dir>/logs/NAME through a pending name; counts the bytes.
copy() {
    cp_part="$dir/logs/$2.pending"
    rm -f "$cp_part" 2>/dev/null || :
    cp "$1" "$cp_part" 2>/dev/null || { rm -f "$cp_part" 2>/dev/null; return 1; }
    rm -f "$dir/logs/$2" 2>/dev/null || :
    mv "$cp_part" "$dir/logs/$2" 2>/dev/null || return 1
    sd_bytes=$((sd_bytes + $(size "$dir/logs/$2")))
}
open_dir() {
    out="$sd/$FOLDER/out"
    [ ! -L "$out" ] || return 1
    [ -d "$out" ] || mkdir "$out" || return 1
    [ -d "$out/f8" ] || mkdir "$out/f8" || return 1
    last=0
    if [ -f "$out/f8/SEQ" ]; then read -r last < "$out/f8/SEQ" || :; fi
    case "$last" in ''|*[!0-9]*) last=0 ;; esac
    next=$((last + 1))
    echo "$next" > "$out/f8/SEQ" || return 1
    dir="$out/f8/boot-$next-$$"
    mkdir "$dir" && mkdir "$dir/logs" || { dir=''; return 1; }
    say "DIR $dir"
}
# flush [final]: buffer -> samples.txt, changed logs -> logs/, sloginfo now and then.
flush() {
    find_sd || { say "NO_SD flush=$((flushes + 1))"; return 1; }
    # final: a rollback holds the lock for up to ~30 s (stop waits for Java) before the
    # monitor sees the archive gone; wait for it so the END record reaches the SD.
    if [ "$1" = final ]; then wait_s=60; else wait_s=20; fi
    sd_lock "$wait_s" || { say "SD_BUSY holder=$(holder "$LOCK")"; return 1; }
    initial=$(mstate "$sd"); restore=0; ok=1
    case "$initial" in
        ro) if mount -uw "$sd" 2>/dev/null; then restore=1; else ok=0; fi ;;
        rw) ;;
        *) ok=0 ;;
    esac
    if [ "$ok" = 1 ] && [ "$(mstate "$sd")" = rw ]; then
        if [ -z "$dir" ]; then open_dir || ok=0; fi
    else
        ok=0
    fi
    if [ "$ok" = 1 ]; then
        flushes=$((flushes + 1))
        if cat "$BUF" >> "$dir/samples.txt" 2>/dev/null; then
            sd_bytes=$((sd_bytes + $(size "$BUF"))); : > "$BUF"
        else
            ok=0
        fi
        if [ "$mirror" = 1 ] && [ "$sd_bytes" -ge "$SD_CAP" ]; then
            mirror=0; echo "=== MIRROR_CAP sd_bytes=$sd_bytes" >> "$dir/samples.txt" 2>/dev/null || :
        fi
        if [ "$mirror" = 1 ]; then
            i=0
            for name in $LOGS; do
                i=$((i + 1)); f=/tmp/$name
                [ -f "$f" ] && [ ! -L "$f" ] || continue
                now=$(stamp "$f")
                eval "was=\${seen_$i-}"
                [ "$now" != "$was" ] || continue
                if [ "$(size "$f")" -gt "$BIG" ] && [ "$1" != final ] && [ $((flushes % BIG_EVERY)) != 1 ]; then continue; fi
                if copy "$f" "$name"; then eval "seen_$i=\$now"; fi
            done
            for f in /tmp/mu1320-f7-gate-*; do
                [ -f "$f" ] && [ ! -L "$f" ] || continue
                name=${f##*/}
                [ -f "$dir/logs/$name" ] || copy "$f" "$name" || :
            done
            if [ "$1" = final ] || [ $((flushes % SLOG_EVERY)) = 1 ]; then
                if sloginfo > "$dir/logs/sloginfo.pending" 2>&1; then
                    rm -f "$dir/logs/sloginfo.txt" 2>/dev/null || :
                    mv "$dir/logs/sloginfo.pending" "$dir/logs/sloginfo.txt" 2>/dev/null || :
                    sd_bytes=$((sd_bytes + $(size "$dir/logs/sloginfo.txt")))
                fi
                { echo "=== OTA flush=$flushes"; ls -ln /mnt/ota/system/logs 2>&1; df -k "$sd" /mnt/ota 2>&1; } >> "$dir/samples.txt" 2>/dev/null || :
            fi
        fi
        sync || ok=0
    fi
    if [ "$restore" = 1 ]; then mount -ur "$sd" 2>/dev/null || ok=0; fi
    final_state=$(mstate "$sd")
    if [ "$final_state" != "$initial" ]; then say "SD_RESTORE_FAILED initial=$initial now=$final_state"; ok=0; fi
    give "$LOCK"
    declare_state
    [ "$ok" = 1 ]
}

# ---- samples ----------------------------------------------------------------------------
cap_buffer() {
    if [ "$(size "$BUF")" -gt "$BUF_CAP" ]; then : > "$BUF"; echo "=== BUFFER_DROPPED cap=$BUF_CAP" >> "$BUF"; fi
    if [ "$(size "$OUTLOG")" -gt "$OUTLOG_CAP" ]; then : > "$OUTLOG"; say "LOG_TRUNCATED"; fi
}
# target NAME: the process name is the last path component (pidin pads with spaces).
target() { for t_name in $TARGETS; do [ "$1" = "$t_name" ] && return 0; done; return 1; }
sample() {
    seq=$((seq + 1))
    {
        echo "=== S $seq date=$(date +%Y%m%d-%H%M%S 2>/dev/null || echo -)"
        echo '--- info'; pidin info 2>&1
        echo '--- times'; pidin times 2>&1
        pidin -F '%a %e %256n' > "$SCRATCH" 2>/dev/null || :
        while read -r s_pid s_ppid s_name; do
            case "$s_pid" in ''|*[!0-9]*) continue ;; esac
            s_base=${s_name##*/}
            target "$s_base" || continue
            # threads and data size from the per-thread table (car-proven "pidin mem");
            # descriptors from "pidin fds" (count of lines, header included).
            s_thr=0; s_first=''
            pidin -p "$s_pid" mem > "$SCRATCH.p" 2>/dev/null || :
            while read -r m_pid m_rest; do
                if [ "$m_pid" = "$s_pid" ]; then s_thr=$((s_thr + 1)); [ -n "$s_first" ] || s_first=$m_rest; fi
            done < "$SCRATCH.p"
            s_fds=0
            pidin -p "$s_pid" fds > "$SCRATCH.p" 2>/dev/null || :
            while read -r m_line; do s_fds=$((s_fds + 1)); done < "$SCRATCH.p"
            echo "P $s_base pid=$s_pid ppid=$s_ppid threads=$s_thr fds_lines=$s_fds first=$s_first"
        done < "$SCRATCH"
        rm -f "$SCRATCH.p" || :
        echo '--- tmp'
        for f in /tmp/carplay_* /tmp/mu1320-*; do [ -f "$f" ] && echo "F $(size "$f") $f"; done
    } >> "$BUF" 2>&1
}
stop_requested() {
    if [ ! -f "$JAR" ]; then end_reason=uninstalled; return 0; fi
    if exists "$OFF"; then end_reason=off; return 0; fi
    if exists "$ROOT/off-monitor"; then end_reason=off-persistent; return 0; fi
    return 1
}

say "BEGIN pid=$$ ppid=$PPID sample=${SAMPLE_S}s flush_every=$FLUSH_EVERY"
{
    echo "=== START pid=$$ ppid=$PPID date=$(date +%Y%m%d-%H%M%S 2>/dev/null || echo -)"
    uname -a 2>&1
    cat "$ROOT/IDENTITY" 2>&1
    cksum "$ROOT/libcarplay_hook.so" "$ROOT/carplay_mu1320_f7_daily_v2.jar" "$ROOT/render/maneuver_render" \
        "$ROOT/render/f7_render.sh" "$MON/f8_mon.sh" "$JAR" 2>&1
    for f in /tmp/mu1320-f7-gate.last /tmp/mu1320-f7-gate.strikes; do if [ -f "$f" ]; then echo "GATE $f $(cat "$f")"; fi; done
    for s in /tmp/mu1320-f5-bap-off /tmp/mu1320-f5-render-off /tmp/mu1320-f6-touchpad-off /tmp/mu1320-f7-native-off /tmp/mu1320-f7-render-hold; do
        if exists "$s"; then echo "SWITCH $s PRESENT"; fi
    done
    for c in native render bap touchpad monitor; do if exists "$ROOT/off-$c"; then echo "SWITCH off-$c PERSISTENT"; fi; done
} >> "$BUF" 2>&1
declare_state
n=0
while :; do
    if stop_requested; then break; fi
    sample
    cap_buffer
    n=$((n + 1))
    if [ "$n" -ge "$FLUSH_EVERY" ]; then n=0; flush regular || :; fi
    declare_state
    sleep "$SAMPLE_S"
done
exit 0
