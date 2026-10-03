# MU1320 F7 v2.1：F8 长期稳定性固定候选（F7 v2 + 自动监测）

F7 v2.1 = **F7 v2（2026-10-02 结项）的全部运行代码不变**（hook、Java、renderer、SI/DIO 配置逐字节相同，车上工作目录仍是
`/mnt/app/root/mu1320-rgi-f7-v2`），只加了一个长期监测脚本和三处脚本改动。F8 用它做多日、多次冷启动的稳定性验收，**不需要每次锁车前按 Collect**。

绿色菜单（`Customization > MU1320 RGI`，5 个按钮）和 Toolbox v1 都不变，不需要重刷 Toolbox。

## 和 F7 v2 的差别

`SHA256SUMS` 与 `reports/f7-v2.1-scripts.diff` 可核对。

| 项 | 改动 | 来源 |
| --- | --- | --- |
| 新文件 `f8_mon.sh` | 自动监测：安装到工作目录的 `mon/`。每次开机第一次连 CarPlay 时由 renderer keeper 启动（每次开机只有一个）；每 60 秒记录空闲内存、各相关进程（dio_manager、smartphone_integrator、j9、displaymanager、maneuver_render、screen、io-usb）的 CPU 时间、线程数、数据段和句柄数，以及 `/tmp` 里各日志的大小；每 2 分钟把记录追加到 SD，并把有变化的 F7 日志复制到 SD；每 10 分钟另存 `sloginfo` 和 `/mnt/ota` 转储目录清单 | **B10**（日志断电即丢）、F8 资源占用观察 |
| `f7.sh` | 和监测共用 SD 锁 `/tmp/mu1320-f8-sd.lock`：菜单动作等监测写完（最多 30 秒）再开始，SD 的读写状态不会在动作中途被改；多了开关 `off|on monitor` | 监测会临时把 SD 改成可写 |
| `control.sh` purge | **重启保护**：本次开机里 F7 Java 运行过、监测还在跑、renderer 还在，或者有带 F7 标记的 DIO，就拒绝 purge，提示先重启 | F7 v2 车上在卸载的同一次开机里 purge（BACKLOG B14 附带建议） |
| `control.sh` status | 新增 `F8_MONITOR:`、`F8_MONITOR_STATE:`（采样数、写 SD 次数、已写字节）、`OTHER_WORKSPACES:`（`/mnt/app/root` 里别的 mu1320 工作目录，例如 v1.1 遗留） | 遗留清理 |
| `collect_f7.sh` | 采集时一并复制监测的日志和状态 | — |

命名：SD 文件夹 `mu1320-f7-daily-v2.1`；工作目录、BUILD_ID（`MU1320-F7-DAILY-V2`）、JAR 名、`/tmp` 开关都与 v2 相同。

## 监测写到哪里、写多少

- SD：`mu1320-f7-daily-v2.1/out/f8/boot-<序号>-<pid>/`，每次开机一个目录（序号记在 `out/f8/SEQ`，车上时钟不可靠，所以用序号排顺序）。
  里面 `samples.txt`（采样记录，约 1 MB/小时）和 `logs/`（F7 日志的最新副本、`sloginfo.txt`）。
- SD 原来是只读的话，监测每 2 分钟改成可写几秒、写完 `sync` 再改回只读；**不写 `/mnt/app`、`/mnt/system`**，只做只读查询（`pidin`、`sloginfo`、`ls`），不调用 `dmdt`。
- 每次开机日志复制最多 256 MB，超过后只记采样。大于 1 MB 的日志每 10 分钟才复制一次。
- 没插 SD 时只在内存里攒（最多 1 MB），插回后下一次补写。
- 熄火断电前最后不到 2 分钟的记录可能没写上，这是预期的。
- 监测在卸载（Uninstall）后 1 分钟内自己结束；`/tmp/mu1320-f8-mon-off` 让它本次开机结束；`f7.sh off monitor` 长期关掉。

## 0. 前提

- 车上为原厂基线（F7 v2 已在 2026-10-02 卸载并 purge）。Toolbox v1 已装。
- SD 根目录：**拿掉 `mu1320-f7-daily-v2/`**（它也带 `TOOLBOX-ENTRY`，两个同时在菜单会显示 `2 F7 FOLDERS`；在 Mac 上保留即可），
  放入本文件夹 `mu1320-f7-daily-v2.1/`，并保留 `mu1320-f7-daily-v1.1/`（场次 L 用它清理 v1.1 遗留）。复制后在 Mac 上 `dot_clean`。
- **F8 期间这张 SD 一直插在车上**。取卡只在熄火锁车、MMI 屏幕关掉以后；拷完马上插回。

## 场次 L：清理 v1.1 遗留工作目录（SSH，安装前）

1. 菜单 **1 Status**，完整输出在 SD 的 `out/action-status-*.txt`；看 `OTHER_WORKSPACES:` 一行（屏幕摘要里没有这一行，用 SSH 看更方便）：

   ```sh
   /bin/sh /fs/sda0/mu1320-f7-daily-v2.1/f7.sh status
   ```

