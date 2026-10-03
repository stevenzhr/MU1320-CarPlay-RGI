# Building and reproducing

Two things are reproducible from this repository alone; the rest needs inputs we cannot ship.

| Artifact | From this repo alone? | How |
| --- | --- | --- |
| Toolbox v1 SD package | **Yes** | `tools/assemble_toolbox_v1.py` (upstream commit `af244e7` + `toolbox/overlay/`); 158 files verified against `release/v0.9.0-rc.1/toolbox-v1.SHA256SUMS`; byte-identical to the package used in the car |
| F8 scripts, monitor, helper binaries | **Yes** | `f8/` (22 of the 28 files in the package) |
| `libcarplay_hook.so` | No | Build the upstream hook (needs the QNX 6.5 ARMv7 toolchain) with this project's changes; see below |
| `maneuver_render`, `flag_atlas.rgba` | No | Upstream renderer build and asset |
| `carplay_mu1320_f7_daily_v2.jar.DISABLED` | No | Java 1.4 patch compiled against **your** unit's `lsd`/HMI JAR, which overrides stock classes |
| `dio_manager.json`, `smartphone_integrator.json` | No | Your car's stock files, edited by `tools/provenance/prepare_configs.py` logic |

`python3 tools/assemble_f8.py --check-only --output x` lists which files come from the repo.
With all inputs, `assemble_f8.py --inputs DIR` checks each file against `release/v0.9.0-rc.1/f8-SHA256SUMS`.
If your own build differs bit-for-bit (a different toolchain, a different firmware dump) the assembler
refuses; in that case you are not installing the car-tested candidate and should validate yours stage by stage.

## Why these inputs are not included

See [NOTICE.md](../../NOTICE.md): the upstream project has no license, and the Java classes and config
files derive from proprietary Audi / e.solutions firmware.

## Native build (hook, renderer, helpers)

- The ARM binaries used here come from GCC 4.9.4 built for QNX 6.5 ARMv7 (see `tools/provenance/` and the
  upstream project's `toolchain/` and `scripts/build_hook.sh`). `build_hook.sh` rejects builds with `emutls`
  symbols, a non-minimal `.init_array`, or eager module constructors; do not work around those checks.
- Helper sources are in `f8/src/` (`f7_spawn.c`, `mount_state.c`, `loader_check.c`, `trial_gate.c/.h`,
  `f4_unbuf.c`). Prebuilt ARM ELF builds are in `f8/bin/`; their hashes are in `f8-SHA256SUMS`.
- `patches/0001`–`0002` apply to the upstream `java_patch/` tree
  (`git apply --directory=java_patch patches/000X-*.patch`, verified). `0003`–`0004` are the hook-side changes
  used during the navhook trials, kept for reference; `0003` uses a nonstandard path prefix and was not re-verified.
- The upstream commit used during development was `f36790d450392516ed9cbfab9cc06aa13a08bf31` plus local
  documentation edits.

## Java patch

Compiled with `-source 1.4 -target 1.4` against the stock jar (extracted from your firmware, converted
JXE → JAR) plus OSGi. Build-time version names (`BUILD_ID`) are injected into a generated copy of
`CarPlayApp.java`, never by editing the source tree. The per-phase scripts in `tools/provenance/`
(`build_f7_*_java.py`, `build_f6_*.py`, …) document how the F7 v2 bytecode was derived from F7 v1.1 and F6 v3 and verified with
`javap -v` comparisons and host harnesses; they expect a private workspace and are reference material.

## Tests

`tests/test_f8_mon.py` runs standalone (36 tests, ~2.5 min, uses `/bin/sh` and `/bin/ksh` with fake
`pidin`/`mount`). `tests/provenance/` holds the per-phase transaction tests, which need the staged package folders.
