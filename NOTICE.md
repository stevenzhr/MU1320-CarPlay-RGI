# Third-party material and what this repository does not contain

The MIT license in [LICENSE](LICENSE) covers only material written for this project:
the shell scripts and C helpers under `f8/`, the Toolbox overlay under `toolbox/overlay/`,
the tools, tests, patches' own hunks, and the documentation.

| Material | Status | Handling here |
| --- | --- | --- |
| `jilleb/mib2-toolbox` (MIT, (c) 2019 Chillout) | Used unmodified at commit `af244e7cb8c912ab47f5c09cd7677370fe86b441` | Not vendored. `tools/assemble_toolbox_v1.py` fetches it and applies the overlay. Its license text is in `toolbox/LICENSE-mib2-toolbox.txt`. |
| `luka-dev/mib2q-carplay-rgi` (hook, Java patch, `maneuver_render`, flag atlas) | **No license file upstream** (all rights reserved by default) | Not redistributed. No upstream source, binary or asset is in this repository. `patches/` holds only our diffs against it. See "Upstream license" below. |
| Audi / e.solutions firmware (JXE/JAR, `libairplay.so`, SI/DIO config files, Java classes under `de/audi`, `de/esolutions`) | Proprietary | Not included. The F8 Java patch overrides stock classes, so it is built locally against **your own** unit's firmware and is not redistributed. The two SI/DIO config files are edited copies of your car's stock files and are likewise not included. |
| Vehicle logs, firmware dumps, local toolchains | Private | Kept outside this repository. |

## Upstream license

`luka-dev/mib2q-carplay-rgi` publishes no license. Until its author adds one, this project
does not republish any of its files. If you are the upstream author and are happy for the
derived binaries to be distributed, please open an issue; the release can then include the
complete, installable F8 package.

## Trademarks

Audi, Virtual Cockpit, MMI, CarPlay, Apple and iPhone are trademarks of their respective
owners. This project is independent and not affiliated with or endorsed by any of them.
