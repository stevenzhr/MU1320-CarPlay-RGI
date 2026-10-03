# MU1320 CarPlay RGI

**English** · [简体中文](README.zh-CN.md)

Turn-by-turn **CarPlay route guidance on the Virtual Cockpit and HUD** for Audi MHI2Q head units
with firmware **MU1320** (QNX 6.5, ARMv7), delivered through the Green-Menu **MIB2 Toolbox** so it
can be installed, collected, rolled back and emergency-stopped from the MMI itself.

This is the MU1320 port and validation work built on top of
[`luka-dev/mib2q-carplay-rgi`](https://github.com/luka-dev/mib2q-carplay-rgi) (MU1316). The stock
`libairplay.so` is never replaced: the patch interposes around CarPlay.

> **Warning — use at your own risk.** This modifies system files and configuration on your
> infotainment unit. It has been validated on **one** car (`MHI2Q_US_AUG22_P4246`, MU1320) by one
> person. A mistake can leave the MMI unusable or void your warranty. Back everything up first, keep
> a working SSH route in, and read [docs/en/status.md](docs/en/status.md) for exactly what has and
> has not been verified. HMI-failure recovery (what to do if the screen never comes up) is **not**
> verified. No warranty of any kind; see [LICENSE](LICENSE).

## What you get

- Maneuver arrow, distance bar and lane overlay in the cluster map frame, plus BAP guidance
  (arrow/distance/lanes) on the VC and HUD, from Apple Maps and Google Maps on a wired CarPlay link.
- MMI touchpad drag bridged to cluster navigation input.
- Five menu buttons — Status, Install, Uninstall, Collect, Emergency Stop — and SSH equivalents.
- A long-term monitor (F8) that logs memory, CPU, threads and handles to the SD card for stability
  validation.

Known gaps: ETA and destination distance are not shown on VC/HUD (not even in stock behaviour on
this car); wireless CarPlay adapters send no route-guidance data; very fast USB re-plugging is not
handled. Full list in [docs/en/status.md](docs/en/status.md).

## Repository map

| Path | Contents |
| --- | --- |
| [`docs/en/`](docs/en/) | How it works, install/rollback, building, verification status |
| [`docs/zh-CN/`](docs/zh-CN/) | 中文文档，以及全部阶段性实车验证报告（`reports/`，中文原文） |
| [`f8/`](f8/) | F8 candidate (`mu1320-f7-daily-v2.1`): lifecycle scripts, monitor, C helpers + ARM builds |
| [`toolbox/`](toolbox/) | Overlay for MIB2 Toolbox v1 (the green-menu page and dispatcher) |
| [`patches/`](patches/) | Our diffs against the upstream sources |
| [`tools/`](tools/) | `assemble_toolbox_v1.py`, `assemble_f8.py`; `provenance/` has the per-phase build scripts |
| [`release/v0.9.0-rc.1/`](release/v0.9.0-rc.1/) | Release notes and the checksums the assemblers verify against |
| [`NOTICE.md`](NOTICE.md) | Licensing and what is deliberately **not** in this repo |

## Quick start (summary)

1. Build or obtain the inputs listed in [docs/en/building.md](docs/en/building.md) (hook, renderer,
   Java patch, edited SI/DIO configs). They are not distributed here — see [NOTICE.md](NOTICE.md).
2. `python3 tools/assemble_toolbox_v1.py --output build/mu1320-toolbox-v1` and
   `python3 tools/assemble_f8.py --inputs <dir> --output build/mu1320-f7-daily-v2.1`
   (both verify checksums and refuse to produce a package that differs from the car-tested one).
3. Copy to the SD card, install Toolbox v1 through the stock update menu, then use
   `Customization > MU1320 RGI`. Details: [docs/en/install.md](docs/en/install.md).

## Tests

```sh
python3 -m unittest tests.test_f8_mon      # monitor, sh and ksh, fake pidin/mount (~2.5 min)
```

The other tests of the build history live in `tests/provenance/`; they need the private build
workspace and are kept as reference only.

## Credits

[luka-dev](https://github.com/luka-dev) for the MU1316 CarPlay RGI research and implementation;
[jilleb](https://github.com/jilleb/mib2-toolbox) and contributors for the MIB2 Toolbox.
