# F7 v2 实车结果（绿色菜单 + B11/B12，场次 T/I/Q/D/R）

- 分析日期：2026-10-02；场次 Q 的车机时间 2026-09-27 20:36–20:37（SI 转储原因里的时间，车机自身时钟为 1970）
- 包：`mu1320-f7-daily-v2/` + 自制 Toolbox v1 `mu1320-toolbox-v1/`
- 证据：`resource/private/vehicle-dump/f7-daily-v2/`（19 个 action 日志、9 个 snapshot、`OBSERVATIONS-F7.txt`）
- 审计：`scripts/audit_f7_vehicle.py` → `reports/f7-daily-v2-vehicle.json`，**26/26 通过**

## 用户观察表

填写了的部分：支持矩阵 4 项 Apple、Google 都是 P（冷启动自动出现、EMERGENCY STOP 后几秒内 VC/HUD 回原厂、
到达前距离条递减、车道与 iPhone 一致）；R1、R2 做了；R4 回原厂（附 purge 终端尾部，`F7_ACTION_PASSED`）；E1 原厂、E2 各功能正常。
T、I、Q、D 各格没有填写，以下按日志判断。

## 开机分组

action 日志没有时间，按 SI 进程号（闸门记录的 ppid）或 `/tmp` 闸门记录（重启即清空）把动作归到各次开机：

| 开机 | 动作 | 内容 |
| --- | --- | --- |
| 安装前 | status `2990118`、install `3780677` | 原厂基线（SI BASELINE、Java ABSENT），首次安装 13 步全部写入、加载检查通过 |
| 安装后首次 | status `2322569` | `F7_TRIAL/F7_TRIAL`、`JAVA_LISTENER: F7_READY`，还没连手机 |
| Q 前一次开机 | status `4616332` | `GATE_STRIKES: 3`（GATE_LAST `3686436`），本次开机没有 collect |
| Q（SI 921679） | stop `6488204`、collect `7356555` | 场次 Q 主体，见下 |
| D ×5（SI 921638、925749、933932、933967、938063） | collect 7 次 | 日常行驶，见下 |
| R1/R2（SI 925746） | rollback `3092507`、collect `5111948`、install `7114892` | 同一次开机内完成，见场次 R |
| 最后一次 | rollback `3489830`、purge `5468290`（SSH） | 同一次开机内完成 |

## 菜单（T/I）

- 除 purge 外 18 个动作都经绿色菜单执行：`RUN_ENV: cwd=/ umask=022`，LD_LIBRARY_PATH 里没有相对路径（GEM 环境清理有效）。
  purge 从 SSH 执行（`/net/mmx/...` 库路径），与设计一致。
- 19 个动作全部 `CONTROL_EXIT=0`、`OUTER_EXIT…=0`、SD 原为 ro，marker 都是 `mu1320_f7_v2_773045ab`。
- I1 首次安装 `F7_install_FILES_PASSED`，挂载恢复 ro；I2 重启后 Status 为 `F7_TRIAL`、`F7_READY`。

## 场次 Q

**B11 闸门直写：实车通过。** 场次 Q 那次开机 7 代 DIO：

| DIO | 模式 | strikes | 说明 |
| --- | --- | --- | --- |
| 3674148 | ACTIVE | 0 | Q1，路线出现，BAP START、renderer TAKE |
| 4444196 | ACTIVE | 0 | 上一代活得够久，不计 |
| 4911140 | ACTIVE | 1 | 快速拔插 |
| 5074980 | ACTIVE | 2 | 快速拔插 |
| 5550116 | **PASSIVE CRASH_GUARD** | 3 | 第 4 次快速拔插被挡住 |
| 5713956、6180900 | PASSIVE CRASH_GUARD | 3 | 之后一直被动，直到重启 |

`/tmp/mu1320-f7-gate.last`、`.strikes` 都存在（v1.1 时从未出现）。另一次开机的 Status 也是 `strikes = 3`。
每次重启后第一代 DIO 都从 strikes 0 开始。没有证据表明在同一次开机里删 strikes 后箭头恢复（Q2 最后一步）；
改为重启恢复，各 D 开机都正常工作。

**B12 stop 先经 Java：执行顺序在车上验证通过，但按下 stop 时没有导航在显示。**

- stop 输出顺序：`JAVA_RELEASE: BAP_OFF` → `JAVA_CLUSTER_CONTEXT: 74 waited=0s` → `RENDERER_STOP` → `DISARM…` → `F7_STOPPED`，
  没有走 native `sc` 兜底。Java BAP 日志只有一条新的 `GATE kill=1`（t=255 s）。
- 紧接着的 Q4 collect：renderer 不在，keeper `KEEP HELD hold`，仪表 context 74 `[20 102 101 33]`，d98 不存在。
- 但这次开机最后一次 BAP TEARDOWN 在 stop 前约 127 秒，之后的 DIO 都是被动的，**stop 时 BAP 和 renderer 都已经空闲**。
  所以这份日志证明的是 stop 的执行路径，不能证明“导航显示中按 stop，VC/HUD 回原厂”。
  支持矩阵里这项填了 P，如果是在别的没有 collect 的开机里做的，就是唯一的直接证据。
- 两次 rollback 也都走同一流程（`JAVA_RELEASE: BAP_OFF`，ctx 74）；`3489830` 那次 renderer 在运行，但没有 collect，不知道当时有没有导航。

