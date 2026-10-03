# F7 v2（绿色菜单部署 + B11/B12）：离线审阅（2026-09-27）

结论：**SD 文件夹 `mu1320-f7-daily-v2/` 与自制 Toolbox `mu1320-toolbox-v1/` 离线验证通过，尚未上车。**
车上当前为原厂基线（F7 v1.1 已回滚并重启），Toolbox 为 v0（诊断页）。

F7 v2 = F7 v1.1（场次 P 实车通过）+ BACKLOG B11、B12 两处修复 + 脚本环境清理 + 绿色菜单入口。
Java 逻辑不变（只有版本名），native 只改闸门写记录的函数，脚本只加三处审阅过的改动块。

## 命名

| 项 | F7 v1.1 | F7 v2 |
| --- | --- | --- |
| SD 文件夹 | `mu1320-f7-daily-v1.1` | `mu1320-f7-daily-v2`（新增 `TOOLBOX-ENTRY`） |
| 工作目录 | `/mnt/app/root/mu1320-rgi-f7-v1.1` | `/mnt/app/root/mu1320-rgi-f7-v2` |
| BUILD_ID | `MU1320-F7-DAILY-V1.1` | `MU1320-F7-DAILY-V2` |
| SI marker | `mu1320_f7_v1_1_30175784` | `mu1320_f7_v2_` + sha256(BUILD_ID) 前 8 位 |
| JAR | `CarPlayRGI-MU1320-F7DailyV1_1.jar` | `CarPlayRGI-MU1320-F7DailyV2.jar` |
| hook | `fc749d3a…c792` | `3e9d4f1e…332f`（242082 字节） |
| Java JAR | `2813457c…88d4` | `2c337043…2d76`（94 类） |

## B11：闸门记录直写（native，`scripts/build_f7_v2_native.py`）

- 原因（v1.1 实车 P4）：`write_small()` 先写 `<path>.<pid>` 再 `rename()`；`/tmp` 是 `/dev/shmem`，不支持 rename，
  `gate.last`、`gate.strikes` 从未出现，崩溃保护和存活 DIO 守卫都没生效。
- 修改：`f7-v2-src/trial_gate.c` 的 `write_small()` 改为 `open(O_WRONLY|O_CREAT|O_TRUNC)` + `write` 直接写；持久开关路径随 v2 工作目录。
  其余代码与 v1.1 一字不差（主机测试逐段比对）。`/tmp` 上 `O_TRUNC` 可用：F5–F7 的脚本一直用 `: > /tmp/...` 截断文件。
  记录只有几个字节，只被后面的 DIO 读；读到半截时失败安全（无 LAST → 当作当前代；STRIKES 读不出 → 0）。
- 构建：同一 Docker 镜像先**逐字节复现 v1.1 hook `fc749d3a…`**，再只替换 `trial_gate.c`（树差异只有这一个文件）。
  ABI 检查通过（emutls 0、`.init_array` 000004、无 eager 构造）；未定义符号是 v1.1 的子集、全部在本车 libc/libsocket 里；
  符号尺寸变化只有 `write_small`（204 → 72）。`rename` 仍被 hook 其他代码导入，所以导入表不变。
- 主机测试 `tests/test_f7_v2_native.py`（14 项）：
  - v1 闸门套件 9 项以 v2 源码重跑；
  - **模拟没有 rename 的文件系统**（`-Drename=` 桩函数恒失败）：v1.1 源码重现车上现象（4 代 DIO 全 ACTIVE、`strikes=0 prev=0`、两个记录文件都不存在）；
    v2 源码第 1–3 代 `strikes=0,1,2`，第 4 代 `PASSIVE reason=CRASH_GUARD`、`gate.strikes` = 3，没有临时文件残留，删 strikes 后恢复——正是场次 P4 的预期；
  - 较长旧记录被较短新记录完整覆盖（`O_TRUNC`）；源码只差写函数和路径；构建报告。

## B12：stop 先经 Java 关 BAP（脚本，`scripts/prepare_f7_v2_daily.py`）