2. 列出 `mu1320-rgi-f7-v1.1` 时，用 v1.1 自己的脚本清理（它会先和备份比对，不一致就拒绝）：

   ```sh
   /bin/sh /fs/sda0/mu1320-f7-daily-v2.1/f7.sh purge
   ```

3. 再看一次 status：`OTHER_WORKSPACES: none`（或只剩你确认要留的）。其他旧目录先不要动，把 status 发回来再决定。

## 场次 I：安装（菜单）

1. **1 Status**：`SI: BASELINE/BASELINE`、`JAVA: ABSENT`、`NAVIGNORE: ACTIVE_BASELINE`。
2. **2 Install**：等 `RESULT: OK`。**完整重启**。
3. **1 Status**：`SI: F7_TRIAL/F7_TRIAL`、`JAVA: F7_INSTALLED`、`LISTENER: F7_READY`。

## 场次 M：停车确认监测（约 10 分钟）

1. 连 USB CarPlay，开始一条 Apple Maps 路线：地图框、BAP 箭头、HUD 与 F7 v2 相同。
2. 等 5 分钟以上，SSH `f7.sh status`：`F8_MONITOR: RUNNING pid=…`，`F8_MONITOR_STATE` 里 `flushes=` 至少 2，`mirror=1`。
3. 按 **4 Collect**（这一次是为了对照监测记录）。
4. 熄火锁车，等 MMI 关闭后取卡：SD 上应有 `out/f8/boot-1-*/samples.txt` 和 `logs/`。把整个 `out/` 拷到 Mac，卡插回。

## 场次 N：日常使用（至少 10 次冷启动，跨几天）

正常用车，不需要按任何按钮。尽量覆盖：

- 冷启动（锁车 → 开锁 → 点火）≥10 次；每次都连 CarPlay，大部分时候用导航。
- 短暂熄火不锁车再启动（MMI 休眠/唤醒）。
- 导航中正常拔插 USB（间隔 10 秒以上）。快速插拔（1 秒内）不用做，那是 B14，F8 不测。
- Apple Maps 与 Google Maps 互相切换；至少一次一小时以上的连续导航。
- 电话、Siri、音乐、倒车影像、收音机照常使用。

观察表 `OBSERVATIONS-F8.txt` 每天记一行（日期、冷启动次数、异常）。有异常时：能按就按 **4 Collect**，再照常处理（见下面“异常处理”）。
每隔几天熄火后把 `out/` 拷回 Mac（SD 空间够的话也可以最后一次拷）。

## 场次 X：最终卸载与重装（菜单）

1. USB 断开，**3 Uninstall** → `RESULT: OK`；**完整重启**；**1 Status** 为原厂基线；连 CarPlay：原厂行为。
2. **2 Install** → 完整重启 → 连 CarPlay 开始路线：一切恢复，`F8_MONITOR: RUNNING`。
3. 之后保持安装状态继续日常使用（F8 通过后就是发行版本）。
   如果要回原厂：**3 Uninstall** → **完整重启** → SSH `f7.sh purge`（v2.1 的 purge 现在会拒绝没重启就执行）。

## 结果回传

把 SD 上 `mu1320-f7-daily-v2.1/out/` 整个目录和填好的 `OBSERVATIONS-F8.txt`（有的话加 SSH 终端输出、照片）复制到工作站
`resource/private/vehicle-dump/f8-v2.1/`。

## 异常处理

- 箭头/地图框错乱、VC 黑块：**5 EMERGENCY STOP**；还不行就正常完整重启。监测不受 stop 影响，继续记录这次开机。
- 怀疑监测有影响（卡顿、SD 读写异常）：SSH `f7.sh off monitor`（长期关，下次开机生效；本次开机立即关：`touch /tmp/mu1320-f8-mon-off`）。
- 菜单显示 `BUSY` 或 `SD busy for 30 s`：监测正在写 SD，过几秒再按。
- HMI 黑屏、循环重启、CarPlay 反复重连、音频/倒车影像异常：不要再连 USB，**4 Collect**，**3 Uninstall** 并完整重启。
- 菜单不可用时 SSH：`/bin/sh /fs/sda0/mu1320-f7-daily-v2.1/f7.sh rollback`。
- **不要运行 `dmdt ts`**。

## 已知限制 / 未在车上验证

- 监测只在主机上测试（sh 与 ksh、假 `pidin`/`mount`）。`pidin info`、`pidin times`、`pidin -p <pid> fds` 三种输出格式在本车上第一次用；
  任何一个不可用时监测照常运行，只是那一项缺数据（场次 M 检查）。
- 监测从第一次连 CarPlay 才开始，开机到连手机之间没有记录；完全不连手机的开机没有记录。
- 无线 CarPlay 适配器不出箭头（B13）；快速插拔时原厂强杀 DIO（B14）未处理，F8 不测。
- BACKLOG B2、B4、B5、B6 未改。