**快速拔插时原厂 SI 强杀 DIO（新观察）。** 场次 Q 的 sloginfo 中有 3 次
`[CProcessDumper] … appState=TIMEOUT_SHUTDOWN` + `ProcessHandling::stop: Killed`（DIO 4444196、5074980、5713956；
`smartphone_integrator_error_17–19` 写到 `/mnt/ota/system/logs`）。
DIO 刚启动、主线程还停在“sleeping on condition”时设备就断开，SI 等关闭超时后转储再杀掉。被杀的 DIO 里有一个是被动的（hook 什么都不做），
三次故障地址都落在 `dio_manager` 本体的同一位置（低位 `0xe4b4`），不在 hook 里。所以更可能是原厂对 1 秒内插拔的处理，
但没有原厂基线的同样测试，不能定论。其他 6 次开机都没有转储。记为 B14。

## 场次 D（日常行驶）

5 次冷启动，每次都自动工作（keeper READY、BAP START、renderer TAKE），共 7 次 collect：

| SI | DIO 代数 | BAP 路线段 | 车道调用 | 到达 | 触摸板手势 |
| --- | --- | --- | --- | --- | --- |
| 933967 | 1 | 2 | 14 | **是** | 7 |
| 925749 | 1 | 2 | 28 | 否 | 1 |
| 933932 | 2（中途拔插 1 次） | 1 | 9 | 否 | 5 |
| 921638 | 1 | 1 | 11 | 否 | 2 |
| 938063 | 3（拔插 2 次） | 2 | 4 | 否 | 8 |

- 全部开机：FAULT 0、REJECT 0、TAKE_FAILED/FIGHT_STOP/DISPLAY fail 0；START 与 TEARDOWN、TAKE 后的 RELEASE 一一对应。
  `STOCK_RECLAIMED` 都是路线开始时原厂收回一次（约 250/750 ms）或切换视图（B5），与 F6/F7 v1.1 相同。
- **Java 回放**：9 个 capture 用 F7 v2 的类回放（`F6V3Replay`），严格比对全部 0 mismatch；车道片段 35 个，全部是实时数据（from_memory=0）。
- **到达**：933967 到达前最后一段距离条 97→8 逐秒递减到 `RCMD BAR 1/1`，然后 ARRIVED。约 48 秒后才 ROUTE_END（到达符号停留，B2 原样）。
- 没有 Java 链接错误，除场次 Q 外 sloginfo 中没有任何进程转储。
- 日志里认不出每次开机用的是 Apple 还是 Google；两个都通过，以观察表为准。

## 场次 R

- **R1**：rollback `3092507` 时这次开机没有连过手机（GATE_LAST ABSENT），先经 Java 关 BAP，然后恢复 SI、NavActiveIgnore，并把 F7 JAR 移出扫描目录。
- **R1 之后没有完整重启**：同一次开机里接着连了 CarPlay 并 collect（`5111948`）。这时 SI 还是开机时读的试验配置，DIO 照样加载 hook，
  只是因为 `native-off` 而被动（`PASSIVE OFF_RUNTIME`）；Java 也还在（`F7_READY`）。看到的“原厂行为”是 stop 后的状态，不是真正的基线。
  R2 的 install `7114892` 也在这次开机里做（`RESUME_WORKSPACE`，13 项都是 `already exact`，提交 JAR/SI），续装路径因此在车上走通了。
  install 后的那次重启 + 路线是哪次 D 开机，日志无法区分。
- **R3**（中断安装）：没做。
- **R4 purge**：`F7_PURGED`、`F7_purge_FILES_PASSED`，备份比对通过，挂载恢复 ro。但 purge 和 rollback `3489830` 在**同一次开机**
  （同一个 GATE_LAST `2502787 43980`，keeper HELD，Java 仍 `F7_READY`），不是观察表写的“Uninstall → 重启 → purge”。
  文件层面没有问题（运行中的进程打开的文件被删后由 QNX 保留到进程退出）；只要 purge 之后重启过，现在车上就是基线。
  purge 目前不检查是否已经重启，可以加一条保护：Java 监听器在线或存在加载了 hook 的 DIO 时拒绝 purge。
- v1.1 的工作目录 `/mnt/app/root/mu1320-rgi-f7-v1.1` 这次没有 purge，这些日志也不能说明它是否还在。

## 结论

| 项 | 结果 |
| --- | --- |
| Toolbox v1 菜单（5 个按钮、环境清理、摘要） | 通过（Status、Install、Uninstall、Collect、EMERGENCY STOP 都在车上用过） |
| 安装 / 续装 / 卸载 / purge | 通过；续装在车上走通；purge 在卸载后、重启前执行 |
| B11 崩溃保护 | **实车通过，关闭** |
| B12 stop 先经 Java | 执行顺序实车通过；用户确认支持矩阵的 P 是导航显示中按 stop 得到的（2026-10-02），**关闭** |
| 日常行驶（5 次冷启动） | 通过：自动工作、车道、到达距离条（B9）、触摸板，无故障，回放 0 mismatch |
| 新问题 | B14 快速插拔时原厂 SI 超时强杀 DIO（是否原厂行为待确认）；purge 不检查重启（建议） |

**F7 v2 结项（2026-10-02，用户决定）**，作为 F8（长期稳定性）的固定候选。B12 的直接证据是用户观察：导航显示中按 EMERGENCY STOP，VC/HUD 几秒内回原厂（Apple、Google 都是 P）。
