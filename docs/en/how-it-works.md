# How it works

The patch never replaces CarPlay (`libairplay.so` stays byte-identical). It listens in on the
iAP2 conversation between the iPhone and the stock `dio_manager`, and drives the cluster with what
it hears. Three processes cooperate:

| Component | Language | Runs in | Role |
| --- | --- | --- | --- |
| `libcarplay_hook.so` | C, ARM32 QNX | `LD_PRELOAD`ed into `dio_manager` only | Intercepts iAP2 route-guidance messages (TLVs `0x5200`–`0x5204`) |
| Java patch (JAR) | Java 1.4 | HMI VM (`j9`, from boot) | Maps route data to BAP functions for the Virtual Cockpit/HUD, drives the renderer, bridges touchpad input |
| `maneuver_render` | C, EGL/GLES2 | Own process, started by the keeper | Draws the maneuver overlay (displayable 98, transparent when idle) over the native cluster map |

```text
iPhone ──iAP2──► dio_manager (stock libairplay 210.81 + hook)
                     │  TCP 127.0.0.1:19810   (hook → Java bus)
                     ▼
               HMI Java patch ──► BAP FctIDs ──► Virtual Cockpit / HUD
                     │  TCP 127.0.0.1:19800   (CMD_MANEUVER)
                     ▼
               maneuver_render ──► overlay composited on the native cluster map
```

## Boot and activation order

1. The HMI starts at boot; the Java patch is already `accept()`ing on the bus port.
2. When a phone connects, `smartphone_integrator` (SI) spawns `dio_manager`. The `dio_manager`
   entry in our edited SI config carries the hook's `LD_PRELOAD` (and a trial marker) for that process only, so the hook's constructor
   fires on connect and not before.
3. The hook connects to the Java bus. On the first CarPlay session of each boot the Java side starts
   the **renderer keeper** (through `f7_spawn`), which starts `maneuver_render` and, from F8 on,
   the **monitor**.
4. Guidance data flows hook → Java → BAP + renderer until the route ends or the phone disconnects.

## Safety mechanisms

- **Opt-in lifecycle.** `f7.sh install` writes files to `/mnt/app/root/mu1320-rgi-f7-v2` and the SI/DIO
  configs after backing up every original; `rollback` restores them; `purge` removes the workspace.
  Both refuse to run unless the current state is what they expect (`STOP: ...`).
- **Crash guard.** Each hook generation records itself; after three quick DIO generations (rapid
  USB re-plugging) the next one goes passive until reboot. The gate files are written directly
  because `/tmp` on the unit is shared memory and does not support `rename` (found in the car, fix B11).
- **Emergency stop.** Switches BAP off through a runtime flag, waits for Java to release the cluster
  context and restore the stock display, then stops the renderer. Stock behaviour returns within seconds
  without unplugging; a reboot re-enables the patch (fix B12).
- **Runtime switches** (`/tmp/mu1320-f5-bap-off`, `-render-off`, `-f6-touchpad-off`,
  `-f7-native-off`, `/tmp/mu1320-f8-mon-off`) disable one component for the current boot; `f7.sh off|on`
  makes it persistent.
- **Environment hygiene.** Menu actions run with `cd /`, `umask 022` and no relative entries in
  `LD_LIBRARY_PATH`, because the Toolbox menu starts scripts with `.` in its path and `umask 000`.
- **Checksums everywhere.** Scripts verify the cksum of binaries they are about to start.

## The monitor (F8)

`f8_mon.sh` samples every 60 s: free memory, CPU time, thread count, data size and descriptor count
of `dio_manager`, `smartphone_integrator`, `j9`, `displaymanager`, `maneuver_render`, `screen`, `io-usb`,
plus `/tmp` log sizes. Every 2 minutes it appends to `out/f8/boot-<seq>-<pid>/samples.txt` on the SD
and mirrors changed F7 logs; every 10 minutes it saves `sloginfo` and the `/mnt/ota` dump listing.
It temporarily remounts the SD read-write for a few seconds and restores read-only; it never writes
to `/mnt/app` or `/mnt/system` and never calls `dmdt`. A shared lock (`/tmp/mu1320-f8-sd.lock`)
keeps menu actions and flushes from changing the SD state under each other.

## Cluster display contexts (for the curious)

The overlay composes over the stock cluster context at rest; while guidance is active the patch
takes a custom set of layers (overlay 98 with 101, 102 and the native map 33). In the first car test
the stock code rewrote the patch's switch request into context 73, which led to the supported "KDK
default" mode of the later versions (F5 v5). Pressing VIEW on the car can briefly show the stock KDK
placeholder (known limit B5). The reverse-engineering record is in the upstream project's `docs/`
vault and in [`docs/zh-CN/reports/`](../zh-CN/reports/) (`F5-*`).
