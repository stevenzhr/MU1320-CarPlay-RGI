# Install, use, roll back

Prerequisites: an Audi MHI2Q unit running **MU1320**, root SSH working (verify a cold-start login
over the car's hotspot first), a FAT-formatted SD card, a wired CarPlay connection, and the build inputs from
[building.md](building.md). Park with stable power. Never run `dmdt ts`.

## 1. Prepare the SD card

```sh
python3 tools/assemble_toolbox_v1.py --output build/mu1320-toolbox-v1
python3 tools/assemble_f8.py --inputs <your-inputs> --output build/mu1320-f7-daily-v2.1
```

- Copy the **contents** of `build/mu1320-toolbox-v1/` to the SD root (replacing any older `Toolbox/`
  and `metainfo2.txt`; leave `Custom/`, `Backup/`, `Log/`).
- Copy the folder `mu1320-f7-daily-v2.1/` to the SD root. It must be the **only** `mu1320-f7-*` folder
  carrying a `TOOLBOX-ENTRY` file, otherwise the menu shows `2 F7 FOLDERS`.
- On macOS clean metadata: `dot_clean -m /Volumes/<SD>` and check `find /Volumes/<SD> -name '._*'` prints nothing.

## 2. Install Toolbox v1 (once)

Hold **MENU** → service screen → *Software updates/versions* → *Update* → select the SD →
*MQB Coding MIB2 Toolbox*. Let it finish (several restarts). Afterwards `Customization > MU1320 RGI`
shows five buttons. SSH is untouched by the update. Confirm you can still log in.

## 3. Install the patch

1. **1 Status** — expect `SI: BASELINE/BASELINE`, `JAVA: ABSENT`, `RESULT: OK`. Any `UNKNOWN`: stop.
2. **2 Install** — wait for `F7_install_FILES_PASSED` and `RESULT: OK` (30–60 s).
3. Do a **full restart** of the MMI. **1 Status** should show `SI: F7_TRIAL/F7_TRIAL`,
   `JAVA: F7_INSTALLED`, `LISTENER: F7_READY`.
4. Connect CarPlay by USB and start a route in Apple Maps or Google Maps.

The SD card stays inserted while the monitor is active. Take it out only after locking the car and
the MMI screen is off; put it back right after copying `out/`.

## Buttons

| Button | Does | Notes |
| --- | --- | --- |
| 1 Status | read-only summary | full output in `out/action-*.txt` on the SD |
| 2 Install | installs, then **full restart** | refuses unless state is baseline |
| 3 Uninstall | restores stock files, stops renderer and BAP now, then **full restart** | |
| 4 Collect | snapshot to `out/snapshot-<pid>/` | press before locking the car if something looked wrong |
| 5 EMERGENCY STOP | BAP off, renderer stopped, stock display back within seconds | patch returns after a restart |

The screen shows at most ~10 lines ending in `Log:` and `RESULT: OK|FAILED`. Wait for `RESULT` before leaving
the page. A second press while one runs shows `BUSY`.

## Rollback and recovery

- Normal: **3 Uninstall** → full restart → **1 Status** shows baseline. To also delete the workspace, over SSH
  **after the restart**: `/bin/sh /fs/sda0/mu1320-f7-daily-v2.1/f7.sh purge` (it refuses before a reboot).
- Menu unavailable: `/bin/sh /fs/sda0/mu1320-f7-daily-v2.1/f7.sh rollback` over SSH.
- Arrows or map frame garbled, black blocks on the VC: **5 EMERGENCY STOP**, then a normal restart.
- Black HMI, restart loops, endless CarPlay reconnects, audio/reversing-camera trouble: do not reconnect
  USB; press **4 Collect** if you can, then **3 Uninstall** and restart. If the HMI never comes up, use SSH
  (cold-start hotspot login worked on the test car) — this path is **unverified** with a broken HMI.
- Suspect the monitor: `f7.sh off monitor` (persistent), or `touch /tmp/mu1320-f8-mon-off` (this boot).

## SSH reference

```sh
/bin/sh /fs/sda0/mu1320-f7-daily-v2.1/f7.sh status|install|stop|rollback|purge
/bin/sh /fs/sda0/mu1320-f7-daily-v2.1/f7.sh collect live|snapshot|restored
/bin/sh /fs/sda0/mu1320-f7-daily-v2.1/f7.sh off|on native|render|bap|touchpad|monitor
```

(`/fs/sdb0` instead of `sda0` if the card is in the second slot.) Note that `stop` and `rollback`
write `/tmp/mu1320-f5-bap-off`, so BAP stays off until a restart.
