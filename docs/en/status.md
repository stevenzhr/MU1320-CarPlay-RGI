# Verification status (v0.9.0-rc.1)

Everything here was observed on **one car**: MU1320, `MHI2Q_US_AUG22_P4246`, wired CarPlay,
iPhone with Apple Maps and Google Maps. Nothing is claimed for other firmware, other cars or Android
Auto. Chronological evidence lives in [`docs/zh-CN/reports/`](../zh-CN/reports/) (Chinese).

## What passed in the car

| Area | Result | Evidence |
| --- | --- | --- |
| Receive route data in the hook (iAP2 `0x5201/0x5202/0x5204`), runtime rollback | passed | `NAVHOOK-TRIAL-VEHICLE-V1-REVIEW.md` |
| `LD_PRELOAD` via SI env into the real `dio_manager`, and its removal | passed | `ENV-PROBE-…`, `PRELOAD-PROBE-…` |
| Hook → Java ingest, BAP output, renderer overlay, VC/HUD integration (F3–F5) | passed | `F3-…`, `F4-…`, `F5-VCHUD-*` |
| Acceptance across apps and dynamic routes, touchpad bridge (F6 v3) | passed | `F6-V3-REVIEW.md` |
| Green-menu lifecycle: install, status, collect, uninstall, emergency stop (F7 v2) | passed, audit 26/26 | `F7-DAILY-V2-VEHICLE-REVIEW.md` |
| Crash guard (strikes → passive) and emergency stop clearing VC/HUD without unplugging | passed | same |
| F8 session I (install), M (monitor on a parked car) | passed 2026-10-03 | `F8-V2.1-VEHICLE-LIM-REVIEW.md` |

## Still open for the F8 candidate

- **Session L** — cleaning the older v1.1 workspace left on the car: not done.
- **Session N** — daily use, at least 10 cold boots over several days, with the monitor recording.
- **Session X** — final uninstall and reinstall.
- The monitor's `pidin` outputs were confirmed on the car; its long-run behaviour is not.

So v0.9.0-rc.1 is a **release candidate that has passed acceptance sessions I and M**, not a completed soak. v1.0.0 will be cut once sessions N and X pass.

## Known limitations

| ID | Limitation |
| --- | --- |
| — | **HMI-failure recovery is unverified**: only a cold-start SSH login via the car's hotspot has been shown |
| B1 | The big-map popup shows the arrow and progress bar but no turn distance (kept as stock design) |
| B2 | After arrival the arrival symbol stays until you end navigation on the phone (iOS keeps the route in `ARRIVED`) |
| B4/B5 | Pressing VIEW can briefly show the stock KDK placeholder; fixing it would require replacing a core HMI class |
| — | ETA and destination distance are not shown on VC/HUD (not even with stock behaviour on this car) |
| B6 | When the unit system is switched while parked, distance units update only on the next distance change |
| B13 | Wireless CarPlay adapters send no route-guidance data, so no arrows |
| B14 | Rapid (≈1 s) USB re-plugging makes the stock code kill DIO; not handled and not tested in F8 |
| — | The monitor records only from the first CarPlay connection in each boot |

The full backlog (Chinese) is in [`docs/zh-CN/BACKLOG.md`](../zh-CN/BACKLOG.md).
