# F7 v2.1（F8 固定候选）离线审阅

日期：2026-10-02。状态：**离线通过，未上车**。SD 文件夹 `mu1320-f7-daily-v2.1/`，由 `scripts/prepare_f7_v21_daily.py` 生成；
清单 `reports/f7-v2.1-prepare.json`，脚本差异 `reports/f7-v2.1-scripts.diff`，主机测试日志 `reports/f7-v2.1-host-tests.txt`。

## 用户决定（2026-10-02）

- F8 证据采集：候选升为 v2.1，加自动监测并镜像日志到 SD（BACKLOG B10），不再依赖每次锁车前按 Collect。
- F8 遗留项只做“清理 v1.1 遗留工作目录”；B14 原厂对照、R3 中断安装、`/mnt/ota` 转储空间检查不在 F8 范围。

## 与 F7 v2 的关系

运行代码不变，从 v2 文件夹逐字节带过来的有：`libcarplay_hook.so`（`3e9d4f1e…`）、JAR（`2c337043…`）、`maneuver_render`、`flag_atlas.rgba`、
`f7_spawn`、`f4_unbuf.so`、`mount_state`、`loader_check`、`smartphone_integrator.json`、`dio_manager.json`、`IDENTITY`、`f5_sc.sh`、`f5_dm.sh`、
`f7_mark.sh`、`trial_gate.c/.h`。工作目录 `mu1320-rgi-f7-v2`、BUILD_ID、SI 标记、JAR 名都不变，所以 native 和 Java 不重编，
F7 v2 实车验证过的行为（B11 闸门、B12 stop 顺序、菜单环境清理）直接沿用。只有 SD 文件夹名变为 `mu1320-f7-daily-v2.1`。

改动的 4 个脚本都只是在 v2 文本上打已审阅的补丁，再更新校验值（prepare 和测试都检查“v2 + 补丁 = v2.1”）：

| 文件 | 补丁 |
| --- | --- |
| `f7_render.sh` | `out "BEGIN"` 之后、所有 HOLD 退出之前调用 `mon_start`：JAR 在、没有关监测、`/tmp/mu1320-f8-mon.run` 里没有活进程时，校验 `mon/f8_mon.sh`、`mon/mount_state`、`f7_spawn`，用 `f7_spawn` 启动监测；任何失败只记 `KEEP MON_FAIL …`，不影响 keeper 的退出码 |
| `control.sh` | 组件多 `monitor`；status 多 `F8_MONITOR`、`F8_MONITOR_STATE`、`OTHER_WORKSPACES`；`runtime_ok`/安装多 `mon/` 目录和两个文件；purge 重启保护 |
| `f7.sh` | `off|on monitor`；动作前拿 SD 锁（最多等 30 s，死进程持有的锁替换），清理时还原 SD 后释放 |
| `collect_f7.sh` | 复制 `/tmp/mu1320-f8-mon.{log,state,buf}`，开关列表多 `monitor` |

## 监测 `f8_mon.sh`

- 启动：Java 每次 CarPlay 会话（hello）都会调 keeper，keeper 保证每次开机只有一个监测（O_EXCL 平文件 `/tmp/mu1320-f8-mon.run`）。
  经 `f7_spawn`：脱离 JVM 的信号状态和描述符，新会话。stop（HOLD）不影响监测，那次开机照样有记录。
- 采样（每 60 s，写 `/tmp/mu1320-f8-mon.buf`）：`pidin info`（空闲内存、进程/线程总数）、`pidin times`（全部进程 CPU 时间）、
  目标进程（dio_manager、smartphone_integrator、displaymanager、j9、maneuver_render、screen、io-usb）的线程数和第一行线程信息（`pidin mem`，
  车上用过）、句柄行数（`pidin fds`）、`/tmp` 下 `carplay_*`/`mu1320-*` 文件大小。
- 写 SD（每 2 次采样）：只在带 `TOOLBOX-ENTRY` 的 `mu1320-f7-daily-v2.1` 文件夹下写 `out/f8/boot-<SEQ>-<pid>/`；先拿锁，只读的 SD 临时改为可写，
  写完 `sync`，改回原状态并核对；有变化的日志才复制（经 `.pending` 名），>1 MB 的每 5 次写一次，每 5 次写存 `sloginfo` 和
  `/mnt/ota/system/logs` 清单、`df`；每次开机日志复制上限 256 MB（之后只写采样）；没有 SD 时缓冲最多 1 MB。
