# 构建与复现

只有两样东西能仅凭本仓库复现，其余需要我们不能分发的输入。

| 产物 | 仅凭本仓库？ | 方法 |
| --- | --- | --- |
| Toolbox v1 SD 包 | **可以** | `tools/assemble_toolbox_v1.py`（上游提交 `af244e7` + `toolbox/overlay/`）；158 个文件对照 `release/v0.9.0-rc.1/toolbox-v1.SHA256SUMS` 校验，和上车用的包逐字节相同 |
| F8 脚本、监测、辅助程序 | **可以** | `f8/`（包内 28 个文件中的 22 个） |
| `libcarplay_hook.so` | 不行 | 用 QNX 6.5 ARMv7 工具链构建上游 hook，并带上本项目的修改（见下） |
| `maneuver_render`、`flag_atlas.rgba` | 不行 | 上游 renderer 的构建和资源 |
| `carplay_mu1320_f7_daily_v2.jar.DISABLED` | 不行 | 针对**你自己**那台机器的 HMI JAR 编译的 Java 1.4 补丁，包含对原厂类的覆盖 |
| `dio_manager.json`、`smartphone_integrator.json` | 不行 | 你车上的原厂文件，按 `tools/provenance/prepare_configs.py` 的逻辑修改 |

`python3 tools/assemble_f8.py --check-only --output x` 会列出哪些文件来自仓库。输入齐全后，`assemble_f8.py --inputs DIR` 会逐个对照 `release/v0.9.0-rc.1/f8-SHA256SUMS`。
如果你自己构建的结果和它逐位不同（工具链不同、固件转储不同），组装器会拒绝；这时你装的就不是车上验证过的候选包，需要自己分阶段验证。

## 为什么不包含这些输入

见 [NOTICE.md](../../NOTICE.md)：上游项目没有许可证，Java 类和配置文件来自 Audi / e.solutions 的专有固件。

## 原生构建（hook、renderer、辅助程序）

- 这里的 ARM 二进制由为 QNX 6.5 ARMv7 构建的 GCC 4.9.4 编译（见 `tools/provenance/` 以及上游的 `toolchain/`、`scripts/build_hook.sh`）。
  `build_hook.sh` 会拒绝含 `emutls` 符号、`.init_array` 不是最小尺寸、或有急切模块构造函数的构建，不要绕过。
- 辅助程序源码在 `f8/src/`（`f7_spawn.c`、`mount_state.c`、`loader_check.c`、`trial_gate.c/.h`、`f4_unbuf.c`），ARM ELF 构建在 `f8/bin/`，哈希在 `f8-SHA256SUMS`。
- `patches/0001`–`0002` 应用于上游 `java_patch/` 目录（`git apply --directory=java_patch patches/000X-*.patch`，已验证）。
  `0003`–`0004` 是 navhook 试验阶段的 hook 侧修改，仅供参考；`0003` 的路径前缀不标准，未重新验证。
- 开发期间使用的上游提交是 `f36790d450392516ed9cbfab9cc06aa13a08bf31`，另有本地文档修改。

## Java 补丁

以 `-source 1.4 -target 1.4` 针对原厂 jar（从你的固件提取并从 JXE 转成 JAR）和 OSGi 编译。版本名（`BUILD_ID`）注入到生成的 `CarPlayApp.java` 副本中，不改源码树。
`tools/provenance/` 里各阶段脚本（`build_f7_*_java.py`、`build_f6_*.py` 等）记录了 F7 v2 字节码如何从 F7 v1.1 和 F6 v3 派生，并用 `javap -v` 对比和主机 harness 验证；它们依赖私有工作区，仅作参考。

## 测试

`tests/test_f8_mon.py` 可独立运行（36 个测试，约 2.5 分钟，用 `/bin/sh` 和 `/bin/ksh` 加假的 `pidin`/`mount`）。`tests/provenance/` 是各阶段的事务测试，需要对应的暂存包目录。