- 现象（v1.1 实车 P7）：`stop` 报 `DISARM_CLUSTER_CONTEXT: 74 restored=1`，但 VC 仍有箭头，拔 USB 后才回原厂；HUD 箭头也还在。
- 分析（修正 v1.1 结项时的推测）：
  1. v1.1 的 stop 只停 renderer，**BAP 输出没有停**：当前 DIO 仍启用，Java 继续向 VC/HUD 发 BAP。VC 在原厂 KDK 位置用 BAP 画转向箭头，
     而 F5 正是把 98 放在这个位置，所以看起来“地图框没回原厂”。拔 USB → LINK_LOST → BAP 拆除，才全部消失。与 HUD 箭头还在、拔 USB 后全消失一致。
  2. stop 的输出里**没有** `CLUSTER_ON_80: switching to 74`，说明 renderer 断开后 Java（`RenderLink` → `frameReady=false` → presenter RELEASE）
     已先把 context 80 放回 74；标记时 render.log 最后一行是 `KEEPER_HELD`，RELEASE 发生在它之前，并不矛盾。
  那次开机没有 collect，以上是推断，场次 Q3 验证。
- 修改：`stop`/`rollback` 的 `stop_runtime` 改为
  1. 写 hold 和 native-off（与 v1.1 相同）；
  2. 写车上验证过的运行时开关 `/tmp/mu1320-f5-bap-off`（F5/F7 Java 每秒轮询：`GATE kill=1` → BAP 拆除 → `owning=false` → presenter RELEASE，kdk 模式同时还原 KDK）；
  3. Java 监听器在线时，最多等 10 秒看 BAP 日志里出现**新的** `GATE kill=1`（按行数比较，之前 off/on 留下的不算）→ `JAVA_RELEASE: BAP_OFF`；
     然后最多 8 秒等 displaymanager 离开 80（`JAVA_CLUSTER_CONTEXT:`）；Java 不在线 → `NO_JAVA` 不等；超时 → `NO_ACK`；已关过 → `ALREADY_OFF`；
  4. 然后才停 renderer，80 还在时照旧用 native `sc 4 74` 兜底（v1.1 路径）。
  Java 字节码不变。stop 之后 `on bap` 不会恢复（运行时开关到重启为止），README 已写明；触摸板不受 stop 影响。
- 主机测试（`tests/test_f7_v2_trial.py`，假 Java 线程模拟 F5Probe/F5BapOutput 对开关的反应）：
  Java 关 BAP 时 renderer 仍在运行、日志顺序 `JAVA_RELEASE` 在 `RENDERER_STOP` 之前、全程没有 native sc；
  Java 不应答 → 等满 10 秒后 native 兜底；无监听器 → 不等（<8 秒）；旧的 `GATE kill=1` 不算应答；第二次 stop 与 stop 后 rollback → `ALREADY_OFF`；
  rollback 同样先经 Java；Java 应答但 80 不走 → 等 8 秒后 native 兜底，总时长在菜单可接受范围（<25 秒）。

## 脚本环境（绿色菜单调用者）

Toolbox v0 实车：GEM 脚本 PATH、LD_LIBRARY_PATH 以 `.` 开头，umask 000，cwd `/mnt/app/eso`。`f7.sh` 和 `control.sh` 在解析出 SD 目录后
`cd /`、`umask 022`、去掉 LD_LIBRARY_PATH 里的相对项（全空则 unset）；PATH 本来就是固定值。status 新增 `RUN_ENV:` 行作证据。
主机测试以 `umask 000`、陌生 cwd、`LD_LIBRARY_PATH=.:/opt/lib:lib-rel::/root/lib-target:/opt/other` 运行，得到 `cwd=/ umask=0022 ld=/opt/lib:/root/lib-target:/opt/other`。

## 脚本派生

v1.1 脚本改名（工作目录、JAR、marker、BUILD_ID）+ 三处改动块（`HUNKS`：`control.sh` 环境/RUN_ENV/stop/F7_STOPPED 文本，`f7.sh` 环境）+ 重新锁定校验值。
prepare 脚本断言：每个改动块只匹配一次；除这些块外与“纯改名”结果完全相同；`sh -n`/`ksh -n` 通过；无 `exists … && fail`、无 `dmdt ts`、无 tr 字符范围；
所有 `/mnt/app/root/mu1320*` 路径只有 v2 工作目录；keeper 与模板重新渲染一致。差异见 `reports/f7-v2-scripts.diff`。
从 v1.1 逐字节带过来：`loader_check(.c)`、`mount_state(.c)`、`dio_manager.json`、`maneuver_render`、`flag_atlas.rgba`、`f4_unbuf.so`、`geom-example.cfg`、`f7_spawn(.c)`、`trial_gate.h`。

## Java（`scripts/build_f7_v2_java.py`）