- 结束：JAR 不在（卸载）、`/tmp/mu1320-f8-mon-off`、`off-monitor`、SIGINT/SIGTERM：记 `=== END reason=…` 并最后写一次（最多等锁 60 s，
  卸载时 f7.sh 持锁约 25 s）。
- 约束：不写 `/mnt/app`、`/mnt/system`；`/tmp` 是 shmem，只用平文件、不 rename；不用 `set -e`、不调用 `dmdt`；没有 `x && fail`；
  消息写 fd 3（信号 trap 可能在采样输出重定向到缓冲文件时执行，主机上 bash 就是这样）。

## purge 重启保护

在原有检查（回滚已完成、SI 基线、NavActiveIgnore 回位、JAR 不在、renderer 不在、与备份一致）之后，再拒绝以下情况：
`/tmp/carplay_java.log` 或 `.1` 有 `MU1320-F7-DAILY-V2 LISTENER_READY`（F7 Java 本次开机运行过）、监测在运行、
任一 `dio_manager` 的环境带 F7 标记（`pidin -p … environment`，车上 collect 用过）。F7 v2 车上的 purge 在卸载的同一次开机执行，会被这一条拒绝。

## 主机测试

`prepare_f7_v21_daily.py` 生成文件夹后运行：`test_f7_v21_trial.py`（含全部 v2 事务测试）、`test_f8_mon.py`、`test_toolbox_v1.py`。
结果见 `reports/f7-v2.1-host-tests.txt`：122 个测试全部通过（748 s）。

- `test_f7_v21_trial.py`：在 v2.1 文件夹上重跑整套 F7/F7 v2 事务测试（假车、真脚本；监测用 `/tmp/mu1320-f8-mon-off` 关掉，保证继承的挂载断言不变），
  外加：安装放入 `mon/`、keeper 每次开机只起一个监测、监测写 SD 并在卸载后结束（`END reason=uninstalled`）、HOLD 时也启动、
  `off|on monitor`、工作目录里的监测被改则不启动且 keeper 不受影响、f7.sh 等锁/替换死锁/30 s 放弃且不动 SD、purge 三种拒绝、
  `OTHER_WORKSPACES`、文件夹校验（运行文件与 v2 相同、补丁复核、监测校验值在 control.sh 3 处和 keeper 1 处）。
- `test_f8_mon.py`（sh 与 ksh 各一遍）：记录内容、SD 只读→可写→只读、可写 SD 不 remount、单实例与死进程替换、无 SD 时缓冲后补写、
  没有 `TOOLBOX-ENTRY` 不写、锁被占用跳过、卸载/开关/SIGTERM 结束并写最后一次、最后一次等卸载释放锁、未变化日志不重复复制、
  第二次开机 SEQ=2、大文件延后、256 MB 上限、缓冲上限、不写 `/mnt`。

## 未在车上验证 / 风险

- `pidin info`、`pidin times`、`pidin -p <pid> fds` 在本车第一次用（SDP 的 pidin 有这些关键字）；不可用时监测照常，只缺那一项。场次 M 检查。
- 每 2 分钟 remount 一次 SD（原来是只读）。如果 MMI 断电正好在写入的几秒里，FAT 可能留下脏标记；写入很短，并且每次 `sync`。
- 监测从第一次连 CarPlay 开始；不连手机的开机没有记录。
- 以下内容只在 F7 v2 实车验证过：stop/卸载/续装/菜单；v2.1 没有再改。

## 场次（README）

L（SSH 用 `mu1320-f7-daily-v1.1/f7.sh purge` 清 v1.1 遗留，status 看 `OTHER_WORKSPACES`）→ I（菜单安装）→ M（停车 10 分钟确认监测）→
N（≥10 次冷启动，休眠唤醒、正常拔插、应用切换、≥60 分钟连续导航，不用按按钮）→ X（最终卸载→重启→重装）。观察表 `OBSERVATIONS-F8.txt`（中文）。
结果回传 `resource/private/vehicle-dump/f8-v2.1/`。