先用 v1.1 源码逐字节复现 v1.1 JAR 的 7 个类，再只替换两个版本名重编；7 个类在 `javap -v` 下把名字换回后与 v1.1 完全相同，其余 87 类与 v1.1 逐字节相同；
JAR 里没有旧版本字符串。Harness 与 v1.1 同一套：keeper 32/0、F1 v2 等价 899,757、触摸板 7,633、F5（含 B9 检查）、F6V3Replay（含 F6 v3 场次 D）全部通过；链接审计 2129 引用 0 缺失。

## 绿色菜单：自制 Toolbox v1（`scripts/prepare_toolbox_v1.py`，`mu1320-toolbox-v1/`）

- 构造与车上已接受的 v0 相同：上游 `mib2-toolbox` `af244e7` 逐字节（149 个文件，`metainfo2.txt`、`Toolbox/final/` 与 v0 相同）+ 7 个叠加文件：
  `Toolbox/GEM/mqb-mu1320.esd`（与 v0 同名，SWDL 覆盖掉诊断页）、`Toolbox/scripts/mu1320/f7menu.sh`（调度脚本）、5 个按钮桩
  `f7_{status,install,uninstall,collect,stop}.sh`。v0 的诊断脚本留在车上但不再被引用，v1 不复用它们的文件名。
- 按钮 → `f7.sh`：Status → `status`，Install → `install`，Uninstall → `rollback`，Collect → `collect snapshot`，EMERGENCY STOP → `stop`。
  purge、off/on 仍只用 SSH。
- 调度脚本：清理环境（PATH、LD_* 、`cd /`、umask 022）；`/tmp` 锁保证同时只跑一个按钮（活着的持有者 → `BUSY`，死掉的 → 替换）；
  在 `/fs/sda0`、`/fs/sdb0` 根目录找**唯一**带 `TOOLBOX-ENTRY`（首行 `MU1320_F7_TOOLBOX_ENTRY 1`）的 `mu1320-f7-*` 目录（符号链接、旧版本文件夹不算）；
  运行其 `f7.sh`，输出暂存 `/tmp`，屏幕显示 ≤10 行、每行 ≤60 字符的摘要（Status 为固定 6 行状态；其他为 STOP/WARNING/关键结果行最多 4 行 + `Saved:`/`Log:`/`NEXT:`/`RESULT:`）。
  菜单脚本自己不写 SD、不改挂载、不调用 dmdt；换 F7 版本不需要重刷 Toolbox。
- 主机测试 `tests/test_toolbox_v1.py`（18 项，sh 与 ksh 各跑一遍）：用 v1.1 实车的 status/install/stop/collect/rollback 输出回放；
  按钮与参数映射、环境清理、摘要行数/宽度、失败（有无日志）、警告截断、文件夹发现（0/1/2、旧文件夹、错误标记、符号链接、sdb0）、
  锁（外部活锁不删、陈旧锁替换、并发按下 BUSY）、菜单不写 SD；包内容（上游逐字节、叠加文件清单、页面只调 5 个桩、标签为 ASCII、校验和）。

## 主机测试

`reports/f7-v2-host-tests.txt`：**222 项全部通过**（`test_f7_gate`、`test_f7_trial`、`test_f7_v11_native`、`test_f7_v11_trial`、`test_f7_mark`、
`test_f7_v2_native`、`test_f7_v2_trial`、`test_toolbox_v1`）。v2 事务套件继承 F7 全套（安装中断续装、keeper、stop、开关、purge 等）以 v2 名字重跑。

## 风险与未验证项

1. B11、B12 只在主机上验证；B12 的原因是推断（那次开机无日志）。场次 Q2、Q3 验证，Q4 在重启前采集。
2. 菜单是第一次上车：GEM 执行环境来自 v0 实车探测；摘要格式在 v1.1 实车输出上回放过。
3. 安装中断续装、purge 只在主机测试里验证，场次 R3/R4 实车验证。
4. stop 最坏耗时约 25 秒（Java 10 秒 + 80 离开 8 秒 + renderer 5 秒 + sc 兜底 3 秒），菜单要等 `RESULT` 再离开。

## 上车顺序

Toolbox v1 更新（SWDL）→ 菜单 Status（原厂基线）→ Install → 完整重启 → 场次 Q（停车，B11/B12）→ 场次 D（至少 2 次冷启动，锁车前 Collect）→
场次 R（Uninstall、重装、可选中断安装、purge）。结果回传 `resource/private/vehicle-dump/f7-daily-v2/`，之后写 `scripts/audit_f7_vehicle.py`。
